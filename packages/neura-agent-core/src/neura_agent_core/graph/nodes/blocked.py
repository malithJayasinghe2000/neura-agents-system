"""The ``blocked`` node — a turn that ends without an answer and without a person.

The third terminal outcome, and the newest. `respond` answers, `escalate` hands
over, and this one stops. What makes it worth having is arithmetic: an escalation
costs a support person a minute, and until this node existed an attacker could
buy one for the price of a sentence. Twenty hand probes on 2026-07-29 measured
exactly that, and it was raised as open question **S4**.

**Blocking is the cheap outcome, and cheapness is the whole argument for it.**
That is also the argument against it, which ADR-0012 weighs: an outcome nobody
sees is an outcome nobody can be alarmed by. So the block is not silent. `guard`
writes a `guard.block` entry to the append-only audit log naming the rule that
matched, and the reply below tells the shopper what to do about it.

**The reply is a file, returned verbatim, and no model runs here.** Same
reasoning as `decline`: a model asked to refuse politely will explain *why* in
terms it invents, and a fabricated explanation of what the store does is the
failure this system exists to prevent, arriving through the one door left
unguarded. It also means there is nothing for `verify` to check, which is why the
graph builder permits this node to be terminal without one.

**What it does not say.** Not "that looked like a prompt injection", and not
which rule fired. Naming the rule turns every block into a free oracle: an
attacker gets told which phrasing tripped the guard and rewrites it. The shopper
is told the message could not be processed and invited to rephrase — which is
also the honest instruction for the false-positive case, where a real customer
typed something unlucky and wants their answer.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph.state import AgentState, runtime_of
from neura_core import get_logger

log = get_logger(__name__)

PROMPT_NAME = "blocked_message"

#: What the shopper is told. Neutral, actionable, and it names no rule.
DEFAULT_MESSAGE = (
    "Sorry — I can't process that message. If you have a question about an "
    "order, a product or one of our policies, send it on its own and I'll help."
)


async def blocked(state: AgentState, config: RunnableConfig) -> AgentState:
    """End the turn safely. No handoff, no model call, no tools."""
    runtime = runtime_of(config or {})

    log.info(
        "blocked_turn",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
        reason=state.get("block_reason", ""),
    )

    return {
        "reply": runtime.prompts.get(PROMPT_NAME, DEFAULT_MESSAGE),
        # Explicitly not an escalation — that is the point of the node, and
        # conflating the two would make escalation precision unreadable in
        # exactly the direction an attacker chooses.
        "escalated": False,
        # It *is* a refusal, and the eval scores it as one.
        "refused": True,
        # Grounded by construction: a fixed file asserts nothing about the world.
        "grounded": True,
        "verify_reason": "a blocked turn makes no factual claim to support",
    }
