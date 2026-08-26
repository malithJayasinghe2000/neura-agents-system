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

from pydantic import BaseModel, ConfigDict

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
            # Turning publication on, rotating the token, and turning it off.
            # Separate from `sell:catalogue:read` on purpose: reading a
            # catalogue and *publishing* one are different powers, and the
            # second is close to irreversible (ADR-0024).
            "sell:feed:manage",
        }
    ),
    route_prefix="/v1/sell",
)

__all__ = ["MANIFEST", "AgentManifest"]
