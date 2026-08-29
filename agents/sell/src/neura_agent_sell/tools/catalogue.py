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

import re
from typing import Any

from neura_agent_core.tools import ToolContext, tool
from neura_agent_sell.tools.card import product_card
from neura_agent_sell.tools.render import (
    candidate,
    category_evidence,
    inventory_evidence,
    product_evidence,
)
from neura_commerce import EntityType, ProductQuery
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

#: A price ceiling written into the search text: `under 40`, `below £40`,
#: `less than $40.00`, `up to 40`, `max 40`, `cheaper than 40`, `no more than 40`.
#:
#: **Bound to a number, never to a bare one.** `size 40`, `40 denier` and `SPF 40`
#: carry no comparison word and are left alone — they are things a shopper
#: genuinely searches for, and a stripper that ate them would trade one silent
#: failure for another.
_PRICE_PHRASE = re.compile(
    r"""\b(?:
          under | below | beneath
        | (?:less|cheaper|lower)\s+than
        | (?:up\s+to) | (?:no\s+more\s+than) | (?:at\s+most) | max(?:imum)?
        | within | around | about
    )\s*
    [\$£€]?\s*\d+(?:[.,]\d+)?\s*
    (?:usd|gbp|eur|dollars?|pounds?|euros?|bucks?|quid)?
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Left over once the phrase goes: a dangling connective, doubled spaces.
_DANGLING = re.compile(r"\b(?:for|at|and|or|with|in)\s*$", re.IGNORECASE)


def strip_price_constraint(text: str) -> str:
    """Remove a price ceiling from a search query. See [ADR-0027].

    The merchant's search engine is a keyword search over their own product
    text, and **no product contains the token `40`**. Measured on the test shop:
    `trousers` returns 4 and `trousers under 40` returns **0**. One adjective
    destroys the turn, and every gate downstream reads green.

    `plan.md` already instructs the model not to do this — *"Search for the
    thing, not the sentence"*, *"Do not try to filter by price yourself"* — and
    the model does it anyway. That is AGENTS.md rule 3 from the inside: a
    behaviour defended only by a sentence in a prompt is not defended, so the
    enforcement is here, at the last point we own the string, and applies
    whatever produced it.

    **Nothing is lost by removing it.** `route` extracts the ceiling
    structurally and `shortlist` enforces it exactly, in code, on the results.
    The phrase in the query was never doing the filtering — it was only
    preventing the search from matching.

    Returns the original text unchanged if stripping would empty it: a query of
    *"under 40"* and nothing else is a shopper who named a budget and no
    product, and an empty search is worse than a bad one.
    """
    stripped = _PRICE_PHRASE.sub(" ", text)
    stripped = _DANGLING.sub("", " ".join(stripped.split())).strip()
    return stripped or text


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

    if (searched := strip_price_constraint(text)) != text:
        log.info(
            "sell_price_stripped_from_query",
            tenant_id=ctx.tenant_id,
            asked=text,
            searched=searched,
        )
    text = searched

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
        # The merchant's engine found nothing. Before saying so, ask our own
        # index which products it would have looked at ([ADR-0029]).
        if recovered := await _from_the_index(text, ctx):
            return recovered

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
    _remember(ctx, sellable)
    return "\n\n".join(candidate(product) for product in sellable)


async def _from_the_index(text: str, ctx: ToolContext) -> str:
    """Candidates the synced index would have found, confirmed live. [ADR-0029]

    **The index names them; the store describes them.** Measured on the test
    shop: `trousers` returns 4 products and `jackets` returns **0**, because the
    titles read *"Waxed Cotton Field Jacket"* and the merchant's search is a
    literal text match with no stemming. One letter, and a shopper is told a
    shop with four jackets is empty — while `retrieve` had already found one in
    the same turn.

    So the ids come from our copy and **every fact comes from the adapter**. A
    product deleted, withdrawn or sold out since the last sync fails the
    confirmation below and disappears, which is what keeps this module's
    "read live, deliberately" guarantee intact: a stale index costs a wasted
    lookup, never a wrong claim in front of a shopper.

    Returns an empty string when there is no index, when it knows nothing, or
    when nothing survives confirmation — the caller then says what it always
    said, and a tenant with no index behaves exactly as before.
    """
    if ctx.retriever is None:
        return ""

    found = await ctx.retriever.search(
        text, limit=MAX_RESULTS * 2, source_types=[EntityType.PRODUCT]
    )
    # De-duplicated in retrieval order: one product is several chunks, and the
    # best-scoring chunk is the one that should decide its place in the list.
    proposed: list[str] = []
    for chunk in found.chunks:
        if chunk.source_id not in proposed:
            proposed.append(chunk.source_id)
    if not proposed:
        return ""

    confirmed = []
    for product_id in proposed[:MAX_RESULTS]:
        product = await ctx.adapter.get_product(product_id)
        if product is not None and product.status is ProductStatus.ACTIVE:
            confirmed.append(product)

    log.info(
        "sell_search_fell_back_to_index",
        tenant_id=ctx.tenant_id,
        query=text,
        proposed=proposed[:MAX_RESULTS],
        confirmed=len(confirmed),
    )

    if not confirmed or not _shares_a_word(text, confirmed):
        # The index always returns its nearest neighbours, and "nearest" in a
        # 29-product catalogue is not "relevant" — measured: `fishing rods`
        # returns a jacket at 0.528 against a best of 0.545, noise that looks
        # exactly like signal. Proposing those would answer "do you sell fishing
        # rods?" with five things that are not fishing rods.
        #
        # **The gate is the merchant's own words, not a score.** This fallback
        # exists for searches their engine missed for a *word* reason — a plural
        # it could not stem, a synonym in the title — so requiring one shared
        # word is requiring evidence that such a reason exists. A score
        # threshold would need a number, and the scales are not comparable
        # across embedding models (measured: `nomic-embed-text` runs 0.50 to 0.75
        # on the same shop where `gemini-embedding-001` runs 0.53 to 0.66), so any
        # constant would be right for one model and wrong for the next.
        #
        # It fails to the behaviour that existed before [ADR-0029]: a shopper
        # asking for "a waterproof coat" in a shop that calls it a shell shares
        # no word, gets no fallback, and is told what they were told yesterday.
        log.info(
            "sell_index_fallback_rejected",
            tenant_id=ctx.tenant_id,
            query=text,
            confirmed=len(confirmed),
            reason="nothing confirmed" if not confirmed else "no word in common",
        )
        return ""

    # Stated, not silent. This line is in the evidence a reviewer reads and in
    # the tool output an eval records, because "two paths reach `compose`" is
    # the cost this decision was weighed against and an unattributable
    # recommendation months from now is how that cost gets paid.
    header = (
        f"The store's own search returned nothing for {text!r}, so these candidates come "
        "from the synced catalogue. Their prices and availability below were confirmed "
        "live with the store just now."
    )
    _remember(ctx, confirmed)
    return header + "\n\n" + "\n\n".join(candidate(product) for product in confirmed)


def _remember(ctx: ToolContext, products: list[Any]) -> None:
    """Keep the structured facts this lookup already fetched. [ADR-0030]

    A tool result is prose, for a model to reason over. `candidate()` renders no
    image and no URL, because a model has no use for either — so a reply that
    has to *show* a product cannot be built from what a reply that only
    *describes* one was given.

    The alternative is fetching every recommended product a second time in
    `respond`, which is up to four extra round-trips to re-read what this turn
    already read. This dies with the turn, so it cannot go stale.

    **Writing here grants nothing.** Whether an entry ever reaches a shopper is
    decided later by the fabrication check, against `promises`.
    """
    for product in products:
        if card := product_card(product):
            ctx.cards[card["id"]] = card


def _shares_a_word(query: str, products: list[Any]) -> bool:
    """Does any confirmed product actually use one of the shopper's words?

    Crude, and deliberately so. It is not deciding whether a product *fits* —
    that is the `sell.md` §2.3 question and a language judgement this node may
    not make. It decides only whether the merchant's own text contains the thing
    the shopper typed, which is the premise this fallback rests on: their search
    missed a word it should have matched.

    Singular and plural fold together, because `jackets` failing to match
    *"Waxed Cotton Field **Jacket**"* is the entire reason this code exists.
    """
    wanted = {
        _fold(word)
        for word in _WORDS.findall(query.lower())
        if len(word) > 2 and word not in _NOT_A_PRODUCT
    }
    if not wanted:
        return False

    for product in products:
        text = f"{product.title or ''} {product.description or ''}".lower()
        if wanted & {_fold(word) for word in _WORDS.findall(text)}:
            return True
    return False


def _fold(word: str) -> str:
    """`jackets` and `jacket` are one word here. Not a stemmer — a plural fold."""
    for suffix in ("ies", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


#: Words that describe the asking rather than the product.
_NOT_A_PRODUCT = frozenset(
    {"any", "for", "have", "looking", "need", "sell", "show", "some", "something", "want", "you"}
)

_WORDS = re.compile(r"[a-z0-9]+")


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

    _remember(ctx, [product])

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
