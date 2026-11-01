"""ADR-0074 piece 3: the routes behind Links, against a real database.

What these tests hold the build to (ADR-0074 §2 to §7, console.md §3.15):

* **who** (R115): the Owner and Support on every route; the Developer is
  refused, a stranger sees no shop;
* **a plan's post link** (R110, R111): made on the first *Copy*, the same link
  on the next; only for the plan's own products and the post's own places; the
  plan's page shows each post's product and clicks;
* **Make a link** (D18): any product with a page of its own, never another;
  the chooser lists those and narrows as the owner types;
* **the Links page**: own links newest first with their clicks; campaigns with
  *See the plan* while the plan exists, and their clicks after it is gone (R116);
* **Remove** (R113): the clicks go and the link keeps opening its product.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

from neura_agent_core.calendar import CalendarRepository, Country, calendar_plans, shop_today
from neura_api.main import create_app
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import memberships, users
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.removal import remove_tenant
from tests.console_permissions import DEVELOPER, OWNER, SUPPORT

pytestmark = pytest.mark.integration

TODAY = shop_today(Country.SRI_LANKA, datetime.now(UTC))
TEA = "https://shop.example/p/4"
SAFARI = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Safari/604.1"
ANSWER = {
    "theme": "A Ceylon tea Avurudu",
    "idea": "Families buy tea for the New Year table.",
    "products": ["4", "7"],
    "act_on": [],
    "texts": {"teaser": "Avurudu is coming.", "launch": "Here: [your offer]."},
    "catalogue_cut": False,
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("LINKS_BASE_URL", "https://go.example")
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


@pytest.fixture
async def team(db: Database):
    tenant = ids.new_id(ids.TENANT)
    made = Team(tenant=tenant)
    async with db.tenant_session(tenant) as session:
        await TenantRepository(session).create(
            tenant_id=tenant, name="Links Test Shop", enabled_agents=["care", "grow"]
        )
        for external_id, document in (
            ("4", {"title": "Ceylon Black Tea BOPF 400g", "url": TEA}),
            ("7", {"title": "Ceylon Cinnamon Sticks 100g", "url": "https://shop.example/p/7"}),
            ("8", {"title": "Cinnamon Tea Bags (25)", "url": "javascript:alert(1)"}),
            (
                "9",
                {
                    "title": "Old Cinnamon Oil",
                    "url": "https://shop.example/p/9",
                    "status": "archived",
                },
            ),
        ):
            await session.execute(
                insert(synced_entities).values(
                    tenant_id=tenant,
                    platform="generic",
                    entity_type="product",
                    external_id=external_id,
                    neura_id=f"nr_{external_id}",
                    fingerprint="f" * 32,
                    document=document,
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

    yield made

    async with db.tenant_session(tenant) as session:
        await remove_tenant(session, tenant)
    async with db.identity_session() as session:
        await session.execute(
            delete(users).where(users.c.id.in_([*made.people.values(), made.stranger]))
        )


async def _plan(db: Database, team: Team, days: int = 20) -> tuple[str, date]:
    day = TODAY + timedelta(days=days)
    async with db.tenant_session(team.tenant) as session:
        stored = await CalendarRepository(session).store_plan(
            team.tenant,
            date_key="s:avurudu",
            day=day,
            name="Avurudu",
            answer=ANSWER,
            prompt_revision="test",
            at=datetime.now(UTC),
        )
    return stored.id, day


def _code(link: str) -> str:
    assert link.startswith("https://go.example/")
    return link.rsplit("/", 1)[1]


def _tap(client: TestClient, link: str) -> None:
    response = client.get(
        f"/go/{_code(link)}", headers={"User-Agent": SAFARI}, follow_redirects=False
    )
    assert response.status_code == 302


class TestWhoMayUseIt:
    async def test_the_owner_and_support_the_developer_never(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id, _ = await _plan(db, team)
        for role in (OWNER, SUPPORT):
            assert (
                client.get(f"{team.base()}/links", cookies=cookie(team.people[role])).status_code
                == 200
            )
        developer = cookie(team.people[DEVELOPER])
        calls = [
            ("GET", f"{team.base()}/links", None),
            ("GET", f"{team.base()}/links/products", None),
            ("POST", f"{team.base()}/links", {"product_id": "4", "place": "facebook", "name": "x"}),
            ("DELETE", f"{team.base()}/links/lnk_x", None),
            (
                "POST",
                f"{team.base()}/calendar/plans/{plan_id}/links",
                {"post": "teaser", "place": "facebook", "product_id": "4"},
            ),
        ]
        for method, path, body in calls:
            refused = client.request(method, path, json=body, cookies=developer)
            assert refused.status_code == 403, (method, path)
            assert refused.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
        assert client.get(f"{team.base()}/links", cookies=cookie(team.stranger)).status_code == 404


class TestAPlansPostLinks:
    async def test_the_first_copy_makes_the_link_and_the_next_gives_it_again(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id, _ = await _plan(db, team)
        support = cookie(team.people[SUPPORT])
        path = f"{team.base()}/calendar/plans/{plan_id}/links"
        body = {"post": "teaser", "place": "facebook", "product_id": "7"}
        first = client.post(path, json=body, cookies=support).json()["data"]
        again = client.post(path, json=body, cookies=support).json()["data"]
        assert first["link"] == again["link"]
        assert first["product_title"] == "Ceylon Cinnamon Sticks 100g"
        whatsapp = client.post(path, json=body | {"place": "whatsapp"}, cookies=support).json()[
            "data"
        ]
        assert whatsapp["link"] != first["link"]

    async def test_only_the_plans_products_and_the_posts_places(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id, _ = await _plan(db, team)
        owner = cookie(team.people[OWNER])
        path = f"{team.base()}/calendar/plans/{plan_id}/links"
        wrong = [
            ({"post": "teaser", "place": "facebook", "product_id": "9"}, "NOT_IN_PLAN"),
            ({"post": "teaser", "place": "email", "product_id": "4"}, "NO_SUCH_PLACE"),
            ({"post": "email", "place": "whatsapp", "product_id": "4"}, "NO_SUCH_PLACE"),
        ]
        for body, code in wrong:
            refused = client.post(path, json=body, cookies=owner)
            assert refused.status_code == 400, body
            assert refused.json()["error"]["code"] == code
        assert (
            client.post(
                path, json={"post": "banner", "place": "facebook", "product_id": "4"}, cookies=owner
            ).status_code
            == 400
        )
        missing = client.post(
            f"{team.base()}/calendar/plans/pln_nope/links",
            json={"post": "teaser", "place": "facebook", "product_id": "4"},
            cookies=owner,
        )
        assert missing.status_code == 404

    async def test_the_plans_page_shows_each_posts_product_and_clicks(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id, _ = await _plan(db, team)
        owner = cookie(team.people[OWNER])
        plan_path = f"{team.base()}/calendar/plans/{plan_id}"
        before = client.get(plan_path, cookies=owner).json()["data"]["post_links"]
        assert before["teaser"] == {
            "product_id": None,
            "clicks": {"facebook": 0, "instagram": 0, "whatsapp": 0},
        }
        assert before["email"] == {"product_id": None, "clicks": {"email": 0}}
        assert "banner" not in before

        made = client.post(
            f"{plan_path}/links",
            json={"post": "teaser", "place": "whatsapp", "product_id": "7"},
            cookies=owner,
        ).json()["data"]
        _tap(client, made["link"])
        _tap(client, made["link"])
        after = client.get(plan_path, cookies=owner).json()["data"]["post_links"]
        assert after["teaser"] == {
            "product_id": "7",
            "clicks": {"facebook": 0, "instagram": 0, "whatsapp": 2},
        }


class TestMakeALink:
    async def test_a_link_for_any_product_with_a_page(self, client: TestClient, team: Team) -> None:
        owner = cookie(team.people[OWNER])
        made = client.post(
            f"{team.base()}/links",
            json={"product_id": "4", "place": "facebook", "name": "  Tuesday   post "},
            cookies=owner,
        )
        assert made.status_code == 200
        data = made.json()["data"]
        assert data["name"] == "Tuesday post"
        assert data["product_title"] == "Ceylon Black Tea BOPF 400g"
        assert data["clicks"] == 0
        response = client.get(
            f"/go/{_code(data['link'])}", headers={"User-Agent": SAFARI}, follow_redirects=False
        )
        assert response.headers["location"].startswith(
            f"{TEA}?utm_source=facebook&utm_medium=social&utm_campaign=tuesday-post"
        )

    async def test_never_a_product_without_a_page_or_not_in_the_shop(
        self, client: TestClient, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        for product_id, code in (("8", "NO_PRODUCT_PAGE"), ("404", "PRODUCT_NOT_FOUND")):
            refused = client.post(
                f"{team.base()}/links",
                json={"product_id": product_id, "place": "facebook", "name": "x"},
                cookies=owner,
            )
            assert refused.status_code == 400
            assert refused.json()["error"]["code"] == code
        for body in (
            {"product_id": "4", "place": "tiktok", "name": "x"},
            {"product_id": "4", "place": "facebook", "name": "   "},
            {"product_id": "4", "place": "facebook", "name": "x" * 61},
            {"product_id": "4", "place": "facebook", "name": "x", "url": "https://evil.example/"},
        ):
            assert client.post(f"{team.base()}/links", json=body, cookies=owner).status_code == 400

    async def test_the_chooser_lists_products_with_a_page_and_narrows(
        self, client: TestClient, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        listed = client.get(f"{team.base()}/links/products", cookies=owner).json()["data"]
        assert [p["title"] for p in listed["products"]] == [
            "Ceylon Black Tea BOPF 400g",
            "Ceylon Cinnamon Sticks 100g",
        ]
        assert listed["more"] is False
        narrowed = client.get(f"{team.base()}/links/products?q=cinn", cookies=owner).json()["data"]
        assert [p["product_id"] for p in narrowed["products"]] == ["7"]
        literal = client.get(f"{team.base()}/links/products?q=%25", cookies=owner).json()["data"]
        assert literal["products"] == []


class TestTheLinksPage:
    async def test_own_links_newest_first_and_campaigns_with_their_plan(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id, day = await _plan(db, team)
        owner = cookie(team.people[OWNER])
        older = client.post(
            f"{team.base()}/links",
            json={"product_id": "4", "place": "whatsapp", "name": "Status"},
            cookies=owner,
        ).json()["data"]
        newer = client.post(
            f"{team.base()}/links",
            json={"product_id": "7", "place": "facebook", "name": "Tuesday post"},
            cookies=owner,
        ).json()["data"]
        for _ in range(3):
            _tap(client, newer["link"])
        plan_links = f"{team.base()}/calendar/plans/{plan_id}/links"
        for body in (
            {"post": "teaser", "place": "facebook", "product_id": "4"},
            {"post": "teaser", "place": "whatsapp", "product_id": "4"},
            {"post": "email", "place": "email", "product_id": "7"},
        ):
            _tap(client, client.post(plan_links, json=body, cookies=owner).json()["data"]["link"])

        data = client.get(f"{team.base()}/links", cookies=owner).json()["data"]
        assert [(link["name"], link["clicks"]) for link in data["own"]] == [
            ("Tuesday post", 3),
            ("Status", 0),
        ]
        assert data["own"][1]["link"] == older["link"]
        [campaign] = data["campaigns"]
        assert campaign["name"] == "Avurudu"
        assert campaign["day"] == day.isoformat()
        assert campaign["plan_id"] == plan_id
        assert campaign["clicks"] == 3
        assert [(p["post"], p["places"]) for p in campaign["posts"]] == [
            ("teaser", {"facebook": 1, "instagram": 0, "whatsapp": 1}),
            ("email", {"email": 1}),
        ]

        # The plan is deleted 30 days after its date; its clicks stay (R116).
        async with db.tenant_session(team.tenant) as session:
            await session.execute(delete(calendar_plans))
        [kept] = client.get(f"{team.base()}/links", cookies=owner).json()["data"]["campaigns"]
        assert kept["plan_id"] is None
        assert kept["clicks"] == 3


class TestRemove:
    async def test_the_clicks_go_and_the_link_keeps_opening_its_product(
        self, client: TestClient, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        made = client.post(
            f"{team.base()}/links",
            json={"product_id": "4", "place": "facebook", "name": "x"},
            cookies=owner,
        ).json()["data"]
        _tap(client, made["link"])
        assert client.delete(f"{team.base()}/links/{made['id']}", cookies=owner).status_code == 200
        assert client.delete(f"{team.base()}/links/{made['id']}", cookies=owner).status_code == 404
        assert client.get(f"{team.base()}/links", cookies=owner).json()["data"]["own"] == []
        _tap(client, made["link"])
