"""The sold-out screen's API — ADR-0046 stage 1, on ADR-0049's field.

What it counts is the whole feature, so most of this file is about what it
**leaves out**: a view of an in-stock product, a basket add, a view whose stock
nobody recorded, a view older than the window, and another merchant's views.
And one assertion outranks the rest: **no session token reaches the payload.**

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

from neura_api.main import create_app
from neura_api.stores import StoreConnection
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.observation import (
    ObservedEvent,
    ObservedEventRepository,
    ObservedEventType,
    observed_events,
)
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.schema import tenants
from neura_domain import Capability, InventoryLevel
from tests.integration.console_fixtures import PLATFORM, Shop, drop_shop, make_shop

pytestmark = pytest.mark.integration

#: Recognisable, so a leak is findable by eye as well as by assertion.
SESSION_A = "sessiontokenAAAA" * 4
SESSION_B = "sessiontokenBBBB" * 4
SOLD_OUT = "9001"
ALSO_SOLD_OUT = "9002"
IN_STOCK = "9003"
NOT_SYNCED = "9004"
SOLD_OUT_VARIANTS = ("9001-s", "9001-m")
CATEGORY = "77"


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


@pytest.fixture
async def shop(db: Database):
    made = await make_shop(db)
    yield made
    await _unseed(db, made)
    await drop_shop(db, made)


@pytest.fixture
async def other_shop(db: Database):
    made = await make_shop(db)
    yield made
    await _unseed(db, made)
    await drop_shop(db, made)


def _view(product: str, session: str, *, in_stock: bool | None, age: timedelta) -> ObservedEvent:
    return ObservedEvent.model_construct(
        event_id=ids.new_id("obs"),
        session_id=session,
        type=ObservedEventType.PRODUCT_VIEWED,
        product_id=product,
        occurred_at=datetime.now(UTC) - age,
        in_stock=in_stock,
    )


async def _seed(db: Database, shop: Shop, *, agreement: bool = True) -> None:
    """Every case the count must include, and every case it must leave out."""
    hour = timedelta(hours=1)
    events = [
        # Counted: SOLD_OUT three times from two sessions, ALSO_SOLD_OUT once.
        _view(SOLD_OUT, SESSION_A, in_stock=False, age=hour),
        _view(SOLD_OUT, SESSION_A, in_stock=False, age=2 * hour),
        _view(SOLD_OUT, SESSION_B, in_stock=False, age=3 * hour),
        _view(ALSO_SOLD_OUT, SESSION_B, in_stock=False, age=hour),
        _view(NOT_SYNCED, SESSION_B, in_stock=False, age=hour),
        # Left out: in stock, unknown, too old.
        _view(IN_STOCK, SESSION_A, in_stock=True, age=hour),
        _view(SOLD_OUT, SESSION_B, in_stock=None, age=hour),
        _view(SOLD_OUT, SESSION_B, in_stock=False, age=timedelta(days=8)),
        # Left out: a basket add is not a view.
        ObservedEvent.model_construct(
            event_id=ids.new_id("obs"),
            session_id=SESSION_A,
            type=ObservedEventType.CART_ADDED,
            product_id=SOLD_OUT,
            occurred_at=datetime.now(UTC),
            in_stock=None,
        ),
    ]
    async with db.tenant_session(shop.tenant) as session:
        await TenantRepository(session).create(tenant_id=shop.tenant, name="Sold-out shop")
        if agreement:
            await TenantRepository(session).set_dpa_signed_at(shop.tenant, datetime.now(UTC))
        repository = ObservedEventRepository(session)
        for event in events:
            await repository.record(shop.tenant, event)
        documents = {
            # Two variants and a category, as a real sync records them: the
            # live check asks for the variants, and the row names the category.
            SOLD_OUT: {
                "title": "Cashmere Crew Jumper",
                "url": f"https://shop.example/{SOLD_OUT}",
                "category_ids": [CATEGORY],
                "price_range_min": {"amount": "185.00", "currency": "USD"},
                "variants": [{"external_id": v} for v in SOLD_OUT_VARIANTS],
            },
            # No variants recorded: asked about by its own id.
            ALSO_SOLD_OUT: {"title": "Rain Shell", "url": f"https://shop.example/{ALSO_SOLD_OUT}"},
        }
        for product, document in documents.items():
            await session.execute(
                insert(synced_entities).values(
                    tenant_id=shop.tenant,
                    platform=PLATFORM,
                    entity_type="product",
                    external_id=product,
                    neura_id=ids.new_id(ids.NEURA_ENTITY),
                    fingerprint="console-sold-out",
                    document=document,
                )
            )
        await session.execute(
            insert(synced_entities).values(
                tenant_id=shop.tenant,
                platform=PLATFORM,
                entity_type="category",
                external_id=CATEGORY,
                neura_id=ids.new_id(ids.NEURA_ENTITY),
                fingerprint="console-sold-out",
                document={"name": "Knitwear"},
            )
        )


async def _unseed(db: Database, shop: Shop) -> None:
    async with db.tenant_session(shop.tenant) as session:
        await session.execute(
            delete(observed_events).where(observed_events.c.tenant_id == shop.tenant)
        )
        await session.execute(
            delete(synced_entities)
            .where(synced_entities.c.tenant_id == shop.tenant)
            .where(synced_entities.c.platform == PLATFORM)
            .where(synced_entities.c.fingerprint == "console-sold-out")
        )
        await session.execute(delete(tenants).where(tenants.c.tenant_id == shop.tenant))


def _get(client: TestClient, shop: Shop, *, as_user: str | None = None, query: str = ""):
    user = as_user or shop.user
    return client.get(
        f"/v1/console/shops/{shop.tenant}/sold-out{query}",
        cookies={COOKIE_NAME: issue(user, get_settings().secret_key)},
    )


class _FakeShop:
    """A shop that answers the one stock lookup — and records that it was asked.

    ``9001-s`` is sold out and ``9001-m`` is not, so the jumper is back in stock
    (any variant counts, as when the shop records a view); ``9002`` is still sold
    out; ``9004`` is a product the shop no longer reports on at all.
    """

    def __init__(self) -> None:
        self.asked: list[list[str]] = []
        self.closed = False

    async def get_inventory(self, variant_external_ids: list[str]) -> list[InventoryLevel]:
        self.asked.append(list(variant_external_ids))
        stock = {"9001-s": 0, "9001-m": 4, ALSO_SOLD_OUT: 0}
        return [
            InventoryLevel(variant_external_id=vid, quantity=stock[vid], in_stock=stock[vid] > 0)
            for vid in variant_external_ids
            if vid in stock
        ]

    async def aclose(self) -> None:
        self.closed = True


def _connect_to(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    fake: _FakeShop,
    capabilities: frozenset[Capability] = frozenset({Capability.INVENTORY_READ}),
) -> list[str]:
    """Replace the store directory's connection with ``fake``; returns who connected."""
    connected: list[str] = []

    async def connect(tenant_id: str, *, store_id: str | None = None) -> StoreConnection:
        connected.append(tenant_id)
        return StoreConnection(
            store_id="st_fake",
            platform=PLATFORM,
            base_url="https://shop.example/neura/v1",
            adapter=fake,
            capabilities=capabilities,
        )

    monkeypatch.setattr(client.app.state.stores, "connect", connect)
    return connected


