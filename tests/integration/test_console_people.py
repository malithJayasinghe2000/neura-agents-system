"""ADR-0058 §3, §4, §6, §9 and R12 over HTTP and against real RLS: people in a shop.

What these tests hold the build to:

* **an invite** is emailed, works **once**, for **7 days**; *Cancel* and *Send
  again* stop the old link; only its hash is stored; it adds the person to
  **that shop only**, creating their account when the email has none; the
  answer is the same whether or not the email has an account; a member is
  refused with a plain sentence; Shop A's owner cannot invite into Shop B;
* **a role change and a removal** bite on the person's **next request**;
* **a shop always keeps one Owner**, also when two Owners act at the same
  moment;
* **every** invite, cancel, send again, acceptance, role change and removal is
  in the audit log with who did it, and with no email in it;
* ``/me`` says what each role may open, ``/home`` gives Support the
  handed-over count and the Developer none (R12), and a secret says who made it.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from neura_api.main import create_app
from neura_core import Database, NeuraError, get_settings, ids, load_env
from neura_core.email import Mailer, SendResult
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.people import INVITE_TTL, PeopleRepository
from neura_core.identity.schema import login_tokens, membership_invites, memberships, users
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.schema import customer_secrets, shop_tokens, tenants
from tests.console_permissions import DEVELOPER, OWNER, SUPPORT
from tests.integration.console_fixtures import drop_shop, make_shop

pytestmark = pytest.mark.integration

#: What a refused link says, whatever was wrong with it.
NO_LONGER_VALID = "That invite link is no longer valid. Ask the shop's owner to send it again."


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
def mail(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Every email the API sends, instead of sending it."""
    sent: list[dict[str, str]] = []

    def send(self: Mailer, *, to: str, subject: str, body: str) -> SendResult:
        sent.append({"to": to, "subject": subject, "body": body})
        return SendResult(sent=True)

    monkeypatch.setattr(Mailer, "send", send)
    return sent


@dataclass
class Shop:
    tenant: str
    owner: str
    owner_email: str
    #: Every email a test used, so the accounts an acceptance made are removed.
    emails: list[str] = field(default_factory=list)

    def email(self, label: str) -> str:
        address = f"{label}-{ids.new_id(ids.USER).lower()}@example.com"
        self.emails.append(address)
        return address


async def _shop(db: Database, name: str = "People Test Shop") -> Shop:
    owner = ids.new_id(ids.USER)
    shop = Shop(tenant=ids.new_id(ids.TENANT), owner=owner, owner_email=f"{owner}@example.com")
    shop.emails.append(shop.owner_email)
    async with db.identity_session() as session:
        await session.execute(
            users.insert().values(id=owner, email=shop.owner_email, name="Pat Owner")
        )
    async with db.tenant_session(shop.tenant) as session:
        await TenantRepository(session).create(
            tenant_id=shop.tenant, name=name, enabled_agents=["care", "sell"]
        )
        await session.execute(
            memberships.insert().values(
                id=ids.new_id(ids.MEMBERSHIP), tenant_id=shop.tenant, user_id=owner, role=OWNER
            )
        )
    return shop


async def _drop(db: Database, shop: Shop) -> None:
    # By the test's own fresh tenant id and its own fresh emails: nothing else
    # can carry them.
    async with db.tenant_session(shop.tenant) as session:
        await session.execute(
            delete(membership_invites).where(membership_invites.c.tenant_id == shop.tenant)
        )
        await session.execute(delete(memberships).where(memberships.c.tenant_id == shop.tenant))
        await session.execute(
            delete(customer_secrets).where(customer_secrets.c.tenant_id == shop.tenant)
        )
        await session.execute(delete(shop_tokens).where(shop_tokens.c.tenant_id == shop.tenant))
        await session.execute(delete(tenants).where(tenants.c.tenant_id == shop.tenant))
    async with db.identity_session() as session:
        made = (
            await session.execute(select(users.c.id).where(users.c.email.in_(shop.emails)))
        ).scalars()
        made_ids = list(made)
        await session.execute(delete(login_tokens).where(login_tokens.c.user_id.in_(made_ids)))
        await session.execute(delete(users).where(users.c.id.in_(made_ids)))
    engine = create_async_engine(str(get_settings().database_migration_url))
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM audit_log WHERE tenant_id = :t"), {"t": shop.tenant}
            )
    finally:
        await engine.dispose()


