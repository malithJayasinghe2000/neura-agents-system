"""ADR-0040's fourth surface: what goes with a product.

**Tests, not evals, and for the reason `test_sell.py` already records** — the
feed and MCP are deterministic, and so is this: no prompt, no graph, no model
call, so there is nothing here that can regress in the way an eval exists to
catch. Two of the three checks that matter most are about what this surface
*refuses* to do, which a graded conversation could not measure anyway.

Everything runs against the same fixture store SELL's evals use, so a pairing
asserted here is a pairing over the products the rest of the suite reasons
about. Its shape is what makes it useful: three products in `c_outer`, one in
`c_foot`, two in `c_acc` — the exact arrangement ADR-0040 §4 was written about,
where word matching alone returns four jackets.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from neura_agent_sell.evals.store import load_store
from neura_agent_sell.pairing import Pairing, select, suggest
from neura_domain import Capability, Money, Product, ProductStatus, ProductVariant

TENANT = "tn_pairing"

ALL = frozenset(
    {
        Capability.PRODUCT_READ,
        Capability.PRODUCT_SEARCH,
        Capability.CATEGORY_READ,
        Capability.INVENTORY_READ,
    }
)

#: The Crag Lightweight Rain Shell — `c_outer`, 129.00, and the product whose
#: description carries the word every other outer layer also has.
RAIN_SHELL = "p_jacket_2"

#: Merino Walking Socks — `c_acc`, 18.00. The cheap thing in the basket.
SOCKS = "p_socks_1"

#: Moor Walking Boot — `c_foot`, 165.00. "waterproof membrane" in its text.
BOOT = "p_boot_1"


def store(tenant: str = TENANT) -> Any:
    return load_store(tenant)


async def pairing_for(
    ids: list[str],
    *,
    capabilities: frozenset[Capability] = ALL,
    cache: Any = None,
    adapter: Any = None,
    choices: Any = None,
) -> Pairing:
    return await suggest(
        ids,
        adapter=adapter if adapter is not None else store(),
        capabilities=capabilities,
        tenant_id=TENANT,
        cache=cache,
        choices=choices,
    )


#: Stored under any fingerprint. Most tests do not care which text produced a
#: pairing; the two that do say so.
ANY_TEXT = "*"


class FakeCache:
    """A :class:`PairingCache` in a dict.

    Enough to drive every branch of ``orchestrate._stored`` with no database, no
    job queue and no model — which is the same reason ``select.py`` is pure and
    the same reason ``suggest(cache=None)`` still works.
    """

    def __init__(self) -> None:
        self.rows: dict[str, tuple[str, list[str]]] = {}
        self.queued: list[str] = []
        self.fail_on_get = False

    def store(self, product_id: str, ids: list[str], *, source_hash: str = ANY_TEXT) -> None:
        self.rows[product_id] = (source_hash, ids)

    async def get(self, product_id: str, *, source_hash: str) -> list[str] | None:
        if self.fail_on_get:
            raise RuntimeError("the database is down")
        row = self.rows.get(product_id)
        if row is None:
            return None
        stored_hash, ids = row
        return ids if stored_hash in (ANY_TEXT, source_hash) else None

    async def queue(self, product_id: str, *, source_hash: str) -> None:
        self.queued.append(product_id)


class FakeChoices:
    """The owner's choices (ADR-0050) in a dict. ``None`` in the dict is never
    stored: a missing key is automatic, and ``[]`` means *show nothing*."""

    def __init__(self, **chosen: list[str]) -> None:
        self.chosen = chosen
        self.fail = False

    async def get(self, product_id: str) -> list[str] | None:
        if self.fail:
            raise RuntimeError("the database is down")
        return self.chosen.get(product_id)


def product(
    external_id: str,
    *,
    title: str = "A product",
    categories: list[str] | None = None,
    price: str | None = "10.00",
    currency: str = "GBP",
    status: ProductStatus = ProductStatus.ACTIVE,
    in_stock: bool = True,
    description: str = "",
) -> Product:
    """A minimal product, for the rules that need a shape the fixtures lack."""
    return Product(
        neura_id=f"prd_{external_id}",
        tenant_id=TENANT,
        platform="fixture",
        synced_at=datetime(2026, 9, 21, tzinfo=UTC),
        external_id=external_id,
        title=title,
        description=description,
        status=status,
        category_ids=categories if categories is not None else ["c_test"],
        price_range_min=Money(amount=Decimal(price), currency=currency) if price else None,
        variants=[ProductVariant(external_id=f"{external_id}_v1", in_stock=in_stock)],
    )


class TestTheAnchor:
    """Which of the named products the suggestions are paired with."""

    def test_it_is_the_most_expensive(self) -> None:
        """ADR-0040 §6 — usually the main purchase, the jacket not the socks."""
        chosen = select.anchor_of(
            [product("cheap", price="18.00"), product("dear", price="165.00")]
        )
        assert chosen and chosen.external_id == "dear"

    def test_mixed_currencies_do_not_get_compared(self) -> None:
        """40 EUR against 50 USD needs a rate we do not have and must not invent.

        The first supplied product is used instead. Comparing the bare numbers
        would put the wrong product's name into a heading that names it, which
        is a visible, attributable wrong answer rather than a silent one.
        """
        chosen = select.anchor_of(
            [
                product("first", price="40.00", currency="EUR"),
                product("second", price="50.00", currency="USD"),
            ]
        )
        assert chosen and chosen.external_id == "first"

    def test_no_prices_at_all_falls_back_to_the_first(self) -> None:
        """Deterministic, where "any of them" is not."""
        chosen = select.anchor_of([product("a", price=None), product("b", price=None)])
        assert chosen and chosen.external_id == "a"

    def test_an_empty_page_has_no_anchor(self) -> None:
        assert select.anchor_of([]) is None


class TestTheWordsItSelectsOn:
    """Selection is by the merchant's own text — a slot each to title and
    description, then the longest words left."""

    def test_the_most_distinctive_word_comes_first(self) -> None:
        terms = select.pairing_terms(
            product("p", title="Rain Shell", description="A waterproof shell with taped seams")
        )
        assert terms[0] == "waterproof"

    def test_connectives_never_reach_the_search(self) -> None:
        """No stopword list — ordering by length buries them below MAX_TERMS."""
        terms = select.pairing_terms(
            product("p", title="Boot", description="A leather boot with a waterproof membrane")
        )
        assert "with" not in terms

    def test_measurements_are_not_words(self) -> None:
        """`20,000mm` finds the product it came from and nothing else."""
        terms = select.pairing_terms(
            product("p", title="Shell", description="A 3-layer shell, 20,000mm hydrostatic head")
        )
        assert not any(character.isdigit() for term in terms for character in term)

    def test_the_title_always_gets_a_search(self) -> None:
        """Measured on the real shop, 2026-09-24: the Leather Loafer spent all
        three searches on care instructions and found nothing.

        `leather` is one letter shorter than `stitched` and finds two boots. A
        title is written to identify a product, so one of its words is always
        tried.
        """
        terms = select.pairing_terms(
            product(
                "p",
                title="Leather Loafer",
                description="Hand-stitched, polished uppers and a flexible sole",
            )
        )
        assert "leather" in terms

    def test_the_description_keeps_a_search_of_its_own(self) -> None:
        """The opposite failure, and the reason the title does not simply win.

        The Lightweight Rain Shell's title says nothing a shoe would share.
        `waterproof` is in its description and is the word that finds the
        Waterproof Hiking Shoe — ADR-0040 §4's measured pairing. Preferring the
        title outright would spend all three searches on `lightweight`, `shell`
        and `rain`.
        """
        terms = select.pairing_terms(
            product(
                "p",
                title="Lightweight Rain Shell",
                description="A waterproof shell, around the size of a paperback",
            )
        )
        assert "waterproof" in terms

    def test_it_spends_at_most_three_searches(self) -> None:
        """Each term is a live HTTP call on a page that loads for every visitor."""
        wordy = product("p", description=" ".join(f"word{n}extra" for n in range(50)))
        assert len(select.pairing_terms(wordy)) <= select.MAX_TERMS


class TestWhatMayBeShown:
    """`is_pairable` — five refusals, each with a reason."""

    def test_the_anchors_own_category_is_excluded(self) -> None:
        """The measured failure of ADR-0040 §4: `jacket` returns four tops.

        This is the single line that separates *similar* from *complementary*,
        and without it the surface recommends a shopper four more of what they
        already chose.
        """
        anchor = product("anchor", categories=["c_outer"])
        same = product("other_jacket", categories=["c_outer"])
        assert not select.is_pairable(same, anchor, excluded_ids=frozenset())

    def test_a_different_category_is_allowed(self) -> None:
        anchor = product("anchor", categories=["c_outer"])
        boot = product("boot", categories=["c_foot"])
        assert select.is_pairable(boot, anchor, excluded_ids=frozenset())

    def test_a_product_sharing_any_category_is_excluded(self) -> None:
        """Products carry several categories; overlapping on one is enough."""
        anchor = product("anchor", categories=["c_outer", "c_sale"])
        overlapping = product("other", categories=["c_foot", "c_sale"])
        assert not select.is_pairable(overlapping, anchor, excluded_ids=frozenset())

    def test_an_uncategorised_candidate_is_refused(self) -> None:
        """Unknown is treated as unsafe: rule 5 cannot be applied without one."""
        anchor = product("anchor", categories=["c_outer"])
        assert not select.is_pairable(
            product("bare", categories=[]), anchor, excluded_ids=frozenset()
        )

    def test_nothing_already_on_the_page_comes_back(self) -> None:
        anchor = product("anchor", categories=["c_outer"])
        already = product("in_cart", categories=["c_foot"])
        assert not select.is_pairable(already, anchor, excluded_ids=frozenset({"in_cart"}))

    def test_an_unpublished_product_is_never_suggested(self) -> None:
        """A suggestion block is a shortlist of two, and a shortlist is a set of
        recommendations — `search_products`' reason, applied here."""
        anchor = product("anchor", categories=["c_outer"])
        draft = product("draft", categories=["c_foot"], status=ProductStatus.DRAFT)
        assert not select.is_pairable(draft, anchor, excluded_ids=frozenset())

    def test_an_out_of_stock_product_is_never_suggested(self) -> None:
        anchor = product("anchor", categories=["c_outer"])
        gone = product("gone", categories=["c_foot"], in_stock=False)
        assert not select.is_pairable(gone, anchor, excluded_ids=frozenset())


