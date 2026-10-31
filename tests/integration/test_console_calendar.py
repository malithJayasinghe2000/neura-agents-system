"""ADR-0072 piece 3: the routes behind the Marketing calendar, against a real database.

What these tests hold the build to (ADR-0072 §3 to §8, console.md §3.14):

* **who** (R86: B): the Owner and Support on every route; the Developer is
  refused, a stranger sees no shop;
* **Coming up**: the kept dates, soonest first, each with what its plan is
  (ready, due tonight, planned for a day, not set);
* **This year's dates**: the suggested list ticked until saved; *Save* keeps the
  ticks, a moving date's day and the country; an own date added and removed,
  with its plans; each write books the night run (R96);
* **a plan**: the products from the catalogue, the counts from the plan, the
  schedule from code; an edit saved; *Make it again* books GROW's job at once,
  and is refused while paused or once the date has passed;
* **Home**: the calendar's lines for the Owner and Support, ``null`` for any
  other role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select

from neura_agent_core.calendar import CalendarRepository, Country, shop_today
from neura_api.main import create_app
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import memberships, users
from neura_core.jobs.schema import job_queue
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.removal import remove_tenant
from neura_core.tenancy.switches import SwitchRepository
from tests.console_permissions import DEVELOPER, OWNER, SUPPORT

pytestmark = pytest.mark.integration

TODAY = shop_today(Country.SRI_LANKA, datetime.now(UTC))
ANSWER = {
    "theme": "A Ceylon tea Avurudu",
    "idea": "Families buy tea for the New Year table.",
    "products": ["4", "7"],
    "act_on": [
        {"kind": "wanted", "label": "tea gift box", "shoppers": 8, "product_id": None},
        {"kind": "gap", "label": "true ceylon cinnamon", "shoppers": 3, "product_id": "7"},
    ],
    "texts": {
        "teaser": "Avurudu is coming.",
        "launch": "Our favourites are here: [your offer].",
        "last_chance": "Last 2 days for [your offer].",
        "email_subject": "Avurudu at the shop",
        "email_body": "Hello,\n\nAvurudu is almost here.",
        "banner": "Avurudu: [your offer]",
    },
    "catalogue_cut": False,
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


@dataclass
class Team:
    tenant: str
    people: dict[str, str] = field(default_factory=dict)
    stranger: str = ""

    def base(self) -> str:
        return f"/v1/console/shops/{self.tenant}/calendar"


def cookie(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


@pytest.fixture
async def team(db: Database):
    tenant = ids.new_id(ids.TENANT)
    made = Team(tenant=tenant)
    async with db.tenant_session(tenant) as session:
        await TenantRepository(session).create(
            tenant_id=tenant, name="Calendar Test Shop", enabled_agents=["care", "grow"]
        )
        for external_id, document in (
            (
                "4",
                {
                    "title": "Ceylon Black Tea BOPF 400g",
                    "url": "https://shop.example/p/4",
                    "image_urls": ["https://shop.example/4.jpg"],
                    "price_range_min": {"amount": "1850.00", "currency": "LKR"},
                },
            ),
            ("7", {"title": "Ceylon Cinnamon Sticks 100g", "url": "javascript:alert(1)"}),
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


async def _own(db: Database, team: Team, days: int, name: str = "Our big sale") -> str:
    async with db.tenant_session(team.tenant) as session:
        row = await CalendarRepository(session).add_own(
            team.tenant, name=name, day=TODAY + timedelta(days=days), every_year=False, by="usr_x"
        )
    return row.date_key


async def _plan(db: Database, team: Team, date_key: str, days: int, name: str) -> str:
    async with db.tenant_session(team.tenant) as session:
        stored = await CalendarRepository(session).store_plan(
            team.tenant,
            date_key=date_key,
            day=TODAY + timedelta(days=days),
            name=name,
            answer=ANSWER,
            prompt_revision="test",
            at=datetime.now(UTC),
        )
    return stored.id


async def _kinds(db: Database, team: Team) -> list[str]:
    async with db.tenant_session(team.tenant) as session:
        return sorted((await session.execute(select(job_queue.c.kind))).scalars().all())


class TestWhoMayOpenIt:
    async def test_the_owner_and_support_the_developer_never(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id = await _plan(db, team, await _own(db, team, 10), 10, "Our big sale")
        reads = [f"{team.base()}", f"{team.base()}/dates", f"{team.base()}/plans/{plan_id}"]
        for role in (OWNER, SUPPORT):
            for path in reads:
                assert client.get(path, cookies=cookie(team.people[role])).status_code == 200
        developer = cookie(team.people[DEVELOPER])
        calls = [
            ("GET", team.base(), None),
            ("GET", f"{team.base()}/dates", None),
            ("PUT", f"{team.base()}/dates", {"country": "lk"}),
            ("POST", f"{team.base()}/dates/own", {"name": "x", "day": TODAY.isoformat()}),
            ("DELETE", f"{team.base()}/dates/own/cal_x", None),
            ("GET", f"{team.base()}/plans/{plan_id}", None),
            ("PUT", f"{team.base()}/plans/{plan_id}/texts", {"texts": {"banner": "x"}}),
            ("POST", f"{team.base()}/plans/{plan_id}/again", None),
        ]
        for method, path, body in calls:
            refused = client.request(method, path, json=body, cookies=developer)
            assert refused.status_code == 403, (method, path)
            assert refused.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
        assert client.get(team.base(), cookies=cookie(team.stranger)).status_code == 404


class TestComingUp:
    async def test_the_kept_dates_soonest_first_with_their_plans(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        ready_key = await _own(db, team, 12, "Ready")
        plan_id = await _plan(db, team, ready_key, 12, "Ready")
        await _own(db, team, 20, "Due")
        await _own(db, team, 40, "Later")

        data = client.get(team.base(), cookies=cookie(team.people[SUPPORT])).json()["data"]

        assert (data["country"], data["time_zone"], data["plan_days_before"]) == (
            "lk",
            "Asia/Colombo",
            21,
        )
        assert data["saved"] is False and data["paused_since"] is None
        rows = [(r["name"], r["status"], r["days_left"]) for r in data["coming_up"]]
        assert rows == [("Ready", "ready", 12), ("Due", "tonight", 20), ("Later", "planned", 40)]
        assert data["coming_up"][0]["plan_id"] == plan_id
        later = data["coming_up"][2]
        assert later["plan_day"] == (TODAY + timedelta(days=19)).isoformat()
        assert later["own"] is True and later["plan_id"] is None

    async def test_paused_says_so_and_no_plan_is_promised(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        await _own(db, team, 20, "Due")
        async with db.tenant_session(team.tenant) as session:
            await SwitchRepository(session).set(team.tenant, "grow.calendar", on=False, by="usr_a")
        data = client.get(team.base(), cookies=cookie(team.people[OWNER])).json()["data"]
        assert data["paused_since"] is not None
        assert [r["status"] for r in data["coming_up"]] == ["paused"]


class TestThisYearsDates:
    async def test_every_date_is_ticked_until_saved(self, client: TestClient, team: Team) -> None:
        data = client.get(f"{team.base()}/dates", cookies=cookie(team.people[OWNER])).json()["data"]
        assert (data["year"], data["country"], data["saved"]) == (TODAY.year, "lk", False)
        groups = {g["group"]: g["dates"] for g in data["groups"]}
        assert [d["name"] for d in groups["monthly"]] == ["Payday"]
        assert all(d["kept"] for g in groups.values() for d in g)
        vesak = next(d for d in groups["festivals"] if d["key"] == "vesak")
        assert (vesak["day"], vesak["moving"], vesak["usually"]) == (None, True, [5])
        black_friday = next(d for d in groups["shopping"] if d["key"] == "black_friday")
        assert black_friday["day"] is not None and black_friday["sri_lanka"] is False

    async def test_save_keeps_the_ticks_a_moving_day_and_the_country_and_books_the_night_run(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        vesak = date(TODAY.year, 5, 20).isoformat()
        saved = client.put(
            f"{team.base()}/dates",
            json={
                "country": "lk",
                "dates": [
                    {"key": "black_friday", "kept": False},
                    {"key": "vesak", "kept": True, "day": vesak},
                ],
            },
            cookies=owner,
        )
        assert saved.status_code == 200, saved.text
        data = client.get(f"{team.base()}/dates", cookies=owner).json()["data"]
        dates = {d["key"]: d for g in data["groups"] for d in g["dates"]}
        assert data["saved"] is True
        assert dates["black_friday"]["kept"] is False
        assert (dates["vesak"]["day"], dates["vesak"]["set_by_owner"]) == (vesak, True)
        assert dates["christmas"]["kept"] is True, "left out of the body: still ticked"
        assert await _kinds(db, team) == ["grow.gaps.scan"]

    async def test_a_shop_elsewhere_keeps_the_shopping_days_only(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        assert client.put(
            f"{team.base()}/dates", json={"country": "other"}, cookies=owner
        ).is_success
        async with db.tenant_session(team.tenant) as session:
            repository = CalendarRepository(session)
            assert await repository.country(team.tenant) is Country.OTHER
            keys = {row.key for row in await repository.rows(team.tenant)}
        assert keys == {
            "valentines_day",
            "mothers_day",
            "eleven_eleven",
            "black_friday",
            "cyber_monday",
        }

    async def test_what_cannot_be_saved(self, client: TestClient, team: Team) -> None:
        owner = cookie(team.people[OWNER])
        for body, code in (
            ({"dates": [{"key": "diwali_typo", "kept": True}]}, "UNKNOWN_DATE"),
            (
                {"dates": [{"key": "christmas", "kept": True, "day": f"{TODAY.year}-12-24"}]},
                "NOT_A_MOVING_DATE",
            ),
            (
                {"dates": [{"key": "vesak", "kept": True, "day": f"{TODAY.year + 1}-05-20"}]},
                "NOT_THIS_YEAR",
            ),
        ):
            refused = client.put(f"{team.base()}/dates", json=body, cookies=owner)
            assert refused.status_code == 400, body
            assert refused.json()["error"]["code"] == code

    async def test_an_own_date_added_and_removed_with_its_plan(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        support = cookie(team.people[SUPPORT])
        day = (TODAY + timedelta(days=20)).isoformat()
        added = client.post(
            f"{team.base()}/dates/own",
            json={"name": "  Test   date (made by Claude) ", "day": day, "every_year": True},
            cookies=support,
        )
        assert added.status_code == 200, added.text
        own = added.json()["data"]
        assert (own["name"], own["day"], own["every_year"], own["kept"]) == (
            "Test date (made by Claude)",
            day,
            True,
            True,
        )
        assert await _kinds(db, team) == ["grow.gaps.scan"], "the night run is booked"
        await _plan(db, team, f"o:{own['id']}", 20, own["name"])

        listed = client.get(f"{team.base()}/dates", cookies=support).json()["data"]["own"]
        assert [o["id"] for o in listed] == [own["id"]]
        assert client.delete(f"{team.base()}/dates/own/{own['id']}", cookies=support).is_success
        assert client.get(team.base(), cookies=support).json()["data"]["coming_up"] == []
        async with db.tenant_session(team.tenant) as session:
            assert await CalendarRepository(session).plans(team.tenant, since=TODAY) == []
        again = client.delete(f"{team.base()}/dates/own/{own['id']}", cookies=support)
        assert again.status_code == 404

    async def test_a_day_that_passed_is_refused(self, client: TestClient, team: Team) -> None:
        refused = client.post(
            f"{team.base()}/dates/own",
            json={"name": "Late", "day": (TODAY - timedelta(days=1)).isoformat()},
            cookies=cookie(team.people[OWNER]),
        )
        assert refused.status_code == 400
        assert refused.json()["error"]["code"] == "DAY_PASSED"


class TestAPlan:
    async def test_products_from_the_catalogue_and_the_schedule_from_code(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id = await _plan(db, team, await _own(db, team, 21, "Avurudu"), 21, "Avurudu")
        data = client.get(
            f"{team.base()}/plans/{plan_id}", cookies=cookie(team.people[OWNER])
        ).json()["data"]

        assert (data["name"], data["state"], data["days_left"]) == ("Avurudu", "ready", 21)
        tea, cinnamon = data["products"]
        assert tea == {
            "product_id": "4",
            "title": "Ceylon Black Tea BOPF 400g",
            "url": "https://shop.example/p/4",
            "image": "https://shop.example/4.jpg",
            "price": {"amount": "1850.00", "currency": "LKR"},
        }
        assert cinnamon["url"] is None, "only an http or https address is a link"
        assert [(f["kind"], f["shoppers"]) for f in data["act_on"]] == [("wanted", 8), ("gap", 3)]
        assert data["act_on"][1]["product_title"] == "Ceylon Cinnamon Sticks 100g"
        day = TODAY + timedelta(days=21)
        assert [s["day"] for s in data["schedule"]] == [
            TODAY.isoformat(),
            (day - timedelta(days=14)).isoformat(),
            (day - timedelta(days=7)).isoformat(),
            (day - timedelta(days=2)).isoformat(),
            day.isoformat(),
        ]
        assert data["texts"]["banner"] == "Avurudu: [your offer]"
        assert data["can_make_again"] is True
        assert data["links"] == {"wanted": True, "gaps": True}

    async def test_support_is_not_sent_to_the_owners_page(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id = await _plan(db, team, await _own(db, team, 5), 5, "Sale")
        data = client.get(
            f"{team.base()}/plans/{plan_id}", cookies=cookie(team.people[SUPPORT])
        ).json()["data"]
        assert data["links"] == {"wanted": False, "gaps": True}

    async def test_an_edit_is_saved_and_an_unknown_text_refused(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id = await _plan(db, team, await _own(db, team, 5), 5, "Sale")
        owner = cookie(team.people[OWNER])
        saved = client.put(
            f"{team.base()}/plans/{plan_id}/texts",
            json={"texts": {"banner": "Avurudu: 20% off everything"}},
            cookies=owner,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["edited"] == ["banner"]
        data = client.get(f"{team.base()}/plans/{plan_id}", cookies=owner).json()["data"]
        assert data["texts"]["banner"] == "Avurudu: 20% off everything", "the owner's words"
        refused = client.put(
            f"{team.base()}/plans/{plan_id}/texts", json={"texts": {"hack": "x"}}, cookies=owner
        )
        assert refused.json()["error"]["code"] == "UNKNOWN_TEXT"

    async def test_make_it_again_books_grows_job_at_once(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id = await _plan(db, team, await _own(db, team, 5), 5, "Sale")
        asked = client.post(
            f"{team.base()}/plans/{plan_id}/again", cookies=cookie(team.people[SUPPORT])
        )
        assert asked.status_code == 200, asked.text
        assert asked.json()["data"] == {"state": "making", "booked": True}
        async with db.tenant_session(team.tenant) as session:
            job = (
                await session.execute(
                    select(job_queue.c.kind, job_queue.c.run_after).where(
                        job_queue.c.kind == "grow.calendar.plans"
                    )
                )
            ).one()
        assert job.run_after <= datetime.now(UTC)
        data = client.get(
            f"{team.base()}/plans/{plan_id}", cookies=cookie(team.people[OWNER])
        ).json()["data"]
        assert data["state"] == "making" and data["can_make_again"] is False

    async def test_make_it_again_is_refused_while_paused_or_once_the_date_passed(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        passed = await _plan(db, team, "s:christmas", -1, "Christmas")
        refused = client.post(f"{team.base()}/plans/{passed}/again", cookies=owner)
        assert refused.json()["error"]["code"] == "DATE_PASSED"

        plan_id = await _plan(db, team, await _own(db, team, 5), 5, "Sale")
        async with db.tenant_session(team.tenant) as session:
            await SwitchRepository(session).set(team.tenant, "grow.calendar", on=False, by="usr_a")
        paused = client.post(f"{team.base()}/plans/{plan_id}/again", cookies=owner)
        assert paused.status_code == 409 and paused.json()["error"]["code"] == "PAUSED"
        data = client.get(f"{team.base()}/plans/{plan_id}", cookies=owner).json()["data"]
        assert data["paused_since"] is not None and data["can_make_again"] is False

    async def test_another_shops_plan_is_no_such_plan(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        other = ids.new_id(ids.TENANT)
        async with db.tenant_session(other) as session:
            stored = await CalendarRepository(session).store_plan(
                other,
                date_key="s:christmas",
                day=TODAY + timedelta(days=5),
                name="Christmas",
                answer=ANSWER,
                prompt_revision="test",
                at=datetime.now(UTC),
            )
        try:
            owner = cookie(team.people[OWNER])
            assert client.get(f"{team.base()}/plans/{stored.id}", cookies=owner).status_code == 404
            again = client.post(f"{team.base()}/plans/{stored.id}/again", cookies=owner)
            assert again.status_code == 404
        finally:
            async with db.tenant_session(other) as session:
                await remove_tenant(session, other)


class TestHome:
    async def test_the_lines_for_the_owner_and_support_and_none_for_the_developer(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        plan_id = await _plan(db, team, await _own(db, team, 12, "Avurudu"), 12, "Avurudu")
        home = f"/v1/console/shops/{team.tenant}/home"
        for role in (OWNER, SUPPORT):
            lines = client.get(home, cookies=cookie(team.people[role])).json()["data"]["calendar"]
            assert lines == {
                "add_dates": True,
                "ready": [
                    {
                        "plan_id": plan_id,
                        "name": "Avurudu",
                        "day": (TODAY + timedelta(days=12)).isoformat(),
                        "days_left": 12,
                    }
                ],
            }
        developer = client.get(home, cookies=cookie(team.people[DEVELOPER])).json()["data"]
        assert developer["calendar"] is None

    async def test_add_dates_goes_once_the_year_is_saved_and_a_date_is_near(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        home = f"/v1/console/shops/{team.tenant}/home"
        assert client.put(f"{team.base()}/dates", json={"country": "lk"}, cookies=owner).is_success
        await _own(db, team, 30, "Near")
        assert client.get(home, cookies=owner).json()["data"]["calendar"]["add_dates"] is False
