"""ADR-0054 over HTTP and against real RLS: the shop owner switches practice mode.

What these tests hold the build to:

* **Go live** and **Back to practice mode** change the mode Home reads, and
  nothing else in the shop's settings: not a per-intent practice list, not a
  key a newer deployment wrote (§5);
* every change is in the audit log, naming who and the mode before and after;
  pressing for the mode the shop is already in records nothing;
* a stranger cannot switch a shop, and a wrong value is refused with a 400.
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


async def _owner(db: Database, *, mode: TurnMode) -> dict[str, str]:
    """A shop in ``mode`` with one owner, and two settings the switch must keep:
    a per-intent practice list and a key this deployment does not know."""
    user = ids.new_id(ids.USER)
    tenant = ids.new_id(ids.TENANT)
    membership = ids.new_id(ids.MEMBERSHIP)
    async with db.identity_session() as session:
        await session.execute(users.insert().values(id=user, email=f"{user}@example.com"))
    async with db.tenant_session(tenant) as session:
        await TenantRepository(session).create(
            tenant_id=tenant,
            name="Mode Test Shop",
            enabled_agents=["care"],
            config=TenantConfig(mode=mode, shadow_intents=frozenset({"policy_qa"})),
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
async def practising(db: Database):
    owner = await _owner(db, mode=TurnMode.SHADOW)
    yield owner
    await _drop(db, owner)


def as_owner(owner: dict[str, str]) -> dict[str, str]:
    return {COOKIE_NAME: issue(owner["user"], get_settings().secret_key)}


def mode_of(owner: dict[str, str]) -> str:
    return f"/v1/console/shops/{owner['tenant']}/mode"


def withheld(client: TestClient, owner: dict[str, str]) -> bool:
    """What Home reads to say *Practice mode is on*."""
    usage = client.get(
        f"/v1/console/shops/{owner['tenant']}/usage?period=7d", cookies=as_owner(owner)
    )
    return bool(usage.json()["data"]["withheld"])


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


class TestTheSwitch:
    async def test_go_live_then_back_to_practice(self, client, db, practising) -> None:
        assert withheld(client, practising)

        live = client.put(mode_of(practising), json={"mode": "live"}, cookies=as_owner(practising))
        assert live.status_code == 200
        assert live.json()["data"] == {"mode": "live", "withheld": False, "changed": True}
        assert not withheld(client, practising)

        back = client.put(
            mode_of(practising), json={"mode": "shadow"}, cookies=as_owner(practising)
        )
        assert back.status_code == 200
        assert back.json()["data"] == {"mode": "shadow", "withheld": True, "changed": True}
        assert withheld(client, practising)

    async def test_only_the_mode_changes(self, client, db, practising) -> None:
        """§5: a whole-settings write would drop the key this deployment does not
        know, and a per-intent list is not the switch's to touch."""
        client.put(mode_of(practising), json={"mode": "live"}, cookies=as_owner(practising))

        settings = await _settings(db, practising["tenant"])
        assert settings["mode"] == "live"
        assert settings["shadow_intents"] == ["policy_qa"]
        assert settings["from_a_newer_neura"] == 7

    async def test_every_change_is_audited_and_a_repeat_is_not(
        self, client, db, practising
    ) -> None:
        cookies = as_owner(practising)
        client.put(mode_of(practising), json={"mode": "live"}, cookies=cookies)
        again = client.put(mode_of(practising), json={"mode": "live"}, cookies=cookies)
        client.put(mode_of(practising), json={"mode": "shadow"}, cookies=cookies)

        assert again.json()["data"]["changed"] is False
        audit = await _audit(db, practising["tenant"])
        assert [row.outcome for row in audit] == ["mode.live", "mode.practice"]
        assert all(row.event_type == "config.change" for row in audit)
        assert all(row.actor == practising["user"] for row in audit)
        assert audit[0].payload == {"from": "shadow", "to": "live"}
        assert audit[1].payload == {"from": "live", "to": "shadow"}


class TestWhoAndWhat:
    async def test_a_stranger_cannot_switch_a_shop(self, client, db, practising) -> None:
        stranger = await _owner(db, mode=TurnMode.LIVE)
        try:
            refused = client.put(
                mode_of(practising), json={"mode": "live"}, cookies=as_owner(stranger)
            )
            assert refused.status_code == 404
            assert withheld(client, practising)
        finally:
            await _drop(db, stranger)

    async def test_no_session_no_switch(self, client, db, practising) -> None:
        refused = client.put(mode_of(practising), json={"mode": "live"})
        assert refused.status_code == 401
        assert withheld(client, practising)

    @pytest.mark.parametrize(
        "body", [{"mode": "supervised"}, {"mode": "LIVE"}, {}, {"mode": "live", "extra": 1}]
    )
    async def test_a_wrong_value_is_refused(self, client, db, practising, body) -> None:
        refused = client.put(mode_of(practising), json=body, cookies=as_owner(practising))
        assert refused.status_code == 400
        assert withheld(client, practising)
