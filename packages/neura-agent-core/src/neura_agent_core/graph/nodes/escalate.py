"""The ``escalate`` node — handing over to a person, with everything they need.

**An escalation is a successful outcome, not a failure** (agent-runtime.md §5).
The metric that matters is escalation *precision*, not rate, and the design
deliberately gates escalation *recall* higher than precision: over-escalating
wastes human time, under-escalating tells someone the wrong thing about their
money.

The handoff is the whole product of this node. A human picking it up should be
able to resolve in one touch, without re-reading the conversation and without
re-doing the lookups the agent already did. That means it carries the reason,
what was retrieved, which tools ran and which were refused, and the draft.

**The draft is included and explicitly not sent.** The human decides — that is
[operating principle 1](../business/blueprint-v2.md) in practice. Marking it
clearly as unsent matters: a support agent skim-reading a handoff must never
believe the customer has already been told something they have not.

**The handoff is rehydrated, and the audit log is not.** ``guard`` replaces the
shopper's email and phone with tokens before any model sees them; a support
person reading "the customer said `[EMAIL_1]` was wrong" has been handed a
puzzle instead of a ticket, and they are the customer's own merchant, entitled
to their own customer's details. So the packet a person reads gets real values
back. The two-year audit log keeps the tokenised form — different recipient,
different retention, different answer (security-model.md §6.2).
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph.state import AgentState, runtime_of
from neura_core import get_logger

log = get_logger(__name__)

#: What the shopper is told. Deliberately plain, and it promises only what the
#: system can actually deliver — a person will see this, not "someone will reply
#: within an hour", which we cannot know.
DEFAULT_MESSAGE = (
    "I want to make sure you get this right, so I'm passing you to a member of "
    "the team. They'll have everything we've discussed."
)


async def escalate(state: AgentState, config: RunnableConfig) -> AgentState:
    """Build the handoff and end the turn."""
    runtime = runtime_of(config or {})
    reason = state.get("escalation_reason") or state.get("verify_reason") or "unspecified"

    handoff = runtime.vault.rehydrate(_handoff(state, reason))

    log.info(
        "escalated",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
        reason=reason,
        tools_used=[i.tool_name for i in state.get("invocations", [])],
    )

    return {
        "escalated": True,
        "escalation_reason": reason,
        "handoff": handoff,
        "reply": runtime.prompts.get("escalation_message", DEFAULT_MESSAGE),
    }


def _handoff(state: AgentState, reason: str) -> str:
    """The packet a human resolves from.

    Plain text rather than JSON: it is read by a person under time pressure, and
    the structured version of all of this is already in the audit log.
    """
    lines = [
        f"Conversation  {state.get('conversation_id', '?')}",
        f"Tenant        {state.get('tenant_id', '?')}",
        f"Reason        {reason}",
        "",
        f"Customer said {state.get('message', '')!r}",
    ]

    if intent := state.get("intent"):
        lines.append(f"Intent        {intent} (confidence {state.get('intent_confidence', 0):.2f})")

    if sources := state.get("sources"):
        lines.append(f"Retrieved     {', '.join(sources)}")
    if note := state.get("retrieval_note"):
        lines.append(f"              note: {note}")

    invocations = state.get("invocations", [])
    if invocations:
        lines.append(
            "Tools used    "
            + " · ".join(f"{i.tool_name} {'✔' if i.ok else '✘'}" for i in invocations)
        )

    # Refusals belong in the handoff, not only in the audit log: "the agent was
    # not allowed to look that up" is often the entire explanation the human
    # needs, and hiding it would send them hunting for a bug that is not there.
    refused = [d for d in state.get("decisions", []) if not d.allowed]
    if refused:
        lines.append(
            "Refused       "
            + " · ".join(
                f"{d.tool_name} ({d.check.value if d.check else 'policy'})" for d in refused
            )
        )

    if draft := state.get("draft"):
        lines.append("")
        lines.append("Draft (NOT SENT — you decide whether to use it)")
        for line in draft.splitlines():
            lines.append(f"    {line}")

    return "\n".join(lines)
