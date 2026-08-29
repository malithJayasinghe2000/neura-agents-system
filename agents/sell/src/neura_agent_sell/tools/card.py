"""A product as a shopper sees it — fields only, never markup. [ADR-0030]

`render.py` turns a product into evidence **for a model**: prose that justifies a
recommendation. This turns the same product into a handful of values **for a
person**: what it is, what it costs, whether it can be bought, and where it
lives.

**Nothing here is HTML.** The widget owns every tag and every attribute; this
supplies the blanks it fills in, as inert strings. The rule that makes the whole
design safe is that a merchant's product description is arbitrary text they
typed, and text placed with `textContent` cannot become code no matter what it
contains — the failure `guard/injection.py` already records as live in the wild
([S6](../../../../../docs/open-questions.md)).

The two fields that are not inert are `url` and `image`, because a browser
*resolves* them. They are the whole security surface of this module, and
:func:`_safe_url` is the whole answer to it.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from neura_domain import Product, ProductStatus

#: Schemes a browser may be handed. `javascript:` and `data:` execute; `http`
#: is accepted because a merchant on a plain-HTTP storefront is a merchant with
#: a worse problem than this, and silently dropping their links would hide it.
_SAFE_SCHEMES = frozenset({"https", "http"})


def product_card(product: Product) -> dict[str, str] | None:
    """One product as display fields, or ``None`` if it cannot be shown.

    Returns ``None`` for a product with no id or no title: a card with nothing
    to name is a grey box, and a shopper reads a grey box as a broken site
    rather than as a missing field.
    """
    if not (product.external_id and product.title):
        return None

    card: dict[str, str] = {
        "id": str(product.external_id),
        "title": str(product.title),
        "in_stock": "true" if _in_stock(product) else "false",
    }

    if price := product.price_range_min:
        card["price"] = str(price.amount)
        card["currency"] = str(price.currency)

    # Absent, not empty. A missing image is normal — the test shop publishes
    # `image_urls: []` for every product, and a card design that needs one is a
    # design that breaks on the first real merchant.
    if url := _safe_url(product.url):
        card["url"] = url
    if product.image_urls and (image := _safe_url(product.image_urls[0])):
        card["image"] = image

    return card


def _in_stock(product: Product) -> bool:
    """Can any variant of this actually be bought?

    The same call `render.py` makes for the model, kept in step deliberately: a
    card that says "In stock" beside prose that says otherwise is worse than
    either alone.
    """
    if product.status is not ProductStatus.ACTIVE:
        return False
    return any(variant.in_stock for variant in product.variants) if product.variants else True


def _safe_url(raw: object) -> str:
    """A URL a browser may be handed, or an empty string.

    **The only place in this feature where merchant data becomes something a
    browser resolves**, so it fails closed: anything that is not plain
    `http`/`https` with a host is dropped, and the card renders without it.

    `javascript:alert(1)` in a product URL is the obvious attack and the least
    likely; `data:text/html,…` is the one that gets written by a tool rather
    than by a person. Neither has a host, and neither survives this.
    """
    if not raw:
        return ""
    try:
        parts = urlsplit(str(raw).strip())
    except ValueError:
        return ""
    if parts.scheme.lower() not in _SAFE_SCHEMES or not parts.netloc:
        return ""
    return parts.geturl()


__all__ = ["product_card"]
