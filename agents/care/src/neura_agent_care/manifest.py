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
)
