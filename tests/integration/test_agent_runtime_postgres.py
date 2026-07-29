"""The checkpointer and the audit log, against a real PostgreSQL.

Both exist for properties a fake cannot demonstrate:

* A conversation **resumes** after the process holding it dies. That is the
  whole reason ADR-0004 specifies a PostgreSQL checkpointer, and it can only be
  shown by writing state, throwing the runtime away, and reading it back.
* The audit chain **detects tampering**. A hash chain that has never been
  attacked is a hash chain nobody has checked.
* Neither is readable across tenants. LangGraph's own checkpointer has no
  ``tenant_id`` at all, which is exactly why this one was written instead.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_agent_core.graph.checkpointer import PostgresCheckpointer
from neura_core import Database, get_settings

pytestmark = pytest.mark.integration

TENANT_A = "tn_rt_a"
TENANT_B = "tn_rt_b"
THREAD = "cnv_rt_1"


def owner_engine():
    """A connection with the privileges an operator has and the app does not.

    Needed for two things the application role is deliberately unable to do:
    clean up the append-only audit log after a test, and tamper with it on
    purpose. If this fixture ever stops needing elevated privilege, the
    append-only guarantee has quietly been lost.
    """
    return create_async_engine(str(get_settings().database_migration_url))


@pytest.fixture
async def db():
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")

    yield database

    engine = owner_engine()
    async with engine.begin() as conn:
        for table in ("agent_checkpoint_writes", "agent_checkpoints", "audit_log"):
            # Table name is interpolated from a fixed tuple above, never input.
            await conn.execute(
                text(f"DELETE FROM {table} WHERE tenant_id = ANY(:t)"),  # noqa: S608
                {"t": [TENANT_A, TENANT_B]},
            )
    await engine.dispose()
    await database.dispose()


def _checkpoint(checkpoint_id: str) -> dict:
    return {
        "v": 1,
        "id": checkpoint_id,
        "ts": "2026-07-28T00:00:00+00:00",
        "channel_values": {"message": "where is my order?"},
        "channel_versions": {},
        "versions_seen": {},
    }


def _config(thread: str = THREAD) -> dict:
    return {"configurable": {"thread_id": thread, "checkpoint_ns": ""}}


class TestCheckpointing:
    async def test_a_conversation_survives_the_process_that_started_it(self, db: Database) -> None:
        """The point of ADR-0004's checkpointer: a deploy mid-turn does not lose
        the shopper's conversation."""
        async with db.tenant_session(TENANT_A) as session:
            saver = PostgresCheckpointer(session, TENANT_A)
            await saver.aput(_config(), _checkpoint("chk_1"), {"source": "loop"}, {})

        # A different session and a different saver instance — as far as this
        # test is concerned, a different process.
        async with db.tenant_session(TENANT_A) as session:
            restored = await PostgresCheckpointer(session, TENANT_A).aget_tuple(_config())

        assert restored is not None
        assert restored.checkpoint["channel_values"]["message"] == "where is my order?"

    async def test_the_newest_checkpoint_is_the_one_resumed(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            saver = PostgresCheckpointer(session, TENANT_A)
            await saver.aput(_config(), _checkpoint("chk_1"), {}, {})
            await saver.aput(_config(), _checkpoint("chk_2"), {}, {})

            restored = await saver.aget_tuple(_config())

        assert restored is not None
        assert restored.config["configurable"]["checkpoint_id"] == "chk_2"

    async def test_writing_the_same_checkpoint_twice_is_a_no_op(self, db: Database) -> None:
        """A node retried after a transient failure writes the same id again."""
        async with db.tenant_session(TENANT_A) as session:
            saver = PostgresCheckpointer(session, TENANT_A)
            await saver.aput(_config(), _checkpoint("chk_1"), {}, {})
            await saver.aput(_config(), _checkpoint("chk_1"), {}, {})

            count = await session.scalar(
                text("SELECT count(*) FROM agent_checkpoints WHERE tenant_id = :t"),
                {"t": TENANT_A},
            )

        assert count == 1

    async def test_one_tenant_cannot_read_another_tenants_conversation(self, db: Database) -> None:
        """The reason this checkpointer exists instead of LangGraph's — theirs
        has no tenant_id, so this could not even be asked."""
        async with db.tenant_session(TENANT_A) as session:
            await PostgresCheckpointer(session, TENANT_A).aput(
                _config(), _checkpoint("chk_1"), {}, {}
            )

        async with db.tenant_session(TENANT_B) as session:
            # Same thread id, different tenant. Nothing.
            assert await PostgresCheckpointer(session, TENANT_B).aget_tuple(_config()) is None

    async def test_history_is_listed_newest_first(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            saver = PostgresCheckpointer(session, TENANT_A)
            for checkpoint_id in ("chk_1", "chk_2", "chk_3"):
                await saver.aput(_config(), _checkpoint(checkpoint_id), {}, {})

            ids = [t.config["configurable"]["checkpoint_id"] async for t in saver.alist(_config())]

        assert ids == ["chk_3", "chk_2", "chk_1"]

    async def test_a_thread_can_be_erased(self, db: Database) -> None:
        """Part of the deletion fan-out: a DSAR that clears the transcript but
        leaves the working state has deleted nothing."""
        async with db.tenant_session(TENANT_A) as session:
            saver = PostgresCheckpointer(session, TENANT_A)
            await saver.aput(_config(), _checkpoint("chk_1"), {}, {})
            await saver.adelete_thread(THREAD)

            assert await saver.aget_tuple(_config()) is None


class TestAuditChain:
    async def test_entries_chain_and_verify(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            log = PostgresAuditLog(session)
            for outcome in ("allow", "reject", "escalate"):
                await log.record(
                    AuditEntry(
                        tenant_id=TENANT_A,
                        event_type=AuditEvent.TOOL_DECISION,
                        actor="policy",
                        outcome=outcome,
                        conversation_id=THREAD,
                        payload={"tool": "get_order_status"},
                    )
                )

            intact, broken = await log.verify(TENANT_A)

        assert intact is True
        assert broken is None

    async def test_tampering_is_detected(self, db: Database) -> None:
        """A hash chain nobody has attacked is a hash chain nobody has checked.

        This edits a row directly in SQL — which the application role is not
        even granted the privilege to do — and confirms verification notices.
        """
        async with db.tenant_session(TENANT_A) as session:
            log = PostgresAuditLog(session)
            for outcome in ("allow", "reject", "allow"):
                await log.record(
                    AuditEntry(
                        tenant_id=TENANT_A,
                        event_type=AuditEvent.TOOL_DECISION,
                        actor="policy",
                        outcome=outcome,
                        conversation_id=THREAD,
                    )
                )

        # Rewrite history as a privileged operator would have to.
        engine = owner_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE audit_log SET outcome = 'allow' WHERE tenant_id = :t AND sequence = 2"
                ),
                {"t": TENANT_A},
            )
        await engine.dispose()

        async with db.tenant_session(TENANT_A) as session:
            intact, broken = await PostgresAuditLog(session).verify(TENANT_A)

        assert intact is False
        assert broken is not None

    async def test_deleting_an_entry_is_detected(self, db: Database) -> None:
        """The subtler attack: not altering a record, but removing one."""
        async with db.tenant_session(TENANT_A) as session:
            log = PostgresAuditLog(session)
            for outcome in ("allow", "reject", "allow"):
                await log.record(
                    AuditEntry(
                        tenant_id=TENANT_A,
                        event_type=AuditEvent.TOOL_DECISION,
                        actor="policy",
                        outcome=outcome,
                    )
                )

        engine = owner_engine()
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM audit_log WHERE tenant_id = :t AND sequence = 2"),
                {"t": TENANT_A},
            )
        await engine.dispose()

        async with db.tenant_session(TENANT_A) as session:
            intact, _ = await PostgresAuditLog(session).verify(TENANT_A)

        assert intact is False

    async def test_the_application_role_cannot_rewrite_the_log(self, db: Database) -> None:
        """Append-only, enforced by privilege rather than by convention.

        The hash chain makes tampering *detectable*; this makes it require a
        role the serving process does not have. Both, because either alone is
        weaker than it sounds.
        """
        async with db.tenant_session(TENANT_A) as session:
            await PostgresAuditLog(session).record(
                AuditEntry(
                    tenant_id=TENANT_A,
                    event_type=AuditEvent.TOOL_DECISION,
                    actor="policy",
                    outcome="allow",
                )
            )

        with pytest.raises(Exception, match=r"permission denied|denied for table"):
            async with db.tenant_session(TENANT_A) as session:
                await session.execute(
                    text("UPDATE audit_log SET outcome = 'x' WHERE tenant_id = :t"),
                    {"t": TENANT_A},
                )

    async def test_one_tenant_cannot_read_anothers_audit_log(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            await PostgresAuditLog(session).record(
                AuditEntry(
                    tenant_id=TENANT_A,
                    event_type=AuditEvent.ESCALATION,
                    actor="graph",
                    outcome="escalated",
                )
            )

        async with db.tenant_session(TENANT_B) as session:
            assert await PostgresAuditLog(session).count(TENANT_A) == 0
