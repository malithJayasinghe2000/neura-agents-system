"""The ``act`` node — where the model's proposals meet the policy engine.

The model proposes; this node disposes. Every proposed call goes through
:class:`PolicyEngine` and only an ``ALLOW`` reaches a tool. Nothing here trusts
the model's choice, its arguments, or its claim about who the shopper is.

**Capped at four calls, and the cap is the point.** Small local models loop —
they call the same tool with the same arguments and convince themselves the
answer will differ (llm-abstraction.md §9). Without a cap that is an infinite
loop, a burned budget and a hung request. With one it becomes an escalation,
which is a good outcome rather than an incident.

The five policy outcomes each mean something different here, and flattening them
into "worked / didn't" would lose exactly the information that makes the graph
debuggable:

* ``ALLOW``    — run it.
* ``REPAIR``   — the arguments were wrong in a fixable way. Tell the model what
                 was wrong and let it try again; this is its commonest mistake.
* ``REJECT``   — not permitted. The model may pick a different tool.
* ``ESCALATE`` — stop. Continuing would mean guessing about someone's data.
* ``DEGRADE``  — out of budget. Answer with what we have rather than failing.
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph.state import AgentState, runtime_of
from neura_agent_core.policy.engine import Decision, Outcome
from neura_agent_core.tools.executor import ToolInvocation, execute
from neura_core import get_logger

log = get_logger(__name__)

#: Where an agent's reasoning node leaves tool calls for `act` to authorise.
#: Must match the key declared on `AgentState` — LangGraph drops anything the
#: state does not declare, silently.
PROPOSALS_KEY = "proposed_calls"


async def act(state: AgentState, config: RunnableConfig) -> AgentState:
    """Execute the tool calls the model proposed for this turn.

    Returns only the keys it changed. LangGraph merges them, and the additive
    reducers on ``invocations`` and ``decisions`` mean the record of what
    happened accumulates rather than being overwritten.
    """
    runtime = runtime_of(config or {})
    proposals = proposals_of(state)

    invocations: list[ToolInvocation] = []
    decisions: list[Decision] = []
    escalate_reason: str | None = None

    for proposal in proposals:
        if runtime.budget.exhausted:
            # Reported rather than silently truncated: an agent that stopped
            # calling tools because it ran out of budget looks identical to one
            # that decided it had enough information.
            log.info(
                "act_budget_reached",
                conversation_id=state.get("conversation_id"),
                calls_used=runtime.budget.calls_used,
            )
            break

        decision = runtime.policy.authorise(
            proposal["name"], proposal.get("arguments", {}), runtime.ctx, runtime.budget
        )
        decisions.append(decision)

        if decision.outcome is Outcome.ESCALATE:
            escalate_reason = (
                f"{decision.check.value if decision.check else 'policy'}: {decision.reason}"
            )
            break

        if decision.outcome is not Outcome.ALLOW:
            # REJECT, REPAIR and DEGRADE all leave the model something to work
            # with next turn. None of them runs a tool.
            invocations.append(
                ToolInvocation(
                    tool_name=decision.tool_name,
                    ok=False,
                    error=decision.as_model_feedback(),
                )
            )
            continue

        spec = runtime.registry.get(decision.tool_name)
        if spec is None:  # pragma: no cover - the engine already proved it exists
            continue

        runtime.budget.spend()
        invocations.append(await execute(spec, decision, runtime.ctx))

    update: AgentState = {"invocations": invocations, "decisions": decisions}
    if escalate_reason is not None:
        update["escalated"] = True
        update["escalation_reason"] = escalate_reason
    return update


def proposals_of(state: AgentState) -> list[dict[str, Any]]:
    """The tool calls awaiting authorisation. Read by ``act``, written by the
    agent's own reasoning node."""
    raw = dict(state).get(PROPOSALS_KEY, [])
    return list(raw) if isinstance(raw, list) else []


def propose(calls: list[dict[str, Any]]) -> AgentState:
    """Hand tool calls to ``act``.

    A separate function rather than a state key an agent sets by hand, so the
    shape stays in one place — ``{"name": str, "arguments": dict}`` is what the
    OpenAI-compatible tool-call format reduces to, and every provider we support
    speaks it.
    """
    return cast(AgentState, {PROPOSALS_KEY: calls})
