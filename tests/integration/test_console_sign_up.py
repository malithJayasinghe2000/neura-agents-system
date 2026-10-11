"""ADR-0058 §7 and R14 to R17 over HTTP and against real RLS: a shop signs up.

What these tests hold the build to:

* **asking for a link** answers the same words for every email, mails a link to
  every email (R15: an existing account may add a shop), stores only the link's
  hash, makes no account and no shop yet, never mails back what was typed, and a
  second request replaces the first;
* **the link** works once, for 15 minutes, and in one step makes the account
  when the email has none, a shop **waiting** for approval with no assistant,
  in practice mode, and its Owner, and signs them in; an existing account gets
  a second waiting shop (R15);
* **a waiting shop opens nothing**: its Owner is refused every shop route
  (403 ``SHOP_WAITING``), a stranger still gets 404, ``/me`` says it waits and
  gives it no permission, and no key can be issued for it;
* **FiveNeurals approves or refuses** (``scripts/tenant_admin.py``): approval
  makes it an ordinary shop with the assistants named (CARE when none, R14) and
  emails its Owner; refusal emails its Owner and removes the shop, and the
  person keeps their account (R16, R17 e); only a waiting shop is listed, and
  only a waiting shop can be approved or refused;
* **sign up and sign in share one limit** per email (G97).
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import create_async_engine

from neura_api.main import create_app
from neura_core import ConfigurationError, Database, get_settings, ids, load_env
from neura_core.email import Mailer, SendResult
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import login_tokens, memberships, sign_up_requests, users
from neura_core.identity.sign_up import waiting_tenant_ids
from neura_core.tenancy import (
    ApiKeyKind,
    ApiKeyRepository,
    TenantConfig,
    TenantRepository,
    TenantStatus,
    TurnMode,
)
from neura_core.tenancy.schema import tenants
from tests.console_permissions import ROUTES

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import tenant_admin

pytestmark = pytest.mark.integration

#: What the form is told, whatever the email: no word about who has an account.
SENT = "A link is on its way. It works once and expires in 15 minutes."

#: What a used, replaced or old link says (R17 b).
NO_LONGER_VALID = (
    "Sign-up links expire after 15 minutes and work once. "
    "If you already confirmed, sign in. If not, create your account again."
)

MADE_UP = "probe-not-there"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "")
    # Each request names its own made-up address (`fresh_address`), so these
    # tests never use up the hour's links of the address every test shares.
    monkeypatch.setenv("NEURA_TRUSTED_PROXY_HOPS", "1")
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
    """Every email the API or a command sends, instead of sending it."""
    sent: list[dict[str, str]] = []

    def send(self: Mailer, *, to: str, subject: str, body: str) -> SendResult:
        sent.append({"to": to, "subject": subject, "body": body})
        return SendResult(sent=True)

    monkeypatch.setattr(Mailer, "send", send)
    return sent


@dataclass
class Made:
    """Every email and shop a test used, so all of it is removed afterwards."""

    emails: list[str] = field(default_factory=list)
    shops: list[str] = field(default_factory=list)

    def email(self, label: str = "signup") -> str:
        address = f"{label}-{ids.new_id(ids.USER).lower()}@example.com"
        self.emails.append(address)
        return address


@pytest.fixture
async def made(db: Database):
    record = Made()
    yield record
    await _drop(db, record)


async def _drop(db: Database, record: Made) -> None:
    """By the test's own fresh emails, and the shops their accounts are in."""
    async with db.identity_session() as session:
        user_ids = list(
            (
                await session.execute(select(users.c.id).where(users.c.email.in_(record.emails)))
            ).scalars()
        )
        await session.execute(
            delete(sign_up_requests).where(sign_up_requests.c.email.in_(record.emails))
        )
    for user_id in user_ids:
        async with db.identity_session(user_id) as session:
            record.shops.extend(
                str(t)
                for t in (
                    await session.execute(
                        select(memberships.c.tenant_id).where(memberships.c.user_id == user_id)
                    )
                ).scalars()
            )
    for tenant_id in set(record.shops):
        async with db.tenant_session(tenant_id) as session:
            await session.execute(delete(memberships).where(memberships.c.tenant_id == tenant_id))
            await session.execute(delete(tenants).where(tenants.c.tenant_id == tenant_id))
    async with db.identity_session() as session:
        await session.execute(delete(login_tokens).where(login_tokens.c.user_id.in_(user_ids)))
        await session.execute(delete(users).where(users.c.id.in_(user_ids)))
    engine = create_async_engine(str(get_settings().database_migration_url))
    try:
        async with engine.begin() as conn:
            for tenant_id in set(record.shops):
                await conn.execute(
                    text("DELETE FROM audit_log WHERE tenant_id = :t"), {"t": tenant_id}
                )
    finally:
        await engine.dispose()


