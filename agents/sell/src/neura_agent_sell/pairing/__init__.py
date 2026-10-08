"""SELL's fourth surface: what goes with a product ([ADR-0040], amended by
[ADR-0045](../../../../../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)).

A page sends product ids and gets back at most two complementary products.

**This surface now has a model in it, and the old sentence saying it does not
must not be repeated.** ADR-0045 §1 is precise about what changed and what did
not: *no model runs between a shopper and an answer.* One may run in the
background, once per product, to decide what **kinds** of thing go with it —
and a kind is then searched in the merchant's own catalogue, so only products
the shop itself returned are ever suggested.

**What that costs and what it does not.** *"There is no model to persuade"* is
no longer available as a safety argument here, and
[Rule 4](../../../../../AGENTS.md) now reaches this surface: the pairing prompt
has eval cases and injection resistance stays at 1.00. What is unchanged is
everything a shopper sees — ``select.heading_for`` still writes every visible
word, the model never names a product, and nothing it produces reaches a page
as text. The remaining safety argument is the policy engine, tenant isolation
and those two structural facts, in that order.

    orchestrate.py   one request: cache hit, or the word path plus a queued job
    select.py        every rule about what a shopper may be shown. Pure
    kinds.py         the model call. Kinds, never products
    compute.py       kinds to the merchant's own product ids. Background only
    cache.py         what is stored, when it stops being valid, how it is asked for
    schema.py        the table
"""

from neura_agent_sell.pairing.orchestrate import Pairing, suggest

__all__ = ["Pairing", "suggest"]
