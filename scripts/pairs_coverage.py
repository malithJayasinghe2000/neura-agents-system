"""How many of a real shop's products produce a suggestion — words versus model.

**[ADR-0045](../docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)
§9's falsification test, and it is a test of the feature rather than of the
code:**

> Measure coverage against the word path on the same real catalogue, before and
> after. **If the model path does not beat that by a margin worth the eval suite
> it drags behind it, delete it and keep the words** — the words cost nothing,
> cannot be injected, and need no eval.

    make pairs-coverage URL=http://bagisto.test/neura/v1 TOKEN=...
    make pairs-coverage URL=... TOKEN=... MODEL=1 ROLE_MAP=cloud-prod

**Two arms, and the first one costs nothing.** `--words` runs today's surface
unchanged: no cache, no model, no database. `--model` computes each product's
pairing the way the background job does and then renders it through the
**request** path, so what is counted on both sides is the same thing — a block
a shopper would actually have been shown.

**It is a measurement, not a check.** It exits 0 whatever it finds, because
"fewer products produce a suggestion" is a result ADR-0045 §9 explicitly plans
for and acts on. A script that failed the build on it would be voting.

**Nothing it computes is stored.** The model arm holds its pairings in memory
for the length of the run: this is an experiment against a merchant's catalogue,
and leaving rows behind would make the next run measure this one.

**What it cannot tell you.** Whether a shopper was helped. Coverage counts
blocks that rendered, and a block that renders with a silly product in it counts
exactly the same as a good one — which is why the per-product list is printed in
full rather than summarised into a number.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from neura_adapters.generic import GenericAdapter
from neura_agent_sell.pairing import compute, suggest
from neura_agent_sell.prompts import load_prompts
from neura_commerce import SyncQuery
from neura_core import load_env
from neura_domain import Product

BOLD, DIM, GREEN, RED, YELLOW, OFF = (
    "\033[1m",
    "\033[2m",
    "\033[32m",
    "\033[31m",
    "\033[33m",
    "\033[0m",
)

#: Its own tenant, and nothing is written under it. Named rather than borrowed
#: so a reader of a log can see this was a measurement.
TENANT = "tn_pairs_coverage"

#: What this repository has already measured, printed for comparison and
#: **never asserted** — a different shop is a different number, and a script
#: that checked one would be checking somebody else's catalogue.
#:
#: **The two rows are the same shop nine products apart, and that is the point.**
#: On 2026-09-26 the test shop had no accessories and no care products at all,
#: so most products' complements were simply not for sale; nine were added the
#: same day (`NeuraDemoDataSeeder`, SKUs `ACC-`/`CAR-`). Coverage moved on
#: **both** arms, and it moved *more* on the word path than on the model path —
#: which is why a coverage number alone cannot settle ADR-0045 §9.
KNOWN_WORD_BASELINE = (
    "words 19/29 · model 19/29 (2026-09-26, before the shop stocked any "
    "complements) → words 28/38 · model 29/38 (same day, after)"
)


@dataclass
class Outcome:
    product_id: str
    title: str
    shown: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    stored: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def covered(self) -> bool:
        return bool(self.shown)

    @property
    def from_model(self) -> bool:
        """Did the block a shopper would see come from the model's pairing?

        **The number the headline hides.** `suggest()` falls through to the word
        path whenever a stored pairing yields nothing live, so a model arm can
        report the same coverage as the word arm while the model contributed
        none of it. Counting only the blocks the stored ids actually produced is
        what separates *"the model matched the baseline"* from *"the word path
        matched the baseline twice"*.
        """
        return bool(self.stored) and bool(self.shown) and set(self.shown) <= set(self.stored)

    @property
    def kinds_found_nothing(self) -> bool:
        """The model named kinds and the merchant stocks none of them.

        Not a model failure. It is the catalogue's ceiling, stated from the one
        angle that can see it: a loafer genuinely pairs with shoe polish, and a
        shop that sells no shoe polish has nothing to show.
        """
        return bool(self.kinds) and not self.stored


class _Held:
    """One product's computed pairing, held in memory for one render.

    The request path takes a `PairingCache`; this is the smallest thing that is
    one. Using it rather than calling `select.choose` directly is deliberate:
    what is being measured has to be the block a shopper would see, which means
    the live stock check, `is_pairable` and `product_card` all run.
    """

    def __init__(self, product_id: str, ids: list[str]) -> None:
        self._rows = {product_id: ids}

    async def get(self, product_id: str, *, source_hash: str) -> list[str] | None:
        return self._rows.get(product_id)

    async def queue(self, product_id: str, *, source_hash: str) -> None:
        # Nothing is stored and nothing is scheduled. This is an experiment.
        return None


async def _catalogue(adapter: Any) -> list[Product]:
    """Every product the shop will give us, following its own pagination."""
    products: list[Product] = []
    cursor = None
    while True:
        page = await adapter.list_products(SyncQuery(limit=100), cursor)
        products.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    return products


async def _one(
    product: Product,
    *,
    adapter: Any,
    capabilities: Any,
    llm: Any,
    use_model: bool,
) -> Outcome:
    outcome = Outcome(product_id=str(product.external_id), title=product.title)
    cache = None

    if use_model:
        computed = await compute.compute(
            product,
            adapter=adapter,
            tenant_id=TENANT,
            llm=llm,
            prompt=load_prompts()["pairing"],
        )
        if not computed.measured:
            # Said out loud and counted separately. A provider outage that was
            # silently counted as "no suggestion" would produce a measurement
            # arguing to delete a feature because a server was down.
            outcome.note = f"the model was unreachable: {computed.provider_error}"
            return outcome
        outcome.kinds = computed.kinds
        outcome.stored = list(computed.suggested_ids)
        cache = _Held(str(product.external_id), computed.suggested_ids)

    pairing = await suggest(
        [str(product.external_id)],
        adapter=adapter,
        capabilities=capabilities,
        tenant_id=TENANT,
        cache=cache,
    )
    outcome.shown = [str(card["id"]) for card in pairing.suggestions]
    return outcome


async def run(url: str, token: str, *, use_model: bool, role_map: str) -> int:
    load_env()
    adapter = GenericAdapter(base_url=url, tenant_id=TENANT, token=token)

    llm: Any = None
    if use_model:
        from neura_llm import LLMClient, ModelRole

        llm = LLMClient.from_role_map_name(role_map)
        print(f"\n  {DIM}reasoner {llm.model_for(ModelRole.REASONER)} · role map {role_map}{OFF}")
    else:
        print(f"\n  {DIM}no model — the word path, exactly as it shipped{OFF}")

    try:
        health = await adapter.health()
        if not health.ok:
            print(f"\n  {RED}the shop at {url} is not reachable{OFF}\n")
            return 1

        products = await _catalogue(adapter)
        if not products:
            print(f"\n  {RED}the shop returned no products; nothing to measure{OFF}\n")
            return 1

        print(f"  {DIM}{len(products)} products · baseline to beat: {KNOWN_WORD_BASELINE}{OFF}\n")

        outcomes = [
            await _one(
                product,
                adapter=adapter,
                capabilities=health.capabilities,
                llm=llm,
                use_model=use_model,
            )
            for product in products
        ]
    finally:
        await adapter.aclose()

    _report(outcomes, use_model=use_model)
    return 0


def _report(outcomes: list[Outcome], *, use_model: bool) -> None:
    covered = [o for o in outcomes if o.covered]
    unreachable = [o for o in outcomes if o.note]

    for outcome in outcomes:
        mark = f"{GREEN}✔{OFF}" if outcome.covered else f"{DIM}·{OFF}"
        print(f"  {mark} {outcome.product_id:>8}  {outcome.title[:44]:<44}", end="")
        if outcome.note:
            print(f"  {RED}{outcome.note}{OFF}")
            continue
        if use_model and outcome.kinds:
            print(f"  {DIM}{', '.join(outcome.kinds)}{OFF}", end="")
        print(f"  {DIM}→ {', '.join(outcome.shown) or 'nothing'}{OFF}")

    arm = "model" if use_model else "words"
    print(f"\n  {BOLD}{arm}: {len(covered)} of {len(outcomes)} products produce a suggestion{OFF}")

    if use_model:
        # The two numbers that say *why*, and without them the headline is
        # ambiguous between a model that matched the baseline and a word path
        # that answered underneath it twice.
        from_model = [o for o in outcomes if o.from_model]
        empty_shelf = [o for o in outcomes if o.kinds_found_nothing]
        print(
            f"  {BOLD}{len(from_model)} of those came from the model's own pairing{OFF}"
            f"  {DIM}(the rest are the word path answering underneath){OFF}"
        )
        print(
            f"  {YELLOW}{len(empty_shelf)}{OFF} product(s) got good kinds the shop does not "
            f"stock {DIM}— the catalogue's ceiling, not the model's{OFF}"
        )

    if unreachable:
        print(
            f"  {YELLOW}{len(unreachable)} product(s) never reached a model — "
            f"not a result, and not counted as a miss{OFF}"
        )
    print(
        f"  {DIM}coverage counts blocks that rendered. It says nothing about "
        f"whether a shopper was helped.{OFF}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Pairing coverage on a real shop.")
    parser.add_argument("--url", required=True, help="The shop's Generic Interface base URL")
    parser.add_argument("--token", required=True, help="The shop's API token")
    parser.add_argument(
        "--model",
        action="store_true",
        help="Compute each pairing with a model (ADR-0045). Costs one call per product.",
    )
    parser.add_argument(
        "--role-map",
        default=os.getenv("NEURA_ROLE_MAP", "ollama-dev"),
        help="Which role map the reasoner comes from. Only read with --model.",
    )
    args = parser.parse_args()

    raise SystemExit(
        asyncio.run(run(args.url, args.token, use_model=args.model, role_map=args.role_map))
    )


if __name__ == "__main__":
    main()
