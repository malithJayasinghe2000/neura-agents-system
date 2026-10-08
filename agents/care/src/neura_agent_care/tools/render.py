"""Turning canonical entities into the evidence a model may answer from.

A tool's return value *is* the evidence. It is what the composer drafts from and
what ``verify`` checks the draft against, so how an entity is rendered decides
what the agent can and cannot truthfully say.

**The rule that shapes every function here: absence is stated, never omitted.**

An order with no tracking number renders "no tracking number recorded yet", not
silence. The two look the same to a reader and are completely different to a
model: silence is a gap it will fill with something plausible, and "your parcel
is with the courier, tracking XY123" is exactly the confident wrong answer this
system is arranged against. Saying it plainly also gives ``verify`` something to
catch the invention *with* — a draft claiming a tracking number is then visibly
contradicted by the evidence rather than merely unsupported by it.

The second rule is narrower and follows from the first: **numbers are copied,
never restated.** A date is rendered as the store gave it and a total keeps its
currency, because a model that sees "arriving in 3 days" has no way back to the
date the store actually holds.
"""

from __future__ import annotations

from datetime import datetime

from neura_domain import (
    Fulfillment,
    InventoryLevel,
    Money,
    Order,
    Policy,
    Product,
)

#: Policy bodies are long and a local model's context is the scarce resource
#: (llm-abstraction.md §9). Truncation is marked, so the model can see that it is
#: reading a fragment and offer to pass the shopper on rather than assume the
#: rule it needs was in the part it got.
MAX_POLICY_CHARS = 1200

#: Enough lines for a shopper to recognise their order without pasting an
#: invoice into a chat window.
MAX_ORDER_LINES = 8


def order_evidence(order: Order) -> str:
    """One order, as the agent may describe it."""
    parts = [
        f"Order {order.order_number}",
        f"  status: {order.status.value}",
        f"  payment: {order.payment_status.value}",
        f"  fulfilment: {order.fulfillment_status.value}",
        f"  placed: {_date(order.placed_at)}",
        f"  total: {_money(order.total)}",
    ]

    if order.cancelled_at is not None:
        parts.append(f"  cancelled: {_date(order.cancelled_at)}")

    parts.append(_lines(order))
    parts.append(_shipping(order))

    # An UNKNOWN status means the store used a word we could not map, not that
    # the order is in limbo. Saying so stops the model reporting "unknown" to a
    # shopper as though it were a state their parcel is in.
    if order.status.value == "unknown":
        parts.append(
            "  note: this store reports a status this system does not recognise; "
            "do not describe the order's progress from it"
        )

    return "\n".join(parts)


def _lines(order: Order) -> str:
    if not order.lines:
        return "  items: none recorded on this order"

    shown = order.lines[:MAX_ORDER_LINES]
    # "2 x Shoe" reads as part of a product name to a model; the multiplication
    # sign does not. Ruff flags it as an ambiguous character, which is the right
    # default for identifiers and the wrong one for text a model reads.
    rendered = "; ".join(f"{line.quantity} × {line.title}" for line in shown)  # noqa: RUF001
    if len(order.lines) > MAX_ORDER_LINES:
        rendered += f"; and {len(order.lines) - MAX_ORDER_LINES} more item(s)"
    return f"  items: {rendered}"


def _shipping(order: Order) -> str:
    if not order.fulfillments:
        return "  shipment: nothing has been dispatched for this order yet"
    return "\n".join(f"  shipment: {_fulfillment(f)}" for f in order.fulfillments)


def _fulfillment(fulfillment: Fulfillment) -> str:
    carrier = fulfillment.carrier or "carrier not recorded"
    tracking = fulfillment.tracking_number or "no tracking number recorded yet"
    parts = [
        f"{fulfillment.status.value} via {carrier}",
        f"tracking {tracking}",
        f"shipped {_date(fulfillment.shipped_at)}",
    ]

    # Delivered and estimated are rendered separately and only when present. An
    # estimate presented as an arrival is the commonest way a support answer
    # becomes a broken promise.
    if fulfillment.delivered_at is not None:
        parts.append(f"delivered {_date(fulfillment.delivered_at)}")
    if fulfillment.estimated_delivery is not None:
        parts.append(f"estimated delivery {_date(fulfillment.estimated_delivery)}")
    else:
        parts.append("no delivery estimate available")

    return ", ".join(parts)


def order_summary(order: Order) -> str:
    """A one-line form, for listing several orders at once."""
    return (
        f"Order {order.order_number}: {order.status.value}, "
        f"placed {_date(order.placed_at)}, total {_money(order.total)}"
    )


def product_evidence(product: Product) -> str:
    """One product, with its price and availability stated explicitly."""
    parts = [
        f"Product {product.external_id}: {product.title}",
        f"  availability: {_availability(product)}",
        f"  price: {_price_range(product)}",
    ]

    if product.description:
        parts.append(f"  description: {product.description.strip()}")
    else:
        parts.append("  description: none published for this product")

    if product.variants:
        parts.append(f"  variants: {_variants(product)}")

    if product.url:
        parts.append(f"  url: {product.url}")

    return "\n".join(parts)


