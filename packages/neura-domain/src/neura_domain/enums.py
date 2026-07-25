"""Canonical enumerations.

Platforms disagree wildly on status vocabulary. Adapters map into these; an
unmappable value becomes ``UNKNOWN`` and raises a warning. A platform-specific
status string must never leak into the agent's reasoning, because the agent
would then be reasoning about a word only one platform uses.
"""

from __future__ import annotations

from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    UNKNOWN = "unknown"


class FulfillmentStatus(StrEnum):
    UNFULFILLED = "unfulfilled"
    PARTIAL = "partial"
    FULFILLED = "fulfilled"
    RETURNED = "returned"
    UNKNOWN = "unknown"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    PAID = "paid"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ProductStatus(StrEnum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"
    UNKNOWN = "unknown"


class PolicyKind(StrEnum):
    RETURNS = "returns"
    SHIPPING = "shipping"
    WARRANTY = "warranty"
    PRIVACY = "privacy"
    TERMS = "terms"
    OTHER = "other"


class Capability(StrEnum):
    """What a commerce platform can do, as declared by its adapter.

    The agent's available tools are computed from this set, so a capability the
    platform lacks makes the corresponding tool structurally unavailable rather
    than merely discouraged. See docs/architecture/commerce-integration.md §3.2.
    """

    PRODUCT_READ = "product.read"
    PRODUCT_SEARCH = "product.search"
    CATEGORY_READ = "category.read"
    INVENTORY_READ = "inventory.read"
    ORDER_READ = "order.read"
    ORDER_SEARCH = "order.search"
    ORDER_WRITE = "order.write"
    CUSTOMER_READ = "customer.read"
    POLICY_READ = "policy.read"
    CART_READ = "cart.read"
    CART_WRITE = "cart.write"
    REALTIME_EVENTS = "events.realtime"
    INCREMENTAL_SYNC = "sync.incremental"


class SideEffect(StrEnum):
    """How dangerous a tool is. Drives the authorisation gate.

    MVP registers READ only — the agent physically cannot mutate a store.
    See docs/architecture/adr/0010-read-only-mvp-tools.md.
    """

    READ = "read"
    WRITE = "write"
    IRREVERSIBLE = "irreversible"
