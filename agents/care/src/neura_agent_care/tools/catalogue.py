"""Catalogue lookups — what the store sells, for how much, and whether it is there.

Three tools, deliberately separate rather than one clever ``ask_the_catalogue``:
search finds candidates, details expands one, stock answers the question a
shopper actually cares about before they buy. Each maps to a capability a store
declares independently, so a store with no live inventory feed keeps the first
two and simply never gets the third.

Nothing here is scoped to a person — a catalogue is public — so none of these
declares ``requires_ownership`` or ``pii_output``. That is the honest
declaration, and over-declaring would be its own bug: marking a public product
search as PII-bearing would evict it from the semantic cache for no reason and
make the flag meaningless where it matters.
"""

from __future__ import annotations

from neura_agent_care.tools.render import inventory_evidence, product_evidence, product_summary
from neura_agent_core.tools import ToolContext, tool
from neura_commerce import ProductQuery
from neura_core import get_logger
from neura_domain import Capability, ProductStatus

log = get_logger(__name__)

#: Five results, matching the retrieval limit. A local model's context is the
#: scarce resource, and a shopper reading a chat window wants a shortlist.
MAX_RESULTS = 5

#: How many variants a shopper may ask about in one go. Bounded because the
#: argument comes from a model and an unbounded list is a way to make one chat
#: turn into an expensive query against a merchant's store.
MAX_VARIANTS = 10


@tool(
    name="search_products",
    description=(
        "Search the store's catalogue by keywords and return matching products with "
        "their prices and availability. Use when the shopper asks what the store sells "
        "or describes what they are looking for."
    ),
    requires=[Capability.PRODUCT_SEARCH],
    scopes=["care:catalogue:read"],
)
async def search_products(query: str, ctx: ToolContext) -> str:
    """Keyword search over the catalogue."""
    text = query.strip()
    if not text:
        return "No search terms were given, so the catalogue was not searched."

    page = await ctx.adapter.search_products(ProductQuery(text=text, limit=MAX_RESULTS))
    products = list(page.items)[:MAX_RESULTS]

    # Only products the shop itself shows. An ARCHIVED product is withdrawn and a
    # DRAFT one is not released yet; neither is on the shop's own pages, which is
    # the same line the retrieval index and SELL draw. A draft used to be listed
    # here, and CARE told a shopper about an unreleased product and its price
    # (CONNECTING_A_NEW_SHOP_LOG.md G37 — the owner: "this product is not in the
    # product list in our shop"). A withdrawn product asked about by id is still
    # named as withdrawn, by `get_product_details`, because the shopper may be
    # holding an old link; a draft has no link to hold.
    hidden = (ProductStatus.ARCHIVED, ProductStatus.DRAFT)
    sellable = [p for p in products if p.status not in hidden]

    if not sellable:
        return f"The catalogue returned no products matching {text!r}."

    lines = [product_summary(product) for product in sellable]

    log.info(
        "product_search",
        tenant_id=ctx.tenant_id,
        results=len(sellable),
        withheld=len(products) - len(sellable),
    )
    return "\n".join(lines)


@tool(
    name="get_product_details",
    description=(
        "Get the full description, price, variants and availability of one product, by "
        "its product id. Use after a search when the shopper asks about a specific item."
    ),
    requires=[Capability.PRODUCT_READ],
    scopes=["care:catalogue:read"],
)
async def get_product_details(product_ref: str, ctx: ToolContext) -> str:
    """One product in full."""
    ref = product_ref.strip()
    product = await ctx.adapter.get_product(ref)

    # A draft is answered exactly as a product that does not exist: not released
    # means not there yet, and "we have it but you can't buy it" is already the
    # leak (G37).
    if product is None or product.status is ProductStatus.DRAFT:
        return (
            f"The store has no product with id {ref!r}. Do not describe a product "
            "from memory — search the catalogue instead."
        )

    if product.status is ProductStatus.ARCHIVED:
        # Retrievable but withdrawn. Said plainly, because the shopper may well
        # be looking at a stale link and deserves to be told rather than sold to.
        return (
            f"{product.title} has been withdrawn from sale by this store and is no "
            "longer available. Tell the shopper it is no longer sold; do not quote "
            "its price or availability."
        )

    return product_evidence(product)


@tool(
    name="check_stock",
    description=(
        "Check whether specific product variants are in stock right now, by their variant "
        "ids. Use when the shopper asks about availability, sizes or quantities."
    ),
    requires=[Capability.INVENTORY_READ],
    scopes=["care:catalogue:read"],
)
async def check_stock(variant_refs: list[str], ctx: ToolContext) -> str:
    """Live stock levels.

    Read live rather than from the synced copy, deliberately. Stock is the field
    that goes stale fastest, and "we have three left" being an hour old is how a
    shopper is sold something that is gone (commerce-integration.md §6.1 makes
    the same call for orders).
    """
    requested = [ref.strip() for ref in variant_refs if ref.strip()][:MAX_VARIANTS]
    if not requested:
        return "No variant ids were given, so stock was not checked."

    levels = await ctx.adapter.get_inventory(requested)
    return inventory_evidence(levels, requested)