class TestRankingIsMeasuredNotAssumed:
    """`rank_by_rarity` — the 2026-09-21 fix, and the only measured thing here.

    A word matching few products distinguishes one; a word matching many is a
    house adjective. The counts come free, because each term is already searched
    on its own.
    """

    def test_the_rarer_term_wins_even_when_it_is_the_shorter_word(self) -> None:
        """Exactly what the real shop showed on 2026-09-21.

        `lightweight` (11 characters) matched three products; `waterproof` (10)
        matched two. Length said the frock; the counts said the hiking shoe, and
        the counts were right.
        """
        common = [product("frock"), product("trousers"), product("shirt")]
        rare = [product("boot"), product("sock")]

        ranked = select.rank_by_rarity([("lightweight", common), ("waterproof", rare)])

        assert [p.external_id for p in ranked[:2]] == ["boot", "sock"]

    def test_a_tie_keeps_the_order_the_terms_arrived_in(self) -> None:
        """Stable, so one cart yields the same suggestions on every request."""
        first = [product("a"), product("b")]
        second = [product("c"), product("d")]
        ranked = select.rank_by_rarity([("one", first), ("two", second)])
        assert [p.external_id for p in ranked] == ["a", "b", "c", "d"]

    def test_a_term_that_matched_nothing_ranks_first_and_costs_nothing(self) -> None:
        """A typo matches zero products, so it sorts to the front and
        contributes no candidates. Harmless, and cheaper than special-casing."""
        ranked = select.rank_by_rarity([("real", [product("x")]), ("typpo", [])])
        assert [p.external_id for p in ranked] == ["x"]

    def test_it_ranks_terms_and_never_products(self) -> None:
        """The safety property. A per-product score is the first step towards
        ranking by something other than the merchant's own words, and what waits
        at the end of that road is behaviour."""
        group = [product("second"), product("first")]
        ranked = select.rank_by_rarity([("term", group)])
        assert [p.external_id for p in ranked] == ["second", "first"]


class TestTheHeading:
    """§3 — the words on the screen are part of the decision, not styling."""

    def test_it_names_the_product_it_pairs_with(self) -> None:
        """With three items on a page an unlabelled block names nothing a
        shopper can judge or reject."""
        assert select.heading_for(product("p", title="Rain Shell")) == (
            "Goes well with your Rain Shell"
        )

    @pytest.mark.parametrize(
        "forbidden",
        ["bought together", "customers also", "trending", "popular"],
    )
    def test_it_makes_no_claim_about_behaviour(self, forbidden: str) -> None:
        """There is no purchase history in this system, so any of these would be
        a false claim to a shopper — the failure class this repository exists to
        prevent, arriving through a heading instead of a sentence."""
        assert forbidden not in select.heading_for(product("p", title="Rain Shell")).lower()


class TestOnTheFixtureStore:
    """End to end against the store SELL's evals use."""

    @pytest.mark.asyncio
    async def test_a_rain_shell_pairs_with_a_boot_and_not_with_more_jackets(self) -> None:
        """The measured example in ADR-0040 §4, asserted rather than quoted.

        `waterproof` matches two other jackets and a boot. The jackets share
        `c_outer` with the anchor and are dropped; the boot is what a shopper
        buying a rain shell might actually want.
        """
        pairing = await pairing_for([RAIN_SHELL])

        assert pairing.suggestions
        suggested = {card["id"] for card in pairing.suggestions}
        assert BOOT in suggested
        assert not suggested & {"p_jacket_1", "p_jacket_3"}

    @pytest.mark.asyncio
    async def test_it_pairs_with_the_dearest_thing_on_the_page(self) -> None:
        """Socks at 18 and a rain shell at 129: the heading names the shell."""
        pairing = await pairing_for([SOCKS, RAIN_SHELL])
        assert pairing.paired_with and pairing.paired_with["id"] == RAIN_SHELL
        assert "Rain Shell" in pairing.heading

    @pytest.mark.asyncio
    async def test_it_never_suggests_what_is_already_on_the_page(self) -> None:
        pairing = await pairing_for([RAIN_SHELL, BOOT])
        assert BOOT not in {card["id"] for card in pairing.suggestions}

    @pytest.mark.asyncio
    async def test_it_shows_at_most_two(self) -> None:
        pairing = await pairing_for([RAIN_SHELL])
        assert len(pairing.suggestions) <= select.MAX_SUGGESTIONS

    @pytest.mark.asyncio
    async def test_the_unreleased_product_never_appears(self) -> None:
        """`p_draft` is an unreleased down jacket: "Should never reach a shopper
        or a feed." It must not reach a cart page either."""
        pairing = await pairing_for([SOCKS])
        assert "p_draft" not in {card["id"] for card in pairing.suggestions}

    @pytest.mark.asyncio
    async def test_no_description_escapes_onto_the_page(self) -> None:
        """`p_injected`'s description carries a live prompt injection.

        It is an ordinary product and may legitimately be suggested — what must
        never happen is its *text* leaving with it. The surface returns display
        fields only, so there is no field in the response for an injection to
        travel in, and no model anywhere to read it if there were.
        """
        pairing = await pairing_for([RAIN_SHELL, SOCKS, BOOT])
        rendered = repr(pairing.suggestions) + repr(pairing.paired_with) + pairing.heading
        assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in rendered.upper()

    @pytest.mark.asyncio
    async def test_the_cards_carry_no_description_field_at_all(self) -> None:
        pairing = await pairing_for([RAIN_SHELL])
        for card in pairing.suggestions:
            assert set(card) <= {"id", "title", "price", "currency", "in_stock", "url", "image"}


