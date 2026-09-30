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


__all__ = ["cited_ids"]
