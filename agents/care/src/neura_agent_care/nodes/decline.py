"""The ``decline`` node — saying no without occupying a person.

Resolves open question A5. Every out-of-scope question used to become an
escalation, because `agent-runtime.md §2` routes them all there. That is right
for "cancel my order" and wrong for "what's the weather in Colombo?" — the second
puts a support person in front of a question no support person should ever see,
and it does so while spending *escalation precision*, which is a gated metric.

So there are now two out-of-scope outcomes, and ``route`` picks between them on
one question: does a person need to act? Cancellations, address changes, refund
requests, complaints, anything about injury or liability, and any explicit ask
for a human all still hand over. Questions merely unrelated to the store are
declined here.

**The default is to hand over.** ``Route.needs_human`` defaults to ``True``, so a
router that omits the field, a model that returns something odd, or a future
intent nobody thought about still reaches a person. Declining is the special
case and has to be asked for.

## Why this node may skip ``verify``

The graph builder only requires ``verify`` on the path to ``respond``, and this
is a separate terminal node — so the exemption is deliberate rather than an
oversight, and it needs justifying.

**Nothing here is generated.** The reply is a file, returned verbatim, with no
model call and no interpolation of anything the shopper or the store said. It
cannot contain a claim about an order, a price or a policy, because it cannot
contain anything that was not written into ``decline.md`` by a human and reviewed
in a pull request. There is no ungrounded statement for ``verify`` to catch.

That is also why the message is a canned file rather than a small generation. A
model asked to "politely decline" will, often enough to matter, explain *why* it
cannot help in terms it invents — and a fabricated reason about what the store
does or does not do is exactly the failure this system is built to prevent,
arriving through the one door left unguarded.
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
        "declined_without_handover",
        conversation_id=state.get("conversation_id"),
        tenant_id=state.get("tenant_id"),
        intent=state.get("intent"),
    )

    return {
        "reply": runtime.prompt(PROMPT_NAME),
        # Explicitly *not* an escalation. This is the whole point of the node:
        # the conversation ends here, no handoff packet is built, and no person
        # is put in a queue. It is also not a failure — `refused` is the honest
        # word for it, and the eval scores it as such.
        "escalated": False,
        "refused": True,
        # Grounded by construction: a fixed file asserts nothing about the world.
        "grounded": True,
        "verify_reason": "a standing decline makes no factual claim to support",
    }
