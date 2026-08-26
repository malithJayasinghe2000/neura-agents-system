"""Renderer 1 — our own model, as JSON.

The rendering that cannot go stale relative to the domain, and the one to reach
for when a consumer wants everything we know rather than everything Schema.org
has a word for.

It is **not** `model_dump()` of anything canonical. It renders a
:class:`PublishableProduct`, which is already the allowlist — see
`publishable.py` for why that is a type rather than an `exclude=` argument.

Money is rendered as a **string**, not a JSON number. `1099.90` in IEEE-754 is
not `1099.90`, and a consumer parsing this into a float has already lost the
merchant's price by the time they display it. Every price in this document is a
string a decimal parser can read exactly, which is the same call
`neura-domain` makes by refusing to accept a float into `Money` at all.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from neura_agent_sell.feed.document import FeedDocument
from neura_agent_sell.feed.publishable import PublishableProduct, PublishableVariant

#: Bumped when the shape changes in a way a consumer must notice. Additive
#: changes do not bump it, matching api-design.md §11 — a client is required to
#: tolerate fields it does not recognise, and is entitled to assume the ones it
#: does keep meaning what they meant.
SCHEMA_VERSION = "1.0"

MEDIA_TYPE = "application/json"


def render(document: FeedDocument) -> dict[str, Any]:
    """One tenant's publishable catalogue, in our own vocabulary."""
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        # `None` for an empty document rather than a date invented to fill the
        # field. See `FeedDocument.synced_at`.
        "synced_at": document.synced_at.isoformat() if document.synced_at else None,
        "product_count": len(document.products),
        # Stated rather than left to be inferred from the absence of the field
        # on every variant. A consumer that guesses will guess that a catalogue
        # with no availability data is a catalogue that is out of stock.
        "availability_asserted": document.availability_asserted,
        "products": [_product(p) for p in document.products],
    }

    if document.store_name:
        body["store_name"] = document.store_name
    if document.next_cursor:
        body["next_cursor"] = document.next_cursor

    return body


def _product(product: PublishableProduct) -> dict[str, Any]:
    body: dict[str, Any] = {
        "product_id": product.product_id,
        "title": product.title,
        "synced_at": product.synced_at.isoformat(),
    }

    _put(body, "description", product.description)
    _put(body, "url", product.url)
    _put(body, "image_urls", product.image_urls or None)
    _put(body, "currency", product.currency)
    _put(body, "price_min", _money(product.price_min))
    _put(body, "price_max", _money(product.price_max))
    _put(body, "variants", [_variant(v) for v in product.variants] or None)

    return body


def _variant(variant: PublishableVariant) -> dict[str, Any]:
    body: dict[str, Any] = {"variant_id": variant.external_id}

    _put(body, "sku", variant.sku)
    _put(body, "title", variant.title)
    _put(body, "price", _money(variant.price))
    _put(body, "currency", variant.currency)
    _put(body, "options", variant.options or None)
    _put(body, "gtin", variant.gtin)

    # Written only when it is a fact. `None` means the store declares no live
    # inventory feed or the sync is stale, and an absent key says "not asserted"
    # in a way `false` cannot.
    if variant.in_stock is not None:
        body["in_stock"] = variant.in_stock

    return body


def _money(amount: Decimal | None) -> str | None:
    """A price a decimal parser reads exactly. Never a JSON number."""
    return None if amount is None else str(amount)


def _put(body: dict[str, Any], key: str, value: Any) -> None:
    """Omit rather than emit null.

    A feed full of explicit nulls is larger, harder to read, and invites a
    consumer to treat "we hold no description" as "the description is empty".
    """
    if value is not None:
        body[key] = value


__all__ = ["MEDIA_TYPE", "SCHEMA_VERSION", "render"]
