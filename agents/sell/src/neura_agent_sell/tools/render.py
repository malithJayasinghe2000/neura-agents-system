"""Turning catalogue entities into evidence a recommendation can be built on.

CARE's `render.py` has the same job and a different emphasis, and the difference
is the whole distinction between the two agents.

CARE renders a product so a **fact** about it can be checked. SELL renders one
so a **suitability claim** can be attributed to something — which is the harder
problem, and the reason open question **A9** is load-bearing here rather than
occasional. `verify` asks whether a claim appears in the evidence, and *"good
for winter hiking"* never appears in a record that says *"waterproof, 3-layer"*.

So the rule specific to this file: **render the attributes, not a summary of
them.** A variant's options, the materials in a description, the price and the
availability are what a claim can point at. A rendering that helpfully
paraphrased "waterproof, taped seams, 10,000mm" as "very weatherproof" would
have destroyed the only thing an attribution could be made against.

The two rules inherited from CARE's renderer hold unchanged, because they are
about honesty rather than about orders:

* **Absence is stated, never omitted.** A product with no description renders
  "no description published", not silence. Silence is a gap a model fills with
  something plausible; a stated absence is something `verify` can catch an
  invention *with*.
* **Numbers are copied, never restated.** A price keeps its currency and its
  trailing zeros, because a model that sees "about twenty-five pounds" has no
  way back to what the store actually charges.
"""

from __future__ import annotations

from neura_domain import Category, InventoryLevel, Money, Product, ProductVariant

#: Descriptions run long and a local model's context is the scarce resource
#: (llm-abstraction.md §9). Truncation is marked, so the model can see it is
#: reading a fragment rather than assume the attribute it needs was absent.
MAX_DESCRIPTION_CHARS = 600

#: Variants shown per product in a shortlist. A shoe in twelve sizes should not
#: crowd out the other four candidates.
MAX_VARIANTS_SHOWN = 8


def candidate(product: Product) -> str:
    """One product as a shortlist entry — enough to justify recommending it.

    Deliberately richer than CARE's `product_summary`. A shortlist entry has to
    carry the attributes a suitability claim will be attributed to, and a
    title-and-price line carries none of them.
    """
    parts = [
        f"Product {product.external_id}: {product.title}",
        f"  price: {_price_range(product)}",
        f"  availability: {_availability(product)}",
    ]

    if description := _description(product):
        parts.append(f"  description: {description}")
    else:
        # Stated, because it is the reason a recommendation may be weak. A model
        # told the description is missing can say it is going on the title
        # alone; a model shown nothing invents the attributes it wishes it had.
        parts.append("  description: none published by this store")

    if options := _option_summary(product):
        parts.append(f"  available options: {options}")

    return "\n".join(parts)


def product_evidence(product: Product) -> str:
    """One product in full, for a comparison or a details lookup."""
    parts = [candidate(product)]

    if not product.variants:
        parts.append("  variants: none — this product is sold as a single item")
        return "\n".join(parts)

    parts.append(f"  variants ({len(product.variants)}):")
    for variant in product.variants[:MAX_VARIANTS_SHOWN]:
        parts.append(f"    {_variant(variant)}")

    if len(product.variants) > MAX_VARIANTS_SHOWN:
        hidden = len(product.variants) - MAX_VARIANTS_SHOWN
        # Named rather than silently dropped: a model that cannot see the rest
        # must not conclude they do not exist and tell a shopper so.
        parts.append(f"    ({hidden} more not shown — do not state that they are unavailable)")

    return "\n".join(parts)


def inventory_evidence(levels: list[InventoryLevel], requested: list[str]) -> str:
    """Live stock, including for the variants the store said nothing about.

    A variant the store did not answer for is reported as *unknown*, never as
    out of stock. The two are different claims and only one of them is
    supported — and "we don't have it" loses a sale the merchant could have had.
    """
    by_id = {level.variant_external_id: level for level in levels}
    lines = []

    for ref in requested:
        level = by_id.get(ref)
        if level is None:
            lines.append(f"{ref}: availability unknown — the store did not report on this variant")
        elif level.in_stock:
            lines.append(f"{ref}: in stock")
        else:
            lines.append(f"{ref}: out of stock")

    return "\n".join(lines)


