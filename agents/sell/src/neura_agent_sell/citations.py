"""Which of the products a turn saw does a draft name?

One function, used by every place that asks — the evidence filter that decides
which descriptions `verify` may read, the fabrication check in `respond`, and
the cards `respond` shows. It used to be one regex copied into two files, and a
test existed only to keep the copies equal.

**Only ids the caller already knows are looked for**, never "anything shaped like
an id". The old pattern found every token of three or more characters and then
checked membership, which quietly made a product whose id is shorter than three
characters uncitable: on a connected shop with products `3`, `4` and `5`, a
correct recommendation of product 4 was never seen as citing it, so its
description was withheld from `verify` and a claim copied from that description
failed as unsupported (CONNECTING_A_NEW_SHOP_LOG.md G36). The same blindness
switched off the fabrication check for those ids.

**Whole tokens only.** An id counts where it is not part of a longer word or
number: `4` is cited by "(Product 4)" and by "product 4.", and not by "400g",
"4.5" or "p_4". What remains possible for a very short id is a false citation
from an ordinary number — "4 cups" names product `4`. Each caller fails safe on
that: the fabrication check escalates, a card is only ever built for a product
on the shortlist, and the evidence filter shows `verify` one more description.
"""

from __future__ import annotations

import re
from collections.abc import Iterable


def cited_ids(draft: str, known: Iterable[str]) -> list[str]:
    """The ids from ``known`` that ``draft`` names, in the order it first names them."""
    first_seen: dict[str, int] = {}
    for product_id in set(known):
        if not product_id:
            continue
        match = re.search(rf"(?<![\w.-]){re.escape(product_id)}(?![\w-]|\.\w)", draft)
        if match:
            first_seen[product_id] = match.start()
    return sorted(first_seen, key=lambda product_id: (first_seen[product_id], product_id))


def without_ids(reply: str, known: Iterable[str]) -> str:
    """The reply as a shopper should read it: the id citations taken out.

    The compose prompt has the model name each product by its id, because that
    is how `verify`, the rejected-product check and the cards know which product
    a sentence means (G36). The shopper then read *"Ceylon Black Tea BOPF 400g
    (Product 4)"* — an internal number that means nothing to them
    (CONNECTING_A_NEW_SHOP_LOG.md G41). Only a **bracketed** mention of a known
    id is removed — ``(4)``, ``(Product 4)``, ``[p_boot_1]`` — never a bare one,
    because "4 cups" and "size 4" are the shopper's own words. Run on the reply
    after every check, so nothing it removes was ever evidence.

    The model also writes it the other way round, *"Product 4 (Ceylon Black Tea
    BOPF 400g)"* (G106): there the word *product* and a known id come before a
    bracketed name, and the name is kept without its brackets; or *"Product 4, the
    Enamel Camp Mug"*, where the id and its comma go. Without the word *product*
    nothing changes, so *"size 4 (UK)"* stays.
    """
    for product_id in sorted({i for i in known if i}, key=len, reverse=True):
        reply = re.sub(
            rf"\bproduct\s+(?:id\s+)?{re.escape(product_id)}\s*\(\s*([^()]+?)\s*\)",
            r"\1",
            reply,
            flags=re.IGNORECASE,
        )
        reply = re.sub(
            rf"\bproduct\s+(?:id\s+)?{re.escape(product_id)},\s+",
            "",
            reply,
            flags=re.IGNORECASE,
        )
        reply = re.sub(
            rf"\s*[(\[]\s*(?:product\s+(?:id\s+)?)?{re.escape(product_id)}\s*[)\]]",
            "",
            reply,
            flags=re.IGNORECASE,
        )
    return reply


__all__ = ["cited_ids", "without_ids"]
