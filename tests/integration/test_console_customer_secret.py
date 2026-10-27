"""ADR-0057 §3 over HTTP and against real RLS: the customer sign-in secret.

What these tests hold the build to:

* the owner makes the secret on Shop connection and sees it **once**; reading
  it back gives only when it was made, never the secret;
* *make a new one* replaces it at once: a pass signed with the old one fails;
* each make is in the audit log, naming who, never the secret;
* a stranger cannot read or make another shop's secret, and nobody signed out
  can at all.
"""

from __future__ import annotations

import time

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import create_async_engine

from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import login_tokens, memberships, users
from neura_core.tenancy import (
    CustomerSecretRepository,
    PassStatus,
    TenantConfig,
    TenantRepository,
    TurnMode,
    check_customer_pass,
)
from neura_core.tenancy.schema import customer_secrets, tenants

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


async def _owner(db: Database) -> dict[str, str]:
    user = ids.new_id(ids.USER)
    tenant = ids.new_id(ids.TENANT)
    membership = ids.new_id(ids.MEMBERSHIP)
    async with db.identity_session() as session:
        await session.execute(users.insert().values(id=user, email=f"{user}@example.com"))
    async with db.tenant_session(tenant) as session:
        await TenantRepository(session).create(
            tenant_id=tenant,
            name="Secret Test Shop",
            enabled_agents=["care"],
            config=TenantConfig(mode=TurnMode.SHADOW, shadow_intents=frozenset({"policy_qa"})),
        )
        await session.execute(
            text(
                "UPDATE tenants SET config = config || '{\"from_a_newer_neura\": 7}'::jsonb "
                "WHERE tenant_id = :t"
            ),
            {"t": tenant},
        )
        await session.execute(
            memberships.insert().values(id=membership, tenant_id=tenant, user_id=user, role="owner")
        )
    return {"user": user, "tenant": tenant, "membership": membership}


async def _drop(db: Database, owner: dict[str, str]) -> None:
    async with db.tenant_session(owner["tenant"]) as session:
        await session.execute(delete(customer_secrets))
        await session.execute(delete(memberships).where(memberships.c.id == owner["membership"]))
        await session.execute(delete(tenants).where(tenants.c.tenant_id == owner["tenant"]))
    async with db.identity_session() as session:
        await session.execute(delete(login_tokens).where(login_tokens.c.user_id == owner["user"]))
        await session.execute(delete(users).where(users.c.id == owner["user"]))
    # The application role is revoked DELETE on the audit log; only the
    # operator's role may remove a test's entries.
    engine = create_async_engine(str(get_settings().database_migration_url))
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM audit_log WHERE tenant_id = :t"), {"t": owner["tenant"]}
            )
    finally:
        await engine.dispose()


@pytest.fixture
async def owner(db: Database):
    made = await _owner(db)
    yield made
    await _drop(db, made)


def as_owner(owner: dict[str, str]) -> dict[str, str]:
    return {COOKIE_NAME: issue(owner["user"], get_settings().secret_key)}


def secret_of(owner: dict[str, str]) -> str:
    return f"/v1/console/shops/{owner['tenant']}/customer-secret"


async def _settings(db: Database, tenant: str) -> dict:
    async with db.tenant_session(tenant) as session:
        row = (
            await session.execute(
                text("SELECT config FROM tenants WHERE tenant_id = :t"), {"t": tenant}
            )
        ).one()
    return dict(row.config)


async def _audit(db: Database, tenant: str) -> list:
    async with db.tenant_session(tenant) as session:
        return (
            await session.execute(
                text(
                    "SELECT event_type, outcome, actor, payload FROM audit_log "
                    "WHERE tenant_id = :t ORDER BY sequence"
                ),
                {"t": tenant},
            )
        ).all()


class TestTheCustomerSignInSecret:
    async def test_nothing_is_made_at_first(self, client, owner) -> None:
        read = client.get(secret_of(owner), cookies=as_owner(owner))
        assert read.status_code == 200
        assert read.json()["data"] == {"made_at": None, "made_by": None}

    async def test_made_shown_once_then_only_its_date(self, client, owner, db) -> None:
        made = client.post(secret_of(owner), cookies=as_owner(owner))
        assert made.status_code == 200
        data = made.json()["data"]
        assert data["secret"].startswith("fn_cs_")
        assert data["made_at"]

        read = client.get(secret_of(owner), cookies=as_owner(owner))
        # When, and who (ADR-0058 §6): a person's name, never the secret.
        assert read.json()["data"] == {"made_at": data["made_at"], "made_by": data["made_by"]}
        assert data["made_by"]["role"] == "owner"
        assert data["secret"] not in read.text

        async with db.tenant_session(owner["tenant"]) as session:
            stored = await CustomerSecretRepository(session).secret(owner["tenant"])
        assert stored == data["secret"]

    async def test_a_new_one_stops_the_old_at_once(self, client, owner, db) -> None:
        old = client.post(secret_of(owner), cookies=as_owner(owner)).json()["data"]["secret"]
        new = client.post(secret_of(owner), cookies=as_owner(owner)).json()["data"]["secret"]
        assert new != old

        issued = int(time.time())
        signed_with_old = jwt.encode(
            {"sub": "385", "iat": issued, "exp": issued + 600}, old, algorithm="HS256"
        )
        async with db.tenant_session(owner["tenant"]) as session:
            stored = await CustomerSecretRepository(session).secret(owner["tenant"])
        assert check_customer_pass(signed_with_old, stored).status is PassStatus.INVALID

    async def test_each_make_is_audited_never_the_secret(self, client, owner, db) -> None:
        first = client.post(secret_of(owner), cookies=as_owner(owner)).json()["data"]["secret"]
        second = client.post(secret_of(owner), cookies=as_owner(owner)).json()["data"]["secret"]
        rows = await _audit(db, owner["tenant"])
        assert [r.outcome for r in rows] == ["customer_secret.made", "customer_secret.replaced"]
        assert all(r.actor == owner["user"] for r in rows)
        for row in rows:
            assert first not in str(row.payload)
            assert second not in str(row.payload)

    async def test_a_stranger_cannot_read_or_make_it(self, client, owner) -> None:
        stranger = {COOKIE_NAME: issue(ids.new_id(ids.USER), get_settings().secret_key)}
        assert client.get(secret_of(owner), cookies=stranger).status_code in {403, 404}
        assert client.post(secret_of(owner), cookies=stranger).status_code in {403, 404}

    async def test_nobody_signed_out_can(self, client, owner) -> None:
        assert client.get(secret_of(owner)).status_code == 401
        assert client.post(secret_of(owner)).status_code == 401