def fresh_address() -> dict[str, str]:
    """A network address no other request used, for the sign-in limit (G97)."""
    return {"X-Forwarded-For": f"probe-{ids.new_id(ids.REQUEST).lower()}"}


def sign_up(
    client: TestClient,
    email: str,
    *,
    name: str = "Tea Leaf",
    website: str = "tea-leaf.example.com",
):
    return client.post(
        "/v1/console/auth/sign-up",
        json={"email": email, "shop_name": name, "website": website},
        headers=fresh_address(),
    )


def token_in(message: dict[str, str]) -> str:
    found = re.search(r"https?://\S+/auth/sign-up\?\S+", message["body"])
    assert found, message["body"]
    return parse_qs(urlparse(found.group(0)).query)["token"][0]


def confirm(client: TestClient, token: str, cookies: dict[str, str] | None = None):
    return client.post(
        "/v1/console/auth/confirm-sign-up", json={"token": token}, cookies=cookies or {}
    )


def signed_in(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


async def _user_id(db: Database, email: str) -> str | None:
    async with db.identity_session() as session:
        found = await session.scalar(select(users.c.id).where(users.c.email == email))
    return str(found) if found else None


async def _existing_account(db: Database, made: Made) -> tuple[str, str, str]:
    """A person who already runs an ordinary shop: (email, user id, shop id)."""
    email = made.email("existing")
    user = ids.new_id(ids.USER)
    shop = ids.new_id(ids.TENANT)
    made.shops.append(shop)
    async with db.identity_session() as session:
        await session.execute(users.insert().values(id=user, email=email, name="Nimal"))
    async with db.tenant_session(shop) as session:
        await TenantRepository(session).create(
            tenant_id=shop, name="Tea Shop", enabled_agents=["care"]
        )
        await session.execute(
            memberships.insert().values(
                id=ids.new_id(ids.MEMBERSHIP), tenant_id=shop, user_id=user, role="owner"
            )
        )
    return email, user, shop


async def _signed_up(client: TestClient, made: Made, mail: list[dict[str, str]], **form) -> dict:
    """Sign up a new email and use its link. The confirm answer's data."""
    email = made.email()
    assert sign_up(client, email, **form).status_code == 200
    confirmed = confirm(client, token_in(mail[-1]))
    data = confirmed.json()["data"]
    assert data["signed_in"] is True, data
    made.shops.append(data["tenant_id"])
    return {**data, "email": email, "cookie": confirmed.cookies[COOKIE_NAME]}


class TestAskingForALink:
    async def test_every_email_gets_the_same_words_and_a_link(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        known, _, _ = await _existing_account(db, made)
        unknown = made.email()
        for_known = sign_up(client, known)
        for_unknown = sign_up(client, unknown)
        assert for_known.status_code == for_unknown.status_code == 200
        assert for_known.json()["data"] == for_unknown.json()["data"] == {"message": SENT}
        assert [m["to"] for m in mail] == [known, unknown]
        assert mail[0]["subject"] == mail[1]["subject"] == "Confirm your FiveNeurals sign-up"

    async def test_only_a_hash_is_kept_and_nothing_is_made_yet(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        email = made.email()
        sign_up(client, email, name="Hash Check Shop")
        token = token_in(mail[-1])
        async with db.identity_session() as session:
            row = (
                await session.execute(
                    select(sign_up_requests).where(sign_up_requests.c.email == email)
                )
            ).one()
        assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(row._mapping.values())
        assert row.shop_name == "Hash Check Shop"
        assert row.website == "https://tea-leaf.example.com"
        assert row.expires_at - row.created_at == timedelta(minutes=15)
        assert await _user_id(db, email) is None

    async def test_the_email_never_repeats_what_was_typed(
        self, client: TestClient, made: Made, mail: list[dict[str, str]]
    ) -> None:
        sign_up(client, made.email(), name="Win money at bad", website="bad.example.com")
        assert "Win money" not in mail[-1]["subject"] + mail[-1]["body"]
        assert "bad.example.com" not in mail[-1]["subject"] + mail[-1]["body"]

    async def test_asking_again_replaces_the_first_link(
        self, client: TestClient, made: Made, mail: list[dict[str, str]]
    ) -> None:
        email = made.email()
        sign_up(client, email, name="First")
        first = token_in(mail[-1])
        sign_up(client, email, name="Second")
        second = token_in(mail[-1])
        refused = confirm(client, first).json()["data"]
        assert refused == {"signed_in": False, "message": NO_LONGER_VALID}
        data = confirm(client, second).json()["data"]
        made.shops.append(data["tenant_id"])
        assert data["signed_in"] is True

    @pytest.mark.parametrize("website", ["not a site", "ftp://shop.example.com", "localhost"])
    def test_a_website_that_is_not_one_is_refused_in_plain_words(
        self, client: TestClient, made: Made, mail: list[dict[str, str]], website: str
    ) -> None:
        refused = sign_up(client, made.email(), website=website)
        assert refused.status_code == 400
        assert refused.json()["error"]["message"] == (
            "Enter your shop's website, like yourshop.com."
        )
        assert mail == []

    def test_a_shop_needs_a_name(
        self, client: TestClient, made: Made, mail: list[dict[str, str]]
    ) -> None:
        refused = sign_up(client, made.email(), name="   ")
        assert refused.status_code == 400
        assert refused.json()["error"]["message"] == (
            "Enter your shop's name, up to 100 characters."
        )
        assert mail == []


class TestTheLink:
    async def test_it_makes_the_account_and_a_waiting_shop_and_signs_in(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail, name="Tea Leaf", website="tea-leaf.lk")
        user = await _user_id(db, data["email"])
        assert user is not None and data["user_id"] == user
        async with db.tenant_session(data["tenant_id"]) as session:
            shop = await TenantRepository(session).get(data["tenant_id"])
            role = await session.scalar(
                select(memberships.c.role).where(
                    memberships.c.tenant_id == data["tenant_id"], memberships.c.user_id == user
                )
            )
        assert shop is not None
        assert shop.name == "Tea Leaf"
        assert shop.website == "https://tea-leaf.lk"
        assert shop.status is TenantStatus.WAITING
        assert shop.enabled_agents == frozenset()
        assert shop.config.mode is TurnMode.SHADOW
        assert role == "owner"
        me = client.get("/v1/console/me", cookies={COOKIE_NAME: data["cookie"]}).json()["data"]
        assert me["user_id"] == user

    async def test_it_works_once(
        self, client: TestClient, made: Made, mail: list[dict[str, str]]
    ) -> None:
        email = made.email()
        sign_up(client, email)
        token = token_in(mail[-1])
        first = confirm(client, token).json()["data"]
        made.shops.append(first["tenant_id"])
        again = confirm(client, token)
        assert again.json()["data"] == {"signed_in": False, "message": NO_LONGER_VALID}
        assert COOKIE_NAME not in again.cookies

    async def test_it_stops_after_15_minutes(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        email = made.email()
        sign_up(client, email)
        async with db.identity_session() as session:
            await session.execute(
                update(sign_up_requests)
                .where(sign_up_requests.c.email == email)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
        assert confirm(client, token_in(mail[-1])).json()["data"]["signed_in"] is False
        assert await _user_id(db, email) is None

    async def test_an_existing_account_gets_a_second_waiting_shop(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        email, user, first_shop = await _existing_account(db, made)
        sign_up(client, email, name="Spice Shop")
        confirmed = confirm(client, token_in(mail[-1]))
        data = confirmed.json()["data"]
        made.shops.append(data["tenant_id"])
        assert data["signed_in"] is True and data["user_id"] == user
        assert COOKIE_NAME in confirmed.cookies
        me = client.get("/v1/console/me", cookies=signed_in(user)).json()["data"]
        held = {m["tenant_id"]: m for m in me["memberships"]}
        assert held[first_shop]["status"] == "active"
        assert held[data["tenant_id"]]["status"] == "waiting"
        assert held[data["tenant_id"]]["name"] == "Spice Shop"

    async def test_it_is_in_the_shops_record_without_an_email(
        self, client: TestClient, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail)
        engine = create_async_engine(str(get_settings().database_migration_url))
        try:
            async with engine.connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT event_type, actor, outcome, payload::text AS payload "
                            "FROM audit_log WHERE tenant_id = :t ORDER BY sequence"
                        ),
                        {"t": data["tenant_id"]},
                    )
                ).all()
        finally:
            await engine.dispose()
        assert [(r.event_type, r.actor, r.outcome) for r in rows] == [
            ("people.change", data["user_id"], "signed_up")
        ]
        assert not any("@" in r.payload for r in rows)


def _call(client: TestClient, method: str, template: str, tenant: str, cookie: str) -> Any:
    path = re.sub(r"\{[a-z_]+\}", MADE_UP, template.replace("{tenant_id}", tenant))
    body = [] if method in {"POST", "PUT", "DELETE"} else None
    return client.request(method, path, json=body, cookies={COOKIE_NAME: cookie})


class TestAWaitingShop:
    async def test_its_owner_is_refused_every_shop_route(
        self, client: TestClient, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail)
        wrong = []
        for method, template in sorted(ROUTES):
            response = _call(client, method, template, data["tenant_id"], data["cookie"])
            error = response.json().get("error") or {}
            if response.status_code != 403 or error.get("code") != "SHOP_WAITING":
                wrong.append(f"{method} {template}: {response.status_code} {error.get('code')}")
        assert not wrong, "\n".join(wrong)

    async def test_a_stranger_still_gets_404(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail)
        _, stranger, _ = await _existing_account(db, made)
        response = client.get(
            f"/v1/console/shops/{data['tenant_id']}/home", cookies=signed_in(stranger)
        )
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "No such shop."

    async def test_me_says_it_waits_and_opens_nothing(
        self, client: TestClient, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail, name="Waiting Tea")
        me = client.get("/v1/console/me", cookies={COOKIE_NAME: data["cookie"]}).json()["data"]
        assert me["email"] == data["email"]
        (only,) = me["memberships"]
        assert only["status"] == "waiting"
        assert only["name"] == "Waiting Tea"
        assert only["role"] == "owner"
        assert only["permissions"] == []
        assert only["assistants"] == []

    async def test_no_key_can_be_issued_for_it(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail)
        async with db.tenant_session(data["tenant_id"]) as session:
            with pytest.raises(ConfigurationError, match="waiting for approval"):
                await ApiKeyRepository(session).issue(
                    data["tenant_id"], kind=ApiKeyKind.SECRET, scopes=["care:chat:write"]
                )


class TestApproval:
    async def test_only_a_waiting_shop_is_listed(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail)
        _, _, ordinary = await _existing_account(db, made)
        async with db.identity_session() as session:
            waiting = await waiting_tenant_ids(session)
        assert data["tenant_id"] in waiting
        assert ordinary not in waiting

    async def test_approval_makes_it_an_ordinary_shop_and_emails_its_owner(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail, name="Tea Leaf")
        assert await tenant_admin.approve(db, data["tenant_id"], ["care", "sell"]) == 0
        async with db.tenant_session(data["tenant_id"]) as session:
            shop = await TenantRepository(session).require(data["tenant_id"])
        assert shop.status is TenantStatus.ACTIVE
        assert shop.enabled_agents == frozenset({"care", "sell"})
        assert shop.config.mode is TurnMode.SHADOW
        assert mail[-1]["to"] == data["email"]
        assert mail[-1]["subject"] == "Tea Leaf is ready on FiveNeurals"
        home = client.get(
            f"/v1/console/shops/{data['tenant_id']}/home", cookies={COOKIE_NAME: data["cookie"]}
        )
        assert home.status_code == 200

    async def test_with_no_assistant_named_it_gets_care(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail)
        assert await tenant_admin.approve(db, data["tenant_id"], []) == 0
        async with db.tenant_session(data["tenant_id"]) as session:
            shop = await TenantRepository(session).require(data["tenant_id"])
        assert shop.enabled_agents == frozenset({"care"})

    async def test_an_ordinary_shop_cannot_be_approved_or_refused(
        self, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        _, _, ordinary = await _existing_account(db, made)
        async with db.tenant_session(ordinary) as session:
            await TenantRepository(session).set_config(ordinary, TenantConfig(mode=TurnMode.LIVE))
        assert await tenant_admin.approve(db, ordinary, ["sell"]) == 1
        assert await tenant_admin.refuse(db, ordinary) == 1
        async with db.tenant_session(ordinary) as session:
            shop = await TenantRepository(session).require(ordinary)
        assert shop.enabled_agents == frozenset({"care"})
        assert shop.config.mode is TurnMode.LIVE
        assert mail == []

    async def test_refusal_emails_its_owner_and_removes_the_shop_not_the_person(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        data = await _signed_up(client, made, mail, name="Tea Leaf")
        assert await tenant_admin.refuse(db, data["tenant_id"]) == 0
        assert mail[-1]["to"] == data["email"]
        assert mail[-1]["subject"] == "Your FiveNeurals sign-up for Tea Leaf"
        async with db.tenant_session(data["tenant_id"]) as session:
            assert await TenantRepository(session).get(data["tenant_id"]) is None
            left = await session.scalar(
                select(memberships.c.id).where(memberships.c.tenant_id == data["tenant_id"])
            )
        assert left is None
        assert await _user_id(db, data["email"]) == data["user_id"]


class TestSignUpIsLimited:
    @pytest.fixture
    def limited(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("SMTP_HOST", "")
        monkeypatch.setenv("NEURA_TRUSTED_PROXY_HOPS", "1")
        monkeypatch.setenv("RATE_LIMIT_SIGN_IN_PER_EMAIL", "3")
        monkeypatch.setenv("RATE_LIMIT_SIGN_IN_PER_CLIENT", "50")
        get_settings.cache_clear()
        try:
            with TestClient(create_app()) as test_client:
                if not test_client.app.state.limiter.available:
                    pytest.skip("no Redis: rate limits cannot be checked")
                yield test_client
        finally:
            get_settings.cache_clear()

    def test_sign_up_and_sign_in_count_together_per_email(
        self, limited: TestClient, made: Made, mail: list[dict[str, str]]
    ) -> None:
        email = made.email()

        answers = [
            limited.post(
                "/v1/console/auth/request-link", json={"email": email}, headers=fresh_address()
            ).status_code,
            limited.post(
                "/v1/console/auth/request-link", json={"email": email}, headers=fresh_address()
            ).status_code,
        ]
        body = {"email": email, "shop_name": "Tea Leaf", "website": "tea-leaf.lk"}
        answers.append(
            limited.post("/v1/console/auth/sign-up", json=body, headers=fresh_address()).status_code
        )
        refused = limited.post("/v1/console/auth/sign-up", json=body, headers=fresh_address())
        assert [*answers, refused.status_code] == [200, 200, 200, 429]
        assert refused.json()["error"]["message"] == (
            "Too many sign-up links were asked for. Please wait a while, then try again."
        )
        assert len(mail) == 1
