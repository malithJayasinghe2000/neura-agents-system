"""NEURA-CARE's identity card.

An agent's manifest is how the system discovers it: what it needs from a store,
what it is allowed to do, and where it lives in the API. Registered via entry
points, so there is no central list to edit
(docs/architecture/tenancy-and-packaging.md §2.2).

``requires_capabilities`` also gives a useful pre-flight check — a store whose
adapter cannot satisfy them is told at *connection* time that this agent will not
work for it, rather than the merchant discovering it through a failed conversation.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from neura_domain import Capability


class AgentManifest(BaseModel):
    """Declared metadata for one sellable agent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    name: str
    version: str
    description: str
    requires_capabilities: frozenset[Capability]
    optional_capabilities: frozenset[Capability] = frozenset()
    scopes: frozenset[str] = frozenset()
    route_prefix: str

    #: What this agent answers, for [ADR-0031]'s dispatcher — one plain
    #: sentence, addressed to whoever is choosing between agents rather than to
    #: a merchant deciding what to buy. That is why it is not ``description``:
    #: every agent's description reduces to "helps shoppers", and CARE and SELL
    #: are exactly the pair that has to be told apart.
    #:
    #: **These two fields are the dispatcher's prompt.** Shared code never names
    #: an agent (``routes/agent.py`` does not know the word "care"), so the only
    #: thing that makes an agent reachable is what it says here — which means a
    #: wrong dispatch is diagnosed by reading a manifest, and a new agent is
    #: made reachable by writing five sentences rather than by editing the
    #: dispatcher.
    handles: str
    #: Three to five real shopper questions this agent answers. Required, and
    #: bounded, because an agent that declares nothing is an agent nobody can
    #: reach — and failing loudly at import beats being silently unroutable.
    handles_examples: tuple[str, ...] = Field(min_length=3, max_length=5)


MANIFEST = AgentManifest(
    key="care",
    name="NEURA-CARE",
    version="0.1.0",
    description=(
        "Customer experience agent. MVP scope is three intents — order status, "
        "product Q&A, and returns/shipping policy — with read-only tools and "
        "escalation to a human when unsure."
    ),
    requires_capabilities=frozenset(
        {
            Capability.ORDER_READ,
            Capability.PRODUCT_SEARCH,
            Capability.POLICY_READ,
        }
    ),
    optional_capabilities=frozenset(
        {
            Capability.INVENTORY_READ,
            Capability.ORDER_SEARCH,
            Capability.CUSTOMER_READ,
        }
    ),
    # Two kinds of scope, in one set on purpose.
    #
    # The first three are API-surface scopes: what a key may do to CARE's routes.
    # The last four are the scopes CARE's *tools* declare, and the policy engine
    # checks them at gate 3 of every call. They must be listed here or a key
    # provisioned from this manifest would be refused by the engine while looking
    # perfectly well configured — a test asserts the tools' scopes are a subset
    # of this set, because the failure is silent and reads as "the agent never
    # calls any tool".
    scopes=frozenset(
        {
            "care:chat:write",
            "care:conversations:read",
            # Reading the shadow queue and grading it are separate on purpose: a
            # dashboard that shows what the agent would have said is a different
            # thing from a key that can change a verdict.
            "care:shadow:read",
            "care:shadow:write",
            "care:knowledge-base:write",
            "care:order:read",
            "care:catalogue:read",
            "care:policies:read",
            "care:escalate",
        }
    ),
    route_prefix="/v1/care",
    # Written from `prompts/route.md`'s own intents and worked examples, not
    # from the pitch. The dispatcher's job is to tell CARE from SELL, and the
    # separating words are the ones SELL cannot claim: *placed*, *returns*,
    # *delivery*, *refunds*.
    handles=(
        "Questions about an order the shopper has already placed, and about how "
        "the store operates — returns, refunds, delivery, payment. Also general "
        "questions about what the store sells. Also questions about one product's "
        "details: what it is made of, its size or weight, where it comes from, "
        "whether it is organic."
    ),
    handles_examples=(
        "Where is my order NRA0001?",
        "How long do I have to return something?",
        "How much is delivery to Ireland?",
        # R54 (G111): a question about one product's details is CARE's.
        "What is this jacket made of?",
        "Do you sell waterproof boots?",
    ),
)
