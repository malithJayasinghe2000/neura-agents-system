"""The canonical commerce entities.

This is the single vocabulary agents, tools, RAG and the API reason in. Every
platform is normalised into these models by an adapter, so nothing above this
layer ever learns that Shopify or any other platform exists.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from neura_domain.base import Address, CanonicalEntity, DomainModel, Money
from neura_domain.enums import (
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    PolicyKind,
    ProductStatus,
)

# ── Catalogue ────────────────────────────────────────────────────────────────


class ProductVariant(DomainModel):
    """A specific buyable configuration — the SKU level."""

    external_id: str
    sku: str | None = None
    title: str | None = None
    price: Money | None = None
    compare_at_price: Money | None = None
    options: dict[str, str] = Field(
        default_factory=dict, description='e.g. {"size": "L", "colour": "blue"}'
    )
    in_stock: bool | None = None
    stock_quantity: int | None = None
    barcode: str | None = None


class Product(CanonicalEntity):
    title: str
    description: str | None = None
    status: ProductStatus = ProductStatus.UNKNOWN
    url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    category_ids: list[str] = Field(default_factory=list)
    variants: list[ProductVariant] = Field(default_factory=list)
    price_range_min: Money | None = None
    price_range_max: Money | None = None
    locale: str | None = None
    updated_at: datetime | None = None

    def searchable_text(self) -> str:
        """Flatten to text for embedding.

        Retrieval quality depends on this being stable; changing it means
        reindexing (docs/architecture/llm-abstraction.md §5.2).
        """
        parts = [self.title, self.description or ""]
        parts.extend(v.title or "" for v in self.variants)
        parts.extend(f"{k}: {v}" for variant in self.variants for k, v in variant.options.items())
        return "\n".join(p for p in parts if p)


class Category(CanonicalEntity):
    name: str
    parent_external_id: str | None = None
    description: str | None = None
    url: str | None = None


class InventoryLevel(DomainModel):
    variant_external_id: str
    quantity: int
    location: str | None = None
    in_stock: bool


# ── People ───────────────────────────────────────────────────────────────────


class Customer(CanonicalEntity):
    email: str | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    default_address: Address | None = None
    order_count: int | None = None
    total_spent: Money | None = None
    created_at: datetime | None = None

    @property
    def display_name(self) -> str:
        name = " ".join(p for p in (self.first_name, self.last_name) if p)
        return name or self.email or "Customer"


class CustomerRef(DomainModel):
    """How a caller identifies a customer without necessarily knowing their ID.

    Deliberately loose: an anonymous shopper in a chat widget usually supplies an
    email or an order number, not a customer ID. Whether that is *sufficient* to
    read data is decided by ownership verification, not here
    (docs/architecture/security-model.md §3).
    """

    external_id: str | None = None
    email: str | None = None
    phone: str | None = None
    order_ref: str | None = None


# ── Orders ───────────────────────────────────────────────────────────────────


class OrderLine(DomainModel):
    external_id: str | None = None
    product_external_id: str | None = None
    variant_external_id: str | None = None
    title: str
    sku: str | None = None
    quantity: int
    unit_price: Money | None = None
    total: Money | None = None


class Fulfillment(DomainModel):
    external_id: str | None = None
    status: FulfillmentStatus = FulfillmentStatus.UNKNOWN
    carrier: str | None = None
    tracking_number: str | None = None
    tracking_url: str | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    estimated_delivery: datetime | None = None


class Order(CanonicalEntity):
    order_number: str = Field(description="What the customer calls it, e.g. '1001'")
    status: OrderStatus = OrderStatus.UNKNOWN
    payment_status: PaymentStatus = PaymentStatus.UNKNOWN
    fulfillment_status: FulfillmentStatus = FulfillmentStatus.UNKNOWN
    customer_external_id: str | None = None
    customer_email: str | None = None
    lines: list[OrderLine] = Field(default_factory=list)
    fulfillments: list[Fulfillment] = Field(default_factory=list)
    subtotal: Money | None = None
    shipping_total: Money | None = None
    tax_total: Money | None = None
    total: Money | None = None
    shipping_address: Address | None = None
    billing_address: Address | None = None
    placed_at: datetime | None = None
    updated_at: datetime | None = None
    cancelled_at: datetime | None = None

    @property
    def tracking_numbers(self) -> list[str]:
        return [f.tracking_number for f in self.fulfillments if f.tracking_number]


# ── Store content ────────────────────────────────────────────────────────────


class Policy(CanonicalEntity):
    """A returns/shipping/warranty policy, as text the agent can ground answers in."""

    kind: PolicyKind
    title: str
    body: str
    url: str | None = None
    locale: str | None = None
    updated_at: datetime | None = None
