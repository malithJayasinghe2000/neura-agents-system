"""ADR-0052 over HTTP and against real RLS: the shop owner connects their own shop.

The shop is the reference store, reached through the registry exactly as the
worker reaches a real one; only the transport is in-process. The check's job is
run by the real handler, through the real queue.

What these tests hold the build to:

* a token is returned **once**, by the response that made it, and never again:
  not by the page, not by a check result, not in the table it is sealed in;
* *Connect* is allowed only after a clean check of **that** address, made after
  **that** token;
* a new token changes what NEURA sends, while the bridge still holds the old one
  (G49), so the next check says the token is refused;
* every change of how NEURA reaches a shop is in the audit log, with no token.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from neura_adapters.generic.adapter import GenericAdapter
from neura_adapters.generic.reference import ReferenceStore
from neura_api.jobs import SHOP_CHECK, JobRunner, ShopCheckHandler
from neura_api.main import create_app
from neura_commerce import registry
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import login_tokens, memberships, users
from neura_core.jobs import job_queue
from neura_core.tenancy import (
    StoreConnectionRepository,
    shop_checks,
    shop_tokens,
    tenant_stores,
)

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


@pytest.fixture
async def owner(db: Database):
    """A shop with an owner and nothing connected."""
    user = ids.new_id(ids.USER)
    tenant = ids.new_id(ids.TENANT)
    membership = ids.new_id(ids.MEMBERSHIP)
    async with db.identity_session() as session:
        await session.execute(users.insert().values(id=user, email=f"{user}@example.com"))
    async with db.tenant_session(tenant) as session:
        await session.execute(
            memberships.insert().values(id=membership, tenant_id=tenant, user_id=user, role="owner")
        )

    yield {"user": user, "tenant": tenant}

    async with db.tenant_session(tenant) as session:
        for table in (shop_checks, shop_tokens, tenant_stores, job_queue):
            await session.execute(delete(table).where(table.c.tenant_id == tenant))
        await session.execute(delete(memberships).where(memberships.c.id == membership))
    async with db.identity_session() as session:
        await session.execute(delete(login_tokens).where(login_tokens.c.user_id == user))
        await session.execute(delete(users).where(users.c.id == user))
    # The application role is revoked DELETE on the audit log; only the
    # operator's role may remove a test's entries.
    engine = create_async_engine(str(get_settings().database_migration_url))
    try:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM audit_log WHERE tenant_id = :t"), {"t": tenant})
    finally:
        await engine.dispose()


@pytest.fixture
def bridge():
    """The reference store, reached through the registry like any shop."""
    store = ReferenceStore(token="the-developer-has-not-put-it-in-yet")
    registry.discover()
    original = registry._adapters["generic"]  # restored below

    def factory(**config):
        return GenericAdapter(transport=store.transport(), **config)

    registry.register("generic", factory, original.capabilities)
    try:
        yield store
    finally:
        registry._adapters["generic"] = original


def as_owner(owner: dict) -> dict[str, str]:
    return {COOKIE_NAME: issue(owner["user"], get_settings().secret_key)}


def shop(owner: dict) -> str:
    return f"/v1/console/shops/{owner['tenant']}"


async def run_checks(db: Database, tenant: str) -> None:
    runner = JobRunner(db)
    runner.register(SHOP_CHECK, ShopCheckHandler(production=False))
    await runner.run_tenant(tenant)


async def check_now(client, db, owner, what: dict) -> dict:
    started = client.post(f"{shop(owner)}/checks", json=what, cookies=as_owner(owner))
    assert started.status_code == 202, started.text
    await run_checks(db, owner["tenant"])
    read = client.get(
        f"{shop(owner)}/checks/{started.json()['data']['check']['id']}", cookies=as_owner(owner)
    )
    return read.json()["data"]["check"]


class TestTheToken:
    async def test_it_is_returned_once_and_never_again(self, client, db, owner) -> None:
        made = client.post(f"{shop(owner)}/token", cookies=as_owner(owner))
        assert made.status_code == 200, made.text
        token = made.json()["data"]["token"]
        assert token.startswith("fn_st_")

        page = client.get(f"{shop(owner)}/store", cookies=as_owner(owner))
        assert page.json()["data"]["connect"]["token_made_at"]
        assert token not in page.text

        async with db.tenant_session(owner["tenant"]) as session:
            sealed = (await session.execute(select(shop_tokens))).first()
        assert sealed is not None and token not in sealed.credentials

    async def test_a_check_needs_the_token_first(self, client, owner) -> None:
        early = client.post(
            f"{shop(owner)}/checks",
            json={"address": "https://store.example.com/neura/v1"},
            cookies=as_owner(owner),
        )
        assert early.status_code == 409
        assert early.json()["error"]["code"] == "NO_SHOP_TOKEN"

    async def test_another_person_cannot_make_one(self, client, owner) -> None:
        stranger = {COOKIE_NAME: issue(ids.new_id(ids.USER), get_settings().secret_key)}
        refused = client.post(f"{shop(owner)}/token", cookies=stranger)
        assert refused.status_code in (403, 404)


class TestConnect:
    async def test_only_after_a_clean_check_of_that_address(
        self, client, db, owner, bridge
    ) -> None:
        address = bridge.base_url()
        token = client.post(f"{shop(owner)}/token", cookies=as_owner(owner)).json()["data"]["token"]

        early = client.post(
            f"{shop(owner)}/connect", json={"address": address}, cookies=as_owner(owner)
        )
        assert early.json()["error"]["code"] == "CHECK_FIRST"

        refused = await check_now(client, db, owner, {"address": address})
        assert refused["status"] == "done"
        assert refused["result"]["cause"] == "token_refused"
        assert not refused["result"]["conformant"]
        assert (
            client.post(
                f"{shop(owner)}/connect", json={"address": address}, cookies=as_owner(owner)
            ).status_code
            == 409
        )

        bridge.token = token  # the developer puts it in the bridge's settings
        passed = await check_now(client, db, owner, {"address": address})
        assert passed["result"]["conformant"], passed["result"]["text"]
        assert token not in str(passed)

        elsewhere = client.post(
            f"{shop(owner)}/connect",
            json={"address": "https://other.example.com/neura/v1"},
            cookies=as_owner(owner),
        )
        assert elsewhere.json()["error"]["code"] == "CHECK_FIRST"

        connected = client.post(
            f"{shop(owner)}/connect", json={"address": address}, cookies=as_owner(owner)
        )
        assert connected.status_code == 200, connected.text

        view = client.get(f"{shop(owner)}/store", cookies=as_owner(owner)).json()["data"]
        assert view["connected"] and view["connect"] is None
        store = view["stores"][0]
        # The clean check that allowed it is the connection's first check.
        assert store["last_check"]["id"] == passed["id"]
        assert store["token_set_at"]

        async with db.tenant_session(owner["tenant"]) as session:
            assert (await session.execute(select(shop_tokens))).first() is None
            kept = await StoreConnectionRepository(session).credentials_for(
                owner["tenant"], store["id"]
            )
            sync = (
                await session.execute(
                    select(job_queue.c.kind).where(job_queue.c.tenant_id == owner["tenant"])
                )
            ).all()
        assert kept == {"token": token}
        assert "sync.store" in {row.kind for row in sync}

    async def test_one_check_at_a_time(self, client, owner, bridge) -> None:
        client.post(f"{shop(owner)}/token", cookies=as_owner(owner))
        what = {"address": bridge.base_url()}
        first = client.post(f"{shop(owner)}/checks", json=what, cookies=as_owner(owner))
        again = client.post(f"{shop(owner)}/checks", json=what, cookies=as_owner(owner))
        assert first.json()["data"]["check"]["id"] == again.json()["data"]["check"]["id"]

    async def test_an_address_that_is_not_a_web_address_is_refused(self, client, owner) -> None:
        client.post(f"{shop(owner)}/token", cookies=as_owner(owner))
        refused = client.post(
            f"{shop(owner)}/checks", json={"address": "ftp://nowhere"}, cookies=as_owner(owner)
        )
        assert refused.status_code == 400
        assert refused.json()["error"]["code"] == "ADDRESS_INVALID"


class TestANewToken:
    async def test_the_bridge_holding_the_old_one_is_refused_until_it_has_the_new(
        self, client, db, owner, bridge
    ) -> None:
        address = bridge.base_url()
        bridge.token = client.post(f"{shop(owner)}/token", cookies=as_owner(owner)).json()["data"][
            "token"
        ]
        await check_now(client, db, owner, {"address": address})
        store_id = client.post(
            f"{shop(owner)}/connect", json={"address": address}, cookies=as_owner(owner)
        ).json()["data"]["id"]

        replaced = client.post(f"{shop(owner)}/store/{store_id}/token", cookies=as_owner(owner))
        assert replaced.status_code == 200, replaced.text
        new = replaced.json()["data"]["token"]
        assert new != bridge.token

        stale = await check_now(client, db, owner, {"store_id": store_id})
        assert stale["result"]["cause"] == "token_refused"  # G49: the bridge has the old one

        bridge.token = new
        fresh = await check_now(client, db, owner, {"store_id": store_id})
        assert fresh["result"]["conformant"]

        page = client.get(f"{shop(owner)}/store", cookies=as_owner(owner))
        assert new not in page.text

        async with db.tenant_session(owner["tenant"]) as session:
            audit = (
                await session.execute(
                    text(
                        "SELECT outcome, actor, payload::text AS payload FROM audit_log "
                        "WHERE tenant_id = :t ORDER BY sequence"
                    ),
                    {"t": owner["tenant"]},
                )
            ).all()
        assert [row.outcome for row in audit] == [
            "shop_token.made",
            "store.connected",
            "shop_token.replaced",
        ]
        assert all(row.actor == owner["user"] for row in audit)
        assert not any("fn_st_" in row.payload for row in audit)

    async def test_a_connected_shop_cannot_make_a_waiting_token(
        self, client, db, owner, bridge
    ) -> None:
        address = bridge.base_url()
        bridge.token = client.post(f"{shop(owner)}/token", cookies=as_owner(owner)).json()["data"][
            "token"
        ]
        await check_now(client, db, owner, {"address": address})
        client.post(f"{shop(owner)}/connect", json={"address": address}, cookies=as_owner(owner))

        again = client.post(f"{shop(owner)}/token", cookies=as_owner(owner))
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "ALREADY_CONNECTED"
