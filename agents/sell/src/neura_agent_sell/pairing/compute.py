"""Computing one product's pairing — the part that runs where no shopper waits.

[ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
§§2 and 3. One anchor product in; a short list of the merchant's own product ids
out. Between those two, in order:

1. a model names **kinds** (``kinds.py``) — never a product;
2. each kind is searched in **the merchant's own catalogue**, through the same
   ``search_products`` the word path uses;
3. ``select.is_complementary`` drops the anchor's own category, exactly as it
   drops it for the word path.

**Only ids that came back from step 2 are ever stored.** That is the one
sentence this module exists to make true, and it is the reason a hostile product
description cannot put a product on a shopper's page: the model's output is a
*query*, and a query for something the shop does not stock returns nothing.

**It does not decide availability.** ``is_complementary`` is the half of
ADR-0040 §4 that stays answered; stock and status are checked live on every
request by ``orchestrate.py``, against the ids stored here. A pairing computed
in July must not still be hiding a product that was out of stock that morning.

**Nothing in this module may be called from a request path.** It makes a model
call, and ADR-0045's first non-negotiable is that no shopper ever waits for one.
The caller that enforces that is the job handler; the caller that must never
appear is a route.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neura_agent_sell.pairing import kinds as kinds_module
from neura_agent_sell.pairing import select
from neura_commerce import ProductQuery
from neura_core import get_logger
from neura_domain import Product

log = get_logger(__name__)

#: How many ids a computed pairing keeps. **More than the two a shopper sees**,
#: and the gap is the point: a stored pairing outlives a stock level, so the
#: serve path needs spares to fall back on when the first suggestion sold out
#: overnight. Three times ``MAX_SUGGESTIONS`` is a guess of the same kind
#: ADR-0045 §8 labels its own — it is *"enough that one product selling out does
#: not empty the block"*, which no shop has been observed to confirm.
MAX_STORED_IDS = select.MAX_SUGGESTIONS * 3


@dataclass(frozen=True, slots=True)
class ComputedPairing:
    """One computation's result, and the evidence for it.

    ``returned_ids`` is everything the merchant's catalogue handed back across
    every search. It is carried rather than discarded because it is what makes
    ADR-0045 §3's central claim *checkable* instead of merely stated: every id
    in ``suggested_ids`` must be in it, and the eval target asserts exactly
    that. A claim nothing tests is a claim in a comment.
    """

    product_id: str
    kinds: list[str] = field(default_factory=list)
    suggested_ids: list[str] = field(default_factory=list)
    returned_ids: frozenset[str] = frozenset()
    #: Set when the model could not be reached at all. **Not a result** — the
    #: caller must retry rather than store this, or one provider outage caches
    #: *"pairs with nothing"* for every product computed during it, permanently.
    provider_error: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.suggested_ids

    @property
    def measured(self) -> bool:
        """Did a model actually answer? The only state worth storing."""
        return not self.provider_error


async def compute(
    anchor: Product,
    *,
    adapter: Any,
    tenant_id: str,
    llm: object,
    prompt: str,
    excluded_ids: frozenset[str] = frozenset(),
) -> ComputedPairing:
    """Ask the model, search the shop, keep what both agree on.

    Returns an empty result — never an error — for every ordinary
    disappointment: a provider that is down, a model that named nothing, kinds
    that match no product, matches that all sit in the anchor's own category.
    Each of those is ADR-0040 §4's *empty is a result*, arriving one layer
    earlier.
    """
    answer = await kinds_module.kinds_for(anchor, llm=llm, prompt=prompt)
    if not answer.reachable:
        # Reported, not swallowed. The difference between "the model found
        # nothing" and "there was no model" is the difference between a result
        # and an outage, and only one of them belongs in a cache.
        return ComputedPairing(product_id=anchor.external_id, provider_error=answer.error)

    wanted = answer.kinds
    if not wanted:
        return ComputedPairing(product_id=anchor.external_id)

    candidates: list[Product] = []
    returned: set[str] = set()

    for kind in wanted:
        try:
            page = await adapter.search_products(
                ProductQuery(text=kind, limit=select.CANDIDATES_PER_TERM)
            )
        except Exception as exc:
            # One failed search must not lose the others — the same forgiveness
            # the word path gives, and it matters more here because the model
            # call that produced these kinds has already been paid for.
            log.warning(
                "pairing_kind_search_failed",
                tenant_id=tenant_id,
                anchor_id=anchor.external_id,
                error=type(exc).__name__,
            )
            continue

        for product in page.items:
            candidates.append(product)
            if product.external_id:
                returned.add(str(product.external_id))

    # **Kept in the model's order, and no rarity ranking is applied.** The word
    # path ranks by how many products a term matched, because one arbitrary word
    # of a description says nothing about how good a pairing it is. A kind is
    # not an arbitrary word — it is an answer to the question, and its position
    # is the model's own ordering. Re-sorting it by result count would throw
    # away the one thing this path has that the word path does not.
    chosen: list[str] = []
    seen: set[str] = set()
    excluded = excluded_ids | {anchor.external_id}

    for product in candidates:
        if len(chosen) == MAX_STORED_IDS:
            break
        if not select.is_complementary(product, anchor, excluded_ids=frozenset(excluded)):
            continue
        if (product_id := str(product.external_id)) in seen:
            continue
        seen.add(product_id)
        chosen.append(product_id)

    log.info(
        "pairing_computed",
        tenant_id=tenant_id,
        anchor_id=anchor.external_id,
        kinds=wanted,
        searched=len(wanted),
        returned=len(returned),
        stored=len(chosen),
    )

    return ComputedPairing(
        product_id=anchor.external_id,
        kinds=wanted,
        suggested_ids=chosen,
        returned_ids=frozenset(returned),
    )


__all__ = ["MAX_STORED_IDS", "ComputedPairing", "compute"]
