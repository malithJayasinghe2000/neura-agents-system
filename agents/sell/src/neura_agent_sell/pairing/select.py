"""Choosing what goes with a product — ordinary code, and no model in *this file*.

[ADR-0040](../../../../../docs/architecture/adr/0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)
is the specification, **amended in one place by
[ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)**:
a model may now compute a pairing, once, in the background, and the result is
stored. So the surface as a whole is no longer model-free and nobody should
quote it as such — but every rule below is still ordinary code, still pure, and
is applied to a model's candidates exactly as to a word search's.

The short version, because the constraints here are easy to erode one
convenience at a time:

* **A page hands over product ids.** It is never said where they came from, and
  nothing in this module may assume a cart. They could be a wishlist or a list
  typed by hand.
* **Selection is by the product's own words** — the text the merchant wrote —
  and **never by behaviour**. There is no purchase history in this system, so
  "customers also bought" would not be a ranking we lack; it would be a claim
  we cannot make.
* **Nothing a shopper reads is generated.** No prose and no sentence: the
  surface returns product ids, display fields the merchant wrote, and
  :func:`heading_for`'s server-built line. A model may name *kinds* to search
  for (ADR-0045 §3) and may never name a product, so this surface still cannot
  put a product on a page that the merchant's own catalogue did not return.
* **Empty is a good answer.** Showing nothing costs a shopper nothing; showing
  something silly costs the merchant's trust in the whole product.

Split from ``orchestrate.py`` on purpose: everything here is pure, so the rules
that decide what a shopper is shown are testable without a store, an adapter or
a network.
"""

from __future__ import annotations

import re

from neura_domain import Product, ProductStatus

#: Ids accepted from one page. **A bound, not a capacity.** Every id costs a
#: live lookup against the merchant's shop, and the list arrives from a page we
#: do not control — the same reasoning that bounds ``MAX_VARIANTS`` in
#: ``tools/catalogue.py``. A cart longer than this is truncated, not refused:
#: the anchor is one item, and ten is far past where the most expensive of them
#: stops changing.
MAX_INPUT_IDS = 10

#: Searches spent on one request. **Three, because each is a live HTTP call to
#: the merchant's shop** on a page that loads for every visitor. Same number and
#: same reason as ``MAX_BROADENED_TERMS``.
MAX_TERMS = 3

#: Candidates asked for per search. Most are discarded by :func:`is_pairable`.
CANDIDATES_PER_TERM = 5

#: **A guess, and ADR-0040 §6 labels it one.** One suggestion is easy to ignore;
#: past two, the weakest match is always on screen, and a poor suggestion
#: discredits the good one beside it. Change it against evidence, not taste.
MAX_SUGGESTIONS = 2

#: How many products an owner may choose for one product (ADR-0050 §2). More
#: than :data:`MAX_SUGGESTIONS` on purpose: the spares stand in when a chosen
#: product sells out, in the owner's own order.
MAX_CHOSEN = 4

#: The shortest word worth searching for. Longer than ``tools/catalogue.py``'s
#: three, because this splits a *product description* rather than a shopper's
#: query: descriptions are full of short connectives no shopper would type.
MIN_TERM_LENGTH = 4

#: Word characters only. A description is arbitrary merchant text, and tokens
#: like ``20,000mm`` or ``2.5-layer`` are measurements — searching for one finds
#: the product it came from and nothing else.
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def anchor_of(products: list[Product]) -> Product | None:
    """Which supplied product the suggestions are paired with.

    **The most expensive**, per ADR-0040 §6 — usually the main purchase, the
    jacket rather than the socks — and an informed guess rather than a
    measurement.

    Two ways it declines to guess, both deliberate:

    * **Mixed currencies.** Comparing 40 EUR with 50 USD needs a rate we do not
      have and must not invent, so the first supplied product is used instead.
      Silently comparing the numbers would put the wrong product in a heading
      that names it.
    * **No prices at all.** Nothing to rank by, so again the first — which is at
      least deterministic, where "any of them" is not.

    Returns ``None`` only for an empty list.
    """
    if not products:
        return None

    priced = [p for p in products if p.price_range_min is not None]
    currencies = {p.price_range_min.currency for p in priced if p.price_range_min}

    if len(currencies) != 1:
        return products[0]

    return max(priced, key=lambda p: p.price_range_min.amount)  # type: ignore[union-attr]


def _words_of(text: str | None) -> list[str]:
    """The searchable words of one piece of merchant text, longest first.

    Stable: equal-length words keep the order the merchant wrote them in, so a
    product yields the same terms on every request.
    """
    seen: dict[str, None] = {}

    for match in _WORD.finditer(text or ""):
        if len(word := match.group().lower()) >= MIN_TERM_LENGTH:
            seen.setdefault(word, None)

    return sorted(seen, key=len, reverse=True)


