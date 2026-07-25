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
    scopes=frozenset(
        {
            "care:chat:write",
            "care:conversations:read",
            "care:knowledge-base:write",
        }
    ),
    route_prefix="/v1/care",
)
