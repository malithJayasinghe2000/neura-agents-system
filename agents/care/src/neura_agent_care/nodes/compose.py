"""The ``compose`` node — drafting the reply, from the evidence and nothing else.

Runs on the ``REASONER`` role. It is the only node whose output a shopper ever
reads, and — importantly — the only one whose output is checked by another model
before it is sent. ``verify`` runs on ``GUARD``, never on the composer, because a
model checking its own work agrees with itself.

**A draft is not an answer.** Everything this node produces goes into
``state["draft"]``, and only ``respond`` promotes a draft to a reply, after
``verify`` has passed it. The graph builder refuses to compile a shape where
that is not true, so it is a structural guarantee and not a convention
(ADR-0004).

The evidence handed over here is assembled deterministically and in priority
order (agent-runtime.md §4.1): tool results first, because they are this turn's
facts about this shopper's order, then retrieved store content, which is
background. Both are delimited; a failed tool call is included as a *failure*
rather than dropped, so a model that would otherwise fill the gap can see there
is a gap.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph import AgentState, infra_error, runtime_of
from neura_core import get_logger
from neura_llm import ChatRequest, ChatResponse, FinishReason, Message, ModelRole

log = get_logger(__name__)

PROMPT_NAME = "compose"

#: A backstop against a model that has started narrating — not a style setting.
#: Brevity is asked for in the prompt; this only stops the pathological case.
#:
#: **Sized for thinking, not for the answer, and that distinction cost a whole
#: eval run to find.** A reasoning model spends tokens in a separate `reasoning`
#: channel before it emits a single character of `content`, so `max_tokens` is a
#: budget for *thinking plus answer*. Set to 400 — a generous ceiling for a
#: two-sentence reply — the configured reasoner used all 400 thinking, returned
#: `finish_reason=length` with empty content, and every case in the suite
#: escalated with "there is no draft to verify". Nothing was broken; the budget
#: was being read as though it meant something it does not.
MAX_TOKENS = 1500

#: Do not deliberate. Restate the evidence.
#:
#: This node has nothing to reason *about*: the thinking was done by the router
#: that classified the turn, the planner that chose the lookups, and the tools
#: that fetched the facts. All that is left is saying it in two sentences, and
#: the local reasoner given free rein spent 1500 tokens and 74 seconds thinking
#: about how to phrase it — per turn, on the model tier that has to be viable for
#: the sovereign product to exist.
#:
#: Set here rather than in the role map on purpose. Whether a role thinks by
#: default is a decision about every agent and every node, and it belongs with a
#: comparison run (llm-abstraction.md §8), not with a side effect of this one.
#: A node that genuinely wants deliberation can still ask for it.
REASONING_EFFORT = "none"


async def compose(state: AgentState, config: RunnableConfig) -> AgentState:
    """Draft a reply for ``verify`` to check."""
    runtime = runtime_of(config or {})
    evidence = _evidence(state)

    try:
        response = await runtime.llm.chat(
            ModelRole.REASONER,
            ChatRequest(
                messages=[
                    Message.system(runtime.prompt(PROMPT_NAME)),
                    Message.user(_render(state, evidence)),
                ],
                temperature=0.2,
                max_tokens=MAX_TOKENS,
                reasoning_effort=REASONING_EFFORT,
            ),
        )
    except Exception as exc:
        # agent-runtime.md §2: compose failure → escalate. There is no degraded
        # reply worth sending here — a shopper receiving a generic apology from
        # an agent that could not draft is worse served than one handed to a
        # person with the lookups already done.
        log.warning("compose_failed", conversation_id=state.get("conversation_id"), error=str(exc))
        return {
            "escalated": True,
            "escalation_reason": f"drafting failed: {type(exc).__name__}",
            **infra_error(exc, "the reasoner was unreachable while drafting"),
        }

    draft = response.content.strip()
    if not draft:
        # Diagnosed, not just reported. An empty draft has two very different
        # causes and they need different fixes: a model that had nothing to say,
        # and a model that ran out of budget mid-thought. Both escalate — the
        # shopper is served either way — but only one of them is a
        # misconfiguration, and it is invisible unless something says so.
        reason = (
            f"the model hit its {MAX_TOKENS}-token ceiling before writing any reply "
            "(reasoning models spend this budget thinking first)"
            if response.finish_reason is FinishReason.LENGTH
            else "the model produced an empty draft"
        )
        log.warning(
            "compose_empty_draft",
            conversation_id=state.get("conversation_id"),
            finish_reason=response.finish_reason.value,
            completion_tokens=response.usage.completion_tokens,
        )
        return {"escalated": True, "escalation_reason": reason}

    log.info(
        "composed",
        conversation_id=state.get("conversation_id"),
        chars=len(draft),
        had_evidence=bool(evidence),
    )
    return {"draft": draft, "usage": _usage(state, response)}


def _evidence(state: AgentState) -> str:
    """Everything the draft may rely on, in priority order.

    Tool results before retrieved content, because a lookup about *this*
    shopper's order outranks a policy page that merely mentions orders. A local
    model's context is the scarce resource and what comes first survives
    truncation (llm-abstraction.md §9).

    Failed calls are included, marked as failures. Dropping them would leave the
    model with a question and no explanation for the silence, which is precisely
    the condition under which it invents an answer; told plainly that the lookup
    did not work, it can say so.
    """
    parts: list[str] = []

    for invocation in state.get("invocations", []):
        if invocation.ok:
            parts.append(
                f'<tool_result name="{invocation.tool_name}">\n{invocation.value}\n</tool_result>'
            )
        else:
            parts.append(
                f'<tool_failed name="{invocation.tool_name}">\n{invocation.error}\n</tool_failed>'
            )

    if context := state.get("context"):
        parts.append(context)

    return "\n\n".join(parts)


def _render(state: AgentState, evidence: str) -> str:
    """The composer's user message."""
    if not evidence:
        # Said explicitly rather than left blank. "No evidence" and "the evidence
        # section is missing" read identically to a model, and only one of them
        # should produce a reply that admits to knowing nothing.
        evidence = (
            "(Nothing was retrieved and no lookup returned data for this question. "
            "You have no facts about this shopper's order, the catalogue, or the "
            "store's policies. Do not state any.)"
        )

    return (
        f"EVIDENCE:\n{evidence}\n\n"
        "<untrusted_customer_message>\n"
        f"{state.get('message', '')}\n"
        "</untrusted_customer_message>"
    )


def _usage(state: AgentState, response: ChatResponse) -> dict[str, Any]:
    """Accumulate cost and tokens for the budget and the merchant's bill.

    Cost is carried as a ``Decimal`` rendered to a string, not a float. The
    amounts are tiny and a float would round them plausibly rather than visibly;
    the state is also checkpointed to Postgres and read back, and a string
    survives that round trip without a JSON encoder quietly choosing a
    representation for us.
    """
    usage = dict(state.get("usage", {}))
    usage["tokens"] = int(usage.get("tokens", 0)) + response.usage.total_tokens
    usage["cost_usd"] = str(Decimal(str(usage.get("cost_usd", "0"))) + response.cost_usd)
    return usage