class TestWhoMaySee:
    async def test_a_person_sees_their_own_shop(self, client: TestClient, db, shop) -> None:
        await _seed(db, shop)
        assert _get(client, shop).status_code == 200

    async def test_another_persons_shop_is_not_reachable(
        self, client: TestClient, db, shop, other_shop
    ) -> None:
        await _seed(db, shop)
        assert _get(client, shop, as_user=other_shop.user).status_code == 404

    def test_no_session_reaches_nothing(self, client: TestClient, shop) -> None:
        assert client.get(f"/v1/console/shops/{shop.tenant}/sold-out").status_code == 401


class TestWhatIsCounted:
    async def test_only_views_while_sold_out_in_the_window(
        self, client: TestClient, db, shop
    ) -> None:
        await _seed(db, shop)
        products = {p["product_id"]: p for p in _get(client, shop).json()["data"]["products"]}

        # In stock, a basket add, unknown stock and an 8-day-old view: all left out.
        assert set(products) == {SOLD_OUT, ALSO_SOLD_OUT, NOT_SYNCED}
        assert products[SOLD_OUT]["views"] == 3
        assert products[SOLD_OUT]["sessions"] == 2
        assert products[ALSO_SOLD_OUT]["views"] == 1

    async def test_the_most_wanted_is_first(self, client: TestClient, db, shop) -> None:
        await _seed(db, shop)
        assert _get(client, shop).json()["data"]["products"][0]["product_id"] == SOLD_OUT

    async def test_names_come_from_the_synced_catalogue_or_are_said_to_be_missing(
        self, client: TestClient, db, shop
    ) -> None:
        await _seed(db, shop)
        products = {p["product_id"]: p for p in _get(client, shop).json()["data"]["products"]}
        assert products[SOLD_OUT]["title"] == "Cashmere Crew Jumper"
        # Not dropped, not invented: shown by id, with no title.
        assert products[NOT_SYNCED]["title"] is None

    async def test_unknown_stock_is_named_rather_than_counted(
        self, client: TestClient, db, shop
    ) -> None:
        await _seed(db, shop)
        caveats = " ".join(_get(client, shop).json()["data"]["caveats"])
        assert "1 product view(s)" in caveats and "without stock information" in caveats

    async def test_the_period_is_stated(self, client: TestClient, db, shop) -> None:
        await _seed(db, shop)
        assert _get(client, shop).json()["data"]["period"]["days"] == 7


