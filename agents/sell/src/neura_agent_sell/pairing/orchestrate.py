"""One pairing request, start to finish.

Everything that touches the merchant's shop lives here; every rule about what a
shopper may be shown lives in ``select.py``. The split is so that the rules can
be tested without a store, and so that the number of live HTTP calls this
surface makes is visible in one file.

**No model runs between a shopper and an answer.** That is
[ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
§1, amending ADR-0040 §5's flat *"no model runs in it"*, and it is the one rule
in this file that may not be relaxed for a special case — not for the first
shopper, not once, not behind a timeout. A model call on this path would be a
cart page whose speed depends on a provider, and the ADR's cost argument dies
with it.

**Two paths in, and the second is not a degraded version of the first:**

===============  ==========================================================
stored pairing   a model computed it in the background, minutes or weeks
                 ago. Its **ids** are used; its availability is not — stock
                 and status are read live, here, on every request
no stored one    the word path answers **now**, exactly as it did before
                 ADR-0045, and a computation is queued for next time
===============  ==========================================================

**The budget, because a cart page loads for every visitor:** at most
``MAX_INPUT_IDS`` product lookups for what the page named, then *either* up to
``MAX_STORED_IDS`` more lookups (a cache hit, no search at all) *or* up to
``MAX_TERMS`` searches (a miss). A miss also writes one job row. No model call,
ever, on this path.

The searches do **not** stop early, and that ceiling is the price of the fix on
2026-09-21: which search term produced the best pairing cannot be known until
every term's result count is in, so all of them are spent. The ceiling itself is
unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from neura_agent_sell.pairing import compute, select
from neura_agent_sell.pairing.cache import PairingCache, source_hash
from neura_agent_sell.pairing.choices import OwnerChoices
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

    ``origin`` and ``reason`` are for the owner's preview in the console
    (2026-09-28), which shows what a basket shows and must say where it came
    from and, when it is empty, why. **The storefront route does not send
    them** — it names its three fields — so a shopper's page learns nothing new.
    """

    suggestions: list[dict[str, str]] = field(default_factory=list)
    heading: str = ""
    paired_with: dict[str, str] | None = None
    #: Who chose what is shown: ``owner``, ``model`` (a stored pairing) or
    #: ``words`` (the product's own text). Empty when nothing is shown.
    origin: str = ""
    #: Why nothing is shown, when nothing is: ``cannot_search``, ``not_found``,
    #: ``owner_nothing``, ``no_category`` or ``nothing_matched``. Empty otherwise.
    reason: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.suggestions


