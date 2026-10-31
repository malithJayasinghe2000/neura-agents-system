"""*Rarely added to cart*'s count against a real PostgreSQL. ADR-0071 §1.

The rule is the whole feature: an in-stock product that **10 or more visitors**
opened in 7 days and **fewer than 1 in 10** of them added to the cart. So most
of this file is about the edges: exactly 1 in 10, exactly 9 visitors, a session
that opened a page fifteen times, an add from a session that never opened the
page, a view of a sold-out product, a view nobody measured, a view too old, and
another shop's views.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from neura_core import Database, ids, load_env
from neura_core.observation import (
    ObservedEvent,
    ObservedEventRepository,
    ObservedEventType,
    observed_events,
)
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.schema import tenants

pytestmark = pytest.mark.integration

WEEK = timedelta(days=7)
HOUR = timedelta(hours=1)

PEPPER = "p-pepper"  # 10 visitors, none added (3 adds from sessions that never opened it)
BLACK_TEA = "p-black-tea"  # 20 visitors, none added
GREEN_TEA = "p-green-tea"  # 12 visitors, 1 added (twice)
ONE_IN_TEN = "p-one-in-ten"  # 10 visitors, 1 added: not *fewer* than 1 in 10
NINE = "p-nine"  # 9 visitors, none added
ONE_SESSION = "p-one-session"  # 1 visitor who opened it 15 times
SOLD_OUT = "p-sold-out"  # 10 visitors while it could not be bought
UNKNOWN = "p-unknown"  # 10 visitors, stock not recorded
OLD = "p-old"  # 10 visitors, 8 days ago


def _event(
    kind: ObservedEventType,
    product: str,
    session: str,
    *,
    in_stock: bool | None = True,
    age: timedelta = HOUR,
) -> ObservedEvent:
    return ObservedEvent.model_construct(
        event_id=ids.new_id("obs"),
        session_id=session,
        type=kind,
        product_id=product,
        occurred_at=datetime.now(UTC) - age,
        in_stock=in_stock if kind is ObservedEventType.PRODUCT_VIEWED else None,
    )


def _visitors(
    product: str, count: int, *, in_stock: bool | None = True, age: timedelta = HOUR
) -> list[ObservedEvent]:
    return [
        _event(
            ObservedEventType.PRODUCT_VIEWED, product, f"{product}-s{n}", in_stock=in_stock, age=age
        )
        for n in range(count)
    ]


def _adds(product: str, *sessions: str) -> list[ObservedEvent]:
    return [_event(ObservedEventType.CART_ADDED, product, s) for s in sessions]


def _the_week() -> list[ObservedEvent]:
    return [
        *_visitors(PEPPER, 10),
        *_adds(PEPPER, "never-opened-1", "never-opened-2", "never-opened-3"),
        *_visitors(BLACK_TEA, 20),
        *_visitors(GREEN_TEA, 12),
        *_adds(GREEN_TEA, f"{GREEN_TEA}-s0", f"{GREEN_TEA}-s0"),
        *_visitors(ONE_IN_TEN, 10),
        *_adds(ONE_IN_TEN, f"{ONE_IN_TEN}-s0"),
        *_visitors(NINE, 9),
        *[_event(ObservedEventType.PRODUCT_VIEWED, ONE_SESSION, "same") for _ in range(15)],
        *_visitors(SOLD_OUT, 10, in_stock=False),
        *_visitors(UNKNOWN, 10, in_stock=None),
        *_visitors(OLD, 10, age=timedelta(days=8)),
    ]


@pytest.fixture
async def db():
    load_env()
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    yield database
    await database.dispose()


async def _shop(db: Database, events: list[ObservedEvent]) -> str:
    tenant = ids.new_id(ids.TENANT)
    async with db.tenant_session(tenant) as session:
        await TenantRepository(session).create(tenant_id=tenant, name="Rarely added shop")
        repository = ObservedEventRepository(session)
        for event in events:
            await repository.record(tenant, event)
    return tenant


async def _drop(db: Database, tenant: str) -> None:
    async with db.tenant_session(tenant) as session:
        await session.execute(delete(observed_events).where(observed_events.c.tenant_id == tenant))
        await session.execute(delete(tenants).where(tenants.c.tenant_id == tenant))


@pytest.fixture
async def shop(db: Database):
    tenant = await _shop(db, _the_week())
    yield tenant
    await _drop(db, tenant)


async def _read(db: Database, tenant: str):
    since = datetime.now(UTC) - WEEK
    async with db.tenant_session(tenant) as session:
        repository = ObservedEventRepository(session)
        return (
            await repository.rarely_added(tenant, since=since),
            await repository.count_rarely_added(tenant, since=since),
        )


class TestWhatIsListed:
    async def test_exactly_the_three_that_qualify_lowest_share_first(
        self, db: Database, shop: str
    ) -> None:
        listed, _ = await _read(db, shop)
        # 0/20 and 0/10 share 0: more visitors first. Then 1/12.
        assert [(p.product_id, p.visitors, p.added) for p in listed] == [
            (BLACK_TEA, 20, 0),
            (PEPPER, 10, 0),
            (GREEN_TEA, 12, 1),
        ]

    async def test_homes_number_is_the_tabs_number(self, db: Database, shop: str) -> None:
        listed, count = await _read(db, shop)
        assert count == len(listed) == 3

    async def test_an_add_counts_only_from_a_visitor_and_only_once(
        self, db: Database, shop: str
    ) -> None:
        listed = {p.product_id: p for p in (await _read(db, shop))[0]}
        # Three adds from sessions that never opened the page: not *added*.
        assert listed[PEPPER].added == 0
        # One visitor added it twice: one.
        assert listed[GREEN_TEA].added == 1

    async def test_the_edges_stay_off(self, db: Database, shop: str) -> None:
        listed = {p.product_id for p in (await _read(db, shop))[0]}
        assert ONE_IN_TEN not in listed  # 1 in 10 is not fewer than 1 in 10
        assert NINE not in listed  # 9 visitors prove nothing yet
        assert ONE_SESSION not in listed  # 15 views, 1 visitor
        assert SOLD_OUT not in listed  # Sold out's, not this tab's
        assert UNKNOWN not in listed  # a view nobody measured is not evidence
        assert OLD not in listed  # older than the window

    async def test_it_carries_the_last_view(self, db: Database, shop: str) -> None:
        listed, _ = await _read(db, shop)
        for product in listed:
            assert datetime.now(UTC) - product.last_viewed_at < 2 * HOUR


class TestIsolation:
    async def test_another_shops_views_never_count(self, db: Database, shop: str) -> None:
        other = await _shop(db, _visitors(PEPPER, 30))
        try:
            listed = {p.product_id: p for p in (await _read(db, shop))[0]}
            assert listed[PEPPER].visitors == 10
            assert [p.product_id for p in (await _read(db, other))[0]] == [PEPPER]
        finally:
            await _drop(db, other)

    async def test_an_empty_shop_lists_nothing(self, db: Database) -> None:
        tenant = await _shop(db, [])
        try:
            assert await _read(db, tenant) == ([], 0)
        finally:
            await _drop(db, tenant)
