"""The owner's side of suggestions — ADR-0050, against a real PostgreSQL.

The console endpoints SELL serves: who may reach them, what a choice may
contain, and what the screen reports as *automatic*. The request path's rules
(the owner wins; nothing automatic replaces a choice) are unit-tested in
``tests/unit/test_sell_pairing.py``; this file is about the rows.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

from neura_agent_sell.pairing.cache import source_hash
from neura_agent_sell.pairing.choices import DatabaseOwnerChoices
from neura_agent_sell.pairing.schema import sell_pairing_choices, sell_pairings
from neura_api.main import create_app
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.schema import tenants
from neura_domain import Money, Product
from tests.integration.console_fixtures import PLATFORM, Shop, drop_shop, make_shop

pytestmark = pytest.mark.integration

JUMPER, CASHMERE, WOOL_WASH, AUTO = "8001", "8002", "8003", "8004"
KNITWEAR = "c_knit"
TITLES = {
    JUMPER: "Cotton Jumper",
    CASHMERE: "Cashmere Jumper",
    WOOL_WASH: "Wool Wash",
    AUTO: "Walking Boot",
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def db():
    load_env()
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    yield database
    await database.dispose()


async def _seed(db: Database, shop: Shop, *, agents: list[str]) -> None:
    async with db.tenant_session(shop.tenant) as session:
        await TenantRepository(session).create(
            tenant_id=shop.tenant, name="Choices shop", enabled_agents=agents
        )
        # One category, named, for the list's category names (2026-09-28).
        await session.execute(
            insert(synced_entities).values(
                tenant_id=shop.tenant,
                platform=PLATFORM,
                entity_type="category",
                external_id=KNITWEAR,
                neura_id=ids.new_id(ids.NEURA_ENTITY),
                fingerprint="owner-choices",
                document={"name": "Knitwear"},
            )
        )
        for product_id, title in TITLES.items():
            document = _product(shop.tenant, product_id, title).model_dump(mode="json")
            await session.execute(
                insert(synced_entities).values(
                    tenant_id=shop.tenant,
                    platform=PLATFORM,
                    entity_type="product",
                    external_id=product_id,
                    neura_id=ids.new_id(ids.NEURA_ENTITY),
                    fingerprint="owner-choices",
                    document=document,
                )
            )


async def _unseed(db: Database, shop: Shop) -> None:
    async with db.tenant_session(shop.tenant) as session:
        for table in (sell_pairing_choices, sell_pairings):
            await session.execute(delete(table).where(table.c.tenant_id == shop.tenant))
        await session.execute(
            delete(synced_entities)
            .where(synced_entities.c.tenant_id == shop.tenant)
            .where(synced_entities.c.fingerprint == "owner-choices")
        )
        await session.execute(delete(tenants).where(tenants.c.tenant_id == shop.tenant))


@pytest.fixture
async def shop(db: Database):
    made = await make_shop(db)
    await _seed(db, made, agents=["sell"])
    yield made
    await _unseed(db, made)
    await drop_shop(db, made)


@pytest.fixture
async def shop_without_sell(db: Database):
    made = await make_shop(db)
    await _seed(db, made, agents=["care"])
    yield made
    await _unseed(db, made)
    await drop_shop(db, made)


def _product(tenant: str, product_id: str, title: str) -> Product:
    # The cotton jumper is the one with a category and a price, so the list's
    # names and prices have something to show and something to leave empty.
    jumper = product_id == JUMPER
    return Product(
        neura_id=f"ne_{product_id}",
        tenant_id=tenant,
        platform=PLATFORM,
        synced_at=datetime(2026, 9, 27, tzinfo=UTC),
        external_id=product_id,
        title=title,
        description=f"{title} — a product for the owner-choices test.",
        category_ids=[KNITWEAR, "c_unnamed"] if jumper else [],
        price_range_min=Money(amount=Decimal("45.00"), currency="GBP") if jumper else None,
    )


def _cookie(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


def _base(shop: Shop) -> str:
    return f"/v1/sell/console/shops/{shop.tenant}/suggestions"


def _listing(client: TestClient, shop: Shop) -> dict[str, dict]:
    response = client.get(_base(shop), cookies=_cookie(shop.user))
    assert response.status_code == 200, response.text
    return {item["product_id"]: item for item in response.json()["data"]["products"]}


class TestWhoMayChoose:
    def test_no_session_reaches_nothing(self, client: TestClient, shop) -> None:
        assert client.get(_base(shop)).status_code == 401

    async def test_another_persons_shop_is_not_reachable(self, client: TestClient, db) -> None:
        mine, theirs = await make_shop(db), await make_shop(db)
        try:
            await _seed(db, mine, agents=["sell"])
            response = client.get(_base(mine), cookies=_cookie(theirs.user))
            assert response.status_code == 404
        finally:
            await _unseed(db, mine)
            await drop_shop(db, mine)
            await drop_shop(db, theirs)

    def test_a_shop_without_sell_is_refused(self, client: TestClient, shop_without_sell) -> None:
        response = client.get(_base(shop_without_sell), cookies=_cookie(shop_without_sell.user))
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AGENT_NOT_ENABLED"


class TestAChoice:
    def test_a_saved_choice_is_what_the_screen_reports(self, client: TestClient, shop) -> None:
        saved = client.put(
            f"{_base(shop)}/{JUMPER}",
            json={"product_ids": [CASHMERE, WOOL_WASH]},
            cookies=_cookie(shop.user),
        )
        assert saved.status_code == 200, saved.text

        jumper = _listing(client, shop)[JUMPER]
        assert jumper["mode"] == "owner"
        assert [s["title"] for s in jumper["suggested"]] == ["Cashmere Jumper", "Wool Wash"]
        assert jumper["chosen_at"]

    async def test_it_records_who_chose(self, client: TestClient, db, shop) -> None:
        client.put(
            f"{_base(shop)}/{JUMPER}", json={"product_ids": [CASHMERE]}, cookies=_cookie(shop.user)
        )
        store_id = shop.store
        choices = await DatabaseOwnerChoices(
            db, tenant_id=shop.tenant, store_id=store_id
        ).for_products([JUMPER])
        assert choices[JUMPER].chosen_by == shop.user

    def test_an_empty_choice_is_kept_as_show_nothing(self, client: TestClient, shop) -> None:
        client.put(f"{_base(shop)}/{JUMPER}", json={"product_ids": []}, cookies=_cookie(shop.user))
        jumper = _listing(client, shop)[JUMPER]
        assert jumper["mode"] == "owner" and jumper["suggested"] == []

    def test_reset_goes_back_to_automatic(self, client: TestClient, shop) -> None:
        client.put(
            f"{_base(shop)}/{JUMPER}", json={"product_ids": [CASHMERE]}, cookies=_cookie(shop.user)
        )
        reset = client.delete(f"{_base(shop)}/{JUMPER}", cookies=_cookie(shop.user))
        assert reset.status_code == 200 and reset.json()["data"]["reset"] is True
        assert _listing(client, shop)[JUMPER]["mode"] == "pending"


class TestWhatAChoiceMayContain:
    def test_not_the_product_itself(self, client: TestClient, shop) -> None:
        response = client.put(
            f"{_base(shop)}/{JUMPER}", json={"product_ids": [JUMPER]}, cookies=_cookie(shop.user)
        )
        assert response.status_code == 400

    def test_only_products_from_the_shops_own_catalogue(self, client: TestClient, shop) -> None:
        response = client.put(
            f"{_base(shop)}/{JUMPER}", json={"product_ids": ["9999"]}, cookies=_cookie(shop.user)
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "UNKNOWN_PRODUCT"

    def test_at_most_four(self, client: TestClient, shop) -> None:
        response = client.put(
            f"{_base(shop)}/{JUMPER}",
            json={"product_ids": [CASHMERE, WOOL_WASH, AUTO, "8005", "8006"]},
            cookies=_cookie(shop.user),
        )
        assert response.status_code == 400

    async def test_another_shops_product_is_unknown_here(
        self, client: TestClient, db, shop
    ) -> None:
        other = await make_shop(db)
        try:
            await _seed(db, other, agents=["sell"])
            async with db.tenant_session(other.tenant) as session:
                await session.execute(
                    insert(synced_entities).values(
                        tenant_id=other.tenant,
                        platform=PLATFORM,
                        entity_type="product",
                        external_id="7777",
                        neura_id=ids.new_id(ids.NEURA_ENTITY),
                        fingerprint="owner-choices",
                        document={"title": "Someone else's product"},
                    )
                )
            response = client.put(
                f"{_base(shop)}/{JUMPER}",
                json={"product_ids": ["7777"]},
                cookies=_cookie(shop.user),
            )
            assert response.status_code == 400
        finally:
            await _unseed(db, other)
            await drop_shop(db, other)


class TestWhatTheScreenCallsAutomatic:
    async def test_a_current_computed_pairing_is_reported(
        self, client: TestClient, db, shop
    ) -> None:
        await self._store_pairing(db, shop, fingerprint_of=TITLES[AUTO])
        auto = _listing(client, shop)[AUTO]
        assert auto["mode"] == "automatic"
        assert [s["product_id"] for s in auto["suggested"]] == [WOOL_WASH]

    async def test_a_stale_one_is_not(self, client: TestClient, db, shop) -> None:
        """The basket page ignores a pairing whose product text changed, so the
        screen must not report it as what shoppers see."""
        await self._store_pairing(db, shop, fingerprint_of="An older title")
        assert _listing(client, shop)[AUTO]["mode"] == "pending"

    async def test_a_stored_empty_pairing_is_not_called_ai(
        self, client: TestClient, db, shop
    ) -> None:
        """The basket falls back to words when the model found nothing, so the
        screen must say automatic — not "chosen by AI" over an empty list."""
        await self._store_pairing(db, shop, fingerprint_of=TITLES[AUTO], suggested=[])
        assert _listing(client, shop)[AUTO]["mode"] == "pending"

    @staticmethod
    async def _store_pairing(
        db: Database, shop: Shop, *, fingerprint_of: str, suggested: list[str] | None = None
    ) -> None:
        async with db.tenant_session(shop.tenant) as session:
            await session.execute(
                insert(sell_pairings).values(
                    id=ids.new_id("prg"),
                    tenant_id=shop.tenant,
                    store_id=shop.store,
                    product_id=AUTO,
                    source_hash=source_hash(_product(shop.tenant, AUTO, fingerprint_of)),
                    suggested_ids=[WOOL_WASH] if suggested is None else suggested,
                )
            )


class TestTheListSaysWhoDecides:
    """2026-09-28, the owner's redesign: counts per mode, a filter by mode, and
    each product's category and price — all from the synced catalogue."""

    def test_each_row_carries_its_category_names_and_price(self, client: TestClient, shop) -> None:
        rows = _listing(client, shop)
        # An id the catalogue cannot name is left out, never shown as a code.
        assert rows[JUMPER]["categories"] == ["Knitwear"]
        assert rows[JUMPER]["price"] == {"amount": "45.00", "currency": "GBP"}
        assert rows[CASHMERE]["categories"] == []
        assert rows[CASHMERE]["price"] is None

    def test_the_counts_say_who_decides_every_product(self, client: TestClient, shop) -> None:
        _choose(client, shop, JUMPER, [CASHMERE])
        meta = client.get(_base(shop), cookies=_cookie(shop.user)).json()["meta"]
        assert meta["counts"] == {"all": 4, "owner": 1, "automatic": 0, "pending": 3}
        assert meta["counted_all"] is True

    def test_the_mode_filter_narrows_the_list_and_not_the_counts(
        self, client: TestClient, shop
    ) -> None:
        """Each chip says what choosing it would show, so the counts ignore the
        mode filter — and still follow the search."""
        _choose(client, shop, JUMPER, [CASHMERE])
        body = client.get(_base(shop), params={"mode": "owner"}, cookies=_cookie(shop.user)).json()
        assert [item["product_id"] for item in body["data"]["products"]] == [JUMPER]
        assert body["meta"]["counts"]["all"] == 4

        searched = client.get(_base(shop), params={"q": "jumper"}, cookies=_cookie(shop.user))
        assert searched.json()["meta"]["counts"]["all"] == 2

    def test_an_unknown_mode_is_refused_rather_than_ignored(self, client: TestClient, shop) -> None:
        response = client.get(_base(shop), params={"mode": "nope"}, cookies=_cookie(shop.user))
        assert response.status_code == 400


