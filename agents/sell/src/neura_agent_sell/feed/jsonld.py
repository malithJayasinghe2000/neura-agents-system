"""Renderer 2 — Schema.org ``Product``, as JSON-LD.

The rendering crawlers and answer engines actually read. `canonical.py` is
complete; this one is *understood*, and being understood is the entire point of
[blueprint §4.1](../../../../../docs/business/blueprint-v2.md) — a store that is
not machine-readable is invisible to the channel that buys through agents.

**This is a rendering, not a second source of truth** (ADR-0023). It reads a
:class:`FeedDocument` and nothing else. If Schema.org changed tomorrow, this
file changes and nothing upstream of it does.

## Three mapping decisions worth stating

**`offers` is a list of `Offer`, one per priced variant — not an `AggregateOffer`.**
An `AggregateOffer` carries a single `priceCurrency`, so a product whose
variants are priced in two currencies cannot be expressed as one without
choosing a currency on the merchant's behalf. A list of offers cannot be wrong
about that, because each offer carries its own. It is also what a consumer needs
in order to answer "do you have it in a UK 9, and how much" — the question
`sell.md` names as the one a size-level answer exists for.

**`availability` is emitted only when it is a fact.** `PublishableVariant.in_stock`
is tri-state and the third state is *not asserted* — no live inventory feed, or
a stale sync. Schema.org has no vocabulary for "we do not know", and the nearest
words (`OutOfStock`, `Discontinued`) are both claims. So the property is absent,
which is the only honest rendering available.

**There is no `aggregateRating`, and there never will be from here.** We hold no
review data. Synthesising ratings into a document that search engines read is
precisely the fake-review problem [blueprint §5.5](../../../../../docs/business/blueprint-v2.md)
describes GUARD as *detecting*, and it would be rich to ship it ourselves.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from neura_agent_sell.feed.document import FeedDocument
from neura_agent_sell.feed.publishable import PublishableProduct, PublishableVariant

CONTEXT = "https://schema.org"

#: JSON-LD's own media type. Serving it as `application/json` works and is worse:
#: a consumer that content-negotiates gets no signal that the payload is linked
#: data, and some crawlers use exactly that signal to decide whether to parse it.
MEDIA_TYPE = "application/ld+json"

IN_STOCK = "https://schema.org/InStock"
OUT_OF_STOCK = "https://schema.org/OutOfStock"


def render(document: FeedDocument) -> dict[str, Any]:
    """The catalogue as an ``ItemList`` of ``Product`` nodes.

    An `ItemList` rather than a bare array: a JSON-LD document needs one root
    node to carry `@context`, and a consumer following `nextPage` needs
    somewhere for that link to live.
    """
    body: dict[str, Any] = {
        "@context": CONTEXT,
        "@type": "ItemList",
        "numberOfItems": len(document.products),
        "itemListElement": [
            {"@type": "ListItem", "position": i, "item": _product(p)}
            for i, p in enumerate(document.products, start=1)
        ],
    }

    if document.store_name:
        body["name"] = document.store_name

    # `dateModified` on the list, from the data. Not a serve-time stamp — see
    # `document.py` for why that is derived rather than passed.
    if document.synced_at:
        body["dateModified"] = document.synced_at.isoformat()

    if document.next_cursor:
        body["nextPage"] = document.next_cursor

    return body


def _product(product: PublishableProduct) -> dict[str, Any]:
    body: dict[str, Any] = {
        "@type": "Product",
        # The merchant's own id. `productID` is the Schema.org property for
        # exactly this, and it is what lets a merchant reconcile a feed against
        # their admin. Our internal ids are not in `PublishableProduct` at all.
        "productID": product.product_id,
        "name": product.title,
    }

    if product.description:
        body["description"] = product.description
    if product.url:
        body["url"] = product.url
    if product.image_urls:
        # Schema.org accepts one or many; emitting a bare string for the single
        # case saves a consumer an isinstance check they would otherwise get
        # wrong exactly once.
        body["image"] = (
            product.image_urls[0] if len(product.image_urls) == 1 else list(product.image_urls)
        )

    if offers := _offers(product):
        body["offers"] = offers[0] if len(offers) == 1 else offers

    return body


def _offers(product: PublishableProduct) -> list[dict[str, Any]]:
    """One ``Offer`` per priced variant, or one for the product itself.

    A product with no variants but a price range is a real shape — some
    platforms carry price at product level only — and it still deserves an
    offer, or the item is published with no price and is useless to every
    consumer that reads this document.
    """
    offers = [_offer(v) for v in product.variants if v.price is not None and v.currency]

    if offers:
        return offers

    if product.price_min is not None and product.currency:
        offer: dict[str, Any] = {
            "@type": "Offer",
            "price": _money(product.price_min),
            "priceCurrency": product.currency,
        }
        # A genuine range at product level. `AggregateOffer` is safe here, where
        # a single currency has already been established — `_currency()` returns
        # `None` the moment the variants disagree.
        if product.price_max is not None and product.price_max != product.price_min:
            offer = {
                "@type": "AggregateOffer",
                "lowPrice": _money(product.price_min),
                "highPrice": _money(product.price_max),
                "priceCurrency": product.currency,
            }
        return [offer]

    return []


def _offer(variant: PublishableVariant) -> dict[str, Any]:
    body: dict[str, Any] = {
        "@type": "Offer",
        "price": _money(variant.price),
        "priceCurrency": variant.currency,
    }

    if variant.sku:
        body["sku"] = variant.sku
    if variant.gtin:
        # Already validated as 8/12/13/14 digits in `publishable.py`. A
        # malformed `gtin` gets the *item* rejected by consumers, so the check
        # happens before publication rather than in a report afterwards.
        body["gtin"] = variant.gtin
    if variant.title:
        body["name"] = variant.title

    # Absent when unknown. See the module docstring: Schema.org has no word for
    # "we do not know", and both of its nearest words are claims.
    if variant.in_stock is not None:
        body["availability"] = IN_STOCK if variant.in_stock else OUT_OF_STOCK

    return body


def _money(amount: Decimal | None) -> str:
    """Schema.org prices as strings, for the reason `canonical.py` gives.

    Google's own structured-data guidance asks for a plain decimal string with
    no currency symbol and no thousands separator, which is what `str(Decimal)`
    produces and what a float would not.
    """
    return str(amount)


__all__ = ["CONTEXT", "IN_STOCK", "MEDIA_TYPE", "OUT_OF_STOCK", "render"]
