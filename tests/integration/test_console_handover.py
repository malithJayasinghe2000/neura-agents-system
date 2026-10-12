"""ADR-0062 §6 to §8: the shop's team sees who is waiting, and answers from its own email.

The dashboard's half of the handover feature, against a real database:

* **Conversations** narrows to *Waiting for an answer* (``?waiting=1``), and each
  row and transcript says how the shop can reach the shopper, **never the address
  itself**: that needs ``shop:handovers:write``, and comes from its own route;
* ``GET …/conversations/{id}/waiting`` gives Owner and Support the address (the
  typed one, or a signed-in customer's **read from the shop, never stored**), and
  the email the team's own app is filled with (R32 6: never the AI's draft);
* ``POST …/conversations/{id}/answered`` deletes the address at once (R30) and
  writes an audit entry naming who, never the address;
* **Home** counts the waiting shoppers for whoever may answer them.

Who may open each route is also held, for every route, by
``tests/integration/test_console_roles.py``; here are the Developer and a
stranger, said out loud for the routes that show a shopper's address.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from neura_agent_core.audit import AuditEvent
from neura_agent_core.conversations import ConversationRepository, ConversationState
from neura_agent_core.graph.schema import audit_log
from neura_agent_core.waiting import WaitingAnswerRepository, waiting_answers
from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import memberships, users
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.schema import tenants
from neura_domain import Capability, Customer
from tests.console_permissions import DEVELOPER, OWNER, SUPPORT
from tests.integration.console_fixtures import TOKENISED_QUESTION, Shop, drop_shop, make_shop

pytestmark = pytest.mark.integration

TYPED = "saman@example.com"
SHOP_NAME = "Ceylon Test Harvester"


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
    shop: Shop
    people: dict[str, str] = field(default_factory=dict)
    memberships: list[str] = field(default_factory=list)
    stranger: str = ""
    #: A chat whose signed-in customer waits (ADR-0057's customer id on it).
    signed_in_conversation: str = ""

    @property
    def tenant(self) -> str:
        return self.shop.tenant

    def base(self) -> str:
        return f"/v1/console/shops/{self.tenant}"


@pytest.fixture
async def team(db: Database):
    shop = await make_shop(db)
    made = Team(shop=shop, people={OWNER: shop.user})
    async with db.tenant_session(shop.tenant) as session:
        await TenantRepository(session).create(
            tenant_id=shop.tenant, name=SHOP_NAME, enabled_agents=["care"]
        )
    for role in (SUPPORT, DEVELOPER):
        user = ids.new_id(ids.USER)
        membership = ids.new_id(ids.MEMBERSHIP)
        async with db.identity_session() as session:
            await session.execute(
                users.insert().values(
                    id=user,
                    email=f"{user}@example.com",
                    name="Kumari Silva" if role == SUPPORT else role,
                )
            )
        async with db.tenant_session(shop.tenant) as session:
            await session.execute(
                memberships.insert().values(
                    id=membership, tenant_id=shop.tenant, user_id=user, role=role
                )
            )
        made.people[role] = user
        made.memberships.append(membership)
    made.stranger = ids.new_id(ids.USER)
    async with db.identity_session() as session:
        await session.execute(
            users.insert().values(id=made.stranger, email=f"{made.stranger}@example.com")
        )

    # The escalated chat waits on a typed address; a second one on a customer.
    made.signed_in_conversation = ids.new_id(ids.CONVERSATION)
    async with db.tenant_session(shop.tenant) as session:
        waiting = WaitingAnswerRepository(session)
        assert await waiting.leave_email(shop.tenant, shop.escalated_conversation, TYPED)
        conversations = ConversationRepository(session)
        await conversations.start(
            shop.tenant,
            conversation_id=made.signed_in_conversation,
            agent_key="care",
            customer_external_id="385",
        )
        await conversations.append_turn(
            shop.tenant,
            made.signed_in_conversation,
            shopper="Can you change the delivery address on my order?",
            reply="I can't answer this here. Your question is with our store.",
            state=ConversationState.ESCALATED,
        )
        await waiting.wait_for_customer(shop.tenant, made.signed_in_conversation)

    yield made

    async with db.tenant_session(shop.tenant) as session:
        # By id, never by shop (console_fixtures.py): the two chats made here.
        await session.execute(
            delete(waiting_answers).where(
                waiting_answers.c.conversation_id.in_(
                    [shop.escalated_conversation, made.signed_in_conversation]
                )
            )
        )
        await session.execute(delete(memberships).where(memberships.c.id.in_(made.memberships)))
        await session.execute(delete(tenants).where(tenants.c.tenant_id == shop.tenant))
    shop_conversations = [made.signed_in_conversation]
    async with db.tenant_session(shop.tenant) as session:
        from neura_agent_core.conversations import conversation_messages, conversations

        await session.execute(
            delete(conversation_messages).where(
                conversation_messages.c.conversation_id.in_(shop_conversations)
            )
        )
        await session.execute(
            delete(conversations).where(conversations.c.id.in_(shop_conversations))
        )
    await drop_shop(db, shop)
    async with db.identity_session() as session:
        await session.execute(
            delete(users).where(
                users.c.id.in_([made.people[SUPPORT], made.people[DEVELOPER], made.stranger])
            )
        )
    engine = create_async_engine(str(get_settings().database_migration_url))
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM audit_log WHERE tenant_id = :t"), {"t": shop.tenant}
            )
    finally:
        await engine.dispose()


def signed_in(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


class _Shop:
    """The shop's bridge, as far as this feature asks it: one customer."""

    def __init__(self, customers: dict[str, Customer], *, fails: bool = False) -> None:
        self.customers = customers
        self.fails = fails
        self.asked: list[str] = []
        self.closed = False

    async def get_customer(self, external_id: str) -> Customer | None:
        self.asked.append(external_id)
        if self.fails:
            raise RuntimeError("the shop did not answer")
        return self.customers.get(external_id)

    async def aclose(self) -> None:
        self.closed = True


