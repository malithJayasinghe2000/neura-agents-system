"""Computing one product's pairing — the part that runs where no shopper waits.

[ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
§§2 and 3. One anchor product in; a short list of the merchant's own product ids
out. Between those two, in order:

1. a model names **kinds** (``kinds.py``) — never a product;
2. each kind is resolved against **the merchant's own catalogue**, two ways:
   ``search_products`` by keyword, and — when the shop is indexed — the
   embedding index by *meaning*
   ([ADR-0047](../../../../../docs/architecture/adr/0047-a-kind-is-resolved-by-meaning-not-by-a-shared-word.md));
3. ``select.is_complementary`` drops the anchor's own category, exactly as it
   drops it for the word path.

**Only ids that came back from step 2 are ever stored.** That is the one
sentence this module exists to make true, and it is the reason a hostile product
description cannot put a product on a shopper's page: the model's output is a
*query*, and a query for something the shop does not stock returns nothing.

**The second lookup exists because of a measured miss, not a hunch.** On
2026-09-26 the model asked a real shop for ``ankle socks``; that shop sells
*Merino Walking Socks*; the keyword lookup returned nothing because no word is
shared, and the block rendered empty. The model knew the answer and the merchant
stocked it. ADR-0047 is one step long for exactly that reason.

**Both lookups read the merchant's own data and neither can invent an id.** A
chunk's ``source_id`` **is** the merchant's ``external_id``, and the index holds
nothing but entities our own sync pulled from that one tenant inside a
``Namespace(tenant_id, embedding_model)``. So a vector hit names a product the
merchant sells — which is
[ADR-0029](../../../../../docs/architecture/adr/0029-the-index-may-name-a-candidate-never-describe-one.md)
unchanged: the index may *name* a candidate, and every field a shopper reads is
still fetched live from the shop.

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

import asyncio
from dataclasses import dataclass, field
from typing import Any

from neura_agent_sell.pairing import kinds as kinds_module
from neura_agent_sell.pairing import select
from neura_commerce import EntityType, ProductQuery
from neura_core import get_logger
from neura_domain import Product

log = get_logger(__name__)

#: How close a chunk must be before a kind is treated as naming it.
#:
#: **Measured on the real shop at three values, and it is the difference between
#: this surface working and this surface embarrassing a merchant.** The
#: retriever's own default is 0.3, tuned for a shopper's *sentence*, where recall
#: matters and a `verify` node rejects anything ungrounded downstream. A kind is
#: two words with no such backstop:
#:
#: ===========  ========  ==============  =============================================
#: `min_score`  coverage  from the model  what it actually suggested
#: ===========  ========  ==============  =============================================
#: 0.30         36 of 38  32              *wool wash → cargo trousers*, *clothes
#:                                        brush → cargo trousers*. **Nonsense**
#: 0.50         35 of 38  32              the same nonsense; barely distinguishable
#: **0.65**     29 of 38  16              *boot → shoe trees + polish*, *jumper →
#:                                        wool wash + brush*, *hiking shoe → socks
#:                                        + waterproofing spray*. **Right**
#: ===========  ========  ==============  =============================================
#:
#: **The high-coverage rows are the worse product.** ADR-0040 §4 makes an empty
#: block a *result*, and 0.3 converts "nothing in this shop goes with a clothes
#: brush" into "cargo trousers" — the *"showing something silly costs the
#: merchant's trust in the whole product"* failure, bought with a coverage number.
#: 0.65 shows less and is not wrong.
#:
#: **It does cost real pairings**, and they are named rather than hidden: at 0.65
#: the Cedar Shoe Trees and the Suede Desert Boot fall to nothing, though the shop
#: stocks the polish and the spray they asked for.
#:
#: **Still a guess, and ADR-0047 §7 labels it one** — one shop, one embedding
#: model (`nomic-embed-text`), one afternoon, 38 products. Do not repeat it as
#: tuned, and re-measure it on any other embedder: a cosine threshold is a
#: property of the model, not of the problem.
MIN_KIND_SCORE = 0.65

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
    retriever: Any | None = None,
    min_kind_score: float = MIN_KIND_SCORE,
    excluded_ids: frozenset[str] = frozenset(),
) -> ComputedPairing:
    """Ask the model, resolve its kinds against the shop, keep what both agree on.

    Returns an empty result — never an error — for every ordinary
    disappointment: a provider that is down, a model that named nothing, kinds
    that match no product, matches that all sit in the anchor's own category.
    Each of those is ADR-0040 §4's *empty is a result*, arriving one layer
    earlier.

    **``retriever`` is optional and its absence is a tier, not a failure**
    (ADR-0047 §4). Semantic resolution needs an indexed catalogue, and indexing
    is a separate operation a merchant may not have run — so without one the
    keyword hits stand alone, and the word path is still underneath that. Three
    tiers, each degrading in silence, which is the shape ``structured.py`` uses
    for provider capability and for the same reason.
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
    by_meaning = 0

    for kind in wanted:
        # **Keyword first, then meaning** (ADR-0047 §3). Where a merchant's own
        # vocabulary is exact, an exact match is likelier to be what they meant;
        # the semantic hit is the fallback for the word they did not use.
        found = await _by_keyword(kind, adapter=adapter, tenant_id=tenant_id, anchor=anchor)

        semantic = await _by_meaning(
            kind,
            adapter=adapter,
            retriever=retriever,
            tenant_id=tenant_id,
            anchor=anchor,
            already=returned | {str(p.external_id) for p in found},
            min_score=min_kind_score,
        )
        by_meaning += len(semantic)

        for product in [*found, *semantic]:
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
        # How many candidates only the index found. The answer to "was ADR-0047
        # worth it on this shop?" is this number over time, and it is free to
        # log where it would be expensive to reconstruct.
        by_meaning=by_meaning,
        stored=len(chosen),
    )

    return ComputedPairing(
        product_id=anchor.external_id,
        kinds=wanted,
        suggested_ids=chosen,
        returned_ids=frozenset(returned),
    )