class TestWhatIsNeverShown:
    async def test_no_session_token_reaches_the_payload(self, client: TestClient, db, shop) -> None:
        """The assertion this screen exists under. Counts, never who."""
        await _seed(db, shop)
        body = _get(client, shop).text
        assert SESSION_A not in body and SESSION_B not in body
        assert "session_id" not in body

    async def test_another_merchants_demand_is_not_in_the_body(
        self, client: TestClient, db, shop, other_shop
    ) -> None:
        await _seed(db, shop)
        await _seed(db, other_shop)
        async with db.tenant_session(other_shop.tenant) as session:
            await ObservedEventRepository(session).record(
                other_shop.tenant, _view("7777", SESSION_A, in_stock=False, age=timedelta(hours=1))
            )
        ids_seen = {p["product_id"] for p in _get(client, shop).json()["data"]["products"]}
        assert "7777" not in ids_seen


class TestTheEmptyStateSaysWhy:
    async def test_without_an_agreement_the_screen_can_say_so(
        self, client: TestClient, db, shop
    ) -> None:
        await _seed(db, shop, agreement=False)
        assert _get(client, shop).json()["data"]["agreement"] is False

    async def test_with_nothing_recorded_there_are_no_caveats_to_skip(
        self, client: TestClient, shop
    ) -> None:
        data = _get(client, shop).json()["data"]
        assert data["products"] == [] and data["caveats"] == []


class TestIsItWorking:
    """The checklist's two facts: the agreement, and whether views arrive —
    which is what tells *switched off* from *nothing sold out was opened*."""

    async def test_the_agreement_says_since_when(self, client: TestClient, db, shop) -> None:
        await _seed(db, shop)
        data = _get(client, shop).json()["data"]
        assert data["agreement"] is True and data["agreement_since"] is not None

    async def test_without_one_there_is_no_date(self, client: TestClient, db, shop) -> None:
        await _seed(db, shop, agreement=False)
        assert _get(client, shop).json()["data"]["agreement_since"] is None

    async def test_views_arriving_is_a_yes(self, client: TestClient, db, shop) -> None:
        await _seed(db, shop)
        assert _get(client, shop).json()["data"]["receiving"] is True

    async def test_an_in_stock_view_alone_still_counts_as_arriving(
        self, client: TestClient, db, shop
    ) -> None:
        """Nothing sold out was opened, and views did arrive: the good case,
        which must not read like a switch that is off."""
        async with db.tenant_session(shop.tenant) as session:
            await ObservedEventRepository(session).record(
                shop.tenant, _view(IN_STOCK, SESSION_A, in_stock=True, age=timedelta(hours=1))
            )
        data = _get(client, shop).json()["data"]
        assert data["products"] == [] and data["receiving"] is True

    async def test_no_views_is_a_no(self, client: TestClient, shop) -> None:
        assert _get(client, shop).json()["data"]["receiving"] is False

    async def test_it_is_a_yes_or_no_never_a_count(self, client: TestClient, db, shop) -> None:
        await _seed(db, shop)
        assert isinstance(_get(client, shop).json()["data"]["receiving"], bool)

    def test_how_long_views_are_kept_is_the_setting_the_sweep_enforces(
        self, client: TestClient, shop
    ) -> None:
        kept = _get(client, shop).json()["data"]["kept_days"]
        assert kept == get_settings().retention_observed_events_days