@dataclass
class _Connection:
    adapter: Any
    capabilities: frozenset[Capability]
    store_id: str = "sto_fixture"


class _Stores:
    """Stands in for the store directory: the fixture's shop has no real bridge."""

    def __init__(self, adapter: _Shop, capabilities: frozenset[Capability]) -> None:
        self.adapter = adapter
        self.capabilities = capabilities

    async def connect(self, tenant_id: str, *, store_id: str | None = None) -> _Connection:
        return _Connection(adapter=self.adapter, capabilities=self.capabilities)


def _with_shop(client: TestClient, adapter: _Shop, *, reads_customers: bool = True) -> None:
    caps = frozenset({Capability.CUSTOMER_READ}) if reads_customers else frozenset()
    client.app.state.stores = _Stores(adapter, caps)  # type: ignore[attr-defined]


NADEESHA = Customer(
    neura_id="cus_fixture_385",
    tenant_id="tn_fixture",
    external_id="385",
    platform="console-fixture",
    synced_at=datetime.now(UTC),
    email="nadeesha.r@example.com",
    first_name="Nadeesha",
)


class TestTheWaitingList:
    async def test_conversations_narrow_to_the_waiting(
        self, client: TestClient, team: Team
    ) -> None:
        response = client.get(
            f"{team.base()}/conversations?waiting=1", cookies=signed_in(team.people[SUPPORT])
        )
        assert response.status_code == 200
        rows = response.json()["data"]
        assert {row["id"] for row in rows} == {
            team.shop.escalated_conversation,
            team.signed_in_conversation,
        }
        assert response.json()["meta"]["total"] == 2
        reach = {row["id"]: row["waiting"]["reach"] for row in rows}
        assert reach[team.shop.escalated_conversation] == "email"
        assert reach[team.signed_in_conversation] == "customer"

    async def test_a_row_and_a_transcript_never_carry_the_address(
        self, client: TestClient, team: Team
    ) -> None:
        cookies = signed_in(team.people[SUPPORT])
        listed = client.get(f"{team.base()}/conversations", cookies=cookies)
        transcript = client.get(
            f"{team.base()}/conversations/{team.shop.escalated_conversation}", cookies=cookies
        )
        assert TYPED not in listed.text
        assert TYPED not in transcript.text
        waiting = transcript.json()["data"]["waiting"]
        assert waiting["reach"] == "email"
        assert waiting["since"]
        assert waiting["answered_at"] is None
        # A chat nobody waits on says so.
        answered = client.get(
            f"{team.base()}/conversations/{team.shop.answered_conversation}", cookies=cookies
        )
        assert answered.json()["data"]["waiting"] is None
        row = next(r for r in listed.json()["data"] if r["id"] == team.shop.answered_conversation)
        assert row["waiting"] is None