async def _by_keyword(kind: str, *, adapter: Any, tenant_id: str, anchor: Product) -> list[Product]:
    """One kind, through the merchant's own search box.

    A failed search loses this kind and not the others — the same forgiveness the
    word path gives, and it matters more here because the model call that
    produced these kinds has already been paid for.
    """
    try:
        page = await adapter.search_products(
            ProductQuery(text=kind, limit=select.CANDIDATES_PER_TERM)
        )
    except Exception as exc:
        log.warning(
            "pairing_kind_search_failed",
            tenant_id=tenant_id,
            anchor_id=anchor.external_id,
            error=type(exc).__name__,
        )
        return []

    return list(page.items)


async def _by_meaning(
    kind: str,
    *,
    adapter: Any,
    retriever: Any | None,
    tenant_id: str,
    anchor: Product,
    already: set[str],
    min_score: float = MIN_KIND_SCORE,
) -> list[Product]:
    """One kind, through the embedding index — ADR-0047.

    **This is the step that exists because a keyword lookup threw away an answer
    the merchant stocked.** ``ankle socks`` against a shop selling *Merino
    Walking Socks* shares no word, so the search box returns nothing and the
    index returns the socks.

    **The index names ids; the shop supplies the products.** A chunk carries the
    merchant's own ``external_id`` and a slice of text, and this deliberately
    uses only the id — ADR-0029's rule that the index may name a candidate and
    never describe one. The category and the status that decide what is shown are
    read from the shop, live, exactly as for a keyword hit.

    Returns ``[]`` and raises nothing for: no retriever, an empty namespace, an
    unreachable embedder, a kind nothing matches. Every one of those is a tier
    degrading quietly rather than a failure (ADR-0047 §4).
    """
    if retriever is None:
        return []

    try:
        result = await retriever.search(
            kind,
            limit=select.CANDIDATES_PER_TERM,
            source_types=[EntityType.PRODUCT],
            min_score=min_score,
        )
    except Exception as exc:
        # An unreachable embedder must cost the semantic tier and nothing more.
        # The keyword hits for this kind have already been gathered.
        log.warning(
            "pairing_kind_meaning_failed",
            tenant_id=tenant_id,
            anchor_id=anchor.external_id,
            error=type(exc).__name__,
        )
        return []

    # Distinct, in score order, and never one the keyword lookup already found —
    # a duplicate would waste a live product lookup to reach the same answer.
    wanted: list[str] = []
    seen = set(already)
    for chunk in result.chunks:
        if (product_id := str(chunk.source_id)) and product_id not in seen:
            seen.add(product_id)
            wanted.append(product_id)

    if not wanted:
        return []

    fetched = await asyncio.gather(
        *(adapter.get_product(product_id) for product_id in wanted),
        return_exceptions=True,
    )

    products: list[Product] = []
    for product_id, found in zip(wanted, fetched, strict=True):
        if isinstance(found, BaseException):
            log.warning(
                "pairing_meaning_lookup_failed",
                tenant_id=tenant_id,
                product_id=product_id,
                error=type(found).__name__,
            )
            continue
        if found is not None:
            products.append(found)

    return products


__all__ = ["MAX_STORED_IDS", "MIN_KIND_SCORE", "ComputedPairing", "compute"]
