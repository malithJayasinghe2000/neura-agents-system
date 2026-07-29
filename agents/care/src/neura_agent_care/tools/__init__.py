"""CARE's tool set — seven tools, every one of them read-only.

The MVP list from agent-runtime.md §3.4, in full:

    get_order_status           ORDER_READ                      order status
    find_orders_for_customer   ORDER_SEARCH + CUSTOMER_READ    order status
    search_products            PRODUCT_SEARCH                  product Q&A
    get_product_details        PRODUCT_READ                    product Q&A
    check_stock                INVENTORY_READ                  product Q&A
    search_policies            POLICY_READ                     returns/shipping
    escalate_to_human          —                               all

**Nothing here can change a store.** Not "is instructed not to" — *cannot*.
Every tool declares ``side_effect=READ``, and the registry refuses to register
anything else while the approval queue does not exist (ADR-0010). A refund tool
is not disabled or hidden; it does not exist, so the most persuasive injection
imaginable has nothing to invoke.

The list is intentionally short. Each tool is a capability a store must declare,
a scope an API key must hold, and a path an eval has to cover — and the failure
mode of a large tool set is a small model choosing badly among lookalikes.
"""

from __future__ import annotations

from neura_agent_care.tools.catalogue import check_stock, get_product_details, search_products
from neura_agent_care.tools.handover import HANDOVER_REQUESTED, escalate_to_human, was_requested
from neura_agent_care.tools.orders import find_orders_for_customer, get_order_status
from neura_agent_care.tools.policies import search_policies
from neura_agent_core.tools import ToolRegistry, ToolSpec

#: Every tool CARE ships, in the order of agent-runtime.md §3.4.
#:
#: A store that declares fewer capabilities simply sees fewer of them — the
#: registry filters per conversation, and a tool the store cannot satisfy is
#: never put in the model's context at all.
CARE_TOOLS: tuple[ToolSpec, ...] = (
    get_order_status,
    find_orders_for_customer,
    search_products,
    get_product_details,
    check_stock,
    search_policies,
    escalate_to_human,
)

#: The scopes CARE's tools require, together. Must be a subset of what the
#: manifest declares, or a correctly-provisioned API key would still be refused
#: at check 3 — asserted by a test rather than trusted to stay true.
TOOL_SCOPES = frozenset(scope for spec in CARE_TOOLS for scope in spec.scopes)


def build_registry() -> ToolRegistry:
    """A registry holding CARE's tools.

    Built per process, not per conversation: registration is about what exists in
    this deployment. *Availability* — which of them a given shopper's turn may
    use — is decided per conversation by ``available_for(ctx)``.
    """
    return ToolRegistry(CARE_TOOLS)


__all__ = [
    "CARE_TOOLS",
    "HANDOVER_REQUESTED",
    "TOOL_SCOPES",
    "build_registry",
    "check_stock",
    "escalate_to_human",
    "find_orders_for_customer",
    "get_order_status",
    "get_product_details",
    "search_policies",
    "search_products",
    "was_requested",
]