def pairing_terms(product: Product) -> list[str]:
    """The product's own words — which ones are worth spending a search on.

    **One slot is reserved for the title and one for the description; the rest
    go to the longest words left.** This decides only which terms are TRIED,
    never which results win — that is :func:`rank_by_rarity`, which measures.

    **Length alone was the rule until 2026-09-24, and the real shop showed twice
    over what it costs.** Ordering by length needs no stopword list, because
    connectives are short and sink below :data:`MAX_TERMS` on their own — and
    that is the whole of what it is good for. It is not a measure of how
    distinctive a word is:

    * The **Leather Loafer** spent all three searches on ``stitched``,
      ``polished`` and ``flexible`` — care instructions, and none of them found
      anything. ``leather``, one letter shorter, finds two boots.
    * The **Cashmere Crew Jumper** spent them on ``mongolian``, ``detergent``
      and ``cashmere``'s longer neighbours, and found nothing.

    **A title names a product; a description sells it.** The words a merchant
    puts in a title are chosen to identify the thing, so at least one of them is
    always tried. The description keeps a slot of its own for the opposite
    reason: it is where *complementary* vocabulary lives. The Lightweight Rain
    Shell's title says nothing about rain resistance that a shoe would share —
    ``waterproof`` is in its description, and it is the word that finds the
    Waterproof Hiking Shoe of ADR-0040 §4. A rule that preferred the title
    outright would have spent all three searches on ``lightweight``, ``shell``
    and ``rain``, and lost the pairing the ADR measures.

    Marketing adjectives and similes can still take the third slot — the Rain
    Shell's ``paperback``, from *"around the size of a paperback"*, still does.
    That is deliberate: **the fix guarantees the two words most likely to name
    the product are tried, rather than trying to recognise a bad word**, which
    would need a list of them and would be a tuned parameter worth less than it
    costs.

    Ordering within the result is unchanged — longest first, ties by the order
    the merchant wrote them — because it feeds nothing but tie-breaks in
    :func:`rank_by_rarity`, and a stable order there keeps one cart returning
    the same suggestions on every request.
    """
    titled = _words_of(product.title)
    described = [word for word in _words_of(product.description) if word not in titled]

    reserved = titled[:1] + described[:1]
    remaining = [word for word in titled[1:] + described[1:] if word not in reserved]
    chosen = reserved + sorted(remaining, key=len, reverse=True)[: MAX_TERMS - len(reserved)]

    return sorted(chosen, key=len, reverse=True)[:MAX_TERMS]


def is_complementary(candidate: Product, anchor: Product, *, excluded_ids: frozenset[str]) -> bool:
    """Does this product *go with* the anchor? Four refusals, none of them about
    whether it happens to be in stock this morning.

    1. **Already on the page.** Suggesting what the shopper has already chosen
       is the clearest possible signal that nothing here understands them.
    2. **The anchor itself**, which is the same failure wearing a different hat.
    3. **No category on either side.** Rule 4 cannot be applied without
       categories, and applying no rule would silently return the four-jackets
       result ADR-0040 §4 measured. Unknown is treated as unsafe.
    4. **The anchor's own category.** A shopper with a jacket in the cart does
       not want four more jackets. Word matching finds *similar* products; a
       pairing needs *complementary* ones, and this is the only line that knows
       the difference.

    **Split out of :func:`is_pairable` for [ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
    §4**, which needs exactly this half and not the other: *"the cache holds a
    pairing, never an availability."* These four rules answer a question about
    two products that stays answered — a loafer went with socks yesterday and
    goes with socks today — so they are the rules a stored pairing may be
    computed under. :func:`is_buyable` is the half that must be asked again on
    every request, and storing its answer would mean a product that sold out on
    Monday is still hidden in October.
    """
    if not candidate.external_id or candidate.external_id in excluded_ids:
        return False

    if candidate.external_id == anchor.external_id:
        return False

    if not candidate.category_ids or not anchor.category_ids:
        return False

    return not set(candidate.category_ids) & set(anchor.category_ids)


def is_buyable(candidate: Product) -> bool:
    """Can a shopper actually buy this today?

    ``search_products`` drops withdrawn products because "a shortlist is a set
    of recommendations: putting an unbuyable product on one is recommending it".
    A suggestion block is a shortlist of two.

    **The one rule that expires.** It is asked live on every request — of the
    word path's fresh search results and of a stored pairing's ids alike — and
    its answer is never written down (ADR-0045 §4).
    """
    return candidate.status is ProductStatus.ACTIVE and _in_stock(candidate)


