"""The ``triage`` node — turning tool-level outcomes into a decision about the turn.

It exists for one reason, and the reason is a limitation worth naming rather than
working around: a LangGraph branch function chooses an edge but cannot write to
the state. So "the model called ``escalate_to_human``" can be *routed* on from a
branch, but the escalation would arrive at the handoff with no reason attached —
and a support person picking up a conversation whose stated reason is
"unspecified" has to reconstruct why it reached them.

So the decision is made in a node, where it can say why.

Sitting between ``act`` and ``compose``, this is also the natural home for any
future "a lookup succeeded but the turn is still not answerable" rule. There is
exactly one such rule today and it is not generalised in advance.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_care.tools import was_requested
from neura_agent_core.graph import AgentState
from neura_core import get_logger

log = get_logger(__name__)


async def triage(state: AgentState, config: RunnableConfig) -> AgentState:
    """Decide whether the turn can still be answered."""
    for invocation in state.get("invocations", []):
        # Only an executed call counts. A handover the policy engine refused must
        # not escalate a conversation the shopper never asked to escalate — and a
        # refused call is recorded as an invocation too, so the `ok` check is
        # load-bearing rather than defensive.
        if invocation.ok and was_requested(invocation.value):
            reason = _reason(str(invocation.value))
            log.info(
                "handover_requested_by_model",
                conversation_id=state.get("conversation_id"),
                reason=reason,
            )
            return {"escalated": True, "escalation_reason": f"handover requested: {reason}"}

    return {}


def _reason(value: str) -> str:
    """The reason the model gave, from ``handover_requested: <reason>``."""
    _, _, reason = value.partition(":")
    return reason.strip() or "the model asked for a person"
