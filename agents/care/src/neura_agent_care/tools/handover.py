"""``escalate_to_human`` — the one action CARE can always take.

Every other tool requires a capability the store had to declare. This one
requires nothing, so it is available in every conversation, on every store, in
every configuration. That is the design: *"`escalate_to_human` is always
available. It is the only action the agent can always take, by design"*
(agent-runtime.md §3.4).

It exists so that "hand me to a person" is a thing the model can *choose*, not
only something that happens to it when a check fails. A shopper who says "just
let me talk to someone" should get someone — and if the only route to a human
were a failed policy check, that request would be answered by an agent
explaining why it cannot help, which is the most irritating possible response.

**The tool does not perform the escalation.** It records that one was asked for.
The graph reads that back and routes to the shared ``escalate`` node, which
builds the handoff. Keeping the two apart means an escalation always takes the
same path and always produces the same packet, whether it was requested here or
forced by ``verify`` — one code path, one thing to get right.
"""

from __future__ import annotations

from neura_agent_core.tools import ToolContext, tool
from neura_core import get_logger

log = get_logger(__name__)

#: What the tool returns. Recognised by the graph, so the marker is a constant
#: rather than a string matched by eye in two places.
HANDOVER_REQUESTED = "handover_requested"


@tool(
    name="escalate_to_human",
    description=(
        "Hand this conversation to a member of the store's team. Use when the shopper "
        "asks for a person, when they want something changed, cancelled or refunded, or "
        "when you cannot answer from the store's own data. Handing over is a good "
        "outcome, not a failure."
    ),
    scopes=["care:escalate"],
)
async def escalate_to_human(reason: str, ctx: ToolContext) -> str:
    """Ask for a person. Always available."""
    log.info(
        "handover_requested",
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        reason=reason,
    )
    return f"{HANDOVER_REQUESTED}: {reason.strip() or 'the shopper asked for a person'}"


def was_requested(value: object) -> bool:
    """Did this tool result ask for a handover?"""
    return isinstance(value, str) and value.startswith(HANDOVER_REQUESTED)
