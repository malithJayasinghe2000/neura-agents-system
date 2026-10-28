"""ADR-0068 piece 3: the data behind *Shoppers asked for*, against a real database.

What these tests hold the build to (ADR-0068 §2 to §8):

* **the page's rows**: one per thing, from 2 shoppers counted by conversation,
  in 30 days, most asked first; the label, the latest question, the count and
  when it was last asked; never who asked;
* **who** (R61: A): the Owner only; Support and the Developer are refused, a
  stranger sees no shop;
* **Hide** (R62: A): the thing leaves the page and Home's count; an unknown one
  is refused and stores nothing;
* **See the chats**: Conversations narrowed to exactly the chats a row counts;
* **Paused** (ADR-0065): the night check's switch pauses this page too, learnt
  from the manifests, never by naming an assistant;
* **Home**: the page's own count for the Owner, ``null`` for any other role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from neura_agent_core.conversations import ConversationRepository, ConversationState
from neura_agent_core.wanted import WantedItem, WantedRepository
from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import memberships, users
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.removal import remove_tenant
from neura_core.tenancy.switches import SwitchRepository
from tests.console_permissions import DEVELOPER, OWNER, SUPPORT

pytestmark = pytest.mark.integration


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
    #: Conversation ids per label.
    chats: dict[str, list[str]] = field(default_factory=dict)

    def base(self) -> str:
        return f"/v1/console/shops/{self.tenant}"


def cookie(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


async def _ask(db: Database, team: Team, label: str, question: str, *, ago: timedelta) -> None:
    conversation = ids.new_id(ids.CONVERSATION)
    async with db.tenant_session(team.tenant) as session:
        conversations = ConversationRepository(session)
        await conversations.start(team.tenant, conversation_id=conversation, agent_key="sell")
        await conversations.append_turn(
            team.tenant,
            conversation,
            shopper=question,
            reply="I can't find anything matching that.",
            state=ConversationState.RESOLVED,
        )
        await WantedRepository(session).record(
            team.tenant,
            WantedItem(
                conversation_id=conversation,
                message_id=f"msg_{conversation}",
                label=label,
                question=question,
                asked_at=datetime.now(UTC) - ago,
            ),
        )
    team.chats.setdefault(label, []).append(conversation)


@pytest.fixture
async def team(db: Database):
    tenant = ids.new_id(ids.TENANT)
    made = Team(tenant=tenant)
    async with db.tenant_session(tenant) as session:
        await TenantRepository(session).create(
            tenant_id=tenant, name="Wanted Test Shop", enabled_agents=["care", "sell", "grow"]
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
        await _ask(db, made, "matcha", "Do you have matcha?", ago=hour * (n + 2))
    for n in range(2):
        await _ask(db, made, "oolong tea", "Any oolong tea?", ago=hour * (n + 2))
    await _ask(db, made, "honey", "Do you sell honey?", ago=hour)  # one: hidden
    for n in range(2):  # older than 30 days: not on the page
        await _ask(db, made, "tea infuser", "Tea infusers?", ago=timedelta(days=31 + n))

    yield made

    async with db.tenant_session(tenant) as session:
        await remove_tenant(session, tenant)
    async with db.identity_session() as session:
        await session.execute(
            delete(users).where(users.c.id.in_([*made.people.values(), made.stranger]))
        )


class TestThePage:
    async def test_rows_from_two_shoppers_most_asked_first(
        self, client: TestClient, team: Team
    ) -> None:
        response = client.get(f"{team.base()}/wanted", cookies=cookie(team.people[OWNER]))
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert (data["days"], data["min_shoppers"], data["paused_since"]) == (30, 2, None)
        assert data["total"] == 2
        matcha, oolong = data["items"]
        assert (matcha["label"], matcha["question"], matcha["shoppers"]) == (
            "matcha",
            "Do you have matcha?",
            3,
        )
        assert matcha["last_asked"]
        assert (oolong["label"], oolong["shoppers"]) == ("oolong tea", 2)
        assert set(matcha) == {"label", "question", "shoppers", "last_asked"}, "never who asked"

    async def test_the_owner_only(self, client: TestClient, team: Team) -> None:
        path = f"{team.base()}/wanted"
        for role in (SUPPORT, DEVELOPER):
            refused = client.get(path, cookies=cookie(team.people[role]))
            assert refused.status_code == 403, role
            assert refused.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
        assert client.get(path, cookies=cookie(team.stranger)).status_code == 404


class TestHide:
    async def test_it_leaves_the_page_and_homes_count(self, client: TestClient, team: Team) -> None:
        owner = cookie(team.people[OWNER])
        before = client.get(f"{team.base()}/home", cookies=owner).json()["data"]["wanted"]
        hidden = client.post(
            f"{team.base()}/wanted/hidden", json={"label": "matcha"}, cookies=owner
        )
        assert hidden.status_code == 200, hidden.text
        assert hidden.json()["data"] == {"hidden": True, "label": "matcha"}
        items = client.get(f"{team.base()}/wanted", cookies=owner).json()["data"]["items"]
        assert [i["label"] for i in items] == ["oolong tea"]
        after = client.get(f"{team.base()}/home", cookies=owner).json()["data"]["wanted"]
        assert (before, after) == (2, 1)

    async def test_an_unknown_thing_is_refused(self, client: TestClient, team: Team) -> None:
        response = client.post(
            f"{team.base()}/wanted/hidden",
            json={"label": "not asked"},
            cookies=cookie(team.people[OWNER]),
        )
        assert response.status_code == 404
        support = client.post(
            f"{team.base()}/wanted/hidden",
            json={"label": "matcha"},
            cookies=cookie(team.people[SUPPORT]),
        )
        assert support.status_code == 403


class TestSeeTheChats:
    async def test_conversations_narrow_to_the_chats_a_row_counts(
        self, client: TestClient, team: Team
    ) -> None:
        owner = cookie(team.people[OWNER])
        listed = client.get(
            f"{team.base()}/conversations", params={"wanted": "matcha"}, cookies=owner
        ).json()
        assert {row["id"] for row in listed["data"]} == set(team.chats["matcha"])
        assert listed["meta"]["total"] == 3

        client.post(f"{team.base()}/wanted/hidden", json={"label": "matcha"}, cookies=owner)
        after = client.get(
            f"{team.base()}/conversations", params={"wanted": "matcha"}, cookies=owner
        ).json()
        assert after["data"] == [], "after Hide, only later asks are counted, and listed"

    async def test_support_reads_chats_but_not_this_filter(
        self, client: TestClient, team: Team
    ) -> None:
        """R61: the page is the Owner's, so the filter that reproduces it is too."""
        support = cookie(team.people[SUPPORT])
        path = f"{team.base()}/conversations"
        assert client.get(path, cookies=support).status_code == 200
        refused = client.get(path, params={"wanted": "matcha"}, cookies=support)
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


class TestPaused:
    async def test_the_night_checks_switch_pauses_this_page_too(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        async with db.tenant_session(team.tenant) as session:
            off = await SwitchRepository(session).set(
                team.tenant, "grow.gaps", on=False, by="usr_admin"
            )
        assert off is not None
        owner = cookie(team.people[OWNER])
        data = client.get(f"{team.base()}/wanted", cookies=owner).json()["data"]
        assert data["paused_since"] == off.changed_at.isoformat()
        assert data["total"] == 2, "what was found stays"
        gaps = client.get(f"{team.base()}/gaps", cookies=owner).json()["data"]
        assert gaps["paused_since"] == off.changed_at.isoformat(), "and still pauses the first page"


class TestHome:
    async def test_the_count_only_for_the_owner(self, client: TestClient, team: Team) -> None:
        for role, expected in ((OWNER, 2), (SUPPORT, None), (DEVELOPER, None)):
            home = client.get(f"{team.base()}/home", cookies=cookie(team.people[role]))
            assert home.json()["data"]["wanted"] == expected, role
