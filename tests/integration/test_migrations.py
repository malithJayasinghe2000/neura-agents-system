"""The schema itself.

Two checks, both of which exist because the failure they catch is invisible
until it is expensive.

**Drift.** The SQLAlchemy tables and the migrations must describe the same
schema. When they diverge, the application queries columns the database does not
have — in production, after a deploy, having passed every test that used a
fixture instead of a database.

**Missing policies.** ADR-0008 says a table with a ``tenant_id`` and no
Row-Level Security policy is a hole, and puts that on the migration review
checklist. A checklist is a hope. This is the check.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from neura_core import Database

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def db():
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    yield database
    await database.dispose()


def test_models_and_migrations_agree() -> None:
    """``alembic check`` must find nothing to generate.

    Equivalent to the OpenAPI drift test in ``test_commerce.py``: a contract
    that silently diverges from its implementation is worse than no contract,
    because everyone downstream trusts the stale one.
    """
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if "Target database is not up to date" in result.stdout + result.stderr:
        pytest.skip("migrations not applied — run `make migrate`")

    assert result.returncode == 0, (
        'the models and the migrations disagree — run `make revision M="..."`:\n'
        f"{result.stdout}\n{result.stderr}"
    )


class TestEveryTenantTableIsProtected:
    async def test_no_tenant_table_lacks_a_policy(self, db: Database) -> None:
        """Every table with a ``tenant_id`` must have RLS enabled, forced, and a policy.

        All three parts are load-bearing:

        * *enabled* without a policy denies everything — visible immediately.
        * *a policy* without *enabled* filters nothing — invisible, and a breach.
        * *enabled* without *forced* exempts the table owner. Since migrations
          run as the owner and a careless deployment might too, this is the one
          most likely to be wrong while looking right.
        """
        async with db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("""
                    SELECT c.relname,
                           c.relrowsecurity,
                           c.relforcerowsecurity,
                           (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relkind = 'r'
                      AND EXISTS (
                          SELECT 1 FROM information_schema.columns col
                          WHERE col.table_name = c.relname
                            AND col.table_schema = 'public'
                            AND col.column_name = 'tenant_id'
                      )
                    """)
                )
            ).all()

        assert rows, "no tenant-scoped tables found — has `make migrate` been run?"

        unprotected = [
            f"{name}: rls={enabled} forced={forced} policies={policies}"
            for name, enabled, forced, policies in rows
            if not (enabled and forced and policies)
        ]
        assert not unprotected, (
            "tables carry a tenant_id but are not isolated (ADR-0008):\n" + "\n".join(unprotected)
        )
