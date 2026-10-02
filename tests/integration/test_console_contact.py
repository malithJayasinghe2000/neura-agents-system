"""ADR-0055 §5 over HTTP and against real RLS: the shop's contact details.

What these tests hold the build to:

* the owner reads and saves an email and a phone, both optional, and an empty
  field clears one;
* only those two keys change in the shop's settings (the mode, a per-intent
  list and a key a newer deployment wrote are kept);
* a wrong email or phone is refused with a 400, before anything is written;
* every change is in the audit log, naming which fields changed and never their
  values; a save that changes nothing records nothing;
* a stranger cannot read or change another shop's details.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import create_async_engine

from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import login_tokens, memberships, users
from neura_core.tenancy import TenantConfig, TenantRepository, TurnMode
from neura_core.tenancy.schema import tenants

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
            name="Contact Test Shop",
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


def contact_of(owner: dict[str, str]) -> str:
    return f"/v1/console/shops/{owner['tenant']}/contact"


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


class TestContactDetails:
    async def test_nothing_is_set_at_first(self, client, owner) -> None:
        read = client.get(contact_of(owner), cookies=as_owner(owner))
        assert read.status_code == 200
        assert read.json()["data"] == {
            "email": None,
            "phone": None,
            # The sentence a handed-over shopper reads now, made by the server.
            "handover": "I can't help with this here. Please contact our store.",
        }

    async def test_saved_then_read_back(self, client, owner) -> None:
        saved = client.put(
            contact_of(owner),
            json={"email": "  hello@yourshop.example ", "phone": "+94 11 234 5678"},
            cookies=as_owner(owner),
        )
        assert saved.status_code == 200
        assert saved.json()["data"] == {
            "email": "hello@yourshop.example",
            "phone": "+94 11 234 5678",
            "handover": "I can't help with this here. Please contact our store: "
            "hello@yourshop.example, +94 11 234 5678.",
        }
        read = client.get(contact_of(owner), cookies=as_owner(owner))
        assert read.json()["data"] == saved.json()["data"]

    async def test_an_empty_field_clears_it(self, client, owner) -> None:
        cookies = as_owner(owner)
        client.put(
            contact_of(owner),
            json={"email": "hello@yourshop.example", "phone": "+94 11 234 5678"},
            cookies=cookies,
        )
        cleared = client.put(
            contact_of(owner),
            json={"email": "hello@yourshop.example", "phone": ""},
            cookies=cookies,
        )
        assert cleared.json()["data"]["email"] == "hello@yourshop.example"
        assert cleared.json()["data"]["phone"] is None

    async def test_only_the_contact_keys_change(self, client, db, owner) -> None:
        client.put(
            contact_of(owner),
            json={"email": "hello@yourshop.example", "phone": "+94 11 234 5678"},
            cookies=as_owner(owner),
        )
        settings = await _settings(db, owner["tenant"])
        assert settings["contact_email"] == "hello@yourshop.example"
        assert settings["contact_phone"] == "+94 11 234 5678"
        assert settings["mode"] == "shadow"
        assert settings["shadow_intents"] == ["policy_qa"]
        assert settings["from_a_newer_neura"] == 7

    async def test_changes_are_audited_by_field_never_by_value(self, client, db, owner) -> None:
        cookies = as_owner(owner)
        body = {"email": "hello@yourshop.example", "phone": "+94 11 234 5678"}
        client.put(contact_of(owner), json=body, cookies=cookies)
        again = client.put(contact_of(owner), json=body, cookies=cookies)
        client.put(contact_of(owner), json={**body, "phone": ""}, cookies=cookies)

        assert again.status_code == 200
        audit = await _audit(db, owner["tenant"])
        assert [row.outcome for row in audit] == ["contact.changed", "contact.changed"]
        assert all(row.event_type == "config.change" for row in audit)
        assert all(row.actor == owner["user"] for row in audit)
        assert audit[0].payload == {"fields": ["email", "phone"]}
        assert audit[1].payload == {"fields": ["phone"]}
        assert not any("hello@" in str(row.payload) or "234" in str(row.payload) for row in audit)


class TestWhoAndWhat:
    @pytest.mark.parametrize(
        "body",
        [
            {"email": "not an email", "phone": ""},
            {"email": "a@b", "phone": ""},
            {"email": "", "phone": "call us!"},
            {"email": "", "phone": "12"},
            {"email": "", "phone": "+94 11 234 5678", "extra": 1},
            {"email": "x" * 250 + "@shop.example", "phone": ""},
        ],
    )
    async def test_a_wrong_value_is_refused_before_anything_is_written(
        self, client, db, owner, body
    ) -> None:
        refused = client.put(contact_of(owner), json=body, cookies=as_owner(owner))
        assert refused.status_code == 400
        settings = await _settings(db, owner["tenant"])
        assert "contact_email" not in settings and "contact_phone" not in settings

    async def test_a_stranger_cannot_read_or_change_a_shop(self, client, db, owner) -> None:
        stranger = await _owner(db)
        try:
            cookies = as_owner(stranger)
            assert client.get(contact_of(owner), cookies=cookies).status_code == 404
            refused = client.put(
                contact_of(owner),
                json={"email": "evil@example.com", "phone": ""},
                cookies=cookies,
            )
            assert refused.status_code == 404
        finally:
            await _drop(db, stranger)

    async def test_no_session_no_details(self, client, owner) -> None:
        assert client.get(contact_of(owner)).status_code == 401
