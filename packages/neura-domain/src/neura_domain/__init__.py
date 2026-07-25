"""neura-domain — the canonical commerce vocabulary.

PURE. Imports only Pydantic and the stdlib: no database, no HTTP, no LLM, and
nothing else from this workspace. That purity is what allows every other layer to
be swapped, and it is enforced by an import-linter contract in CI.

If you find yourself wanting to import something here, the logic belongs in a
higher layer.
"""

from neura_domain.base import Address, CanonicalEntity, CurrencyCode, DomainModel, Money
from neura_domain.commerce import (
    Category,
    Customer,
    CustomerRef,
    Fulfillment,
    InventoryLevel,
    Order,
    OrderLine,
    Policy,
    Product,
    ProductVariant,
)
from neura_domain.enums import (
    Capability,
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    PolicyKind,
    ProductStatus,
    SideEffect,
)
from neura_domain.events import Event, EventKind

__all__ = [
    "Address",
    "CanonicalEntity",
    "Capability",
    "Category",
    "CurrencyCode",
    "Customer",
    "CustomerRef",
    "DomainModel",
    "Event",
    "EventKind",
    "Fulfillment",
    "FulfillmentStatus",
    "InventoryLevel",
    "Money",
    "Order",
    "OrderLine",
    "OrderStatus",
    "PaymentStatus",
    "Policy",
    "PolicyKind",
    "Product",
    "ProductStatus",
    "ProductVariant",
    "SideEffect",
]
