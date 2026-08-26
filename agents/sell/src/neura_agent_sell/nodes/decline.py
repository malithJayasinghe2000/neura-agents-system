"""The ``decline`` node — saying no without occupying a person.

CARE's A5 resolution, inherited rather than re-derived. "What's the weather in
Colombo?" does not need a support person, and routing it to one spends the
scarcest resource a merchant has on a question no human should ever see — while
counting against *escalation precision*, which is a gated metric.

**The default is to hand over.** `route` reaches this node only on a positive
`out_of_scope` classification **and** confidence at or above
`DECLINE_MIN_CONFIDENCE`, which is higher than the bar for answering. Anything
unclear escalates instead.

## Why this node may skip ``verify``

The graph builder requires `verify` only on the path to `respond`, and this is a
separate terminal node — so the exemption is deliberate and needs justifying.

**Nothing here is generated.** The reply is a file, returned verbatim, with no
model call and no interpolation of anything the shopper or the store said. It
cannot contain a claim about a product, a price or availability, because it
cannot contain anything a human did not write into `decline.md` and review in a
pull request.

That is also why it is a canned file rather than a small generation. A model
asked to "politely decline" will, often enough to matter, explain *why* in terms
it invents — and a fabricated reason about what the store does or does not sell
is exactly the failure this system is built to prevent, arriving through the one
door left unguarded.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from neura_agent_core.graph import AgentState, runtime_of
from neura_core import get_logger

log = get_logger(__name__)

PROMPT_NAME = "decline"


async def decline(state: AgentState, config: RunnableConfig) -> AgentState:
    """Answer an out-of-scope question with the store's standing decline."""
    runtime = runtime_of(config or {})

    log.info(
        "sell_declined_without_handover",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
    )

    return {
        "reply": runtime.prompt(PROMPT_NAME),
        # Explicitly *not* an escalation. The conversation ends here, no handoff
        # packet is built, and no person is queued. It is also not a failure —
        # `refused` is the honest word, and the eval scores it as such.
        "escalated": False,
        "refused": True,
        # Grounded by construction: a fixed file asserts nothing about the world.
        "grounded": True,
        "verify_reason": "a standing decline makes no factual claim to support",
    }


__all__ = ["PROMPT_NAME", "decline"]