def product_summary(product: Product) -> str:
    """A search-result line. Short enough that five of them fit a small context."""
    return (
        f"{product.external_id}: {product.title} — "
        f"{_price_range(product)}, {_availability(product)}"
    )


def _variants(product: Product) -> str:
    rendered = []
    for variant in product.variants[:10]:
        label = variant.title or variant.sku or variant.external_id
        options = ", ".join(f"{k}={v}" for k, v in sorted(variant.options.items()))
        stock = "in stock" if variant.in_stock else "out of stock"
        if variant.in_stock is None:
            stock = "stock unknown"
        rendered.append(
            f"{variant.external_id} ({label}{'; ' + options if options else ''}) {stock}"
        )
    if len(product.variants) > 10:
        rendered.append(f"and {len(product.variants) - 10} more")
    return " | ".join(rendered)


def _availability(product: Product) -> str:
    """Never guessed from stock, and never softened.

    ``UNKNOWN`` is reported as unknown rather than assumed available. A shopper
    told an item is in stock when the store never said so is the same failure as
    an invented tracking number, one aisle over.

    **The wording of this line is load-bearing, and the first version got it
    wrong.** It read "on sale", meaning *offered for sale* — and against the real
    shop the agent duly told a shopper the shoe was "available now at $132.00 and
    currently on sale", which in every high street in the language means
    discounted. The evidence was accurate, the answer was grounded in it, and the
    shopper would have gone looking for a discount that does not exist.

    Nothing but reading the output catches that: no assertion fails, because
    nothing is false. Evidence is read by a model that will paraphrase it, so a
    phrase with two meanings will eventually be published in the wrong one.

    **And it happened again, with stock.** "available to buy" was decided from
    the status alone, and a search-result line carries nothing else — so a
    connected shop's sold-out cardamom was rendered "available to buy" and the
    agent told a shopper *"Yes, we have it"*, with the fact check passing,
    because the reply matched its evidence (CONNECTING_A_NEW_SHOP_LOG.md G35).
    An active product is now available to buy only when a variant is in stock;
    sold out and unreported are said in words that cannot be read as "yes".
    """
    if product.status.value == "unknown":
        return "this store did not report a status for this product"
    if product.status.value != "active":
        return f"not available to buy ({product.status.value})"

    stock = [variant.in_stock for variant in product.variants]
    if any(state is True for state in stock):
        return "available to buy, in stock"
    if stock and all(state is False for state in stock):
        return "listed for sale but out of stock, so it cannot be bought right now"
    return "listed for sale; this store did not report whether it is in stock"


def _price_range(product: Product) -> str:
    low, high = product.price_range_min, product.price_range_max
    if low is None and high is None:
        return "no price published"
    if low is not None and high is not None and low != high:
        return f"{_money(low)} to {_money(high)}"
    return _money(low or high)


def inventory_evidence(levels: list[InventoryLevel], requested: list[str]) -> str:
    """Stock for the variants that were asked about.

    A variant the store did not return is named as *not answered* rather than
    dropped. Omission would read to the model as "nothing in stock", and telling
    a shopper an available item is sold out costs the merchant a sale as surely
    as the reverse costs them trust.
    """
    if not levels:
        return f"The store returned no stock information for: {', '.join(requested)}"

    by_id = {level.variant_external_id: level for level in levels}
    parts = []
    for variant_id in requested:
        level = by_id.get(variant_id)
        if level is None:
            parts.append(f"{variant_id}: the store returned no stock record for this variant")
            continue
        state = "in stock" if level.in_stock else "out of stock"
        location = f" at {level.location}" if level.location else ""
        parts.append(f"{variant_id}: {state}, quantity {level.quantity}{location}")

    return "\n".join(parts)


def policy_evidence(policy: Policy) -> str:
    """One policy page. Truncation is marked so a fragment is not read as the whole."""
    body = policy.body.strip()
    truncated = len(body) > MAX_POLICY_CHARS
    if truncated:
        body = body[:MAX_POLICY_CHARS].rstrip()

    parts = [f"Policy: {policy.title} ({policy.kind.value})", body]
    if truncated:
        parts.append(
            "[This policy text is truncated. Do not state a rule that would depend "
            "on the part not shown.]"
        )
    if policy.url:
        parts.append(f"Source: {policy.url}")

    return "\n".join(parts)


def _money(value: Money | None) -> str:
    return str(value) if value is not None else "not recorded"


def _date(value: datetime | None) -> str:
    """ISO date, copied rather than described.

    "3 days ago" cannot be turned back into a date by anything downstream, and a
    model handed a relative phrase will happily produce a different one.
    """
    return value.date().isoformat() if value is not None else "not recorded"
