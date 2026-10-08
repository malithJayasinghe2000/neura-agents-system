"""Tenancy against a real PostgreSQL.

Everything here is a property of the *database* rather than of our code, which
is why none of it can be a unit test:

* Row-Level Security actually isolating the four tables tenancy adds. A fake
  store "proving" isolation proves only that the fake filters.
* The authentication bootstrap (ADR-0014) — that a session which has set only
  ``app.api_key_hash`` can read exactly one row of ``api_keys``, no row of any
  other table, and cannot write.
* ``ON CONFLICT DO UPDATE SET x = x + excluded.x`` being an atomic increment, so
  two turns finishing at once cannot lose a count.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).

``ping()`` is asserted first, deliberately: if ``DATABASE_URL`` ever regresses to
the owner or a superuser, every test below passes while isolating nothing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import DBAPIError

from neura_core import Database
from neura_core.errors import AuthenticationError, ForbiddenError
from neura_core.tenancy import keys
from neura_core.tenancy.auth import authenticate
from neura_core.tenancy.keys import ApiKeyKind
from neura_core.tenancy.models import TenantConfig, TenantStatus
from neura_core.tenancy.repository import (
    ApiKeyRepository,
    StoreConnectionRepository,
    TenantRepository,
)
from neura_core.tenancy.schema import api_keys, tenant_stores, tenant_usage, tenants
from neura_core.tenancy.usage import UsageDelta, UsageMeter

pytestmark = pytest.mark.integration

TENANT_A = "tn_itest_tenancy_a"
TENANT_B = "tn_itest_tenancy_b"
DAY = datetime(2026, 8, 2, tzinfo=UTC).date()
KEK = "5RBUEQFtJVKvUmZ2CMwjWSMmMbtLoQxYlYy2FRJHSTA="  # 32 random bytes, base64


@pytest.fixture
async def db():
    database = Database.from_settings()

    # A database that is not running is a skip: not everyone has Docker up.
    # A database connected as a role RLS does not apply to is a FAILURE — a
    # suite that skips its own security checks reports green for the wrong
    # reason (AGENTS.md).
    try:
        reachable = await database.ping()
    except Exception:
        await database.dispose()
        raise
    if not reachable:
        await database.dispose()
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")

    await _purge(database)
    try:
        yield database
    finally:
        await _purge(database)
        await database.dispose()


async def _purge(database: Database) -> None:
    for tenant_id in (TENANT_A, TENANT_B):
        async with database.tenant_session(tenant_id) as session:
            for table in (tenant_usage, tenant_stores, api_keys, tenants):
                await session.execute(delete(table))


async def _make_tenant(database: Database, tenant_id: str, **kwargs):
    async with database.tenant_session(tenant_id) as session:
        return await TenantRepository(session).create(
            tenant_id=tenant_id,
            name=f"Merchant {tenant_id}",
            enabled_agents=["care"],
            **kwargs,
        )


class TestIsolation:
    """ADR-0008's promise, applied to the tables 1.13 adds."""

    async def test_a_tenant_cannot_read_another_tenants_record(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)

        async with db.tenant_session(TENANT_B) as session:
            assert await TenantRepository(session).get(TENANT_A) is None
            assert (await session.execute(select(tenants))).all() == []

    async def test_a_tenant_cannot_read_another_tenants_keys(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            await ApiKeyRepository(session).issue(TENANT_A, scopes=["care:chat:write"])

        async with db.tenant_session(TENANT_B) as session:
            assert await ApiKeyRepository(session).list_for(TENANT_A) == []

    async def test_a_tenant_cannot_write_a_row_belonging_to_another(self, db: Database) -> None:
        """The ``WITH CHECK`` half. Without it, isolation stops leaks and permits
        planting."""
        with pytest.raises(DBAPIError):
            async with db.tenant_session(TENANT_A) as session:
                await session.execute(insert(tenants).values(tenant_id=TENANT_B, name="planted"))

    async def test_usage_rows_are_isolated(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            await UsageMeter(session).record(TENANT_A, "care", UsageDelta(turns=1), on=DAY)

        async with db.tenant_session(TENANT_B) as session:
            totals = await UsageMeter(session).totals(TENANT_A, on=DAY)
            assert totals.turns == 0
            assert (await session.execute(select(tenant_usage))).all() == []

    async def test_every_tenancy_table_is_forced(self, db: Database) -> None:
        """Restates the repository-wide check for these four tables by name, so
        a failure says *which* table lost its policy."""
        async with db.engine.connect() as conn:
            rows = (
                await conn.execute(
                    text("""
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname IN ('tenants','api_keys','tenant_stores','tenant_usage')
                    """)
                )
            ).all()

        assert len(rows) == 4
        assert all(enabled and forced for _, enabled, forced in rows), rows


class TestCredentialBootstrap:
    """ADR-0014 — reading one row before the tenant is known."""

    async def test_it_sees_exactly_the_row_for_the_key_presented(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        await _make_tenant(db, TENANT_B)

        async with db.tenant_session(TENANT_A) as session:
            _, issued_a = await ApiKeyRepository(session).issue(TENANT_A)
        async with db.tenant_session(TENANT_B) as session:
            await ApiKeyRepository(session).issue(TENANT_B)

        async with db.credential_session(issued_a.token_hash) as session:
            visible = (await session.execute(select(api_keys))).all()

        assert len(visible) == 1
        assert visible[0].tenant_id == TENANT_A

    async def test_it_sees_nothing_else_in_the_database(self, db: Database) -> None:
        """The property that makes the widened policy defensible: possessing a
        key discloses that key, and not the tenant behind it."""
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            _, issued = await ApiKeyRepository(session).issue(TENANT_A)
            await UsageMeter(session).record(TENANT_A, "care", UsageDelta(turns=1), on=DAY)

        async with db.credential_session(issued.token_hash) as session:
            assert (await session.execute(select(tenants))).all() == []
            assert (await session.execute(select(tenant_usage))).all() == []
            assert (await session.execute(select(tenant_stores))).all() == []

    async def test_an_unknown_hash_sees_nothing(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            await ApiKeyRepository(session).issue(TENANT_A)

        async with db.credential_session(keys.fingerprint("fn_sk_test_nope")) as session:
            assert (await session.execute(select(api_keys))).all() == []

    async def test_the_bootstrap_transaction_cannot_write(self, db: Database) -> None:
        """``READ ONLY`` makes it structural rather than careful.

        The policy would refuse this row too, so the assertion is on *which*
        refusal: the transaction has to be incapable of writing, not merely
        pointed at rows it may not write.
        """
        with pytest.raises(DBAPIError) as exc:
            async with db.credential_session("any-hash") as session:
                await session.execute(insert(tenants).values(tenant_id=TENANT_A, name="x"))
        assert "read-only transaction" in str(exc.value)

    async def test_an_empty_hash_is_refused_rather_than_matching_nothing(
        self, db: Database
    ) -> None:
        from neura_core.errors import ConfigurationError

        with pytest.raises(ConfigurationError):
            async with db.credential_session(""):
                pass


class TestAuthentication:
    async def test_a_valid_key_yields_its_tenant(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            record, issued = await ApiKeyRepository(session).issue(
                TENANT_A, scopes=["care:chat:write"], name="server"
            )

        caller = await authenticate(db, issued.token)

        assert caller.tenant_id == TENANT_A
        assert caller.scopes == frozenset({"care:chat:write"})
        assert caller.api_key.id == record.id
        assert caller.may_use("care")
        assert not caller.may_use("sell")

    async def test_the_plaintext_is_not_stored_anywhere(self, db: Database) -> None:
        """The whole point of hashing: a database dump cannot be replayed."""
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            _, issued = await ApiKeyRepository(session).issue(TENANT_A)
            rows = (await session.execute(select(api_keys))).all()

        stored = " ".join(str(value) for row in rows for value in row)
        assert issued.token not in stored
        assert issued.token_hash in stored

    async def test_authentication_records_last_used(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            record, issued = await ApiKeyRepository(session).issue(TENANT_A)
        assert record.last_used_at is None

        await authenticate(db, issued.token)

        async with db.tenant_session(TENANT_A) as session:
            refreshed = await ApiKeyRepository(session).get(record.id)
        assert refreshed is not None
        assert refreshed.last_used_at is not None

    async def test_an_unknown_key_is_refused(self, db: Database) -> None:
        unknown = keys.generate()
        with pytest.raises(AuthenticationError):
            await authenticate(db, unknown.token)

    async def test_a_revoked_key_is_refused(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            record, issued = await ApiKeyRepository(session).issue(TENANT_A)
            revoked = await ApiKeyRepository(session).revoke(record.id)
        assert revoked.revoked_at is not None

        with pytest.raises(AuthenticationError):
            await authenticate(db, issued.token)

    async def test_an_expired_key_is_refused(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            _, issued = await ApiKeyRepository(session).issue(
                TENANT_A, expires_at=datetime.now(UTC) - timedelta(seconds=1)
            )

        with pytest.raises(AuthenticationError):
            await authenticate(db, issued.token)

    async def test_a_suspended_tenant_is_refused_with_a_valid_key(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            _, issued = await ApiKeyRepository(session).issue(TENANT_A)
            await TenantRepository(session).set_status(TENANT_A, TenantStatus.SUSPENDED)

        with pytest.raises(ForbiddenError) as exc:
            await authenticate(db, issued.token)
        assert exc.value.code == "TENANT_NOT_ACTIVE"

    async def test_a_public_key_is_locked_to_its_origins(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            _, issued = await ApiKeyRepository(session).issue(
                TENANT_A,
                kind=ApiKeyKind.PUBLIC,
                allowed_origins=["https://shop.example"],
                scopes=["care:chat:write"],
            )

        assert (await authenticate(db, issued.token, origin="https://shop.example")).tenant_id

        with pytest.raises(ForbiddenError) as exc:
            await authenticate(db, issued.token, origin="https://evil.example")
        assert exc.value.code == "ORIGIN_NOT_ALLOWED"

    async def test_a_public_key_cannot_be_issued_without_origins(self, db: Database) -> None:
        from neura_core.errors import ConfigurationError

        await _make_tenant(db, TENANT_A)
        with pytest.raises(ConfigurationError):
            async with db.tenant_session(TENANT_A) as session:
                await ApiKeyRepository(session).issue(TENANT_A, kind=ApiKeyKind.PUBLIC)

    async def test_a_public_key_cannot_be_issued_with_more_than_the_chat_box_uses(
        self, db: Database
    ) -> None:
        """G80: refused when the key is made, where it is a typo, not found
        later in a page where anyone can copy it."""
        from neura_core.errors import ConfigurationError

        await _make_tenant(db, TENANT_A)
        with pytest.raises(ConfigurationError) as exc:
            async with db.tenant_session(TENANT_A) as session:
                await ApiKeyRepository(session).issue(
                    TENANT_A,
                    kind=ApiKeyKind.PUBLIC,
                    allowed_origins=["https://shop.example"],
                    scopes=["care:chat:write", "care:conversations:read"],
                )
        assert "care:conversations:read" in str(exc.value)


class TestUsageMetering:
    async def test_recording_accumulates_into_one_row_per_day(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            meter = UsageMeter(session)
            await meter.record(
                TENANT_A, "care", UsageDelta(turns=1, llm_calls=3, cost_usd=Decimal("0.01")), on=DAY
            )
            await meter.record(
                TENANT_A, "care", UsageDelta(turns=1, llm_calls=2, cost_usd=Decimal("0.02")), on=DAY
            )
            totals = await meter.totals(TENANT_A, on=DAY)

        assert (totals.turns, totals.llm_calls) == (2, 5)
        assert totals.cost_usd == Decimal("0.030000")

    async def test_concurrent_increments_do_not_lose_counts(self, db: Database) -> None:
        """The reason the increment is ``x + excluded.x`` in SQL rather than a
        read-modify-write in Python."""

        async def one_turn() -> None:
            async with db.tenant_session(TENANT_A) as session:
                await UsageMeter(session).record(
                    TENANT_A, "care", UsageDelta(turns=1, cost_usd=Decimal("0.001")), on=DAY
                )

        await asyncio.gather(*(one_turn() for _ in range(20)))

        async with db.tenant_session(TENANT_A) as session:
            totals = await UsageMeter(session).totals(TENANT_A, on=DAY)

        assert totals.turns == 20
        assert totals.cost_usd == Decimal("0.020000")

    async def test_usage_is_attributed_per_agent(self, db: Database) -> None:
        """ "Billed for CARE only" is only true if the rows say which agent."""
        async with db.tenant_session(TENANT_A) as session:
            meter = UsageMeter(session)
            await meter.record(TENANT_A, "care", UsageDelta(turns=2), on=DAY)
            await meter.record(TENANT_A, "sell", UsageDelta(turns=5), on=DAY)
            per_agent = await meter.by_agent(TENANT_A, on=DAY)
            everything = await meter.totals(TENANT_A, on=DAY)

        assert per_agent["care"].turns == 2
        assert per_agent["sell"].turns == 5
        assert everything.turns == 7

    async def test_an_empty_delta_writes_nothing(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            await UsageMeter(session).record(TENANT_A, "care", UsageDelta(), on=DAY)
            assert (await session.execute(select(tenant_usage))).all() == []

    async def test_spend_today_is_what_the_budget_reads(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            meter = UsageMeter(session)
            await meter.record(TENANT_A, "care", UsageDelta(cost_usd=Decimal("1.5")), on=DAY)
            assert await meter.spend_today(TENANT_A, on=DAY) == Decimal("1.500000")


class TestTenantConfiguration:
    async def test_config_round_trips_through_jsonb(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            repository = TenantRepository(session)
            updated = await repository.set_config(
                TENANT_A,
                TenantConfig(
                    daily_cost_usd_hard=Decimal("3.5"),
                    max_tool_calls=2,
                    allowed_tools=frozenset({"search_policies"}),
                ),
            )

        assert updated.config.daily_cost_usd_hard == Decimal("3.5")
        assert updated.config.max_tool_calls == 2
        assert updated.config.allowed_tools == frozenset({"search_policies"})

    async def test_entitlements_are_a_row_not_a_deploy(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            upgraded = await TenantRepository(session).set_enabled_agents(
                TENANT_A, ["care", "sell"]
            )

        assert upgraded.may_use("sell")


class TestStoreCredentials:
    async def test_credentials_are_ciphertext_at_rest(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            store_id = await StoreConnectionRepository(session, kek=KEK).connect(
                TENANT_A,
                platform="generic",
                base_url="https://shop.example/neura/v1",
                credentials={"token": "s3cret-token"},
            )
            rows = (await session.execute(select(tenant_stores))).all()

        stored = " ".join(str(value) for row in rows for value in row)
        assert "s3cret-token" not in stored
        assert store_id.startswith("st_")

    async def test_credentials_decrypt_for_their_own_tenant(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            repository = StoreConnectionRepository(session, kek=KEK)
            store_id = await repository.connect(
                TENANT_A,
                platform="generic",
                base_url="https://shop.example/neura/v1",
                credentials={"token": "s3cret-token"},
            )
            assert await repository.credentials_for(TENANT_A, store_id) == {"token": "s3cret-token"}

    async def test_reconnecting_replaces_rather_than_duplicates(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            repository = StoreConnectionRepository(session, kek=KEK)
            for token in ("first", "second"):
                store_id = await repository.connect(
                    TENANT_A,
                    platform="generic",
                    base_url="https://shop.example/neura/v1",
                    credentials={"token": token},
                )
            connections = await repository.list_for(TENANT_A)
            assert await repository.credentials_for(TENANT_A, store_id) == {"token": "second"}

        assert len(connections) == 1

    async def test_listing_never_returns_a_secret(self, db: Database) -> None:
        await _make_tenant(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            repository = StoreConnectionRepository(session, kek=KEK)
            await repository.connect(
                TENANT_A,
                platform="generic",
                base_url="https://shop.example/neura/v1",
                credentials={"token": "s3cret-token"},
            )
            listed = await repository.list_for(TENANT_A)

        assert listed[0]["platform"] == "generic"
        assert "credentials" not in listed[0]
        assert "wrapped_dek" not in listed[0]