@pytest.fixture
async def shop(db: Database):
    made = await _shop(db)
    yield made
    await _drop(db, made)


@pytest.fixture
async def other_shop(db: Database):
    made = await _shop(db, name="Other Test Shop")
    yield made
    await _drop(db, made)


def signed_in(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


def base(shop: Shop) -> str:
    return f"/v1/console/shops/{shop.tenant}"


def invite(client: TestClient, shop: Shop, email: str, role: str, *, by: str | None = None):
    return client.post(
        f"{base(shop)}/invites",
        json={"email": email, "role": role},
        cookies=signed_in(by or shop.owner),
    )


def link_in(message: dict[str, str]) -> tuple[str, str]:
    """The shop and the token from an invite email's link."""
    found = re.search(r"https?://\S+/auth/invite\?\S+", message["body"])
    assert found, message["body"]
    query = parse_qs(urlparse(found.group(0)).query)
    return query["shop"][0], query["token"][0]


def accept(client: TestClient, shop_id: str, token: str):
    return client.post("/v1/console/auth/accept-invite", json={"shop": shop_id, "token": token})


async def join(client: TestClient, shop: Shop, mail: list[dict[str, str]], role: str) -> str:
    """Invite a new person with ``role`` and accept it. Their user id."""
    email = shop.email(role)
    assert invite(client, shop, email, role).status_code == 200
    accepted = accept(client, *link_in(mail[-1]))
    assert accepted.json()["data"]["signed_in"] is True
    return accepted.json()["data"]["user_id"]


async def active_role(db: Database, tenant: str, user: str) -> str | None:
    async with db.tenant_session(tenant) as session:
        return await session.scalar(
            select(memberships.c.role).where(
                memberships.c.tenant_id == tenant,
                memberships.c.user_id == user,
                memberships.c.revoked_at.is_(None),
            )
        )


class TestInvite:
    async def test_an_invite_is_emailed_and_waits_in_the_list(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        email = shop.email("dev")
        sent = invite(client, shop, email, DEVELOPER)

        assert sent.status_code == 200
        data = sent.json()["data"]
        assert data["emailed"] is True
        assert data["invite"]["email"] == email
        assert data["invite"]["role"] == DEVELOPER
        assert "token" not in sent.text.lower().replace("token_", "")

        assert [m["to"] for m in mail] == [email]
        shop_id, token = link_in(mail[0])
        assert shop_id == shop.tenant
        assert "People Test Shop" in mail[0]["body"]
        assert "Developer" in mail[0]["body"]

        listed = client.get(f"{base(shop)}/people", cookies=signed_in(shop.owner)).json()["data"]
        assert [i["email"] for i in listed["invites"]] == [email]
        expires = datetime.fromisoformat(listed["invites"][0]["expires_at"])
        assert timedelta(days=6, hours=23) < expires - datetime.now(UTC) <= INVITE_TTL

        async with db.tenant_session(shop.tenant) as session:
            stored = (
                await session.execute(
                    select(membership_invites).where(membership_invites.c.tenant_id == shop.tenant)
                )
            ).one()
        assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(tuple(stored))

    async def test_a_member_is_refused_with_a_plain_sentence(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        refused = invite(client, shop, shop.owner_email, SUPPORT)
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "ALREADY_A_MEMBER"
        assert refused.json()["error"]["message"] == "That person is already in this shop."
        assert mail == []

    async def test_the_answer_is_the_same_whether_or_not_the_email_has_an_account(
        self,
        client: TestClient,
        shop: Shop,
        other_shop: Shop,
        mail: list[dict[str, str]],
    ) -> None:
        """Someone elsewhere in NEURA, and nobody at all: the owner cannot tell."""
        known = invite(client, shop, other_shop.owner_email, SUPPORT).json()["data"]
        unknown = invite(client, shop, shop.email("new"), SUPPORT).json()["data"]
        assert set(known) == set(unknown)
        assert set(known["invite"]) == set(unknown["invite"])
        assert known["emailed"] == unknown["emailed"]

    async def test_inviting_the_same_email_again_replaces_the_waiting_invite(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        email = shop.email("twice")
        invite(client, shop, email, SUPPORT)
        first = link_in(mail[-1])
        invite(client, shop, email, DEVELOPER)

        listed = client.get(f"{base(shop)}/people", cookies=signed_in(shop.owner)).json()["data"]
        assert [(i["email"], i["role"]) for i in listed["invites"]] == [(email, DEVELOPER)]
        assert accept(client, *first).json()["data"]["signed_in"] is False
        assert accept(client, *link_in(mail[-1])).json()["data"]["signed_in"] is True

    async def test_shop_a_cannot_invite_into_shop_b(
        self, client: TestClient, db: Database, shop: Shop, other_shop: Shop, mail: list[Any]
    ) -> None:
        refused = invite(client, other_shop, shop.email("x"), SUPPORT, by=shop.owner)
        assert refused.status_code == 404
        assert mail == []
        async with db.tenant_session(other_shop.tenant) as session:
            assert (
                await session.scalar(
                    select(membership_invites.c.id).where(
                        membership_invites.c.tenant_id == other_shop.tenant
                    )
                )
            ) is None

    async def test_an_unknown_role_is_refused(
        self, client: TestClient, shop: Shop, mail: list[Any]
    ) -> None:
        assert invite(client, shop, shop.email("x"), "admin").status_code == 400
        assert mail == []


class TestTheLink:
    async def test_it_makes_the_account_and_adds_the_person_to_that_shop_only(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        email = shop.email("new")
        invite(client, shop, email, DEVELOPER)
        accepted = accept(client, *link_in(mail[-1]))

        data = accepted.json()["data"]
        assert data["signed_in"] is True
        assert data["tenant_id"] == shop.tenant
        assert COOKIE_NAME in accepted.cookies

        me = client.get(
            "/v1/console/me", cookies={COOKIE_NAME: accepted.cookies[COOKIE_NAME]}
        ).json()["data"]
        assert [(m["tenant_id"], m["role"]) for m in me["memberships"]] == [
            (shop.tenant, DEVELOPER)
        ]

        async with db.identity_session() as session:
            account = (await session.execute(select(users).where(users.c.email == email))).one()
        assert account.id == data["user_id"]

    async def test_it_works_once(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        invite(client, shop, shop.email("once"), SUPPORT)
        link = link_in(mail[-1])
        assert accept(client, *link).json()["data"]["signed_in"] is True
        again = accept(client, *link).json()["data"]
        assert again == {"signed_in": False, "message": NO_LONGER_VALID}

    async def test_it_stops_after_7_days(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        invite(client, shop, shop.email("late"), SUPPORT)
        link = link_in(mail[-1])
        async with db.tenant_session(shop.tenant) as session:
            await session.execute(
                update(membership_invites)
                .where(membership_invites.c.tenant_id == shop.tenant)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert accept(client, *link).json()["data"] == {
            "signed_in": False,
            "message": NO_LONGER_VALID,
        }
        listed = client.get(f"{base(shop)}/people", cookies=signed_in(shop.owner)).json()["data"]
        assert listed["invites"][0]["expired"] is True

    async def test_cancel_stops_it(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        made = invite(client, shop, shop.email("cancel"), SUPPORT).json()["data"]["invite"]
        link = link_in(mail[-1])
        cancelled = client.delete(
            f"{base(shop)}/invites/{made['id']}", cookies=signed_in(shop.owner)
        )
        assert cancelled.status_code == 200
        assert accept(client, *link).json()["data"]["signed_in"] is False
        listed = client.get(f"{base(shop)}/people", cookies=signed_in(shop.owner)).json()["data"]
        assert listed["invites"] == []

    async def test_send_again_stops_the_old_link_and_the_new_one_works(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        made = invite(client, shop, shop.email("again"), SUPPORT).json()["data"]["invite"]
        old = link_in(mail[-1])
        again = client.post(
            f"{base(shop)}/invites/{made['id']}/send-again", cookies=signed_in(shop.owner)
        )
        assert again.status_code == 200
        assert again.json()["data"]["emailed"] is True
        assert len(mail) == 2
        assert accept(client, *old).json()["data"]["signed_in"] is False
        assert accept(client, *link_in(mail[-1])).json()["data"]["signed_in"] is True

    async def test_a_link_with_another_shop_in_it_is_refused(
        self, client: TestClient, shop: Shop, other_shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        invite(client, shop, shop.email("swap"), SUPPORT)
        _, token = link_in(mail[-1])
        assert accept(client, other_shop.tenant, token).json()["data"]["signed_in"] is False
        assert accept(client, shop.tenant, token).json()["data"]["signed_in"] is True

    async def test_a_made_up_link_says_the_same_as_a_used_one(self, client: TestClient) -> None:
        assert accept(client, ids.new_id(ids.TENANT), "made-up").json()["data"] == {
            "signed_in": False,
            "message": NO_LONGER_VALID,
        }

    async def test_a_person_removed_earlier_can_be_invited_again(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        email = shop.email("back")
        invite(client, shop, email, SUPPORT)
        user = accept(client, *link_in(mail[-1])).json()["data"]["user_id"]
        assert (
            client.delete(f"{base(shop)}/people/{user}", cookies=signed_in(shop.owner)).status_code
            == 200
        )
        assert await active_role(db, shop.tenant, user) is None

        invite(client, shop, email, DEVELOPER)
        # Their account exists now, so the link adds the shop and does not sign
        # them in (R13).
        assert accept(client, *link_in(mail[-1])).json()["data"]["joined"] is True
        assert await active_role(db, shop.tenant, user) == DEVELOPER

    async def test_someone_who_already_has_an_account_is_added_but_not_signed_in(
        self,
        client: TestClient,
        db: Database,
        shop: Shop,
        other_shop: Shop,
        mail: list[dict[str, str]],
    ) -> None:
        """R13: Amali works in Shop X; Shop Y's invite, if forwarded, must not open
        Shop X. So the link adds Shop Y, and she signs in as usual."""
        invite(client, shop, other_shop.owner_email, SUPPORT)
        accepted = accept(client, *link_in(mail[-1]))

        assert accepted.json()["data"] == {
            "signed_in": False,
            "joined": True,
            "tenant_id": shop.tenant,
            "message": "You've joined People Test Shop. Sign in to open it.",
        }
        assert COOKIE_NAME not in accepted.cookies
        assert await active_role(db, shop.tenant, other_shop.owner) == SUPPORT

        me = client.get("/v1/console/me", cookies=signed_in(other_shop.owner)).json()["data"]
        assert {m["tenant_id"] for m in me["memberships"]} == {shop.tenant, other_shop.tenant}

    async def test_signed_in_already_as_that_person_goes_straight_in(
        self, client: TestClient, shop: Shop, other_shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        invite(client, shop, other_shop.owner_email, DEVELOPER)
        _, token = link_in(mail[-1])
        accepted = client.post(
            "/v1/console/auth/accept-invite",
            json={"shop": shop.tenant, "token": token},
            cookies=signed_in(other_shop.owner),
        )
        assert accepted.json()["data"]["signed_in"] is True
        assert accepted.json()["data"]["tenant_id"] == shop.tenant

    async def test_signed_in_as_someone_else_is_not_switched(
        self, client: TestClient, shop: Shop, other_shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        """A link for Amali, opened where Pat is signed in, adds Amali and leaves
        Pat signed in as Pat: no cookie is written over Pat's."""
        invite(client, shop, other_shop.owner_email, DEVELOPER)
        _, token = link_in(mail[-1])
        accepted = client.post(
            "/v1/console/auth/accept-invite",
            json={"shop": shop.tenant, "token": token},
            cookies=signed_in(shop.owner),
        )
        assert accepted.json()["data"]["signed_in"] is False
        assert accepted.json()["data"]["joined"] is True
        assert COOKIE_NAME not in accepted.cookies


class TestRolesAndRemoval:
    async def test_a_role_change_bites_on_the_next_request(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        user = await join(client, shop, mail, SUPPORT)
        chats = f"{base(shop)}/conversations"
        assert client.get(chats, cookies=signed_in(user)).status_code == 200

        changed = client.put(
            f"{base(shop)}/people/{user}", json={"role": DEVELOPER}, cookies=signed_in(shop.owner)
        )
        assert changed.status_code == 200
        assert client.get(chats, cookies=signed_in(user)).status_code == 403

    async def test_a_removed_person_is_refused_on_the_next_request(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        user = await join(client, shop, mail, DEVELOPER)
        home = f"{base(shop)}/home"
        assert client.get(home, cookies=signed_in(user)).status_code == 200

        removed = client.delete(f"{base(shop)}/people/{user}", cookies=signed_in(shop.owner))
        assert removed.status_code == 200
        assert client.get(home, cookies=signed_in(user)).status_code == 404

        listed = client.get(f"{base(shop)}/people", cookies=signed_in(shop.owner)).json()["data"]
        assert user not in [m["user_id"] for m in listed["members"]]

    async def test_the_last_owner_cannot_be_removed_or_given_another_role(
        self, client: TestClient, db: Database, shop: Shop
    ) -> None:
        cookies = signed_in(shop.owner)
        demoted = client.put(
            f"{base(shop)}/people/{shop.owner}", json={"role": SUPPORT}, cookies=cookies
        )
        removed = client.delete(f"{base(shop)}/people/{shop.owner}", cookies=cookies)
        for refused in (demoted, removed):
            assert refused.status_code == 409
            assert refused.json()["error"]["code"] == "LAST_OWNER"
        assert await active_role(db, shop.tenant, shop.owner) == OWNER

    async def test_with_two_owners_one_may_step_down(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        partner = await join(client, shop, mail, OWNER)
        stepped = client.put(
            f"{base(shop)}/people/{shop.owner}",
            json={"role": SUPPORT},
            cookies=signed_in(partner),
        )
        assert stepped.status_code == 200
        assert await active_role(db, shop.tenant, shop.owner) == SUPPORT

    async def test_two_owners_removing_each_other_at_once_leave_one(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        """The rule is checked in the same transaction as the change, under a lock on
        the shop's Owners: the second waits for the first, then sees one Owner."""
        partner = await join(client, shop, mail, OWNER)

        async def remove(target: str, by: str) -> None:
            async with db.tenant_session(shop.tenant) as session:
                await PeopleRepository(session).remove(shop.tenant, target, by=by)

        async with db.tenant_session(shop.tenant) as first:
            await PeopleRepository(first).remove(shop.tenant, partner, by=shop.owner)
            second = asyncio.create_task(remove(shop.owner, partner))
            await asyncio.sleep(0.5)
            assert not second.done(), "the second change did not wait for the first"

        with pytest.raises(NeuraError):
            await second
        assert await active_role(db, shop.tenant, shop.owner) == OWNER
        assert await active_role(db, shop.tenant, partner) is None

    async def test_two_owners_demoting_each_other_at_once_leave_one(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        partner = await join(client, shop, mail, OWNER)

        async def demote(target: str, by: str) -> None:
            async with db.tenant_session(shop.tenant) as session:
                await PeopleRepository(session).change_role(
                    shop.tenant, target, role=SUPPORT, by=by
                )

        async with db.tenant_session(shop.tenant) as first:
            await PeopleRepository(first).change_role(
                shop.tenant, partner, role=SUPPORT, by=shop.owner
            )
            second = asyncio.create_task(demote(shop.owner, partner))
            await asyncio.sleep(0.5)
            assert not second.done()

        with pytest.raises(NeuraError):
            await second
        assert await active_role(db, shop.tenant, shop.owner) == OWNER

    async def test_someone_not_in_the_shop_cannot_be_changed(
        self, client: TestClient, shop: Shop, other_shop: Shop
    ) -> None:
        cookies = signed_in(shop.owner)
        path = f"{base(shop)}/people/{other_shop.owner}"
        assert client.put(path, json={"role": SUPPORT}, cookies=cookies).status_code == 404
        assert client.delete(path, cookies=cookies).status_code == 404


class TestTheRecord:
    async def test_every_change_is_recorded_with_who_and_no_email(
        self, client: TestClient, db: Database, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        owner = signed_in(shop.owner)
        cancelled = invite(client, shop, shop.email("c"), SUPPORT).json()["data"]["invite"]
        client.delete(f"{base(shop)}/invites/{cancelled['id']}", cookies=owner)
        made = invite(client, shop, shop.email("a"), SUPPORT).json()["data"]["invite"]
        client.post(f"{base(shop)}/invites/{made['id']}/send-again", cookies=owner)
        user = accept(client, *link_in(mail[-1])).json()["data"]["user_id"]
        client.put(f"{base(shop)}/people/{user}", json={"role": DEVELOPER}, cookies=owner)
        client.delete(f"{base(shop)}/people/{user}", cookies=owner)

        engine = create_async_engine(str(get_settings().database_migration_url))
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT event_type, actor, outcome, payload::text AS payload "
                            "FROM audit_log WHERE tenant_id = :t ORDER BY sequence"
                        ),
                        {"t": shop.tenant},
                    )
                ).all()
        finally:
            await engine.dispose()

        assert [(r.outcome, r.actor) for r in rows] == [
            ("invite.sent", shop.owner),
            ("invite.cancelled", shop.owner),
            ("invite.sent", shop.owner),
            ("invite.sent_again", shop.owner),
            ("invite.accepted", user),
            ("member.role_changed", shop.owner),
            ("member.removed", shop.owner),
        ]
        assert all(r.event_type == "people.change" for r in rows)
        assert not any("@" in r.payload for r in rows)


class TestWhatEachRoleIsShown:
    async def test_me_says_what_each_role_may_open(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        support = await join(client, shop, mail, SUPPORT)
        developer = await join(client, shop, mail, DEVELOPER)

        def held(user: str) -> list[str]:
            me = client.get("/v1/console/me", cookies=signed_in(user)).json()["data"]
            return next(m for m in me["memberships"] if m["tenant_id"] == shop.tenant)[
                "permissions"
            ]

        assert held(support) == [
            "shop:conversations:read",
            "shop:home:read",
            "shop:review:write",
        ]
        assert held(developer) == [
            "shop:connect:write",
            "shop:connection:write",
            "shop:contact:write",
            "shop:home:read",
        ]
        owner = held(shop.owner)
        assert "people:members:write" in owner
        assert "sell:suggestions:write" in owner
        assert set(held(support)) | set(held(developer)) < set(owner)

    async def test_home_gives_support_the_handed_over_count_and_the_developer_none(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        support = await join(client, shop, mail, SUPPORT)
        developer = await join(client, shop, mail, DEVELOPER)

        for_support = client.get(f"{base(shop)}/home", cookies=signed_in(support)).json()["data"]
        for_developer = client.get(f"{base(shop)}/home", cookies=signed_in(developer)).json()[
            "data"
        ]
        assert for_support["mode"] == for_developer["mode"] == "live"
        assert for_support["practice"] is False
        assert for_support["handed"] == 0
        assert for_developer["handed"] is None


class TestASecretSaysWhoMadeIt:
    async def test_the_sign_in_secret(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        developer = await join(client, shop, mail, DEVELOPER)
        assert (
            client.post(f"{base(shop)}/customer-secret", cookies=signed_in(developer)).status_code
            == 200
        )
        read = client.get(f"{base(shop)}/customer-secret", cookies=signed_in(shop.owner))
        made_by = read.json()["data"]["made_by"]
        # No name was ever given, so the email stands in for it.
        assert made_by["name"].startswith("developer-")
        assert made_by["role"] == DEVELOPER

    async def test_the_shop_token_before_connecting(
        self, client: TestClient, shop: Shop, mail: list[dict[str, str]]
    ) -> None:
        assert client.post(f"{base(shop)}/token", cookies=signed_in(shop.owner)).status_code == 200
        store = client.get(f"{base(shop)}/store", cookies=signed_in(shop.owner)).json()["data"]
        assert store["connect"]["token_made_by"] == {"name": "Pat Owner", "role": OWNER}

    async def test_a_new_token_for_a_connected_shop(
        self, client: TestClient, db: Database, mail: list[dict[str, str]]
    ) -> None:
        connected = await make_shop(db)
        async with db.tenant_session(connected.tenant) as session:
            await TenantRepository(session).create(
                tenant_id=connected.tenant, name="Connected Test Shop", enabled_agents=["care"]
            )
        as_shop = Shop(tenant=connected.tenant, owner=connected.user, owner_email=connected.email)
        try:
            developer = await join(client, as_shop, mail, DEVELOPER)
            made = client.post(
                f"{base(as_shop)}/store/{connected.store}/token", cookies=signed_in(developer)
            )
            assert made.status_code == 200
            store = client.get(f"{base(as_shop)}/store", cookies=signed_in(connected.user)).json()[
                "data"
            ]
            row = next(s for s in store["stores"] if s["id"] == connected.store)
            assert row["token_made_by"]["role"] == DEVELOPER
        finally:
            async with db.tenant_session(connected.tenant) as session:
                await session.execute(
                    delete(memberships).where(
                        memberships.c.tenant_id == connected.tenant,
                        memberships.c.id != connected.membership,
                    )
                )
                await session.execute(
                    delete(membership_invites).where(
                        membership_invites.c.tenant_id == connected.tenant
                    )
                )
                await session.execute(
                    delete(tenants).where(tenants.c.tenant_id == connected.tenant)
                )
            await drop_shop(db, connected)
            await _drop(db, as_shop)