def is_pairable(candidate: Product, anchor: Product, *, excluded_ids: frozenset[str]) -> bool:
    """May this product be shown beside the anchor, right now?

    The five refusals of ADR-0040 §4, unchanged in behaviour and now stated in
    two halves: does it go with the anchor at all
    (:func:`is_complementary`), and can it be bought (:func:`is_buyable`).
    """
    return is_complementary(candidate, anchor, excluded_ids=excluded_ids) and is_buyable(candidate)


def rank_by_rarity(found: list[tuple[str, list[Product]]]) -> list[Product]:
    """Flatten per-term results, rarest term first.

    **The one thing in this module that is measured rather than assumed.** A
    word matching few products in a catalogue distinguishes one; a word matching
    many is a house adjective. On the real shop `waterproof` returned 2 products
    and `lightweight` returned 3, so the hiking shoe outranks the frock — and
    nothing had to know what either word means.

    Free, in the sense that matters: the count is the length of a page this
    surface has already paid for. No index, no catalogue scan, no second call.

    **This ranks TERMS, never products, and that distinction is a safety
    property rather than a detail.** No product is scored, and nothing about a
    product beyond the merchant's own words affects its position. A per-product
    score would be the first step towards ranking by something else, and what
    waits at the end of that road is behaviour — which ADR-0040 §3 forbids and
    which there is no purchase history here to attempt.

    Ties break on the order :func:`pairing_terms` produced, which is stable, so
    one cart yields the same suggestions on every request.
    """
    ordered = sorted(enumerate(found), key=lambda item: (len(item[1][1]), item[0]))
    return [product for _, (_, products) in ordered for product in products]


def choose(
    candidates: list[Product], anchor: Product, *, excluded_ids: frozenset[str]
) -> list[Product]:
    """The final two, in the order :func:`rank_by_rarity` put them.

    Ordering is inherited, not computed here. **Nothing in this function scores
    or ranks** — it filters, deduplicates, and stops at two.
    """
    chosen: list[Product] = []
    taken: set[str] = set()

    for candidate in candidates:
        if len(chosen) == MAX_SUGGESTIONS:
            break
        if not is_pairable(candidate, anchor, excluded_ids=excluded_ids):
            continue
        if (product_id := str(candidate.external_id)) in taken:
            continue
        taken.add(product_id)
        chosen.append(candidate)

    return chosen


def choose_owned(candidates: list[Product], *, excluded_ids: frozenset[str]) -> list[Product]:
    """The owner's choice (ADR-0050), in the owner's order, up to two.

    **Two of ADR-0040 §4's rules still apply and one does not.** A chosen
    product must be buyable *now* — checked live, as for every suggestion — and
    must not already be on the page. **The category rule does not bind the
    owner**: a better jumper beside a jumper is an upsell the owner asked for,
    where the same pair chosen automatically would be a mistake.
    """
    chosen: list[Product] = []
    taken: set[str] = set()

    for candidate in candidates:
        if len(chosen) == MAX_SUGGESTIONS:
            break
        product_id = str(candidate.external_id)
        if product_id in excluded_ids or product_id in taken or not is_buyable(candidate):
            continue
        taken.add(product_id)
        chosen.append(candidate)

    return chosen


def heading_for_owner_choice(anchor: Product) -> str:
    """ADR-0050 §5. An owner may choose an *alternative*, and a cashmere jumper
    does not "go well with" a cotton one. "Recommended" is true because the
    shop recommended it — and it is still none of ADR-0040 §3's forbidden claims
    about what other shoppers did."""
    return f"Recommended with your {anchor.title}"


def heading_for(anchor: Product) -> str:
    """What the block says, and it is part of the decision rather than styling.

    **Built here, in code, and not left to the page.** ADR-0040 §3 rules out
    "Often bought together", "Customers also bought" and "Trending" — every one
    of them a claim about behaviour this system has never observed. A heading
    the merchant's theme composed could make any of those claims with our
    products underneath it, and the ADR's one allowed form is the reason the
    suggestion is attributable at all: with three items on a page, an unlabelled
    "goes well with" names nothing a shopper can judge or reject.
    """
    return f"Goes well with your {anchor.title}"


def _in_stock(product: Product) -> bool:
    """Kept in step with ``tools/card.py`` deliberately: a card that says "In
    stock" beside a block that would not have shown it is two answers to one
    question."""
    if not product.variants:
        return True
    return any(variant.in_stock for variant in product.variants)


__all__ = [
    "CANDIDATES_PER_TERM",
    "MAX_CHOSEN",
    "MAX_INPUT_IDS",
    "MAX_SUGGESTIONS",
    "MAX_TERMS",
    "MIN_TERM_LENGTH",
    "anchor_of",
    "choose",
    "choose_owned",
    "heading_for",
    "heading_for_owner_choice",
    "is_buyable",
    "is_complementary",
    "is_pairable",
    "pairing_terms",
    "rank_by_rarity",
]
