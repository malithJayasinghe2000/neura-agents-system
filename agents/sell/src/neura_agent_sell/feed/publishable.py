"""What may leave the building.

The single most important file in the feed, and the reason it exists is one
sentence: **the feed is an allowlist, and the allowlist is a type.**

`Product` is a `CanonicalEntity`, so it carries four fields that must never be
published, and one of them is unbounded:

    raw         the platform's entire original payload. Cost prices, supplier
                references, internal flags, whatever that platform happens to
                include. We do not know what is in it, which is the point —
                `CanonicalEntity` keeps it precisely because no canonical model
                survives contact with every platform.
    platform    which commerce platform the merchant runs. Nobody's business,
                and free reconnaissance for anyone deciding what to attack.
    tenant_id   our internal identifier for this merchant.
    neura_id    our internal identifier for this product.

A renderer written as `product.model_dump()` publishes all four. So would one
written as `model_dump(exclude={"raw", "platform", ...})` — right today, and
wrong the day somebody adds a field to `CanonicalEntity`, because a denylist
leaks whatever it has not heard of. **The failure would be silent, permanent and
public**, which is the worst combination this system can produce (ADR-0024: a
cached document cannot be un-published).

So the renderers never see a `Product` at all. They are handed
:class:`PublishableProduct`, which has no `raw`, no `platform`, no ids of ours,
and no way to reach them — a renderer physically cannot publish what it was
never given. Adding a field to the canonical model publishes nothing until
somebody adds it here, on purpose, in a diff a human reads.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from neura_domain import Product, ProductStatus, ProductVariant

#: A GTIN is 8, 12, 13 or 14 digits. `ProductVariant.barcode` is whatever the
#: merchant typed, which is frequently an internal code, a shelf label, or an
#: ISBN with hyphens.
#:
#: Validated before publication rather than after, because a malformed `gtin`
#: does not degrade a feed — consumers reject the *item*, and the merchant is
#: then absent from the channel they paid for with nothing saying why.
_GTIN = re.compile(r"^\d{8}$|^\d{12}$|^\d{13}$|^\d{14}$")


class PublishableVariant(BaseModel):
    """One buyable configuration, reduced to what may be published."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    external_id: str
    sku: str | None = None
    title: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    options: dict[str, str] = {}
    gtin: str | None = None
    #: Tri-state, and the third state is load-bearing.
    #:
    #: ``None`` means *not asserted* — the store declares no live inventory feed,
    #: or the sync is stale. It is rendered as an **absent** field, never as
    #: `OutOfStock`, because "we do not know" and "we do not have it" are
    #: different claims and only one of them is true.
    in_stock: bool | None = None


class PublishableProduct(BaseModel):
    """One product, reduced to what may be published.

    Every field here was added deliberately. Nothing arrives by inheritance,
    and there is no `model_dump()` of a canonical entity anywhere behind it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The **merchant's** id for this product, not ours. It is what a merchant
    #: recognises in their own admin and what lets them reconcile a feed against
    #: their catalogue. Our `neura_id` would mean nothing to anyone outside here.
    product_id: str
    title: str
    description: str | None = None
    url: str | None = None
    image_urls: list[str] = []
    variants: list[PublishableVariant] = []
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    currency: str | None = None
    #: When this product was last read from the merchant's store. Carried per
    #: item as well as per document, because a catalogue is synced in pages and
    #: a shopper acting on a price deserves to know the age of *that* price.
    synced_at: datetime


def publishable(
    products: list[Product],
    *,
    may_assert_availability: bool,
) -> list[PublishableProduct]:
    """Project synced products onto what may leave the building.

    ``may_assert_availability`` comes from the caller and is two facts joined:
    the store declares ``INVENTORY_READ``, **and** its sync is fresh enough to
    be worth believing. When it is false every ``in_stock`` becomes ``None`` and
    the field is omitted downstream — an omitted field is honest, and a guessed
    ``InStock`` is a claim a shopper acts on with their money.

    It is a parameter rather than something inferred here because neither half
    is visible from a `Product`. A function that guessed would guess optimistically.
    """
    return [
        _project(product, may_assert_availability=may_assert_availability)
        for product in products
        if is_publishable(product)
    ]


def is_publishable(product: Product) -> bool:
    """Only ``ACTIVE``. Not merely "not archived".

    **A deliberately higher bar than the agent applies in conversation**, and the
    asymmetry is the interesting part.

    `search_products` mentions everything except `ARCHIVED`, because a shopper
    looking at a cached search result deserves to be told a product was
    withdrawn rather than to hear "we don't sell that" — and a human is present
    to take the correction.

    A feed has no human, no turn and no correction. It is fetched by a machine,
    cached, and may be republished somewhere we will never see (ADR-0024). So
    `DRAFT` — a product the merchant has not finished writing — and `UNKNOWN` —
    a status the adapter could not map — are both withheld. Publishing a product
    whose status we could not determine, into a permanent public document,
    asserts it is for sale on the strength of not knowing.
    """
    return product.status is ProductStatus.ACTIVE


def _project(product: Product, *, may_assert_availability: bool) -> PublishableProduct:
    """One product. Field by field, on purpose."""
    variants = [
        _variant(v, may_assert_availability=may_assert_availability) for v in product.variants
    ]

    return PublishableProduct(
        product_id=product.external_id,
        title=product.title,
        description=product.description,
        url=product.url,
        image_urls=list(product.image_urls),
        variants=variants,
        price_min=product.price_range_min.amount if product.price_range_min else None,
        price_max=product.price_range_max.amount if product.price_range_max else None,
        currency=_currency(product),
        synced_at=product.synced_at,
    )


def _variant(variant: ProductVariant, *, may_assert_availability: bool) -> PublishableVariant:
    return PublishableVariant(
        external_id=variant.external_id,
        sku=variant.sku,
        title=variant.title,
        price=variant.price.amount if variant.price else None,
        currency=variant.price.currency if variant.price else None,
        options=dict(variant.options),
        gtin=_gtin(variant.barcode),
        in_stock=variant.in_stock if may_assert_availability else None,
        # `stock_quantity` is deliberately absent from PublishableVariant
        # entirely, rather than dropped here. It is commercially sensitive, it is
        # stale the moment it is written, and no consumer of a feed needs it —
        # so there is no field for a future edit to populate by accident.
    )


def _currency(product: Product) -> str | None:
    """The product's currency, if it has exactly one.

    A price range is only meaningful within one currency, and a product whose
    variants disagree gets `None` here rather than the first one found. The
    renderers then fall back to per-variant offers, which carry their own
    currency and cannot be wrong.
    """
    codes = {v.price.currency for v in product.variants if v.price}
    for money in (product.price_range_min, product.price_range_max):
        if money:
            codes.add(money.currency)
    return codes.pop() if len(codes) == 1 else None


def _gtin(barcode: str | None) -> str | None:
    """A barcode only if it is actually a GTIN. Otherwise nothing."""
    if barcode is None:
        return None
    cleaned = barcode.strip().replace("-", "").replace(" ", "")
    return cleaned if _GTIN.match(cleaned) else None


__all__ = ["PublishableProduct", "PublishableVariant", "is_publishable", "publishable"]