class TestWhenItShowsNothing:
    """§4 — an empty result is an acceptable result, and never an error."""

    @pytest.mark.asyncio
    async def test_no_ids_is_an_empty_pairing(self) -> None:
        assert (await pairing_for([])).is_empty

    @pytest.mark.asyncio
    async def test_unknown_ids_are_an_empty_pairing(self) -> None:
        """Pages hold stale ids all the time; `get_product` returns None by design."""
        assert (await pairing_for(["p_does_not_exist"])).is_empty

    @pytest.mark.asyncio
    async def test_a_store_that_cannot_search_gets_nothing_rather_than_an_error(self) -> None:
        """An absent capability is normal, per INTEGRATION_GUIDE §4 — the
        feature is simply not offered."""
        pairing = await pairing_for([RAIN_SHELL], capabilities=frozenset({Capability.PRODUCT_READ}))
        assert pairing.is_empty

    @pytest.mark.asyncio
    async def test_an_empty_pairing_carries_no_heading(self) -> None:
        """A heading with nothing under it still takes up space and still makes
        a claim."""
        pairing = await pairing_for([])
        assert pairing.heading == ""
        assert pairing.paired_with is None

    @pytest.mark.asyncio
    async def test_a_shop_that_fails_on_lookup_does_not_500_the_cart_page(self) -> None:
        """The merchant's outage must not become ours, on the one page where the
        shopper has already decided to buy (Finding 49's lesson)."""

        class Broken:
            capabilities = ALL

            async def get_product(self, external_id: str) -> Product:
                raise RuntimeError("the shop is down")

            async def search_products(self, query: Any) -> Any:  # pragma: no cover
                raise AssertionError("should never be reached")

        pairing = await suggest([RAIN_SHELL], adapter=Broken(), capabilities=ALL, tenant_id=TENANT)
        assert pairing.is_empty

    @pytest.mark.asyncio
    async def test_a_failing_search_loses_only_its_own_term(self) -> None:
        """One broken search must not discard the results of the others."""
        real = store()
        calls: list[str] = []

        class Flaky:
            capabilities = ALL

            async def get_product(self, external_id: str) -> Any:
                return await real.get_product(external_id)

            async def search_products(self, query: Any) -> Any:
                calls.append(query.text)
                if len(calls) == 1:
                    raise RuntimeError("timeout")
                return await real.search_products(query)

        pairing = await suggest([RAIN_SHELL], adapter=Flaky(), capabilities=ALL, tenant_id=TENANT)
        assert len(calls) > 1
        assert pairing.suggestions


class TestTheBudget:
    """A cart page loads for every visitor, so the call count is a design fact."""

    @pytest.mark.asyncio
    async def test_it_looks_up_at_most_ten_products(self) -> None:
        real = store()
        looked_up: list[str] = []

        class Counting:
            capabilities = ALL

            async def get_product(self, external_id: str) -> Any:
                looked_up.append(external_id)
                return await real.get_product(external_id)

            async def search_products(self, query: Any) -> Any:
                return await real.search_products(query)

        await suggest(
            [f"id_{n}" for n in range(50)],
            adapter=Counting(),
            capabilities=ALL,
            tenant_id=TENANT,
        )
        assert len(looked_up) == select.MAX_INPUT_IDS

    @pytest.mark.asyncio
    async def test_a_long_page_is_truncated_rather_than_refused(self) -> None:
        """A shopper with eleven things in their basket should not meet an error."""
        pairing = await pairing_for([RAIN_SHELL] + [f"id_{n}" for n in range(30)])
        assert pairing.suggestions

    @pytest.mark.asyncio
    async def test_it_never_spends_more_than_three_searches(self) -> None:
        """The ceiling is the budget, and a cart page loads for every visitor."""
        real = store()
        searches: list[str] = []

        class Counting:
            capabilities = ALL

            async def get_product(self, external_id: str) -> Any:
                return await real.get_product(external_id)

            async def search_products(self, query: Any) -> Any:
                searches.append(query.text)
                return await real.search_products(query)

        await suggest([SOCKS], adapter=Counting(), capabilities=ALL, tenant_id=TENANT)
        assert len(searches) <= select.MAX_TERMS

    @pytest.mark.asyncio
    async def test_it_does_not_stop_at_the_first_term_that_fills_both_places(self) -> None:
        """**The 2026-09-21 fix, asserted so it cannot come back.**

        There used to be an early stop: as soon as two pairable candidates
        existed, the remaining terms went unsearched. That made the *first* term
        decide the answer — and the first term is only the longest word. On the
        real shop it filled both places from `lightweight` and never searched
        `waterproof`, which is the word ADR-0040 §4 names as the genuine pair.

        Which term wins cannot be known until every count is in, so every term
        is now searched.
        """
        real = store()
        searches: list[str] = []

        class Counting:
            capabilities = ALL

            async def get_product(self, external_id: str) -> Any:
                return await real.get_product(external_id)

            async def search_products(self, query: Any) -> Any:
                searches.append(query.text)
                return await real.search_products(query)

        anchor = await real.get_product(RAIN_SHELL)
        expected = select.pairing_terms(anchor)

        await suggest([RAIN_SHELL], adapter=Counting(), capabilities=ALL, tenant_id=TENANT)
        assert searches == expected


