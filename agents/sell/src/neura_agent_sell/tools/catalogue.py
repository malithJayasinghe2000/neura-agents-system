"""Catalogue lookups — what the store sells, and whether it can actually be bought.

Four tools, kept separate rather than folded into one clever `ask_the_catalogue`:
search finds candidates, details expands one, stock answers the question that
decides a sale, and categories say what the store carries at all. Each maps to a
capability a store declares independently, so a store with no live inventory
feed keeps the first two and simply never gets the third.

Nothing here is scoped to a person — a catalogue is public — so none declares
``requires_ownership`` or ``pii_output``. That is the honest declaration, and
over-declaring would be its own bug: marking a public search as PII-bearing
would evict it from the semantic cache for no reason and make the flag
meaningless where it matters.

**Read live, deliberately.** These reach the merchant's store rather than the
synced copy, which is the difference between this surface and the feed. A feed
is cached and may be an hour old; an agent about to recommend a purchase is
making a claim about *now*, and stock is the field that goes stale fastest.
"""

from __future__ import annotations

from neura_agent_core.tools import ToolContext, tool
from neura_agent_sell.tools.render import (
    candidate,
    category_evidence,
    inventory_evidence,
    product_evidence,
)
from neura_commerce import ProductQuery
from neura_core import get_logger
from neura_domain import Capability, ProductStatus

log = get_logger(__name__)

#: Candidates per search. A shortlist a shopper reads in a chat window, and a
#: ceiling on how much of a small model's context one lookup can consume.
MAX_RESULTS = 5

#: Variants checkable in one call. Bounded because the argument comes from a
#: model — or, over MCP, from *someone else's* model — and an unbounded list is
#: a way to turn one request into an expensive query against a merchant's store.
MAX_VARIANTS = 20


@tool(
    name="search_products",
    description=(
        "Search this store's catalogue and return candidate products with their prices, "
        "availability and options. Use when the shopper describes what they need rather "
        "than naming a product. Returns the store's own data — never describe a product "
        "that does not appear in the results."
    ),
    requires=[Capability.PRODUCT_SEARCH],
    scopes=["sell:catalogue:read"],
)
async def search_products(query: str, ctx: ToolContext) -> str:
    """Find candidates for a need."""
    text = query.strip()
    if not text:
        return "No search terms were given, so the catalogue was not searched."

    page = await ctx.adapter.search_products(ProductQuery(text=text, limit=MAX_RESULTS))
    products = list(page.items)[:MAX_RESULTS]

    # Withdrawn products are dropped here rather than named, which is the
    # opposite of what CARE does — and the difference is deliberate.
    #
    # CARE is answering *about* a product the shopper already found, so "that
    # one was withdrawn" is the useful answer. SELL is building a shortlist of
    # things to buy, and a shortlist is a set of recommendations: putting an
    # unbuyable product on one is recommending it.
    sellable = [p for p in products if p.status is ProductStatus.ACTIVE]

    if not sellable:
        # Said precisely. "No candidates" is not "this store sells nothing like
        # that" — one is about this query, the other is a claim about the whole
        # catalogue, and only `shortlist` may make the second one (sell.md §2.3).
        return (
            f"The catalogue returned no available products matching {text!r}. "
            "This is one search, not a statement about what the store carries."
        )

    log.info(
        "sell_product_search",
        tenant_id=ctx.tenant_id,
        results=len(sellable),
        withheld=len(products) - len(sellable),
    )
    return "\n\n".join(candidate(product) for product in sellable)


@tool(
    name="get_product_details",
    description=(
        "Get one product in full — description, price, every variant and its "
        "availability — by its product id. Use to confirm a candidate before "
        "recommending it, or to compare two products the shopper named."
    ),
    requires=[Capability.PRODUCT_READ],
    scopes=["sell:catalogue:read"],
)
async def get_product_details(product_ref: str, ctx: ToolContext) -> str:
    """One product in full."""
    ref = product_ref.strip()
    product = await ctx.adapter.get_product(ref)

    if product is None:
        return (
            f"The store has no product with id {ref!r}. Do not describe a product "
            "from memory — search the catalogue instead."
        )

    if product.status is not ProductStatus.ACTIVE:
        return (
            f"{product.title} is not currently on sale in this store. Do not "
            "recommend it, quote its price, or state that it is available."
        )

    return product_evidence(product)


@tool(
    name="check_stock",
    description=(
        "Check whether specific product variants can be bought right now, by their "
        "variant ids. Use before recommending a specific size, colour or configuration."
    ),
    requires=[Capability.INVENTORY_READ],
    scopes=["sell:catalogue:read"],
)
async def check_stock(variant_refs: list[str], ctx: ToolContext) -> str:
    """Live stock levels.

    Read live rather than from the synced copy. Recommending something that is
    gone is the failure that costs the merchant twice — a shopper who does not
    get what they were promised, and a support ticket explaining why.
    """
    requested = [ref.strip() for ref in variant_refs if ref.strip()][:MAX_VARIANTS]
    if not requested:
        return "No variant ids were given, so stock was not checked."

    levels = await ctx.adapter.get_inventory(requested)
    return inventory_evidence(levels, requested)


@tool(
    name="list_categories",
    description=(
        "List the categories this store sells in. Use to establish what the store "
        "carries at all — particularly before telling a shopper it does not sell "
        "something."
    ),
    requires=[Capability.CATEGORY_READ],
    scopes=["sell:catalogue:read"],
)
async def list_categories(ctx: ToolContext) -> str:
    """What this store carries.

    Takes no arguments, and that is not an accident of scope: there is nothing
    for a caller to narrow, so there is nothing an injected instruction could
    put here. A tool with no arguments has no argument to poison.
    """
    categories = await ctx.adapter.list_categories()
    return category_evidence(list(categories))
