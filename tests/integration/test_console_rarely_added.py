"""ADR-0071 piece 2: the data behind *Rarely added to cart*, against a real database.

What these tests hold the build to (ADR-0071 §1 to §6; the count's own edges are
in ``test_rarely_added_postgres.py``):

* **the tab's rows**: each listed product with the catalogue's name, address,
  first photo and price, its visitors and how many of them added it; the rule
  (10 visitors, fewer than 1 in 10) in the payload, from the code that applies it;
* **never a session token** anywhere in the payload;
* **who** (R76): the Owner only, as Sold out; Support and the Developer are
  refused, a stranger sees no shop;
* **nothing to show**: whether views arrive, said apart from *nothing qualifies*;
* **Home** (R78): the tab's own count for the Owner, ``null`` for any other role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

from neura_api.main import create_app
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import memberships, users
from neura_core.observation import ObservedEvent, ObservedEventRepository, ObservedEventType
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.removal import remove_tenant
from tests.console_permissions import DEVELOPER, OWNER, SUPPORT

pytestmark = pytest.mark.integration

GREEN_TEA = "5"  # 12 visitors, 1 added: listed, in the catalogue
PEPPER = "2"  # 10 visitors, none added: listed first, not in the catalogue
CARDAMOM = "3"  # 10 visitors, 5 added: not listed
SESSION_PREFIX = "sessiontoken"  # recognisable, so a leak is findable by eye too


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


@dataclass
class Team:
    tenant: str
    people: dict[str, str] = field(default_factory=dict)
    stranger: str = ""

    def base(self) -> str:
        return f"/v1/console/shops/{self.tenant}"


def cookie(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


def _event(kind: ObservedEventType, product: str, n: int) -> ObservedEvent:
    return ObservedEvent.model_construct(
        event_id=ids.new_id("obs"),
        session_id=f"{SESSION_PREFIX}-{product}-{n}",
        type=kind,
        product_id=product,
        occurred_at=datetime.now(UTC) - timedelta(hours=1),
        in_stock=True if kind is ObservedEventType.PRODUCT_VIEWED else None,
    )


def _week(product: str, visitors: int, added: int) -> list[ObservedEvent]:
    return [_event(ObservedEventType.PRODUCT_VIEWED, product, n) for n in range(visitors)] + [
        _event(ObservedEventType.CART_ADDED, product, n) for n in range(added)
    ]


async def _team(db: Database, events: list[ObservedEvent]) -> Team:
    tenant = ids.new_id(ids.TENANT)
    made = Team(tenant=tenant)
    async with db.tenant_session(tenant) as session:
        await TenantRepository(session).create(
            tenant_id=tenant, name="Rarely Added Shop", enabled_agents=["care", "sell"]
        )
        await TenantRepository(session).set_dpa_signed_at(tenant, datetime.now(UTC))
        repository = ObservedEventRepository(session)
        for event in events:
            await repository.record(tenant, event)
        await session.execute(
            insert(synced_entities).values(
                tenant_id=tenant,
                platform="console-fixture",
                entity_type="product",
                external_id=GREEN_TEA,
                neura_id=ids.new_id(ids.NEURA_ENTITY),
                fingerprint="console-rarely-added",
                document={
                    "title": "Green Tea Loose Leaf 100g",
                    "url": "https://shop.example/product/5",
                    "image_urls": [
                        "https://shop.example/green-tea.jpg",
                        "https://shop.example/2.jpg",
                    ],
                    "price_range_min": {"amount": "1200.00", "currency": "LKR"},
                },
            )
        )
    for role in (OWNER, SUPPORT, DEVELOPER):
        user = ids.new_id(ids.USER)
        async with db.identity_session() as session:
            await session.execute(users.insert().values(id=user, email=f"{user}@example.com"))
        async with db.tenant_session(tenant) as session:
            await session.execute(
                memberships.insert().values(
                    id=ids.new_id(ids.MEMBERSHIP), tenant_id=tenant, user_id=user, role=role
                )
            )
        made.people[role] = user
    made.stranger = ids.new_id(ids.USER)
    async with db.identity_session() as session:
        await session.execute(
            users.insert().values(id=made.stranger, email=f"{made.stranger}@example.com")
        )
    return made


async def _drop(db: Database, team: Team) -> None:
    async with db.tenant_session(team.tenant) as session:
        await remove_tenant(session, team.tenant)
    async with db.identity_session() as session:
        await session.execute(
            delete(users).where(users.c.id.in_([*team.people.values(), team.stranger]))
        )


@pytest.fixture
async def team(db: Database):
    made = await _team(
        db, [*_week(GREEN_TEA, 12, 1), *_week(PEPPER, 10, 0), *_week(CARDAMOM, 10, 5)]
    )
    yield made
    await _drop(db, made)


def _tab(client: TestClient, team: Team, user: str):
    return client.get(f"{team.base()}/sold-out/rarely-added", cookies=cookie(user))


class TestTheTab:
    def test_the_rows_and_the_rule(self, client: TestClient, team: Team) -> None:
        response = _tab(client, team, team.people[OWNER])
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert (data["min_visitors"], data["one_in"], data["period"]["days"]) == (10, 10, 7)
        assert (data["agreement"], data["receiving"], data["truncated"]) == (True, True, False)
        pepper, green_tea = data["products"]
        assert (pepper["product_id"], pepper["visitors"], pepper["added"]) == (PEPPER, 10, 0)
        # Not in the catalogue: said as unknown, never invented.
        assert (pepper["title"], pepper["url"], pepper["image"], pepper["price"]) == (
            None,
            None,
            None,
            None,
        )
        assert green_tea == {
            "product_id": GREEN_TEA,
            "title": "Green Tea Loose Leaf 100g",
            "url": "https://shop.example/product/5",
            "image": "https://shop.example/green-tea.jpg",
            "price": {"amount": "1200.00", "currency": "LKR"},
            "visitors": 12,
            "added": 1,
            "last_viewed_at": green_tea["last_viewed_at"],
        }
        assert len(data["caveats"]) == 2

    def test_no_session_token_leaves(self, client: TestClient, team: Team) -> None:
        assert SESSION_PREFIX not in _tab(client, team, team.people[OWNER]).text

    def test_the_owner_only(self, client: TestClient, team: Team) -> None:
        for role in (SUPPORT, DEVELOPER):
            refused = _tab(client, team, team.people[role])
            assert refused.status_code == 403, role
            assert refused.json()["error"]["code"] == "ROLE_NOT_ALLOWED", role
        assert _tab(client, team, team.stranger).status_code == 404


class TestNothingToShow:
    async def test_views_arrive_and_nothing_qualifies(
        self, client: TestClient, db: Database
    ) -> None:
        made = await _team(db, _week(CARDAMOM, 10, 5))
        try:
            data = _tab(client, made, made.people[OWNER]).json()["data"]
            assert (data["products"], data["receiving"], data["caveats"]) == ([], True, [])
        finally:
            await _drop(db, made)

    async def test_no_views_arrive(self, client: TestClient, db: Database) -> None:
        made = await _team(db, [])
        try:
            data = _tab(client, made, made.people[OWNER]).json()["data"]
            assert (data["products"], data["receiving"]) == ([], False)
        finally:
            await _drop(db, made)


class TestHome:
    def test_the_tabs_count_only_for_the_owner(self, client: TestClient, team: Team) -> None:
        for role, expected in ((OWNER, 2), (SUPPORT, None), (DEVELOPER, None)):
            home = client.get(f"{team.base()}/home", cookies=cookie(team.people[role]))
            assert home.json()["data"]["rarely_added"] == expected, role
