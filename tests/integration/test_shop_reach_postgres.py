"""G78 (a) against a real database: every later call to a shop is checked too.

The owner's Check and Connect checked the shop's address once. Every chat turn,
Sync now, the suggestions and the AI connection open the shop through
``StoreDirectory``, which connected with no check at all: a name that passed
once could be pointed at one of our own addresses the next day, and NEURA's
server would call it with the shop token attached.
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from neura_api.stores import StoreDirectory
from neura_core import Database, get_settings, ids, load_env
from neura_core.tenancy import StoreConnectionRepository, tenant_stores
from neura_core.tenancy.schema import tenants
from tests.reach import answer_names, private_listener

pytestmark = pytest.mark.integration


@pytest.fixture
async def db():
    load_env()
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    yield database
    await database.dispose()


async def test_a_chat_turn_never_reaches_a_shop_name_now_pointing_inside(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEURA_ENV", "production")
    get_settings.cache_clear()
    tenant = ids.new_id(ids.TENANT)
    try:
        async with private_listener() as inside:
            async with db.tenant_session(tenant) as session:
                await session.execute(tenants.insert().values(tenant_id=tenant, name="Reach test"))
                await StoreConnectionRepository(session).connect(
                    tenant,
                    platform="generic",
                    base_url=f"https://shop.rebind.example:{inside.port}/neura/v1",
                    credentials={"token": "the-shop-token"},
                )
            # Connected while the name was public; today it answers one of ours.
            answer_names(monkeypatch, {"shop.rebind.example": [["127.0.0.1"]]})

            with pytest.raises(Exception):  # noqa: B017 - the shop cannot be reached
                await StoreDirectory(db).connect(tenant)

            assert inside.hits == [], "a chat turn connected to a private address"
    finally:
        get_settings.cache_clear()
        async with db.tenant_session(tenant) as session:
            await session.execute(delete(tenant_stores).where(tenant_stores.c.tenant_id == tenant))
            await session.execute(delete(tenants).where(tenants.c.tenant_id == tenant))