class TestEachRow:
    async def test_category_and_price_come_from_the_synced_catalogue(
        self, client: TestClient, db, shop
    ) -> None:
        await _seed(db, shop)
        products = {p["product_id"]: p for p in _get(client, shop).json()["data"]["products"]}
        assert products[SOLD_OUT]["categories"] == ["Knitwear"]
        assert products[SOLD_OUT]["price"] == {"amount": "185.00", "currency": "USD"}
        assert products[NOT_SYNCED]["categories"] == [] and products[NOT_SYNCED]["price"] is None

    async def test_a_session_is_said_not_to_be_a_person(self, client: TestClient, db, shop) -> None:
        await _seed(db, shop)
        caveats = " ".join(_get(client, shop).json()["data"]["caveats"])
        assert "not one person" in caveats and "crawlers" in caveats


class TestStockNow:
    """Whether each listed product can be bought now — one question to the
    shop, asked only when the screen asks (``?stock=now``)."""

    async def test_not_asked_means_the_shop_is_not_called(
        self, client: TestClient, db, shop, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Home reads this route without the parameter, on every visit."""
        await _seed(db, shop)
        connected = _connect_to(monkeypatch, client, _FakeShop())
        data = _get(client, shop).json()["data"]
        assert connected == []
        assert data["stock"] is None
        assert all(p["in_stock_now"] is None for p in data["products"])

    async def test_one_question_for_every_product_listed(
        self, client: TestClient, db, shop, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _seed(db, shop)
        fake = _FakeShop()
        _connect_to(monkeypatch, client, fake)
        data = _get(client, shop, query="?stock=now").json()["data"]

        # One lookup, carrying the jumper's variants and the others' own ids.
        assert len(fake.asked) == 1
        assert sorted(fake.asked[0]) == sorted([*SOLD_OUT_VARIANTS, ALSO_SOLD_OUT, NOT_SYNCED])
        assert fake.closed
        assert data["stock"]["answered"] is True and data["stock"]["reason"] is None

    async def test_each_product_says_what_the_shop_said(
        self, client: TestClient, db, shop, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _seed(db, shop)
        _connect_to(monkeypatch, client, _FakeShop())
        products = {
            p["product_id"]: p
            for p in _get(client, shop, query="?stock=now").json()["data"]["products"]
        }
        # One variant in stock is enough — the rule the shop applies to a view.
        assert products[SOLD_OUT]["in_stock_now"] is True
        assert products[ALSO_SOLD_OUT]["in_stock_now"] is False
        # The shop said nothing about it: unknown, never "sold out".
        assert products[NOT_SYNCED]["in_stock_now"] is None

    async def test_a_shop_that_does_not_answer_is_said(self, client: TestClient, db, shop) -> None:
        """The fixture's connection holds placeholder credentials, so the shop
        cannot be reached — said as that, and the counts are still there."""
        await _seed(db, shop)
        data = _get(client, shop, query="?stock=now").json()["data"]
        assert data["stock"]["answered"] is False
        assert data["stock"]["reason"] == "unreachable"
        assert all(p["in_stock_now"] is None for p in data["products"])
        assert data["products"][0]["views"] == 3

    async def test_a_shop_that_does_not_share_stock_is_said(
        self, client: TestClient, db, shop, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _seed(db, shop)
        fake = _FakeShop()
        _connect_to(monkeypatch, client, fake, capabilities=frozenset())
        data = _get(client, shop, query="?stock=now").json()["data"]
        assert data["stock"]["answered"] is False and data["stock"]["reason"] == "not_supported"
        assert fake.asked == [] and fake.closed

    async def test_an_empty_list_asks_nothing(
        self, client: TestClient, shop, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connected = _connect_to(monkeypatch, client, _FakeShop())
        data = _get(client, shop, query="?stock=now").json()["data"]
        assert connected == [] and data["stock"] is None

    def test_an_unknown_value_is_refused(self, client: TestClient, shop) -> None:
        """Quietly ignored, it would read as "your shop was asked" when it was not."""
        assert _get(client, shop, query="?stock=yesterday").status_code == 400
