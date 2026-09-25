"""One pairing request, start to finish.

Everything that touches the merchant's shop lives here; every rule about what a
shopper may be shown lives in ``select.py``. The split is so that the rules can
be tested without a store, and so that the number of live HTTP calls this
surface makes is visible in one file.

**The budget, because a cart page loads for every visitor:** at most
``MAX_INPUT_IDS`` product lookups (concurrent) and at most ``MAX_TERMS``
searches. No model call, ever — that is ADR-0040 §5, and it is a cost decision
as much as a safety one.

The searches do **not** stop early, and that ceiling is the price of the fix on
2026-09-21: which search term produced the best pairing cannot be known until
every term's result count is in, so all of them are spent. The ceiling itself is
unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from neura_agent_sell.pairing import select
from neura_agent_sell.tools.card import product_card
from neura_commerce import ProductQuery
from neura_core import get_logger
from neura_domain import Capability, Product

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Pairing:
    """What a page gets back. ``suggestions`` is routinely empty.

    ``heading`` and ``paired_with`` are present only when there is something to
    head — a heading with no products under it is an empty block that still
    takes up space and still makes a claim.
    """

    suggestions: list[dict[str, str]] = field(default_factory=list)
    heading: str = ""
    paired_with: dict[str, str] | None = None

    @property
    def is_empty(self) -> bool:
        return not self.suggestions


async def suggest(
    product_ids: list[str],
    *,
    adapter: Any,
    capabilities: frozenset[Capability],
    tenant_id: str,
) -> Pairing:
    """Products that go with the ones a page named.

    Returns an empty :class:`Pairing` — never an error — for every ordinary
    disappointment: no ids, unknown ids, a store that cannot search, a product
    with no categories, nothing complementary in the catalogue. **ADR-0040 §4
    makes that a result rather than a failure**, and the block simply does not
    render.

    An error here would be worse than nothing twice over: it would put a
    developer's problem on a shopper's cart page, which is exactly
    [Finding 49](../../../../../docs/TESTING_LOG.md), and it would do so on a
    page where the shopper has already decided to buy.
    """
    wanted = _clean_ids(product_ids)
    if not wanted:
        return Pairing()

    if not {Capability.PRODUCT_READ, Capability.PRODUCT_SEARCH} <= capabilities:
        # A store that cannot search cannot be asked what goes with anything.
        # Declared capability, not a guess — and an absent one is normal, per
        # INTEGRATION_GUIDE §4: the feature is simply not offered.
        log.info("pairing_store_cannot_search", tenant_id=tenant_id)
        return Pairing()

    on_the_page = await _load(wanted, adapter=adapter, tenant_id=tenant_id)
    if not on_the_page:
        return Pairing()

    anchor = select.anchor_of(on_the_page)
    if anchor is None:  # pragma: no cover — _load returning [] is handled above
        return Pairing()

    if not anchor.category_ids:
        # Rule 5 of `is_pairable` would refuse everything anyway. Logged
        # separately because this is a *merchant data* problem with a fix —
        # "your products have no categories, so pairings stay empty" — and it
        # would otherwise be indistinguishable from a thin catalogue.
        log.info(
            "pairing_anchor_has_no_category",
            tenant_id=tenant_id,
            product_id=anchor.external_id,
        )
        return Pairing()

    excluded = frozenset(wanted)
    chosen = await _search(anchor, adapter=adapter, excluded_ids=excluded, tenant_id=tenant_id)

    if not chosen:
        log.info(
            "pairing_nothing_complementary",
            tenant_id=tenant_id,
            anchor_id=anchor.external_id,
            detail="an empty block is a result, not a failure",
        )
        return Pairing()

    cards = [card for product in chosen if (card := product_card(product))]
    anchor_card = product_card(anchor)

    if not cards or anchor_card is None:
        # `product_card` returns None for a product with nothing to name. A
        # heading naming an unnameable anchor is the grey box that module
        # already refuses to render.
        return Pairing()

    log.info(
        "pairing_suggested",
        tenant_id=tenant_id,
        anchor_id=anchor.external_id,
        suggested=len(cards),
        # Ids, never titles. A log is not a place to accumulate a merchant's
        # catalogue copy.
        suggested_ids=[card["id"] for card in cards],
    )

    return Pairing(
        suggestions=cards,
        heading=select.heading_for(anchor),
        paired_with=anchor_card,
    )


def _clean_ids(raw: list[str]) -> list[str]:
    """Distinct, non-empty, bounded — in the order the page sent them.

    Order is preserved because :func:`select.anchor_of` falls back to the first
    product when it cannot rank by price, and a fallback that depended on set
    iteration order would be a different suggestion on every request.
    """
    seen: dict[str, None] = {}
    for candidate in raw:
        if (product_id := str(candidate).strip()) and len(product_id) <= 128:
            seen.setdefault(product_id, None)
    return list(seen)[: select.MAX_INPUT_IDS]


async def _load(ids: list[str], *, adapter: Any, tenant_id: str) -> list[Product]:
    """Fetch what the page named, concurrently and forgivingly.

    **A missing product is not an error.** ``get_product`` returns ``None`` for
    an unknown id by design — pages hold stale ids all the time — and one
    withdrawn line in a cart must not cost the shopper the whole block.

    A *raised* lookup is caught for the same reason and logged: the merchant's
    shop failing on one product is their outage, and turning it into a 500 on
    their cart page would make it ours as well.
    """
    results = await asyncio.gather(
        *(adapter.get_product(product_id) for product_id in ids),
        return_exceptions=True,
    )

    found: list[Product] = []
    for product_id, result in zip(ids, results, strict=True):
        if isinstance(result, BaseException):
            log.warning(
                "pairing_product_lookup_failed",
                tenant_id=tenant_id,
                product_id=product_id,
                error=type(result).__name__,
            )
            continue
        if result is not None:
            found.append(result)

    return found


async def _search(
    anchor: Product,
    *,
    adapter: Any,
    excluded_ids: frozenset[str],
    tenant_id: str,
) -> list[Product]:
    """Search the anchor's own words, most distinctive first, and stop early.

    Each term is a separate call rather than one query of several words, because
    a merchant's search is a keyword engine over their own text: *"waterproof
    taped seams"* matches the product the words were taken from and very little
    else. One term at a time is what finds a different product that shares an
    attribute — the mechanism ``tools/catalogue.py`` already relies on when it
    broadens a failed search.

    **Separate calls also buy the ranking.** Because each term is asked on its
    own, the size of each answer is a free measure of how common that word is in
    this catalogue, which is what :func:`select.rank_by_rarity` orders by.
    """
    terms = select.pairing_terms(anchor)
    if not terms:
        return []

    found: list[tuple[str, list[Product]]] = []

    for term in terms:
        try:
            page = await adapter.search_products(
                ProductQuery(text=term, limit=select.CANDIDATES_PER_TERM)
            )
        except Exception as exc:
            # One failed search must not lose the results of the others.
            log.warning(
                "pairing_search_failed",
                tenant_id=tenant_id,
                term=term,
                error=type(exc).__name__,
            )
            continue

        found.append((term, list(page.items)))

    # **Every term is searched — there is no early stop, and removing it was the
    # fix rather than an oversight.** Stopping as soon as two candidates existed
    # meant the first term decided the answer, and the order terms arrive in is
    # not a ranking. On the real shop, 2026-09-21, that filled both places from
    # `lightweight` and never searched `waterproof` — the word ADR-0040 §4 names
    # as the genuine pair. Which term wins cannot be known before every count is
    # in, so the budget is spent in full: `MAX_TERMS` searches, unchanged.
    candidates = select.rank_by_rarity(found)

    if found:
        log.info(
            "pairing_terms_searched",
            tenant_id=tenant_id,
            anchor_id=anchor.external_id,
            # The counts are the ranking, so they are the thing worth being able
            # to read back when a merchant asks why they were shown a frock.
            counts={term: len(products) for term, products in found},
        )

    return select.choose(candidates, anchor, excluded_ids=excluded_ids)


__all__ = ["Pairing", "suggest"]