class TestNoModelRunsWhileAShopperWaits:
    """ADR-0045 §1, asserted structurally rather than by reading the code.

    **This class used to be called `TestTheSurfaceHasNoModelInIt` and it used to
    check something stronger**, because until ADR-0045 something stronger was
    true: no module in the package imported `neura_llm` at all. That ADR
    deliberately ends it — a model may now compute a pairing — and the honest
    replacement is not a weaker version of the old check but a different one.

    The property that remains, and the one a shopper depends on, is about
    *which* modules may: `orchestrate.py` answers a request, `select.py` decides
    what may be shown, and **neither may reach a model on any path**. `kinds.py`
    and `compute.py` run in a worker where nobody is waiting, and they may.

    Parsed rather than grepped: every one of these modules *discusses* prompts
    and models at length, and a substring check would be satisfied by a comment
    promising not to do the thing.
    """

    #: The request path. A model call from either of these is a cart page whose
    #: speed depends on a provider.
    ON_THE_REQUEST_PATH = ("orchestrate.py", "select.py", "cache.py", "schema.py")

    def _imports_of(self, name: str) -> set[str]:
        import ast
        import pathlib

        path = (
            pathlib.Path(__file__).resolve().parents[2]
            / "agents/sell/src/neura_agent_sell/pairing"
            / name
        )
        assert path.exists(), f"{name} moved; this check is now measuring nothing"

        imported: set[str] = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        return imported

    @pytest.mark.parametrize("module", ON_THE_REQUEST_PATH)
    def test_the_request_path_reaches_no_model(self, module: str) -> None:
        """A future edit that puts one there should fail here rather than in a
        shopper's cart."""
        imported = self._imports_of(module)
        assert not any(name.startswith("neura_llm") for name in imported)
        assert not any("prompt" in name for name in imported)
        assert not any(name.endswith("pairing.kinds") for name in imported)

    def test_the_background_half_is_where_the_model_lives(self) -> None:
        """The other side of the same rule, asserted so it cannot quietly move.

        If `kinds.py` stopped importing a model, this surface would have gone
        back to words without anybody deciding to — and the eval suite ADR-0045
        §6 drags behind it would be grading nothing.
        """
        assert any(name.startswith("neura_llm") for name in self._imports_of("kinds.py"))

    def test_orchestrate_never_imports_the_computation(self) -> None:
        """`compute.py` makes a model call, so the module that answers a request
        must not be able to reach it even by accident.

        `orchestrate` does import `compute` for one constant — `MAX_STORED_IDS`
        — which is why this asserts on the *call* rather than on the import: a
        bound is not a behaviour.
        """
        import ast
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[2]
            / "agents/sell/src/neura_agent_sell/pairing/orchestrate.py"
        ).read_text(encoding="utf-8")

        called = {
            node.func.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "compute" not in called
        assert "kinds_for" not in called


class TestTheOwnersChoiceWins:
    """ADR-0050 — the shop owner chose, and nothing automatic overrides it."""

    @pytest.mark.asyncio
    async def test_the_owners_list_replaces_both_automatic_paths(self) -> None:
        """A stored model pairing exists and the word path would find the boot;
        the owner chose the socks, and the socks are what the page gets."""
        cache = FakeCache()
        cache.store(RAIN_SHELL, [BOOT])

        pairing = await pairing_for(
            [RAIN_SHELL], cache=cache, choices=FakeChoices(**{RAIN_SHELL: [SOCKS]})
        )

        assert [card["id"] for card in pairing.suggestions] == [SOCKS]
        assert cache.queued == [], "an owner's choice needs no computation"

    @pytest.mark.asyncio
    async def test_the_same_category_is_allowed_because_that_is_upsell(self) -> None:
        """A jacket beside a jacket: a mistake automatically, the owner's call here."""
        pairing = await pairing_for(
            [RAIN_SHELL], choices=FakeChoices(**{RAIN_SHELL: ["p_jacket_3"]})
        )
        assert [card["id"] for card in pairing.suggestions] == ["p_jacket_3"]

    @pytest.mark.asyncio
    async def test_its_heading_says_recommended_not_goes_well_with(self) -> None:
        pairing = await pairing_for(
            [RAIN_SHELL], choices=FakeChoices(**{RAIN_SHELL: ["p_jacket_3"]})
        )
        assert pairing.heading == "Recommended with your Crag Lightweight Rain Shell"

    @pytest.mark.asyncio
    async def test_an_empty_choice_shows_nothing_and_searches_nothing(self) -> None:
        cache = FakeCache()
        pairing = await pairing_for(
            [RAIN_SHELL], cache=cache, choices=FakeChoices(**{RAIN_SHELL: []})
        )
        assert pairing.is_empty and pairing.heading == ""
        assert cache.queued == []

    @pytest.mark.asyncio
    async def test_the_owners_order_is_kept_and_two_are_shown(self) -> None:
        pairing = await pairing_for(
            [RAIN_SHELL],
            choices=FakeChoices(**{RAIN_SHELL: [SOCKS, "p_jacket_3", "p_jacket_1"]}),
        )
        assert [card["id"] for card in pairing.suggestions] == [SOCKS, "p_jacket_3"]

    @pytest.mark.asyncio
    async def test_what_is_on_the_page_is_still_never_suggested(self) -> None:
        pairing = await pairing_for(
            [RAIN_SHELL, SOCKS], choices=FakeChoices(**{RAIN_SHELL: [SOCKS, BOOT]})
        )
        assert [card["id"] for card in pairing.suggestions] == [BOOT]

    @pytest.mark.asyncio
    async def test_an_unbuyable_choice_is_skipped_and_never_replaced_automatically(
        self,
    ) -> None:
        """The draft jacket cannot be bought and an unknown id finds nothing. The
        block is empty — the automatic path would bring back what the owner
        removed."""
        pairing = await pairing_for(
            [RAIN_SHELL], choices=FakeChoices(**{RAIN_SHELL: ["p_draft", "p_gone"]})
        )
        assert pairing.is_empty

    @pytest.mark.asyncio
    async def test_a_choice_that_cannot_be_read_shows_nothing(self) -> None:
        choices = FakeChoices()
        choices.fail = True
        assert (await pairing_for([RAIN_SHELL], choices=choices)).is_empty

    @pytest.mark.asyncio
    async def test_no_choice_is_automatic_and_unchanged(self) -> None:
        pairing = await pairing_for([RAIN_SHELL], choices=FakeChoices())
        assert BOOT in {card["id"] for card in pairing.suggestions}
        assert pairing.heading.startswith("Goes well with your")

    @pytest.mark.asyncio
    async def test_a_product_without_a_category_can_still_carry_a_choice(self) -> None:
        """The category rule does not bind the owner, so neither does the
        category check that ends the automatic path early."""

        class Store:
            async def get_product(self, product_id: str) -> Product | None:
                return {
                    "a": product("a", title="Plain Tee", categories=[], price="20.00"),
                    "b": product("b", title="Better Tee", categories=[], price="35.00"),
                }.get(product_id)

        pairing = await pairing_for(["a"], adapter=Store(), choices=FakeChoices(a=["b"]))
        assert [card["id"] for card in pairing.suggestions] == ["b"]


class TestTheEndpoint:
    """The gate, which is where ADR-0040 puts the safety argument.

    There is no model on this surface, so "a persuaded model achieves nothing"
    is not available as a defence and must not be offered as one
    ([CLAUDE.md §5](../../CLAUDE.md)). What stands in its place is the scope
    check and tenant isolation, and both of them are these few lines.

    Authentication is monkeypatched rather than faked at the database: the
    route imports `authenticate_request` at call time, so replacing it exercises
    the real handler, the real `require_scopes` and the real `require_agent`
    against a caller we control. The database half — that a key resolves to one
    tenant and no other — belongs to `test_sell_feed_postgres.py`'s kind of
    test and is not restated here.
    """

    @pytest.fixture
    def client(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        from fastapi.testclient import TestClient

        from neura_api.main import create_app

        self._install_stubs(monkeypatch)
        with TestClient(create_app()) as test_client:
            yield test_client

    def _install_stubs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import neura_api.dependencies as dependencies

        async def _authenticate(request: Any) -> Any:
            return self._caller(
                scopes=request.headers.get("x-test-scopes", "sell:suggest:read").split(),
                agents=request.headers.get("x-test-agents", "sell").split(),
            )

        monkeypatch.setattr(dependencies, "authenticate_request", _authenticate)

    def _caller(self, *, scopes: list[str], agents: list[str]) -> Any:
        from neura_core.tenancy.models import ApiKey, ApiKeyKind, AuthenticatedCaller, Tenant

        return AuthenticatedCaller(
            tenant=Tenant(
                tenant_id=TENANT,
                name="A shop",
                enabled_agents=frozenset(agents),
            ),
            api_key=ApiKey(
                id="key_pairing",
                tenant_id=TENANT,
                kind=ApiKeyKind.PUBLIC,
                token_prefix="fn_pk_live_test",
                scopes=frozenset(scopes),
            ),
        )

    @pytest.fixture
    def shop(self, client: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
        """A connected store and a cache, without a database behind either.

        The cache is replaced at `routes._pairing_cache`, which is the seam that
        exists for this. Everything else is real: the real route, the real scope
        check, the real orchestration, the real `select` rules — so what these
        tests measure is the endpoint and not a re-implementation of it.
        """
        from neura_agent_sell import routes as sell_routes

        class Connection:
            def __init__(self) -> None:
                self.adapter = store()
                self.capabilities = ALL
                # Resolved by `StoreDirectory.connect`, and what a pairing is
                # keyed by.
                self.store_id = "st_pairing"

        class Directory:
            async def connect(self, tenant_id: str, *, store_id: str | None = None) -> Any:
                return Connection()

        cache = FakeCache()
        monkeypatch.setattr(
            sell_routes, "_pairing_cache", lambda tenant_id, store_id: cache, raising=True
        )
        choices = FakeChoices()
        monkeypatch.setattr(
            sell_routes, "_owner_choices", lambda tenant_id, store_id: choices, raising=True
        )

        client.app.state.stores = Directory()
        client.pairing_cache = cache
        client.owner_choices = choices
        return client

    def test_a_miss_queues_a_computation_and_still_answers(self, shop: Any) -> None:
        """ADR-0045 §2 end to end, over HTTP.

        The two halves that matter are in one request: the shopper gets the word
        path's answer **now**, and a computation exists for the next one. A
        version of this that queued and returned nothing would satisfy the ADR's
        letter and break its first sentence.
        """
        response = shop.post("/v1/sell/suggestions", json={"product_ids": [RAIN_SHELL]})

        assert response.status_code == 200
        assert response.json()["suggestions"], "the first shopper must not be punished"
        assert shop.pairing_cache.queued == [RAIN_SHELL]

    def test_a_stored_pairing_is_what_the_page_gets(self, shop: Any) -> None:
        """And the word path is not consulted at all — the boot is not a product
        any of the Rain Shell's own words would have found."""
        shop.pairing_cache.store(RAIN_SHELL, [BOOT])

        body = shop.post("/v1/sell/suggestions", json={"product_ids": [RAIN_SHELL]}).json()

        assert [card["id"] for card in body["suggestions"]] == [BOOT]
        assert shop.pairing_cache.queued == []

    def test_the_owners_choice_reaches_the_page(self, shop: Any) -> None:
        """ADR-0050 over HTTP: the route passes the owner's choices in."""
        shop.owner_choices.chosen[RAIN_SHELL] = ["p_jacket_3"]

        body = shop.post("/v1/sell/suggestions", json={"product_ids": [RAIN_SHELL]}).json()

        assert [card["id"] for card in body["suggestions"]] == ["p_jacket_3"]
        assert body["heading"].startswith("Recommended with your")

    def test_the_route_is_mounted_without_the_api_naming_sell(self, client: Any) -> None:
        """Through the `neura.agent_routes` entry point, like the feed and MCP.

        Asserted against the **published** document rather than the route table:
        a surface a merchant's developer cannot discover is one they will not
        wire up, and the feed's public routes set `include_in_schema=False`
        precisely because they are not for integrators. This one is.
        """
        paths = client.app.openapi()["paths"]
        assert "/v1/sell/suggestions" in paths
        assert "post" in paths["/v1/sell/suggestions"]

    def test_it_answers_a_page_that_holds_the_scope(self, shop: Any) -> None:
        response = shop.post("/v1/sell/suggestions", json={"product_ids": [RAIN_SHELL]})
        assert response.status_code == 200
        body = response.json()
        assert body["suggestions"]
        assert "Rain Shell" in body["heading"]

    def test_a_catalogue_key_cannot_ask_for_a_pairing(self, shop: Any) -> None:
        """`sell:suggest:read` is its own gate, exactly as `sell:mcp:connect` is.

        The key on a merchant's cart page is served to every browser that loads
        it. If this accepted `sell:catalogue:read`, that public key would be a
        catalogue-reading key, which is a larger power than the page needs.
        """
        response = shop.post(
            "/v1/sell/suggestions",
            json={"product_ids": [RAIN_SHELL]},
            headers={"x-test-scopes": "sell:catalogue:read sell:chat:write"},
        )
        assert response.status_code == 403

    def test_a_tenant_without_sell_is_refused(self, shop: Any) -> None:
        """Entitlement, not a bug — the tenant has not bought this agent."""
        response = shop.post(
            "/v1/sell/suggestions",
            json={"product_ids": [RAIN_SHELL]},
            headers={"x-test-agents": "care"},
        )
        assert response.status_code in (402, 403)

    def test_an_empty_pairing_is_a_200_and_not_an_error(self, shop: Any) -> None:
        """A 4xx on a cart page costs the merchant a support ticket about an
        error nobody can act on."""
        response = shop.post("/v1/sell/suggestions", json={"product_ids": ["p_unknown"]})
        assert response.status_code == 200
        assert response.json()["suggestions"] == []

    def test_no_ids_at_all_is_still_a_200(self, shop: Any) -> None:
        response = shop.post("/v1/sell/suggestions", json={})
        assert response.status_code == 200
        assert response.json()["suggestions"] == []

    def test_the_body_cannot_name_a_cart(self, shop: Any) -> None:
        """`extra="forbid"`, and the field is `product_ids` for a reason.

        The page says what it is displaying; it never tells this surface what a
        shopper is doing. A field that accepted `cart_id` would be the first
        step towards the tenth endpoint ADR-0040 §2 refuses to add.
        """
        response = shop.post(
            "/v1/sell/suggestions",
            json={"product_ids": [RAIN_SHELL], "cart_id": "c_1"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"

    def test_a_shoppers_page_learns_nothing_new(self, shop: Any) -> None:
        """2026-09-28: `Pairing` gained `origin` and `reason` for the owner's
        preview. The storefront names its three fields, so a cart page is told
        neither who chose nor why a block is empty."""
        body = shop.post("/v1/sell/suggestions", json={"product_ids": [RAIN_SHELL]}).json()
        assert set(body) == {"heading", "paired_with", "suggestions"}


class OneProduct:
    """A shop holding one product, whose searches go to the fixture store."""

    capabilities = ALL

    def __init__(self, item: Product) -> None:
        self.item = item

    async def get_product(self, external_id: str) -> Product | None:
        return self.item if external_id == self.item.external_id else None

    async def search_products(self, query: Any) -> Any:
        return await store().search_products(query)


class TestWhatThePreviewIsTold:
    """2026-09-28 — `suggest()` says who chose what it shows, and why it shows
    nothing, so the owner's preview can say both. The rules are unchanged."""

    @pytest.mark.asyncio
    async def test_a_miss_is_answered_from_the_words(self) -> None:
        pairing = await pairing_for([RAIN_SHELL], cache=FakeCache())
        assert pairing.suggestions
        assert pairing.origin == "words"

    @pytest.mark.asyncio
    async def test_a_stored_pairing_is_the_models(self) -> None:
        cache = FakeCache()
        cache.store(RAIN_SHELL, [BOOT])
        pairing = await pairing_for([RAIN_SHELL], cache=cache)
        assert [card["id"] for card in pairing.suggestions] == [BOOT]
        assert pairing.origin == "model"

    @pytest.mark.asyncio
    async def test_the_owners_choice_is_the_owners(self) -> None:
        pairing = await pairing_for([RAIN_SHELL], choices=FakeChoices(**{RAIN_SHELL: [SOCKS]}))
        assert pairing.origin == "owner"
        assert pairing.reason == ""

    @pytest.mark.asyncio
    async def test_an_owner_who_chose_nothing_is_told_so(self) -> None:
        pairing = await pairing_for([RAIN_SHELL], choices=FakeChoices(**{RAIN_SHELL: []}))
        assert pairing.is_empty
        assert pairing.reason == "owner_nothing"

    @pytest.mark.asyncio
    async def test_a_product_with_no_category_is_told_so(self) -> None:
        """The one empty result an owner can fix in their own shop."""
        bare = product("p_bare", title="Merino Crew Knit", categories=[])
        pairing = await suggest(
            ["p_bare"], adapter=OneProduct(bare), capabilities=ALL, tenant_id=TENANT
        )
        assert pairing.reason == "no_category"

    @pytest.mark.asyncio
    async def test_nothing_matched_is_told_so(self) -> None:
        lonely = product("p_lonely", title="Zyxwv Qqqqq", description="Zyxwv")
        pairing = await suggest(
            ["p_lonely"], adapter=OneProduct(lonely), capabilities=ALL, tenant_id=TENANT
        )
        assert pairing.is_empty
        assert pairing.reason == "nothing_matched"

    @pytest.mark.asyncio
    async def test_an_unknown_product_and_a_shop_that_cannot_search(self) -> None:
        assert (await pairing_for(["p_does_not_exist"])).reason == "not_found"
        cannot = await pairing_for([RAIN_SHELL], capabilities=frozenset({Capability.PRODUCT_READ}))
        assert cannot.reason == "cannot_search"


class TestTheOwnersPreview:
    """The console's preview endpoint (2026-09-28): the basket's own answer,
    asked of the shop when the owner opens a product — and never a model run.

    The console's session and role check is replaced with FastAPI's own
    override of SELL's permission, and the shop lookup at `console._store`
    (their own tests cover both); the shop, cache and choices at the same seams
    the storefront tests use, so this is the real route and the real
    `suggest()`.
    """

    @pytest.fixture
    def preview(self, monkeypatch: pytest.MonkeyPatch) -> Any:
        from types import SimpleNamespace

        from fastapi.testclient import TestClient

        from neura_agent_sell import console as sell_console
        from neura_agent_sell import routes as sell_routes
        from neura_api.dependencies import Permitted
        from neura_api.main import create_app

        async def _store(actor: Any, agent_key: str) -> str:
            return "st_pairing"

        async def _computed(tenant_id: str, store_id: str, product_id: str) -> Any:
            return self.tried

        async def _rows(tenant_id: str, store_id: str, **_: Any) -> Any:
            return [], True

        self.tried: Any = None
        self.adapter: Any = store()
        cache, choices = FakeCache(), FakeChoices()
        monkeypatch.setattr(sell_console, "_store", _store)
        monkeypatch.setattr(sell_console, "_computed", _computed)
        monkeypatch.setattr(sell_console, "_rows", _rows)
        monkeypatch.setattr(sell_routes, "_pairing_cache", lambda tenant_id, store_id: cache)
        monkeypatch.setattr(sell_routes, "_owner_choices", lambda tenant_id, store_id: choices)

        test = self

        class Directory:
            async def connect(self, tenant_id: str, *, store_id: str | None = None) -> Any:
                return SimpleNamespace(
                    adapter=test.adapter, capabilities=ALL, store_id="st_pairing"
                )

        app = create_app()
        app.dependency_overrides[Permitted(sell_console.SUGGESTIONS)] = lambda: SimpleNamespace(
            tenant_id=TENANT, user_id="usr_owner", role="owner"
        )
        with TestClient(app) as client:
            client.app.state.stores = Directory()
            client.pairing_cache = cache
            client.owner_choices = choices
            yield client

    def ask(self, client: Any, product_id: str) -> dict[str, Any]:
        response = client.get(f"/v1/sell/console/shops/{TENANT}/suggestions/{product_id}/preview")
        assert response.status_code == 200, response.text
        data: dict[str, Any] = response.json()["data"]
        return data

    def test_opening_a_product_never_queues_the_model(self, preview: Any) -> None:
        """The one way it differs from a basket. A basket's miss queues a model
        computation; an owner clicking through products must not spend one."""
        data = self.ask(preview, RAIN_SHELL)
        assert data["suggestions"]
        assert data["origin"] == "words"
        assert preview.pairing_cache.queued == []

    def test_a_stored_pairing_is_previewed_as_the_ais(self, preview: Any) -> None:
        preview.pairing_cache.store(RAIN_SHELL, [BOOT])
        data = self.ask(preview, RAIN_SHELL)
        assert data["origin"] == "model"
        assert [card["id"] for card in data["suggestions"]] == [BOOT]

    def test_the_owners_choice_is_previewed_as_theirs(self, preview: Any) -> None:
        preview.owner_choices.chosen[RAIN_SHELL] = [SOCKS]
        data = self.ask(preview, RAIN_SHELL)
        assert data["origin"] == "owner"
        assert data["heading"].startswith("Recommended with your")

    def test_a_shop_that_does_not_answer_is_said_not_shown_as_empty(self, preview: Any) -> None:
        """`suggest()` forgives a failed lookup as a missing product; here that
        would read as "not in your shop" while the shop was simply down."""

        class Down:
            capabilities = ALL

            async def get_product(self, external_id: str) -> Any:
                raise RuntimeError("the shop is down")

        self.adapter = Down()
        data = self.ask(preview, RAIN_SHELL)
        assert data["reachable"] is False
        assert data["suggestions"] == []
        assert data["reason"] is None

    def test_a_product_the_shop_no_longer_has(self, preview: Any) -> None:
        data = self.ask(preview, "p_does_not_exist")
        assert data["reachable"] is True
        assert data["reason"] == "not_found"

    def test_what_the_ai_looked_for_is_passed_through(self, preview: Any) -> None:
        self.tried = {"kinds": ["socks", "shoe polish"], "found": 1}
        assert self.ask(preview, RAIN_SHELL)["ai"] == self.tried


# ─────────────────────────────────────────────────────────────────────────────
# ADR-0045 — a pairing may be computed by a model, but never while a shopper
# waits.
#
# **Still tests, and now only half the story.** Everything below is
# deterministic: what a stored pairing is used for, what is stripped out of a
# model's answer before it becomes a search, and which of the merchant's own
# products may be written down. None of it asks a model anything.
#
# The half that *is* a model — whether the pairing prompt returns kinds rather
# than products, and whether a hostile product description can move what a
# shopper sees — is an eval, because it can regress in the way only an eval
# catches. It lives in `agents/sell/.../evals/datasets/pairing.yaml`, and
# ADR-0045 §6 is why: Rule 4 now reaches this surface, and `E8`'s "these are
# tests, not evals" reasoning stops applying the moment a model chooses
# anything.
# ─────────────────────────────────────────────────────────────────────────────


class StubLLM:
    """A model that returns what the test says, and records what it was asked."""

    def __init__(self, kinds: list[str] | None = None, *, raises: bool = False) -> None:
        self._kinds = kinds or []
        self._raises = raises
        self.requests: list[Any] = []

    async def chat_structured(self, role: Any, request: Any, schema_type: Any) -> Any:
        self.requests.append(request)
        if self._raises:
            raise RuntimeError("the provider is unreachable")

        class Result:
            value = schema_type(kinds=self._kinds)
            attempts = 1

        return Result()


class TestTheStoredPairing:
    """ADR-0045 §2 — which of the two paths answers, and what each costs."""

    async def test_a_stored_pairing_is_used_and_nothing_is_searched(self) -> None:
        """The whole point: a cache hit spends no search on the merchant's shop.

        The Moor Walking Boot is the assertion that this is a *different* answer
        rather than the same one arriving differently — the Rain Shell's own
        words do find it today, so the test also counts the searches.
        """
        searched: list[str] = []
        real = store()

        class Counting:
            async def get_product(self, product_id: str) -> Any:
                return await real.get_product(product_id)

            async def search_products(self, query: Any) -> Any:
                searched.append(query.text)
                return await real.search_products(query)

        cache = FakeCache()
        cache.store(RAIN_SHELL, [BOOT])

        pairing = await pairing_for([RAIN_SHELL], cache=cache, adapter=Counting())

        assert [card["id"] for card in pairing.suggestions] == [BOOT]
        assert searched == []
        assert cache.queued == []

    async def test_a_miss_answers_from_words_and_queues_exactly_one(self) -> None:
        """*"The first shopper is never punished"* — §2, and the queue is the
        only thing that makes that sentence affordable."""
        cache = FakeCache()

        pairing = await pairing_for([RAIN_SHELL], cache=cache)

        assert not pairing.is_empty
        assert cache.queued == [RAIN_SHELL]

    async def test_a_pairing_computed_from_older_text_is_not_used(self) -> None:
        """§5 — *"a stale pairing is a wrong suggestion with a long life"*.

        The merchant rewrote the description; the fingerprint no longer matches;
        the stored ids are ignored and a recomputation is queued. What the
        shopper gets meanwhile is the word path, which is reading the text that
        actually exists.
        """
        cache = FakeCache()
        cache.store(RAIN_SHELL, [BOOT], source_hash="a fingerprint of some older words")

        pairing = await pairing_for([RAIN_SHELL], cache=cache)

        assert [card["id"] for card in pairing.suggestions] != [BOOT]
        assert cache.queued == [RAIN_SHELL]

    async def test_the_fingerprint_it_stores_under_is_the_live_one(self) -> None:
        """The other direction of the same rule: a matching hash *is* used."""
        from neura_agent_sell.pairing.cache import source_hash

        anchor = await store().get_product(RAIN_SHELL)
        cache = FakeCache()
        cache.store(RAIN_SHELL, [BOOT], source_hash=source_hash(anchor))

        pairing = await pairing_for([RAIN_SHELL], cache=cache)

        assert [card["id"] for card in pairing.suggestions] == [BOOT]
        assert cache.queued == []

    async def test_a_stored_product_that_sold_out_is_skipped_not_shown(self) -> None:
        """§4 — *"the cache holds a pairing, never an availability"*.

        Stock is read live, here, on this request. A surface that trusted the
        row would recommend a product the shopper cannot buy, which is the
        failure `is_pairable` rule 3 exists for, arriving a month late.
        """
        real = store()
        sold_out = BOOT

        class Withdrawn:
            async def get_product(self, product_id: str) -> Any:
                found = await real.get_product(product_id)
                if found is not None and product_id == sold_out:
                    return found.model_copy(update={"status": ProductStatus.ARCHIVED})
                return found

            async def search_products(self, query: Any) -> Any:
                return await real.search_products(query)

        cache = FakeCache()
        # The spare is why `MAX_STORED_IDS` is larger than `MAX_SUGGESTIONS`.
        cache.store(RAIN_SHELL, [sold_out, SOCKS])

        pairing = await pairing_for([RAIN_SHELL], cache=cache, adapter=Withdrawn())

        assert [card["id"] for card in pairing.suggestions] == [SOCKS]

    async def test_a_stored_pairing_with_nothing_left_falls_back_to_words(self) -> None:
        """Every spare gone is still not an empty block — the word path is
        underneath, and ADR-0045's "reversible" claim is this line."""
        real = store()

        class AllGone:
            async def get_product(self, product_id: str) -> Any:
                if product_id == "p_vanished":
                    return None
                return await real.get_product(product_id)

            async def search_products(self, query: Any) -> Any:
                return await real.search_products(query)

        cache = FakeCache()
        cache.store(RAIN_SHELL, ["p_vanished"])

        pairing = await pairing_for([RAIN_SHELL], cache=cache, adapter=AllGone())

        assert not pairing.is_empty

    async def test_a_stored_empty_pairing_is_respected_and_not_requeued(self) -> None:
        """A model ran, found nothing complementary, and that was written down.

        Re-queueing it would mean every cart page paid for the same model call
        to reach the same empty answer — which is the cost `cache.put` stores an
        empty result to avoid. The word path still runs, because empty here is
        *the model's* empty and not the surface's.
        """
        cache = FakeCache()
        cache.store(RAIN_SHELL, [])

        await pairing_for([RAIN_SHELL], cache=cache)

        assert cache.queued == []

    async def test_a_cache_that_raises_costs_a_shopper_nothing(self) -> None:
        """A database outage must not reach a cart page. ADR-0040 §4's
        *empty is a result* protects the block; this protects the whole page."""
        cache = FakeCache()
        cache.fail_on_get = True

        pairing = await pairing_for([RAIN_SHELL], cache=cache)

        assert not pairing.is_empty

    async def test_without_a_cache_the_surface_is_what_it_was(self) -> None:
        """ADR-0045 §9's falsification test only exists because both still run.

        `make pairs-check`'s stub mode, every other test in this file, and a
        deployment that has not migrated all take this path.
        """
        with_none = await pairing_for([RAIN_SHELL], cache=None)
        assert not with_none.is_empty


class TestTheKindsAModelMayReturn:
    """ADR-0045 §3 and §7 — what is done to a model's answer before it is
    trusted with anything, and it is done in code rather than asked for in the
    prompt (AGENTS.md rule 3)."""

    def test_markup_and_punctuation_never_reach_a_search(self) -> None:
        from neura_agent_sell.pairing.kinds import clean_kinds

        assert clean_kinds(["<script>alert(1)</script>"]) == ["script alert script"]
        assert clean_kinds(["javascript:void(0)"]) == ["javascript void"]
        assert clean_kinds(["  Wool   Socks  "]) == ["wool socks"]

    def test_a_kind_is_bounded_in_words_and_in_number(self) -> None:
        """The prompt asks for one to three of each. This is the bound that
        holds when the prompt is ignored, which is the only kind worth having."""
        from neura_agent_sell.pairing import kinds as kinds_module

        long_kind = kinds_module.clean_kinds(["one two three four five six"])
        assert long_kind == ["one two three"]

        many = kinds_module.clean_kinds(["socks", "polish", "laces", "spray", "insoles"])
        assert len(many) == kinds_module.MAX_KINDS

    def test_duplicates_go_and_the_model_s_order_stays(self) -> None:
        """Unlike the word path, nothing here measures rarity — the order *is*
        the model's ranking, and it is the only one this path has."""
        from neura_agent_sell.pairing.kinds import clean_kinds

        assert clean_kinds(["shoe polish", "Shoe Polish", "wool socks"]) == [
            "shoe polish",
            "wool socks",
        ]

    def test_nothing_survives_a_kind_with_no_words_in_it(self) -> None:
        from neura_agent_sell.pairing.kinds import clean_kinds

        assert clean_kinds(["", "   ", "!!!", "2000"]) == []

    def test_the_product_text_is_delimited_and_bounded(self) -> None:
        """Same tagging as `route.md`'s untrusted message and the same reason:
        the boundary between material and instruction is invisible to a model
        unless it is visible in the text."""
        from neura_agent_sell.pairing import kinds as kinds_module

        rendered = kinds_module.render(product("p_long", title="A jacket", description="x" * 9000))

        assert rendered.startswith("<untrusted_product_text>")
        assert rendered.endswith("</untrusted_product_text>")
        assert len(rendered) < kinds_module.MAX_TEXT_CHARS + 100

    async def test_the_model_is_offered_no_tools(self) -> None:
        """§7 point 2, asserted rather than asserted *about*. It reads one
        product's text and returns a short list; there is nothing for a
        persuaded model to invoke."""
        from neura_agent_sell.pairing.kinds import kinds_for

        llm = StubLLM(["wool socks"])
        await kinds_for(product("p_x", title="Boot"), llm=llm, prompt="a prompt")

        assert llm.requests[0].tools in (None, [])

    async def test_a_provider_that_is_down_is_reported_and_not_swallowed(self) -> None:
        """**An outage and an honest empty are not the same answer.**

        Both produce no kinds, and collapsing them into an empty list would
        write *"this product pairs with nothing"* into the cache on the strength
        of a dead server — permanently, because the row would go on matching the
        live fingerprint for ever. That is `E6`'s shape arriving in a table
        instead of a report, and it is why this returns a result object rather
        than a list.
        """
        from neura_agent_sell.pairing.kinds import kinds_for

        answer = await kinds_for(product("p_x"), llm=StubLLM(raises=True), prompt="p")

        assert answer.kinds == []
        assert not answer.reachable
        # A type name, never the exception's text: a provider's message can
        # carry a URL or a key fragment, and this string is logged and stored.
        assert answer.error == "RuntimeError"

    async def test_an_honest_empty_is_reachable(self) -> None:
        """The other side of the same distinction. A model that read a product
        and found nothing to pair with it is a **result**, and ADR-0040 §4 has
        always said so."""
        from neura_agent_sell.pairing.kinds import kinds_for

        answer = await kinds_for(product("p_x"), llm=StubLLM([]), prompt="p")

        assert answer.kinds == []
        assert answer.reachable


class TestComputingAPairing:
    """ADR-0045 §3 — *"only ids that come back from that search are ever
    stored"*. This is the sentence that bounds an indirect injection to a bad
    suggestion, and it is the one worth several tests."""

    async def test_a_model_cannot_name_a_product_into_existence(self) -> None:
        """A hallucinated *"Dry Bag Pro 2000"* becomes a **search**, and only
        what the merchant's own catalogue hands back may be stored.

        **Note what this does not claim, because writing it the other way was
        wrong.** The first version of this test asserted that an invented name
        *finds nothing*. It does not: a keyword search matches on any shared
        word, so `Dry Bag Pro 2000` can perfectly well return a real product
        that happens to contain "pro". That outcome is a **bad suggestion** —
        which is exactly the worst case ADR-0045 §7 says this surface carries,
        and says is an eval case rather than a security incident.

        What is structural, and is what this asserts, is that nothing the model
        invented is ever in the result. The id came from the shop.
        """
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        result = await compute(
            anchor,
            adapter=real,
            tenant_id=TENANT,
            llm=StubLLM(["Dry Bag Pro 2000"]),
            prompt="a prompt",
        )

        assert set(result.suggested_ids) <= result.returned_ids
        assert not any("dry bag" in product_id.lower() for product_id in result.suggested_ids)

    async def test_every_stored_id_came_back_from_the_merchant_s_own_search(self) -> None:
        """The invariant stated as an assertion rather than as a comment."""
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        result = await compute(
            anchor,
            adapter=real,
            tenant_id=TENANT,
            llm=StubLLM(["socks", "boot"]),
            prompt="a prompt",
        )

        assert result.suggested_ids
        assert set(result.suggested_ids) <= result.returned_ids

    async def test_the_anchor_s_own_category_is_excluded_here_too(self) -> None:
        """§4 — applied to the model's candidates exactly as to the word path's.

        `jacket` finds the other outer layers, all of which sit in the Rain
        Shell's own category, and none of them may be stored.
        """
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        result = await compute(
            anchor,
            adapter=real,
            tenant_id=TENANT,
            # `hardshell` is the one word in this catalogue that only an outer
            # layer has. `jacket` would not do: it appears in the *injected*
            # product's description, and matching it there is a finding of its
            # own rather than a test of this rule.
            llm=StubLLM(["hardshell"]),
            prompt="a prompt",
        )

        assert result.suggested_ids == []

    async def test_it_stores_spares_beyond_what_a_shopper_sees(self) -> None:
        """`MAX_STORED_IDS` is larger than `MAX_SUGGESTIONS` so that one product
        selling out does not empty the block until the next computation."""
        from neura_agent_sell.pairing.compute import MAX_STORED_IDS

        assert MAX_STORED_IDS > select.MAX_SUGGESTIONS

    async def test_one_failed_search_does_not_lose_the_others(self) -> None:
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        class Flaky:
            async def search_products(self, query: Any) -> Any:
                if query.text == "socks":
                    raise RuntimeError("the shop returned a 500")
                return await real.search_products(query)

        result = await compute(
            anchor,
            adapter=Flaky(),
            tenant_id=TENANT,
            llm=StubLLM(["socks", "boot"]),
            prompt="a prompt",
        )

        assert result.suggested_ids

    async def test_an_outage_is_not_a_result_and_must_not_be_stored(self) -> None:
        """`measured` is what the job handler branches on. A computation that
        never reached a model raises and writes nothing, so the queue's backoff
        retries it — rather than caching an outage until somebody edits the
        product's description."""
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        result = await compute(
            anchor,
            adapter=real,
            tenant_id=TENANT,
            llm=StubLLM(raises=True),
            prompt="a prompt",
        )

        assert not result.measured
        assert result.provider_error == "RuntimeError"
        assert result.is_empty

    async def test_a_model_that_says_nothing_costs_no_search(self) -> None:
        from neura_agent_sell.pairing.compute import compute

        searched: list[str] = []
        real = store()

        class Counting:
            async def search_products(self, query: Any) -> Any:
                searched.append(query.text)
                return await real.search_products(query)

        anchor = await real.get_product(RAIN_SHELL)
        result = await compute(
            anchor, adapter=Counting(), tenant_id=TENANT, llm=StubLLM([]), prompt="a prompt"
        )

        assert result.is_empty
        assert searched == []


class TestWhatInvalidatesAStoredPairing:
    """ADR-0045 §5 — the fingerprint is of the text the model read, and of
    nothing else."""

    def test_editing_the_title_or_the_description_changes_it(self) -> None:
        from neura_agent_sell.pairing.cache import source_hash

        base = product("p_1", title="Walking Boot", description="Leather, waterproof.")
        assert source_hash(base) != source_hash(base.model_copy(update={"title": "Cycling Shoe"}))
        assert source_hash(base) != source_hash(
            base.model_copy(update={"description": "Canvas, breathable."})
        )

    def test_a_price_change_does_not(self) -> None:
        """A pairing does not depend on a price, and recomputing every product
        whose price moved would spend model calls on nothing."""
        from neura_agent_sell.pairing.cache import source_hash

        base = product("p_1", title="Walking Boot", price="165.00")
        assert source_hash(base) == source_hash(base.model_copy(update={"price_range_min": None}))

    def test_the_same_words_split_differently_are_not_the_same_product(self) -> None:
        """The NUL separator. Without one, a title ending where a description
        begins collides with the same words divided elsewhere — and a collision
        here means a pairing that is never invalidated."""
        from neura_agent_sell.pairing.cache import source_hash

        left = product("p_1", title="Wool", description="Socks")
        right = product("p_1", title="Wool Socks", description="")
        assert source_hash(left) != source_hash(right)

    def test_one_live_computation_per_product_however_many_pages_missed(self) -> None:
        """§2 — *"no request triggers more than one computation"*. Twenty cart
        pages in a minute find the same empty cache; the dedupe key is what
        makes that one model call rather than twenty."""
        from neura_agent_sell.pairing.cache import dedupe_key_for

        assert dedupe_key_for("st_1", "1315") == dedupe_key_for("st_1", "1315")
        assert dedupe_key_for("st_1", "1315") != dedupe_key_for("st_2", "1315")
        assert len(dedupe_key_for("st_1", "x" * 400)) <= 128


# ─────────────────────────────────────────────────────────────────────────────
# ADR-0047 — a kind is resolved by meaning, not by a shared word.
#
# One step of ADR-0045 §3 changes: a kind goes to the embedding index as well as
# to the merchant's search box. **Deterministic, and tested with a stub index
# rather than a real embedder** — what changed is a lookup, not a model
# behaviour, so there is nothing here an eval could catch that a test cannot.
#
# The measured miss it exists for: the model asked a real shop for `ankle socks`,
# the shop sells *Merino Walking Socks*, no word is shared, and the block
# rendered nothing.
# ─────────────────────────────────────────────────────────────────────────────


class StubRetriever:
    """An embedding index in a dict, keyed by the phrase asked of it.

    Returns chunks the way `Retriever.search` does — `source_id` is the
    merchant's own `external_id`, which is the fact ADR-0047 §2 rests on.
    """

    def __init__(self, hits: dict[str, list[str]] | None = None, *, raises: bool = False) -> None:
        self._hits = hits or {}
        self._raises = raises
        self.queries: list[str] = []
        self.source_types: list[Any] = []

    async def search(
        self, query: str, *, limit: int = 5, source_types: Any = None, **_: Any
    ) -> Any:
        self.queries.append(query)
        self.source_types.append(source_types)
        if self._raises:
            raise RuntimeError("the embedder is unreachable")

        class Chunk:
            def __init__(self, source_id: str) -> None:
                self.source_id = source_id

        class Result:
            chunks = [Chunk(product_id) for product_id in self._hits.get(query, [])][:limit]

        return Result()


class TestAKindIsResolvedByMeaning:
    """ADR-0047 — what the second lookup adds, and what it may not do."""

    async def test_a_kind_the_shop_stocks_under_another_word_is_found(self) -> None:
        """**The whole ADR, in one assertion.**

        `hosiery` shares no word with *Merino Walking Socks*. The keyword lookup
        returns nothing; the index returns the socks; the block renders.
        """
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        class NoKeywordMatch:
            async def search_products(self, query: Any) -> Any:
                from neura_commerce import Page

                return Page(items=[])

            async def get_product(self, product_id: str) -> Any:
                return await real.get_product(product_id)

        result = await compute(
            anchor,
            adapter=NoKeywordMatch(),
            tenant_id=TENANT,
            llm=StubLLM(["hosiery"]),
            prompt="a prompt",
            retriever=StubRetriever({"hosiery": [SOCKS]}),
        )

        assert result.suggested_ids == [SOCKS]
        assert SOCKS in result.returned_ids

    async def test_without_a_retriever_nothing_changes(self) -> None:
        """ADR-0047 §4 — a shop that was never indexed loses nothing, which is
        what lets this ship without a reindex."""
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        with_none = await compute(
            anchor, adapter=real, tenant_id=TENANT, llm=StubLLM(["socks"]), prompt="p"
        )
        with_empty = await compute(
            anchor,
            adapter=real,
            tenant_id=TENANT,
            llm=StubLLM(["socks"]),
            prompt="p",
            retriever=StubRetriever({}),
        )

        assert with_none.suggested_ids == with_empty.suggested_ids

    async def test_an_unreachable_embedder_costs_the_tier_and_nothing_else(self) -> None:
        """The keyword hits for that kind have already been gathered, and the
        word path is underneath both. A provider outage must not empty a block
        the shop could have filled."""
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        result = await compute(
            anchor,
            adapter=real,
            tenant_id=TENANT,
            llm=StubLLM(["socks"]),
            prompt="p",
            retriever=StubRetriever(raises=True),
        )

        assert result.suggested_ids

    async def test_the_index_may_name_a_candidate_and_never_describe_one(self) -> None:
        """ADR-0029, and it is why a vector hit costs a live product lookup.

        The chunk carries an id *and* a slice of text. Only the id is used: the
        category and the status that decide what a shopper sees are read from the
        shop. A pairing built from indexed text would be a pairing built on a
        catalogue that may be hours stale.
        """
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)
        fetched: list[str] = []

        class Watching:
            async def search_products(self, query: Any) -> Any:
                from neura_commerce import Page

                return Page(items=[])

            async def get_product(self, product_id: str) -> Any:
                fetched.append(product_id)
                return await real.get_product(product_id)

        await compute(
            anchor,
            adapter=Watching(),
            tenant_id=TENANT,
            llm=StubLLM(["hosiery"]),
            prompt="p",
            retriever=StubRetriever({"hosiery": [SOCKS]}),
        )

        assert fetched == [SOCKS]

    async def test_it_asks_the_index_for_products_and_nothing_else(self) -> None:
        """A policy page or a category chunk is not a product and must never
        become a suggestion."""
        from neura_agent_sell.pairing.compute import compute
        from neura_commerce import EntityType

        real = store()
        anchor = await real.get_product(RAIN_SHELL)
        retriever = StubRetriever({"socks": [SOCKS]})

        await compute(
            anchor,
            adapter=real,
            tenant_id=TENANT,
            llm=StubLLM(["socks"]),
            prompt="p",
            retriever=retriever,
        )

        assert retriever.source_types == [[EntityType.PRODUCT]]

    async def test_an_id_the_index_returns_is_still_subject_to_every_rule(self) -> None:
        """§5 — the anchor's own category is excluded for a vector hit exactly as
        for a keyword hit. The index is a lookup, not a bypass."""
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        class NoKeywordMatch:
            async def search_products(self, query: Any) -> Any:
                from neura_commerce import Page

                return Page(items=[])

            async def get_product(self, product_id: str) -> Any:
                return await real.get_product(product_id)

        # `p_jacket_1` sits in `c_outer`, the anchor's own category.
        result = await compute(
            anchor,
            adapter=NoKeywordMatch(),
            tenant_id=TENANT,
            llm=StubLLM(["outerwear"]),
            prompt="p",
            retriever=StubRetriever({"outerwear": ["p_jacket_1"]}),
        )

        assert result.suggested_ids == []

    async def test_the_keyword_hit_comes_first(self) -> None:
        """§7's ordering, and it is a guess the ADR labels as one: where a
        merchant's own vocabulary is exact, the exact match is likelier to be
        what they meant."""
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)

        result = await compute(
            anchor,
            adapter=real,
            tenant_id=TENANT,
            llm=StubLLM(["socks"]),
            prompt="p",
            # The index offers the boot; the search box already finds the socks.
            retriever=StubRetriever({"socks": [BOOT]}),
        )

        assert result.suggested_ids[0] == SOCKS

    async def test_a_duplicate_costs_no_second_lookup(self) -> None:
        """The index and the search box agreeing is the common case, and a
        product fetched twice is a live HTTP call spent to reach an answer
        already held."""
        from neura_agent_sell.pairing.compute import compute

        real = store()
        anchor = await real.get_product(RAIN_SHELL)
        fetched: list[str] = []

        class Watching:
            async def search_products(self, query: Any) -> Any:
                return await real.search_products(query)

            async def get_product(self, product_id: str) -> Any:
                fetched.append(product_id)
                return await real.get_product(product_id)

        await compute(
            anchor,
            adapter=Watching(),
            tenant_id=TENANT,
            llm=StubLLM(["socks"]),
            prompt="p",
            retriever=StubRetriever({"socks": [SOCKS]}),
        )

        assert fetched == []