def category_evidence(categories: list[Category]) -> str:
    """What this store actually carries.

    The evidence behind an honest "we do not sell that". A `no_match` reply that
    can name what the store *does* carry is useful; one that cannot is a dead
    end, which is why `CATEGORY_READ` degrades that node rather than the agent.
    """
    if not categories:
        return (
            "This store publishes no category list. Do not infer what it does or "
            "does not sell from the absence of one."
        )
    return "This store's categories: " + ", ".join(sorted(c.name for c in categories))


def _variant(variant: ProductVariant) -> str:
    parts = [variant.external_id]

    if options := ", ".join(f"{k}: {v}" for k, v in sorted(variant.options.items())):
        parts.append(options)
    elif variant.title:
        parts.append(variant.title)

    parts.append(_money(variant.price))

    # Tri-state, and the third state is stated. `None` means the store declares
    # no live inventory feed — not that the variant is unavailable.
    if variant.in_stock is True:
        parts.append("in stock")
    elif variant.in_stock is False:
        parts.append("out of stock")
    else:
        parts.append("stock unknown")

    return " — ".join(parts)


def _description(product: Product) -> str:
    text = (product.description or "").strip()
    if not text:
        return ""
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    return text[:MAX_DESCRIPTION_CHARS] + " […truncated]"


def _option_summary(product: Product) -> str:
    """Which options this product varies on — **and which of them can be bought.**

    Rendered at product level as well as per variant because "does it come in a
    UK 9" is answerable from this line alone, and a shortlist that answers it
    without a second lookup survives a single-pass graph (open question A7).

    **Each value carries its stock state, and the first version did not.**
    Measured on SELL's first eval run: this line read `size: UK 8, UK 9`, and
    the model answered *"available in UK 9"* about a variant the fixture holds
    out of stock. It was not hallucinating — it was reading a list of *options*
    as a list of *availability*, which is exactly what that line looked like.

    That is the failure `sell.md` §1.3 calls the one that costs a return, and
    the fix belongs in the rendering rather than the prompt: a model shown
    "UK 9 (out of stock)" cannot make the mistake, and a model shown "UK 9" and
    told to be careful still can.
    """
    seen: dict[str, list[str]] = {}
    for variant in product.variants:
        label = _option_label(variant)
        for key, value in variant.options.items():
            values = seen.setdefault(key, [])
            rendered = f"{value}{label}"
            if rendered not in values:
                values.append(rendered)

    return "; ".join(f"{key}: {', '.join(values)}" for key, values in sorted(seen.items()))


def _option_label(variant: ProductVariant) -> str:
    """The stock state to append to one option value.

    Nothing is appended when a variant is in stock: the common case stays
    readable, and an unmarked value is the one a model may offer. Absence is
    marked — the same rule the module docstring states, applied to the field a
    shopper acts on.
    """
    if variant.in_stock is True:
        return ""
    if variant.in_stock is False:
        return " (out of stock)"
    return " (stock unknown)"


def _price_range(product: Product) -> str:
    low, high = product.price_range_min, product.price_range_max

    if low is None and high is None:
        priced = [v.price for v in product.variants if v.price]
        if not priced:
            return "no price published"
        low = min(priced, key=lambda m: m.amount)
        high = max(priced, key=lambda m: m.amount)

    if low is not None and high is not None and low.amount != high.amount:
        return f"{_money(low)} to {_money(high)}"
    return _money(low or high)


def _availability(product: Product) -> str:
    states = {v.in_stock for v in product.variants}

    if not states or states == {None}:
        return "unknown — this store does not report live stock"
    if states == {True}:
        return "in stock"
    if states == {False}:
        return "out of stock"
    if True in states:
        return "some options in stock, some not"
    return "unknown"


def _money(money: Money | None) -> str:
    """Copied, never restated. The currency travels with the number."""
    return "no price published" if money is None else f"{money.amount} {money.currency}"


__all__ = [
    "MAX_DESCRIPTION_CHARS",
    "MAX_VARIANTS_SHOWN",
    "candidate",
    "category_evidence",
    "inventory_evidence",
    "product_evidence",
]
