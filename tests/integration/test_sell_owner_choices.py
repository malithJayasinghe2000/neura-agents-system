"""The owner's side of suggestions — ADR-0050, against a real PostgreSQL.

The console endpoints SELL serves: who may reach them, what a choice may
contain, and what the screen reports as *automatic*. The request path's rules
(the owner wins; nothing automatic replaces a choice) are unit-tested in
``tests/unit/test_sell_pairing.py``; this file is about the rows.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import UTC, datetime

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
from neura_domain import Product
from tests.integration.console_fixtures import PLATFORM, Shop, drop_shop, make_shop

pytestmark = pytest.mark.integration

JUMPER, CASHMERE, WOOL_WASH, AUTO = "8001", "8002", "8003", "8004"
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
    return Product(
        neura_id=f"ne_{product_id}",
        tenant_id=tenant,
        platform=PLATFORM,
        synced_at=datetime(2026, 9, 27, tzinfo=UTC),
        external_id=product_id,
        title=title,
        description=f"{title} — a product for the owner-choices test.",
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
