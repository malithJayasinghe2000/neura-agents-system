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


async def pairing_for(ids: list[str], *, capabilities: frozenset[Capability] = ALL) -> Pairing:
    return await suggest(ids, adapter=store(), capabilities=capabilities, tenant_id=TENANT)


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


class TestTheSurfaceHasNoModelInIt:
    """§5 — asserted structurally, not by reading the code."""

    def test_nothing_in_the_package_imports_an_llm(self) -> None:
        """The property that makes this surface un-injectable is that there is
        no model to persuade. A future edit that adds one should fail here
        rather than in a shopper's cart.

        Parsed rather than grepped: these modules *discuss* prompts and models
        at length, and a substring check would be satisfied by a comment
        promising not to do the thing.
        """
        import ast
        import pathlib

        package = pathlib.Path(__file__).resolve().parents[2] / (
            "agents/sell/src/neura_agent_sell/pairing"
        )
        modules = sorted(package.glob("*.py"))
        assert modules, "the pairing package moved; this check is now measuring nothing"

        imported: set[str] = set()
        for path in modules:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)

        assert not any(name.startswith("neura_llm") for name in imported)
        assert not any("prompt" in name for name in imported)


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
    def shop(self, client: Any) -> Any:
        """A connected store, without a database behind it."""

        class Connection:
            def __init__(self) -> None:
                self.adapter = store()
                self.capabilities = ALL

        class Directory:
            async def connect(self, tenant_id: str, *, store_id: str | None = None) -> Any:
                return Connection()

        client.app.state.stores = Directory()
        return client

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
