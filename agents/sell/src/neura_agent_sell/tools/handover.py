"""``escalate_to_human`` — the one action SELL can always take.

Every other tool requires a capability the store had to declare. This one
requires nothing, so it is available in every conversation, on every store, in
every configuration. That is the design (agent-runtime.md §3.4): it is the only
action the agent can *always* take.

For SELL specifically, it is also where a whole class of question goes. This
agent has no order tools, no policy tools and no way to change anything, so
"where is my order", "can I return this if it does not fit" and "I want to
cancel" all end here. That cost is named in `sell.md` §10 rather than hidden —
and there is no cross-agent handoff to CARE, because an agent may not import
another agent and the event bus is Phase 3 (open question **A13**).

**The tool does not perform the escalation.** It records that one was asked for;
the graph reads that back and routes to the shared ``escalate`` node. One code
path for every handover is one thing to get right.

**It is deliberately absent from ``MCP_TOOLS``.** There is no human in an MCP
session to escalate *to*, and a tool that files into a merchant's support queue
on a bot's say-so is a denial-of-service surface with a friendly name.
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
        "asks for a person, asks about an existing order, asks about returns or "
        "delivery policy, or wants something bought, changed or cancelled. Handing "
        "over is a good outcome, not a failure."
    ),
    scopes=["sell:escalate"],
)
async def escalate_to_human(reason: str, ctx: ToolContext) -> str:
    """Ask for a person. Always available."""
    log.info(
        "sell_handover_requested",
        tenant_id=ctx.tenant_id,
        conversation_id=ctx.conversation_id,
        reason=reason,
    )
    return f"{HANDOVER_REQUESTED}: {reason.strip() or 'the shopper asked for a person'}"


def was_requested(value: object) -> bool:
    """Did this tool result ask for a handover?"""
    return isinstance(value, str) and value.startswith(HANDOVER_REQUESTED)
