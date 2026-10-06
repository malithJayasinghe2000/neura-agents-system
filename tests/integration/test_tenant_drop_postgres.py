"""`make tenant-drop` removes everything a shop left in the database (G76).

Its list of tables was written before the shop token, the full check, the
pairings, the owner's choices and practice-mode evidence existed, and nothing
noticed: no table has a foreign key to `tenants`, so the drop succeeded and
left those rows with no shop to belong to.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from neura_core import Database, ids, load_env
from neura_core.tenancy import ShopCheckRepository, ShopTokenRepository
from neura_core.tenancy.schema import shop_checks, shop_tokens, tenants

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from widget_check import deprovision

pytestmark = pytest.mark.integration

#: NEURA may only add to the audit log (S10), so a drop leaves it, on purpose.
KEPT_ON_PURPOSE = {"audit_log"}


@pytest.fixture
async def db():
    load_env()
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    yield database
    await database.dispose()


async def test_a_dropped_shop_leaves_no_token_and_no_check(db: Database) -> None:
    tenant = ids.new_id(ids.TENANT)
    async with db.tenant_session(tenant) as session:
        await session.execute(tenants.insert().values(tenant_id=tenant, name="Drop test"))
        await ShopTokenRepository(session).make(tenant, made_by="test")
        await ShopCheckRepository(session).create(
            tenant, address="https://shop.example/neura/v1", store_id=None, requested_by="test"
        )

    await deprovision(tenant)

    async with db.tenant_session(tenant) as session:
        left = {
            table.name: (
                await session.execute(
                    select(func.count()).select_from(table).where(table.c.tenant_id == tenant)
                )
            ).scalar_one()
            for table in (shop_tokens, shop_checks, tenants)
        }
    assert left == {"shop_tokens": 0, "shop_checks": 0, "tenants": 0}


async def test_the_drop_knows_every_table_that_holds_a_shop(db: Database) -> None:
    """A new table with a `tenant_id` fails this until the drop knows it."""
    from widget_check import tenant_tables

    async with db.identity_session() as session:
        rows = await session.execute(
            text(
                "select table_name from information_schema.columns "
                "where column_name = 'tenant_id' and table_schema = 'public'"
            )
        )
        in_database = {str(row[0]) for row in rows} - KEPT_ON_PURPOSE

    assert {table.name for table in tenant_tables()} == in_database