class TestTheAddress:
    async def test_a_typed_address_and_the_email_the_team_sends(
        self, client: TestClient, team: Team
    ) -> None:
        response = client.get(
            f"{team.base()}/conversations/{team.shop.escalated_conversation}/waiting",
            cookies=signed_in(team.people[SUPPORT]),
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["reach"] == "email"
        assert data["email"] == TYPED
        assert data["customer_id"] is None
        # R32 (6) and the approved mockup: the subject, the question, the shop's
        # name; never the AI's unsent draft. The question as stored (tokens).
        assert data["subject"] == f"Your question to {SHOP_NAME}"
        assert data["body"] == (
            "Hello,\n\nYou asked us in the chat on our website:\n"
            f"“{TOKENISED_QUESTION}”\n\n\n\n{SHOP_NAME}"
        )

    async def test_a_signed_in_customers_address_comes_from_the_shop_and_is_not_kept(
        self, client: TestClient, team: Team, db: Database
    ) -> None:
        shop = _Shop({"385": NADEESHA})
        _with_shop(client, shop)

        data = client.get(
            f"{team.base()}/conversations/{team.signed_in_conversation}/waiting",
            cookies=signed_in(team.people[OWNER]),
        ).json()["data"]

        assert data["reach"] == "customer"
        assert data["email"] == "nadeesha.r@example.com"
        assert shop.asked == ["385"]
        assert shop.closed is True
        async with db.tenant_session(team.tenant) as session:
            row = await WaitingAnswerRepository(session).get(
                team.tenant, team.signed_in_conversation
            )
        assert row is not None and row.email is None

    @pytest.mark.parametrize(
        ("adapter", "reads_customers"),
        [
            (_Shop({}), True),  # no such customer
            (_Shop({"385": NADEESHA}, fails=True), True),  # the shop did not answer
            (_Shop({"385": NADEESHA}), False),  # the bridge cannot give customers
        ],
        ids=["unknown", "unreachable", "no-customer-read"],
    )
    async def test_when_the_shop_cannot_give_it_the_customers_id_is_shown(
        self, client: TestClient, team: Team, adapter: _Shop, reads_customers: bool
    ) -> None:
        _with_shop(client, adapter, reads_customers=reads_customers)

        response = client.get(
            f"{team.base()}/conversations/{team.signed_in_conversation}/waiting",
            cookies=signed_in(team.people[SUPPORT]),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["email"] is None
        assert data["customer_id"] == "385"

    async def test_the_developer_and_a_stranger_never_see_it(
        self, client: TestClient, team: Team
    ) -> None:
        path = f"{team.base()}/conversations/{team.shop.escalated_conversation}/waiting"
        developer = client.get(path, cookies=signed_in(team.people[DEVELOPER]))
        stranger = client.get(path, cookies=signed_in(team.stranger))
        assert developer.status_code == 403
        assert stranger.status_code == 404
        assert TYPED not in developer.text + stranger.text

    async def test_a_chat_nobody_waits_on(self, client: TestClient, team: Team) -> None:
        response = client.get(
            f"{team.base()}/conversations/{team.shop.answered_conversation}/waiting",
            cookies=signed_in(team.people[SUPPORT]),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "NOT_WAITING"


class TestMarkAsAnswered:
    async def test_it_deletes_the_address_and_says_who(
        self, client: TestClient, team: Team, db: Database
    ) -> None:
        cookies = signed_in(team.people[SUPPORT])
        conversation = team.shop.escalated_conversation

        response = client.post(
            f"{team.base()}/conversations/{conversation}/answered", cookies=cookies
        )

        assert response.status_code == 200, response.text
        assert response.json()["data"]["answered_by"] == {"name": "Kumari Silva", "role": SUPPORT}
        assert response.json()["data"]["answered_at"]
        async with db.tenant_session(team.tenant) as session:
            row = await WaitingAnswerRepository(session).get(team.tenant, conversation)
            entries = (
                await session.execute(
                    select(audit_log).where(
                        audit_log.c.tenant_id == team.tenant,
                        audit_log.c.event_type == AuditEvent.ESCALATION.value,
                    )
                )
            ).all()
        assert row is not None
        assert row.email is None
        assert row.answered_by == team.people[SUPPORT]
        assert [entry.outcome for entry in entries] == ["handover.answered"]
        assert entries[0].actor == team.people[SUPPORT]
        assert entries[0].conversation_id == conversation
        assert TYPED not in str(entries[0].payload)

        # It leaves the list and the transcript says who answered.
        waiting = client.get(f"{team.base()}/conversations?waiting=1", cookies=cookies).json()
        assert conversation not in {row["id"] for row in waiting["data"]}
        transcript = client.get(f"{team.base()}/conversations/{conversation}", cookies=cookies)
        assert transcript.json()["data"]["waiting"]["answered_by"] == {
            "name": "Kumari Silva",
            "role": SUPPORT,
        }

    async def test_twice_is_refused(self, client: TestClient, team: Team) -> None:
        cookies = signed_in(team.people[OWNER])
        path = f"{team.base()}/conversations/{team.shop.escalated_conversation}/answered"
        assert client.post(path, cookies=cookies).status_code == 200

        again = client.post(path, cookies=cookies)

        assert again.status_code == 409
        assert again.json()["error"]["code"] == "NOT_WAITING"

    async def test_the_developer_cannot(self, client: TestClient, team: Team, db: Database) -> None:
        response = client.post(
            f"{team.base()}/conversations/{team.shop.escalated_conversation}/answered",
            cookies=signed_in(team.people[DEVELOPER]),
        )
        assert response.status_code == 403
        async with db.tenant_session(team.tenant) as session:
            row = await WaitingAnswerRepository(session).get(
                team.tenant, team.shop.escalated_conversation
            )
        assert row is not None and row.email == TYPED

    async def test_an_unknown_chat_is_no_such_chat(self, client: TestClient, team: Team) -> None:
        response = client.post(
            f"{team.base()}/conversations/cnv_not_there/answered",
            cookies=signed_in(team.people[OWNER]),
        )
        assert response.status_code == 404


class TestHome:
    async def test_whoever_may_answer_sees_how_many_wait(
        self, client: TestClient, team: Team
    ) -> None:
        for role in (OWNER, SUPPORT):
            home = client.get(f"{team.base()}/home", cookies=signed_in(team.people[role]))
            assert home.json()["data"]["waiting"] == 2, role
        developer = client.get(f"{team.base()}/home", cookies=signed_in(team.people[DEVELOPER]))
        assert developer.json()["data"]["waiting"] is None

    async def test_an_answer_takes_one_off(self, client: TestClient, team: Team) -> None:
        cookies = signed_in(team.people[SUPPORT])
        client.post(
            f"{team.base()}/conversations/{team.shop.escalated_conversation}/answered",
            cookies=cookies,
        )
        assert client.get(f"{team.base()}/home", cookies=cookies).json()["data"]["waiting"] == 1