class TestTheCategoryFilterAndPages:
    """2026-09-28, the owner's follow-up: filter by category (including *no
    category*, the products that can never get an automatic suggestion), and
    pages of 25 like Conversations instead of one list in a scroll box."""

    def test_the_menu_names_each_category_and_counts_products_with_none(
        self, client: TestClient, shop
    ) -> None:
        meta = client.get(_base(shop), cookies=_cookie(shop.user)).json()["meta"]
        # The unnamed id the jumper also carries is not offered: an owner
        # could not recognise it.
        assert meta["categories"] == {
            "named": [{"id": KNITWEAR, "name": "Knitwear", "count": 1}],
            "none": 3,
        }

    def test_a_category_narrows_the_list_and_the_counts(self, client: TestClient, shop) -> None:
        body = client.get(
            _base(shop), params={"category": KNITWEAR}, cookies=_cookie(shop.user)
        ).json()
        assert [item["product_id"] for item in body["data"]["products"]] == [JUMPER]
        assert body["meta"]["counts"]["all"] == 1
        # The menu still offers every way out.
        assert body["meta"]["categories"]["none"] == 3

    def test_no_category_lists_exactly_the_products_with_none(
        self, client: TestClient, shop
    ) -> None:
        body = client.get(
            _base(shop), params={"category": "none"}, cookies=_cookie(shop.user)
        ).json()
        assert sorted(item["product_id"] for item in body["data"]["products"]) == sorted(
            [CASHMERE, WOOL_WASH, AUTO]
        )

    def test_an_unknown_category_matches_nothing_rather_than_everything(
        self, client: TestClient, shop
    ) -> None:
        body = client.get(
            _base(shop), params={"category": "c_nowhere"}, cookies=_cookie(shop.user)
        ).json()
        assert body["data"]["products"] == []
        assert body["meta"]["total"] == 0

    def test_pages_say_where_they_sit_and_walk_back_exactly(
        self, client: TestClient, shop, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from neura_agent_sell import console as sell_console

        monkeypatch.setattr(sell_console, "PAGE_SIZE", 2)
        first = client.get(_base(shop), cookies=_cookie(shop.user)).json()
        assert [item["product_id"] for item in first["data"]["products"]] == [JUMPER, CASHMERE]
        meta = first["meta"]
        assert (meta["total"], meta["offset"], meta["has_previous"]) == (4, 0, False)
        assert first["meta"]["next_cursor"] == CASHMERE

        second = client.get(
            _base(shop), params={"after": CASHMERE}, cookies=_cookie(shop.user)
        ).json()
        assert [item["product_id"] for item in second["data"]["products"]] == [WOOL_WASH, AUTO]
        assert second["meta"]["offset"] == 2
        assert second["meta"]["has_previous"] is True
        assert second["meta"]["has_more"] is False
        # `null` with `has_previous` true: the page before is the first.
        assert second["meta"]["previous_cursor"] is None


class TestWhoMayPreview:
    """The preview is the only console call that reaches the shop, so the gate
    in front of it is asserted on its own route."""

    def test_no_session_reaches_nothing(self, client: TestClient, shop) -> None:
        assert client.get(f"{_base(shop)}/{JUMPER}/preview").status_code == 401

    def test_a_shop_without_sell_is_refused(self, client: TestClient, shop_without_sell) -> None:
        response = client.get(
            f"{_base(shop_without_sell)}/{JUMPER}/preview",
            cookies=_cookie(shop_without_sell.user),
        )
        assert response.status_code == 403

    async def test_another_persons_shop_is_not_reachable(self, client: TestClient, db) -> None:
        mine, theirs = await make_shop(db), await make_shop(db)
        try:
            await _seed(db, mine, agents=["sell"])
            response = client.get(f"{_base(mine)}/{JUMPER}/preview", cookies=_cookie(theirs.user))
            assert response.status_code == 404
        finally:
            await _unseed(db, mine)
            await drop_shop(db, mine)
            await drop_shop(db, theirs)


class TestAShopThatDoesNotAnswer:
    def test_the_preview_says_so_and_still_names_the_product(
        self, client: TestClient, shop
    ) -> None:
        """The fixture's connection holds placeholder credentials, so the shop
        cannot be reached — which must read as that, not as "nothing to show",
        with the product still named from the synced catalogue."""
        response = client.get(f"{_base(shop)}/{JUMPER}/preview", cookies=_cookie(shop.user))
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["reachable"] is False
        assert data["suggestions"] == []
        assert data["product"]["title"] == "Cotton Jumper"
        assert data["product"]["categories"] == ["Knitwear"]


class TestWhatTheAiLookedFor:
    """Shown under a preview only for the product's **current** text.

    `_computed` is called directly, on this test's own database: the module's
    shared one belongs to whichever event loop first opened it.
    """

    @pytest.fixture(autouse=True)
    def _this_database(self, monkeypatch: pytest.MonkeyPatch, db: Database) -> None:
        from neura_agent_sell import console as sell_console

        monkeypatch.setattr(sell_console, "get_database", lambda: db)

    async def test_a_current_pairing_says_what_it_looked_for(self, db, shop) -> None:
        from neura_agent_sell import console as sell_console

        await self._store(db, shop, fingerprint_of=TITLES[AUTO])
        assert await sell_console._computed(shop.tenant, shop.store, AUTO) == {
            "kinds": ["wool wash"],
            "found": 1,
        }

    async def test_a_stale_one_says_nothing(self, db, shop) -> None:
        from neura_agent_sell import console as sell_console

        await self._store(db, shop, fingerprint_of="An older title")
        assert await sell_console._computed(shop.tenant, shop.store, AUTO) is None

    async def test_another_shops_pairing_is_not_read(self, db, shop, shop_without_sell) -> None:
        from neura_agent_sell import console as sell_console

        await self._store(db, shop, fingerprint_of=TITLES[AUTO])
        assert await sell_console._computed(shop_without_sell.tenant, shop.store, AUTO) is None

    @staticmethod
    async def _store(db: Database, shop: Shop, *, fingerprint_of: str) -> None:
        async with db.tenant_session(shop.tenant) as session:
            await session.execute(
                insert(sell_pairings).values(
                    id=ids.new_id("prg"),
                    tenant_id=shop.tenant,
                    store_id=shop.store,
                    product_id=AUTO,
                    source_hash=source_hash(_product(shop.tenant, AUTO, fingerprint_of)),
                    suggested_ids=[WOOL_WASH],
                    kinds=["wool wash"],
                )
            )


def _choose(client: TestClient, shop: Shop, product_id: str, chosen: list[str]) -> None:
    response = client.put(
        f"{_base(shop)}/{product_id}",
        json={"product_ids": chosen},
        cookies=_cookie(shop.user),
    )
    assert response.status_code == 200, response.text


class TestThePicker:
    def test_it_finds_by_title(self, client: TestClient, shop) -> None:
        response = client.get(
            f"{_base(shop)}/catalogue", params={"q": "cash"}, cookies=_cookie(shop.user)
        )
        assert response.status_code == 200
        assert [p["title"] for p in response.json()["data"]] == ["Cashmere Jumper"]


class TestIsolation:
    async def test_one_tenants_choices_are_invisible_to_another(self, db, shop) -> None:
        await DatabaseOwnerChoices(db, tenant_id=shop.tenant, store_id=shop.store).choose(
            JUMPER, [CASHMERE], chosen_by=shop.user
        )
        other = await make_shop(db)
        try:
            # A different tenant's session, asking for this tenant's row by name.
            peek = DatabaseOwnerChoices(db, tenant_id=other.tenant, store_id=shop.store)
            assert await peek.get(JUMPER) is None
        finally:
            await drop_shop(db, other)