async def suggest(
    product_ids: list[str],
    *,
    adapter: Any,
    capabilities: frozenset[Capability],
    tenant_id: str,
    cache: PairingCache | None = None,
    choices: OwnerChoices | None = None,
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

    **``cache`` is optional and its absence is not a degraded mode.** Without
    one this is byte-for-byte the surface of 2026-09-24: the word path, no
    database, no queue, no model anywhere in the system. That is what
    `make pairs-check`'s stub mode runs, what every existing test runs, and what
    a deployment that has not migrated runs — and ADR-0045's own falsification
    test (§9) is the comparison between the two, which only exists because both
    still work.
    """
    wanted = _clean_ids(product_ids)
    if not wanted:
        return Pairing()

    if not {Capability.PRODUCT_READ, Capability.PRODUCT_SEARCH} <= capabilities:
        # A store that cannot search cannot be asked what goes with anything.
        # Declared capability, not a guess — and an absent one is normal, per
        # INTEGRATION_GUIDE §4: the feature is simply not offered.
        log.info("pairing_store_cannot_search", tenant_id=tenant_id)
        return Pairing(reason="cannot_search")

    on_the_page = await _load(wanted, adapter=adapter, tenant_id=tenant_id)
    if not on_the_page:
        return Pairing(reason="not_found")

    anchor = select.anchor_of(on_the_page)
    if anchor is None:  # pragma: no cover — _load returning [] is handled above
        return Pairing()

    excluded = frozenset(wanted)

    # **The owner's choice is asked first, and when there is one it is the
    # whole answer** (ADR-0050): no stored model pairing and no word search can
    # bring back a product the owner removed. Before the category check below,
    # because the category rule does not bind an owner.
    owned = await _owner_choice(
        anchor, adapter=adapter, excluded_ids=excluded, tenant_id=tenant_id, choices=choices
    )
    if owned is not None:
        return _pairing(
            owned,
            anchor,
            heading=select.heading_for_owner_choice(anchor),
            tenant_id=tenant_id,
            source="owner",
            origin="owner",
        )

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
        return Pairing(reason="no_category")

    chosen = await _stored(
        anchor, adapter=adapter, excluded_ids=excluded, tenant_id=tenant_id, cache=cache
    )
    origin = "model"

    if not chosen:
        # Either there is no cache, or nothing was stored, or everything stored
        # has since sold out. All three answer the same way and all three are
        # ordinary: **the word path answers now**, and the computation queued
        # above lands before the next shopper.
        chosen = await _search(anchor, adapter=adapter, excluded_ids=excluded, tenant_id=tenant_id)
        origin = "words"

    return _pairing(
        chosen,
        anchor,
        heading=select.heading_for(anchor),
        tenant_id=tenant_id,
        source="automatic",
        origin=origin,
    )


def _pairing(
    chosen: list[Product],
    anchor: Product,
    *,
    heading: str,
    tenant_id: str,
    source: str,
    origin: str,
) -> Pairing:
    """Cards and a heading, or an empty :class:`Pairing` — the same for both paths.

    ``source`` is what the log has always said (``owner`` or ``automatic``);
    ``origin`` splits automatic into ``model`` and ``words`` for the preview.
    """
    empty = Pairing(reason="owner_nothing" if origin == "owner" else "nothing_matched")
    if not chosen:
        log.info(
            "pairing_nothing_to_show",
            tenant_id=tenant_id,
            anchor_id=anchor.external_id,
            source=source,
            detail="an empty block is a result, not a failure",
        )
        return empty

    cards = [card for product in chosen if (card := product_card(product))]
    anchor_card = product_card(anchor)

    if not cards or anchor_card is None:
        # `product_card` returns None for a product with nothing to name. A
        # heading naming an unnameable anchor is the grey box that module
        # already refuses to render.
        return empty

    log.info(
        "pairing_suggested",
        tenant_id=tenant_id,
        anchor_id=anchor.external_id,
        source=source,
        suggested=len(cards),
        # Ids, never titles. A log is not a place to accumulate a merchant's
        # catalogue copy.
        suggested_ids=[card["id"] for card in cards],
    )

    return Pairing(suggestions=cards, heading=heading, paired_with=anchor_card, origin=origin)


async def _owner_choice(
    anchor: Product,
    *,
    adapter: Any,
    excluded_ids: frozenset[str],
    tenant_id: str,
    choices: OwnerChoices | None,
) -> list[Product] | None:
    """The owner's list for this product, checked live — or ``None`` for automatic.

    ``[]`` means *show nothing*, and it is returned in three cases, all on
    purpose (ADR-0050 §4): the owner chose nothing, everything they chose is
    unbuyable right now, or **their choice could not be read**. None of them
    falls back to the automatic path, which could bring back the very product
    the owner removed.
    """
    if choices is None:
        return None

    try:
        chosen_ids = await choices.get(anchor.external_id)
    except Exception as exc:
        log.warning(
            "pairing_owner_choice_unreadable",
            tenant_id=tenant_id,
            anchor_id=anchor.external_id,
            error=type(exc).__name__,
            detail="showing nothing rather than risk contradicting the owner",
        )
        return []

    if chosen_ids is None:
        return None
    if not chosen_ids:
        return []

    live = await _load(chosen_ids[: select.MAX_CHOSEN], adapter=adapter, tenant_id=tenant_id)
    by_id = {str(product.external_id): product for product in live}
    # The owner's order, not lookup-completion order.
    return select.choose_owned(
        [by_id[product_id] for product_id in chosen_ids if product_id in by_id],
        excluded_ids=excluded_ids,
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


async def _stored(
    anchor: Product,
    *,
    adapter: Any,
    excluded_ids: frozenset[str],
    tenant_id: str,
    cache: PairingCache | None,
) -> list[Product]:
    """The pairing a model computed earlier, if there is a usable one.

    Returns ``[]`` for a miss, a stale row, a cache that raised, or a stored
    pairing every product of which has since become unbuyable — and **queues a
    computation** for the first two. The caller then answers from the word path,
    which is the whole of ADR-0045 §2's *"the first shopper is never punished"*.

    **The stored half is ids and nothing else.** Every product is fetched live
    and re-checked by ``select.is_pairable``, so a product that sold out
    yesterday is not suggested today and a product withdrawn last month is not
    suggested at all — ADR-0045 §4, and the reason the row holds no price, no
    title and no stock level to go stale.

    **Nothing in here may raise.** A database that is down must cost a shopper
    the *model's* answer and not the block; the word path runs either way.
    """
    if cache is None:
        return []

    fingerprint = source_hash(anchor)

    try:
        stored_ids = await cache.get(anchor.external_id, source_hash=fingerprint)
    except Exception as exc:
        log.warning(
            "pairing_cache_read_failed",
            tenant_id=tenant_id,
            anchor_id=anchor.external_id,
            error=type(exc).__name__,
        )
        return []

    if stored_ids is None:
        try:
            await cache.queue(anchor.external_id, source_hash=fingerprint)
        except Exception as exc:
            # A queue that refused is a pairing this shop does not get yet. It
            # is not a reason to fail the page, and it is not a reason to fall
            # back to computing one here — there is no "here" that is allowed
            # to run a model.
            log.warning(
                "pairing_queue_failed",
                tenant_id=tenant_id,
                anchor_id=anchor.external_id,
                error=type(exc).__name__,
            )
        return []

    if not stored_ids:
        # A stored **empty** pairing: the model ran, its kinds matched nothing
        # complementary, and that was written down. Deliberately not re-queued —
        # recomputing it on every cart page is the cost `cache.put`'s docstring
        # explains storing an empty result to avoid.
        return []

    live = await _load(stored_ids[: compute.MAX_STORED_IDS], adapter=adapter, tenant_id=tenant_id)
    by_id = {str(product.external_id): product for product in live}
    # Stored order, not lookup-completion order: `_load` gathers concurrently
    # and the order things come back in is not a ranking.
    chosen = select.choose(
        [by_id[product_id] for product_id in stored_ids if product_id in by_id],
        anchor,
        excluded_ids=excluded_ids,
    )

    log.info(
        "pairing_from_cache",
        tenant_id=tenant_id,
        anchor_id=anchor.external_id,
        stored=len(stored_ids),
        still_live=len(live),
        shown=len(chosen),
    )
    return chosen


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
