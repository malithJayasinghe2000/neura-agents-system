"""NEURA-SELL's identity card.

Same shape as CARE's, and deliberately so — a manifest is how the system
discovers an agent: what it needs from a store, what it is allowed to do, and
where it lives in the API (docs/architecture/tenancy-and-packaging.md §2.2).

``requires_capabilities`` earns its keep here more than it does for CARE. A
merchant whose store cannot both *find* and *expand* a product cannot be
recommended from at all, and they should learn that at **connection** time
rather than by watching a shopper get handed to a human.
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
    key="sell",
    name="NEURA-SELL",
    version="0.1.0",
    description=(
        "Agent-readiness. Grounded product recommendation for shoppers, an MCP "
        "server so external AI agents can read the catalogue, and a "
        "machine-readable product feed. Read-only throughout."
    ),
    # Required, because without both there is no recommendation to make:
    # `retrieve` finds candidates and the tools confirm them, and a store that
    # cannot expand a candidate can only ever offer a guess.
    requires_capabilities=frozenset(
        {
            Capability.PRODUCT_SEARCH,
            Capability.PRODUCT_READ,
        }
    ),
    # Optional, and each degrades a named thing rather than breaking the agent
    # (sell.md §3.3):
    #
    #   INVENTORY_READ  availability cannot be confirmed, so it is never
    #                   asserted — the feed omits the field rather than
    #                   guessing `InStock`.
    #   CATEGORY_READ   `no_match` loses its "here is what we do carry" half.
    optional_capabilities=frozenset(
        {
            Capability.INVENTORY_READ,
            Capability.CATEGORY_READ,
        }
    ),
    # Two kinds of scope in one set, as CARE does, and for the same reason: the
    # policy engine checks a tool's declared scopes at gate 3, so a scope a tool
    # needs must appear here or a correctly-provisioned key is refused while
    # looking perfectly configured. The failure reads as "the agent never calls
    # any tool", which is the hardest kind to diagnose.
    #
    # `sell:mcp:connect` is the odd one out and is deliberately narrow: it is
    # what an *external* AI agent presents, and it must not be confused with a
    # key that can hold a conversation. Note there is no feed scope — the feed
    # carries no key at all (ADR-0024), which is the whole reason that ADR
    # exists.
    scopes=frozenset(
        {
            "sell:chat:write",
            "sell:conversations:read",
            "sell:shadow:read",
            "sell:shadow:write",
            "sell:catalogue:read",
            "sell:escalate",
            "sell:mcp:connect",
            # ADR-0040's fourth surface. Separate from `sell:catalogue:read`
            # for the same reason `sell:mcp:connect` is: this key is served to
            # every browser that loads a merchant's cart page, and a key that
            # can ask "what goes with these two products" must not thereby be
            # able to read the catalogue directly.
            "sell:suggest:read",
            # Turning publication on, rotating the token, and turning it off.
            # Separate from `sell:catalogue:read` on purpose: reading a
            # catalogue and *publishing* one are different powers, and the
            # second is close to irreversible (ADR-0024).
            "sell:feed:manage",
        }
    ),
    route_prefix="/v1/sell",
    # Written from `prompts/route.md`'s two intents — `recommend` and `compare`
    # — and deliberately narrow. SELL's `needs_person` covers orders, delivery,
    # returns, refunds and store policy, so claiming any of those here would
    # dispatch a shopper to an agent that answers by fetching a human.
    handles=(
        "Helping a shopper find or choose a product they have not bought yet: "
        "describing what they need and being shown options, or comparing "
        "products they have named."
    ),
    handles_examples=(
        "I need a warm jacket for winter, under 150",
        "Which of these two is warmer?",
        "Do you have anything like this in navy?",
        "What would you recommend for hiking in the rain?",
    ),
)

__all__ = ["MANIFEST", "AgentManifest"]
