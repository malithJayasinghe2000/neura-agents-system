"""ADR-0064 piece 2: the data behind *Missing from your pages*, against a real database.

What these tests hold the build to (console.md §3.11):

* **the page's rows**: grouped by product, with *About your shop* apart; a
  question shows from 2 shoppers, counted by conversation, in 30 days; most
  asked first; each product's title and its own page address, **only an http or
  https one**;
* **who**: Owner and Support; the Developer is refused (they never read a
  shopper's words, ADR-0058), a stranger sees no shop;
* **I added it**: the question leaves the page and Home's count; an unknown one
  is refused and stores nothing;
* **See the chats**: Conversations narrowed to exactly the chats a row counts;
* **Paused** (ADR-0065): while FiveNeurals has the night check off, the page
  says since when; the route learns that from the manifests, never by naming an
  assistant;
* **Home**: the page's own count, for a role that may open it, ``null`` for any
  other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert

from neura_agent_core.conversations import ConversationRepository, ConversationState
from neura_agent_core.gaps import GapKind, PageGap, PageGapRepository
from neura_api.main import create_app
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import memberships, users
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.removal import remove_tenant
from neura_core.tenancy.switches import SwitchRepository
from tests.console_permissions import DEVELOPER, OWNER, SUPPORT

pytestmark = pytest.mark.integration

GREEN_TEA = "5"
BLACK_TEA = "4"
ODD_LINK = "9"


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
    #: Conversation ids per (product or "", fact).
    chats: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def base(self) -> str:
        return f"/v1/console/shops/{self.tenant}"


def cookie(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


async def _ask(
    db: Database, team: Team, product: str | None, fact: str, question: str, *, ago: timedelta
) -> None:
    conversation = ids.new_id(ids.CONVERSATION)
    async with db.tenant_session(team.tenant) as session:
        conversations = ConversationRepository(session)
        await conversations.start(team.tenant, conversation_id=conversation, agent_key="care")
        await conversations.append_turn(
            team.tenant,
            conversation,
            shopper=question,
            reply="I can't confirm that.",
            state=ConversationState.RESOLVED,
        )
        await PageGapRepository(session).record(
            team.tenant,
            PageGap(
                conversation_id=conversation,
                message_id=f"msg_{conversation}",
                kind=GapKind.HALF_ANSWERED,
                product_id=product,
                fact=fact,
                question=question,
                asked_at=datetime.now(UTC) - ago,
            ),
        )
    team.chats.setdefault((product or "", fact), []).append(conversation)


@pytest.fixture
async def team(db: Database):
    tenant = ids.new_id(ids.TENANT)
    made = Team(tenant=tenant)
    async with db.tenant_session(tenant) as session:
        await TenantRepository(session).create(
            tenant_id=tenant, name="Gaps Test Shop", enabled_agents=["care", "grow"]
        )
        for product, title, url in (
            (GREEN_TEA, "Green Tea Loose Leaf 100g", "http://shop.example/product/5"),
            (BLACK_TEA, "Ceylon Black Tea BOPF 400g", "https://shop.example/product/4"),
            (ODD_LINK, "Odd Link Tea", "javascript:alert(1)"),
        ):
            await session.execute(
                insert(synced_entities).values(
                    tenant_id=tenant,
                    platform="generic",
                    entity_type="product",
                    external_id=product,
                    neura_id=f"nr_{product}",
                    fingerprint="f" * 32,
                    document={"title": title, "url": url},
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

    hour = timedelta(hours=1)
    for n in range(3):
        await _ask(db, made, GREEN_TEA, "organic", "Is it organic?", ago=hour * (n + 2))
    for n in range(2):
        await _ask(db, made, BLACK_TEA, "caffeine", "How much caffeine?", ago=hour * (n + 2))
    await _ask(db, made, GREEN_TEA, "cups per pack", "How many cups?", ago=hour)  # one: hidden
    for n in range(2):
        await _ask(db, made, None, "cash on delivery", "Can I pay cash?", ago=hour * (n + 2))
    for n in range(2):
        # Asked as often as the caffeine question, but longer ago: after it.
        await _ask(db, made, ODD_LINK, "origin", "Where is it from?", ago=hour * (n + 5))
    for n in range(2):  # older than 30 days: not on the page
        await _ask(db, made, BLACK_TEA, "weight", "How heavy?", ago=timedelta(days=31 + n))

    yield made

    async with db.tenant_session(tenant) as session:
        await remove_tenant(session, tenant)
    async with db.identity_session() as session:
        await session.execute(
            delete(users).where(users.c.id.in_([*made.people.values(), made.stranger]))
        )


class TestThePage:
    async def test_rows_are_grouped_by_product_with_the_shop_apart(
        self, client: TestClient, team: Team
    ) -> None:
        response = client.get(f"{team.base()}/gaps", cookies=cookie(team.people[OWNER]))
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert (data["days"], data["min_shoppers"], data["paused_since"]) == (30, 2, None)
        assert (data["total"], data["groups"]) == (4, 4)

        products = data["products"]
        assert [p["product_id"] for p in products] == [GREEN_TEA, BLACK_TEA, ODD_LINK]
        green = products[0]
        assert green["title"] == "Green Tea Loose Leaf 100g"
        assert green["url"] == "http://shop.example/product/5"
        [organic] = green["topics"]
        assert (organic["fact"], organic["question"], organic["shoppers"]) == (
            "organic",
            "Is it organic?",
            3,
        )
        assert organic["last_asked"]
        assert products[1]["url"] == "https://shop.example/product/4"
        assert products[2]["url"] is None, "only an http or https address is a link"

        [cash] = data["shop"]
        assert (cash["fact"], cash["shoppers"]) == ("cash on delivery", 2)

    async def test_owner_and_support_only(self, client: TestClient, team: Team) -> None:
        path = f"{team.base()}/gaps"
        assert client.get(path, cookies=cookie(team.people[SUPPORT])).status_code == 200
        developer = client.get(path, cookies=cookie(team.people[DEVELOPER]))
        assert developer.status_code == 403
        assert developer.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
        assert client.get(path, cookies=cookie(team.stranger)).status_code == 404


class TestIAddedIt:
    async def test_the_question_leaves_the_page_and_homes_count(
        self, client: TestClient, team: Team
    ) -> None:
        support = cookie(team.people[SUPPORT])
        before = client.get(f"{team.base()}/home", cookies=support).json()["data"]["gaps"]
        added = client.post(
            f"{team.base()}/gaps/added",
            json={"product_id": GREEN_TEA, "fact": "organic"},
            cookies=support,
        )
        assert added.status_code == 200, added.text
        data = client.get(f"{team.base()}/gaps", cookies=support).json()["data"]
        assert GREEN_TEA not in [p["product_id"] for p in data["products"]]
        after = client.get(f"{team.base()}/home", cookies=support).json()["data"]["gaps"]
        assert (before, after) == (4, 3)

        shop = client.post(
            f"{team.base()}/gaps/added",
            json={"product_id": None, "fact": "cash on delivery"},
            cookies=support,
        )
        assert shop.status_code == 200
        assert client.get(f"{team.base()}/gaps", cookies=support).json()["data"]["shop"] == []

    async def test_an_unknown_question_is_refused(self, client: TestClient, team: Team) -> None:
        response = client.post(
            f"{team.base()}/gaps/added",
            json={"product_id": GREEN_TEA, "fact": "not asked"},
            cookies=cookie(team.people[OWNER]),
        )
        assert response.status_code == 404
        developer = client.post(
            f"{team.base()}/gaps/added",
            json={"product_id": GREEN_TEA, "fact": "organic"},
            cookies=cookie(team.people[DEVELOPER]),
        )
        assert developer.status_code == 403


class TestSeeTheChats:
    async def test_conversations_narrow_to_the_chats_a_row_counts(
        self, client: TestClient, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        listed = client.get(
            f"{team.base()}/conversations",
            params={"gap": "organic", "gap_product": GREEN_TEA},
            cookies=owner,
        ).json()
        assert {row["id"] for row in listed["data"]} == set(team.chats[(GREEN_TEA, "organic")])
        assert listed["meta"]["total"] == 3

        shop = client.get(
            f"{team.base()}/conversations", params={"gap": "cash on delivery"}, cookies=owner
        ).json()
        assert {row["id"] for row in shop["data"]} == set(team.chats[("", "cash on delivery")])


class TestPaused:
    async def test_the_page_says_since_when(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        async with db.tenant_session(team.tenant) as session:
            off = await SwitchRepository(session).set(
                team.tenant, "grow.gaps", on=False, by="usr_admin"
            )
        assert off is not None
        data = client.get(f"{team.base()}/gaps", cookies=cookie(team.people[OWNER])).json()["data"]
        assert data["paused_since"] == off.changed_at.isoformat()
        assert data["total"] == 4, "what was found stays"

        async with db.tenant_session(team.tenant) as session:
            await SwitchRepository(session).set(team.tenant, "grow.gaps", on=True, by="usr_admin")
        data = client.get(f"{team.base()}/gaps", cookies=cookie(team.people[OWNER])).json()["data"]
        assert data["paused_since"] is None


class TestHome:
    async def test_the_count_only_for_a_role_that_may_open_the_page(
        self, client: TestClient, team: Team
    ) -> None:
        for role, expected in ((OWNER, 4), (SUPPORT, 4), (DEVELOPER, None)):
            home = client.get(f"{team.base()}/home", cookies=cookie(team.people[role]))
            assert home.json()["data"]["gaps"] == expected, role
