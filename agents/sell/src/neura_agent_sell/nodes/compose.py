"""The ``compose`` node — drafting the shortlist, from the evidence and nothing else.

Runs on the ``REASONER`` role. The only node whose output a shopper reads, and
the only one checked by another model before it is sent — ``verify`` runs on
``GUARD``, never on the composer, because a model checking its own work agrees
with itself.

**A draft is not an answer.** Everything here goes into ``state["draft"]``, and
only ``respond`` promotes a draft to a reply, after ``verify`` has passed it.
The graph builder refuses to compile a shape where that is not true (ADR-0004).

## What is different from CARE's composer

**The evidence is already filtered.** `shortlist` passes only surviving
candidates, so there is no rejected product in context for the model to mention
and no price ceiling for it to violate — those were enforced in code one node
earlier. CARE's composer sees every tool result; this one sees a shortlist.

**Every suitability claim must be attributed.** This is where open question
**A9** stops being occasional and becomes the whole job: `verify` asks whether a
claim appears in the evidence, and *"good for winter hiking"* never appears in a
record that says *"waterproof, 3-layer"*. The prompt requires the attribute to
be named alongside the inference — *"waterproof and 3-layer, so it should handle
winter hiking"* — which makes the claim checkable by `verify`, by a judge, and
by the shopper.

**That does not resolve A9**, and this docstring is not a claim that it does.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph import AgentState, accrue, infra_error, runtime_of
from neura_core import get_logger
from neura_llm import ChatRequest, FinishReason, Message, ModelRole

log = get_logger(__name__)

PROMPT_NAME = "compose"

#: A backstop against a model that has started narrating — not a style setting.
#:
#: **Sized for thinking plus answer.** A reasoning model spends tokens in a
#: separate channel before emitting a character of content, and CARE lost a
#: whole eval run to a 400-token ceiling being read as a budget for the reply.
MAX_TOKENS = 1500

#: Do not deliberate. Restate the evidence and attribute the claims.
#:
#: The thinking was done by the router that extracted the constraints, the
#: planner that chose the lookups, and `shortlist` which decided what may be
#: recommended at all. What is left is saying it — and CARE measured the local
#: reasoner spending 1500 tokens and 74 seconds deciding how to phrase two
#: sentences.
REASONING_EFFORT = "none"


async def compose(state: AgentState, config: RunnableConfig) -> AgentState:
    """Draft a shortlist for ``verify`` to check."""
    runtime = runtime_of(config or {})

    try:
        response = await runtime.llm.chat(
            ModelRole.REASONER,
            ChatRequest(
                messages=[
                    Message.system(runtime.prompt(PROMPT_NAME)),
                    Message.user(_render(state)),
                ],
                temperature=0.2,
                max_tokens=MAX_TOKENS,
                reasoning_effort=REASONING_EFFORT,
            ),
        )
    except Exception as exc:
        log.warning(
            "sell_compose_failed", conversation_id=state.get("conversation_id"), error=str(exc)
        )
        return {
            "escalated": True,
            "escalation_reason": f"drafting failed: {type(exc).__name__}",
            **infra_error(exc, "the reasoner was unreachable while drafting"),
        }

    draft = response.content.strip()
    if not draft:
        # Diagnosed rather than merely reported. Two very different causes need
        # different fixes, and only one of them is a misconfiguration.
        reason = (
            f"the model hit its {MAX_TOKENS}-token ceiling before writing any reply "
            "(reasoning models spend this budget thinking first)"
            if response.finish_reason is FinishReason.LENGTH
            else "the model produced an empty draft"
        )
        log.warning(
            "sell_compose_empty_draft",
            conversation_id=state.get("conversation_id"),
            finish_reason=response.finish_reason.value,
        )
        # Charged. A model that spent its whole ceiling thinking and emitted
        # nothing spent it; booking that as free hides the most expensive
        # failure this node has.
        return {
            "escalated": True,
            "escalation_reason": reason,
            "usage": accrue(state, ModelRole.REASONER, response),
        }

    log.info(
        "sell_composed",
        conversation_id=state.get("conversation_id"),
        chars=len(draft),
        candidates=len(state.get("promises", [])),
    )
    return {"draft": draft, "usage": accrue(state, ModelRole.REASONER, response)}


def _render(state: AgentState) -> str:
    """The composer's user message.

    The shortlist is named explicitly as well as rendered, so the constraint the
    prompt states — recommend only these — has something exact to point at.
    """
    evidence = state.get("context", "")
    promised = state.get("promises", [])

    if not evidence or not promised:
        # Unreachable through the compiled graph: `shortlist` routes an empty
        # shortlist to `no_match` or `escalate`. Stated explicitly anyway,
        # because the failure it prevents is a model inventing a shortlist.
        evidence = (
            "(No products were retrieved for this question. You have no catalogue "
            "data. Do not name or describe any product.)"
        )

    parts = [f"SHORTLIST — you may recommend these products and no others:\n{evidence}"]

    if promised:
        parts.append("PRODUCT IDS YOU MAY CITE: " + ", ".join(promised))

    if ceiling := state.get("entities", {}).get("max_price"):
        parts.append(
            f"The shopper asked for under {ceiling}. Every product above already "
            "meets that — you do not need to check it, and must not exclude any."
        )

    parts.append(
        f"<untrusted_customer_message>\n{state.get('message', '')}\n</untrusted_customer_message>"
    )
    return "\n\n".join(parts)


__all__ = ["MAX_TOKENS", "PROMPT_NAME", "compose"]
