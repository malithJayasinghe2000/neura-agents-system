"""ADR-0044 phase 1 against a real PostgreSQL — collect, delete on schedule, show nothing.

Everything here is a property of the database, or of the request path plus the
database, which is why none of it is a unit test:

* **Isolation of the one table that holds observed personal data.** A fake that
  "proves" RLS proves only that the fake filters.
* **The key-issue refusal**, which reads the tenant row inside the issuing
  transaction.
* **Deletion that runs** (ADR-0042 §3): old events and old conversations go —
  with their messages and checkpointed state — and the job re-arms only while
  something is left.
* **The route end to end**: a real key, a real agreement, a real row, and a
  sweep booked in the same transaction as the row.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, insert, select, text, update

from neura_agent_core.conversations import (
    ConversationRepository,
    ConversationState,
    conversation_messages,
    conversations,
)
from neura_agent_core.graph.schema import agent_checkpoint_writes, agent_checkpoints
from neura_agent_core.waiting import WaitingAnswerRepository, waiting_answers
from neura_api.jobs.retention import (
    RETENTION,
    RETENTION_SWEEP,
    RetentionSweepHandler,
    enqueue_sweep,
    sweep,
)
from neura_api.jobs.runner import JobRunner
from neura_core import ConfigurationError, Database, Settings, get_database, get_settings
from neura_core.jobs import JobQueue, JobStatus
from neura_core.jobs.schema import job_queue
from neura_core.observation import (
    OBSERVE_WRITE,
    ObservedEvent,
    ObservedEventRepository,
    observed_events,
)
from neura_core.tenancy import (
    ApiKeyKind,
    ApiKeyRepository,
    AuthenticatedCaller,
    TenantRepository,
)
from neura_core.tenancy.schema import api_keys, tenants

pytestmark = pytest.mark.integration

TENANT_A = "tn_iobs_a"
TENANT_B = "tn_iobs_b"
#: Stated, not read from the developer's `.env`: the window assertions below are
#: about 7 and 90 days, and an override there would make them lie.
SETTINGS = Settings(RETENTION_OBSERVED_EVENTS_DAYS=7, RETENTION_CONVERSATIONS_DAYS=90)  # type: ignore[call-arg]


@pytest.fixture
async def db():
    get_settings.cache_clear()
    get_database.cache_clear()
    database = Database.from_settings()
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
            for table in (
                observed_events,
                waiting_answers,
                conversation_messages,
                conversations,
                agent_checkpoint_writes,
                agent_checkpoints,
                job_queue,
                api_keys,
                tenants,
            ):
                await session.execute(delete(table))


async def _tenant(database: Database, tenant_id: str, *, dpa: bool = True) -> None:
    async with database.tenant_session(tenant_id) as session:
        repository = TenantRepository(session)
        await repository.create(tenant_id=tenant_id, name=f"Shop {tenant_id}")
        if dpa:
            await repository.set_dpa_signed_at(tenant_id, datetime.now(UTC))


def _event(event_id: str, *, age: timedelta = timedelta(0)) -> ObservedEvent:
    return ObservedEvent(
        event_id=event_id,
        session_id="s" * 64,
        type="product.viewed",  # type: ignore[arg-type]
        product_id="1315",
        occurred_at=datetime.now(UTC) - age,
        in_stock=True,
    )


async def _record(database: Database, tenant_id: str, *events: ObservedEvent) -> None:
    async with database.tenant_session(tenant_id) as session:
        repository = ObservedEventRepository(session)
        for event in events:
            await repository.record(tenant_id, event)


async def _held(database: Database, tenant_id: str) -> int:
    async with database.tenant_session(tenant_id) as session:
        return await ObservedEventRepository(session).count_for(tenant_id)


async def _conversation(database: Database, tenant_id: str, cid: str, *, idle: timedelta) -> None:
    """A conversation with a turn and a checkpoint, last touched ``idle`` ago."""
    async with database.tenant_session(tenant_id) as session:
        repository = ConversationRepository(session)
        await repository.start(tenant_id, conversation_id=cid, agent_key="care")
        await repository.append_turn(
            tenant_id,
            cid,
            shopper="where is it?",
            reply="on its way",
            state=ConversationState.RESOLVED,
        )
        await session.execute(
            insert(agent_checkpoints).values(
                tenant_id=tenant_id,
                thread_id=cid,
                checkpoint_ns="",
                checkpoint_id=f"cp_{cid}",
                checkpoint_type="msgpack",
                checkpoint=b"\x00",
            )
        )
        await session.execute(
            update(conversations)
            .where(conversations.c.tenant_id == tenant_id, conversations.c.id == cid)
            .values(updated_at=datetime.now(UTC) - idle)
        )


async def _waiting(database: Database, tenant_id: str, cid: str, *, age: timedelta) -> None:
    """A handed-over shopper's typed email (ADR-0062), left ``age`` ago."""
    async with database.tenant_session(tenant_id) as session:
        assert await WaitingAnswerRepository(session).leave_email(
            tenant_id, cid, "saman@example.com"
        )
        await session.execute(
            update(waiting_answers)
            .where(
                waiting_answers.c.tenant_id == tenant_id, waiting_answers.c.conversation_id == cid
            )
            .values(created_at=datetime.now(UTC) - age)
        )


async def _count(database: Database, tenant_id: str, table: Any, **where: str) -> int:
    async with database.tenant_session(tenant_id) as session:
        query = select(func.count()).select_from(table).where(table.c.tenant_id == tenant_id)
        for column, value in where.items():
            query = query.where(table.c[column] == value)
        return int(await session.scalar(query) or 0)


class TestIsolation:
    """ADR-0008, on the one table that holds observed personal data."""

    async def test_the_connected_role_is_subject_to_rls(self, db: Database) -> None:
        await db.assert_isolation_applies()

    async def test_a_tenant_cannot_see_another_tenants_events(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        await _tenant(db, TENANT_B)
        await _record(db, TENANT_A, _event("evt_isolation_000001"))

        async with db.tenant_session(TENANT_B) as session:
            repository = ObservedEventRepository(session)
            assert await repository.count_for(TENANT_A) == 0
            assert await repository.any_for(TENANT_A) is False
            # A delete aimed across the boundary deletes nothing.
            assert await repository.delete_all(TENANT_A) == 0
        assert await _held(db, TENANT_A) == 1

    async def test_a_tenant_cannot_write_another_tenants_event(self, db: Database) -> None:
        """The ``WITH CHECK`` half: a bug must not file A's shopper under B."""
        with pytest.raises(Exception, match="row-level security"):
            async with db.tenant_session(TENANT_B) as session:
                await ObservedEventRepository(session).record(TENANT_A, _event("evt_cross_0000001"))

    async def test_a_retried_delivery_is_one_row(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            repository = ObservedEventRepository(session)
            assert await repository.record(TENANT_A, _event("evt_retry_00000001")) is True
            assert await repository.record(TENANT_A, _event("evt_retry_00000001")) is False
        assert await _held(db, TENANT_A) == 1


class TestTheKeyIsTheGate:
    """ADR-0042 §2 and ADR-0044 §2, refused where they are a typo, not an incident."""

    async def test_no_agreement_no_key(self, db: Database) -> None:
        await _tenant(db, TENANT_A, dpa=False)
        with pytest.raises(ConfigurationError, match="data-processing agreement"):
            async with db.tenant_session(TENANT_A) as session:
                await ApiKeyRepository(session).issue(TENANT_A, scopes=[OBSERVE_WRITE])

    async def test_never_on_a_browser_key(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        with pytest.raises(ConfigurationError, match="secret"):
            async with db.tenant_session(TENANT_A) as session:
                await ApiKeyRepository(session).issue(
                    TENANT_A,
                    kind=ApiKeyKind.PUBLIC,
                    scopes=[OBSERVE_WRITE],
                    allowed_origins=["https://shop.example"],
                )

    async def test_a_secret_key_with_an_agreement_is_issued(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            record, _ = await ApiKeyRepository(session).issue(TENANT_A, scopes=[OBSERVE_WRITE])
        assert OBSERVE_WRITE in record.scopes

    async def test_other_scopes_are_untouched_by_the_gate(self, db: Database) -> None:
        """No agreement is needed for a key that cannot send events."""
        await _tenant(db, TENANT_A, dpa=False)
        async with db.tenant_session(TENANT_A) as session:
            record, _ = await ApiKeyRepository(session).issue(TENANT_A, scopes=["stores:read"])
        assert record.scopes == frozenset({"stores:read"})


class TestDeletionRuns:
    """ADR-0042 §3: *a job, not a documented intention*."""

    async def test_old_events_go_and_recent_ones_stay(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        await _record(
            db,
            TENANT_A,
            _event("evt_old_000000001", age=timedelta(days=8)),
            _event("evt_new_000000001", age=timedelta(days=1)),
        )

        async with db.tenant_session(TENANT_A) as session:
            result = await sweep(session, TENANT_A, now=datetime.now(UTC), settings=SETTINGS)

        assert result.events_deleted == 1
        assert result.remaining is True
        assert await _held(db, TENANT_A) == 1

    async def test_without_an_agreement_every_event_goes(self, db: Database) -> None:
        """Removal on resolution — the reason to hold them has ended."""
        await _tenant(db, TENANT_A)
        await _record(db, TENANT_A, _event("evt_withdrawn_0001"), _event("evt_withdrawn_0002"))
        async with db.tenant_session(TENANT_A) as session:
            await TenantRepository(session).set_dpa_signed_at(TENANT_A, None)

        async with db.tenant_session(TENANT_A) as session:
            result = await sweep(session, TENANT_A, now=datetime.now(UTC), settings=SETTINGS)

        assert result.no_agreement is True
        assert result.events_deleted == 2
        assert await _held(db, TENANT_A) == 0

    async def test_an_expired_conversation_goes_with_everything_it_left(self, db: Database) -> None:
        """The fan-out: transcript, messages and working state, together."""
        await _tenant(db, TENANT_A)
        await _conversation(db, TENANT_A, "cnv_iobs_stale", idle=timedelta(days=91))
        await _conversation(db, TENANT_A, "cnv_iobs_fresh", idle=timedelta(days=89))

        async with db.tenant_session(TENANT_A) as session:
            result = await sweep(session, TENANT_A, now=datetime.now(UTC), settings=SETTINGS)

        assert result.conversations_deleted == 1
        stale = {"conversation_id": "cnv_iobs_stale"}
        assert await _count(db, TENANT_A, conversations, id="cnv_iobs_stale") == 0
        assert await _count(db, TENANT_A, conversation_messages, **stale) == 0
        assert await _count(db, TENANT_A, agent_checkpoints, thread_id="cnv_iobs_stale") == 0

        fresh = {"conversation_id": "cnv_iobs_fresh"}
        assert await _count(db, TENANT_A, conversations, id="cnv_iobs_fresh") == 1
        assert await _count(db, TENANT_A, conversation_messages, **fresh) == 2
        assert await _count(db, TENANT_A, agent_checkpoints, thread_id="cnv_iobs_fresh") == 1

    async def test_an_unanswered_email_goes_after_30_days(self, db: Database) -> None:
        """ADR-0062 §4 (R30): unanswered after 30 days, the typed email is deleted
        and the chat leaves the waiting list. The chat itself stays (90 days)."""
        await _tenant(db, TENANT_A)
        await _conversation(db, TENANT_A, "cnv_iobs_old_wait", idle=timedelta(days=1))
        await _conversation(db, TENANT_A, "cnv_iobs_new_wait", idle=timedelta(days=1))
        await _waiting(db, TENANT_A, "cnv_iobs_old_wait", age=timedelta(days=31))
        await _waiting(db, TENANT_A, "cnv_iobs_new_wait", age=timedelta(days=29))

        async with db.tenant_session(TENANT_A) as session:
            result = await sweep(session, TENANT_A, now=datetime.now(UTC), settings=SETTINGS)

        assert result.emails_deleted == 1
        assert await _count(db, TENANT_A, waiting_answers, conversation_id="cnv_iobs_old_wait") == 0
        assert await _count(db, TENANT_A, waiting_answers, conversation_id="cnv_iobs_new_wait") == 1
        assert await _count(db, TENANT_A, conversations, id="cnv_iobs_old_wait") == 1

    async def test_an_answered_chat_keeps_who_answered_and_no_email(self, db: Database) -> None:
        """*Mark as answered* already deleted the address; what is left is who
        answered and when, which holds no shopper, and goes with the chat."""
        await _tenant(db, TENANT_A)
        await _conversation(db, TENANT_A, "cnv_iobs_answered", idle=timedelta(days=1))
        await _waiting(db, TENANT_A, "cnv_iobs_answered", age=timedelta(days=40))
        async with db.tenant_session(TENANT_A) as session:
            assert await WaitingAnswerRepository(session).mark_answered(
                TENANT_A, "cnv_iobs_answered", answered_by="usr_kumari"
            )

        async with db.tenant_session(TENANT_A) as session:
            result = await sweep(session, TENANT_A, now=datetime.now(UTC), settings=SETTINGS)
            waiting = await WaitingAnswerRepository(session).get(TENANT_A, "cnv_iobs_answered")

        assert result.emails_deleted == 0
        assert waiting is not None
        assert waiting.email is None
        assert waiting.answered_by == "usr_kumari"

    async def test_an_expired_chat_takes_its_waiting_row_with_it(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        await _conversation(db, TENANT_A, "cnv_iobs_gone", idle=timedelta(days=91))
        await _waiting(db, TENANT_A, "cnv_iobs_gone", age=timedelta(days=1))

        async with db.tenant_session(TENANT_A) as session:
            await sweep(session, TENANT_A, now=datetime.now(UTC), settings=SETTINGS)

        assert await _count(db, TENANT_A, waiting_answers, conversation_id="cnv_iobs_gone") == 0

    async def test_a_sweep_never_reaches_another_tenant(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        await _tenant(db, TENANT_B)
        await _record(db, TENANT_B, _event("evt_neighbour_0001", age=timedelta(days=8)))

        async with db.tenant_session(TENANT_A) as session:
            await sweep(session, TENANT_A, now=datetime.now(UTC), settings=SETTINGS)

        # B's row is expired, and it is B's sweep's to delete — not A's.
        assert await _held(db, TENANT_B) == 1


class TestTheScheduleKeepsItself:
    """No cron (ADR-0022): one live job per tenant, re-armed while anything is left."""

    async def _run_due_sweep(self, db: Database) -> Any:
        async with db.tenant_session(TENANT_A) as session:
            # Booked a day ago, so it is due now.
            job = await enqueue_sweep(session, TENANT_A, now=datetime.now(UTC) - timedelta(days=1))
        runner = JobRunner(db)
        runner.register(RETENTION_SWEEP, RetentionSweepHandler(SETTINGS))
        await runner.run_tenant(TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            return await JobQueue(session).get(job.id)

    async def test_it_re_arms_for_tomorrow_while_data_remains(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        await _record(db, TENANT_A, _event("evt_keep_00000001"))

        after = await self._run_due_sweep(db)

        assert after.status is JobStatus.PENDING
        assert after.run_after > datetime.now(UTC) + timedelta(hours=23)

    async def test_it_finishes_when_nothing_is_left(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        await _record(db, TENANT_A, _event("evt_gone_00000001", age=timedelta(days=8)))

        after = await self._run_due_sweep(db)

        assert after.status is JobStatus.DONE
        assert await _held(db, TENANT_A) == 0

    async def test_every_write_folds_onto_one_live_job(self, db: Database) -> None:
        await _tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            first = await enqueue_sweep(session, TENANT_A)
            second = await enqueue_sweep(session, TENANT_A)
            live = await JobQueue(session).find_by_dedupe(
                TENANT_A, RETENTION_SWEEP, RETENTION, live_only=True
            )
        assert first.id == second.id == live.id  # type: ignore[union-attr]


class TestANewConversationBooksItsDeletion:
    """The other write that creates something to expire: ``TurnService`` opening a transcript.

    Proved here rather than in ``test_api_postgres.py``, whose turn tests were
    failing when this was written (a stub missing ``structured_repairs``; fixed
    2026-09-30, G42 in CONNECTING_A_NEW_SHOP_LOG.md). A tenant with **no store**
    fails with ``NO_STORE_CONNECTED`` *after* the opening transaction has
    committed, so the conversation and its booking are both observable without
    running a turn, a graph or a model.
    """

    async def test_the_booking_commits_with_the_transcript(self, db: Database) -> None:
        from neura_api.stores import StoreDirectory
        from neura_api.turns import TurnInput, TurnService
        from neura_core import NotFoundError
        from neura_core.tenancy.models import ApiKey, Tenant

        await _tenant(db, TENANT_A)
        caller = AuthenticatedCaller(
            tenant=Tenant(tenant_id=TENANT_A, name="Shop", enabled_agents=frozenset({"care"})),
            api_key=ApiKey(
                id="key_iobs", tenant_id=TENANT_A, kind=ApiKeyKind.SECRET, token_prefix="fn_sk_x"
            ),
        )
        turns = TurnService(db, llm=None, stores=StoreDirectory(db))

        with pytest.raises(NotFoundError):
            await turns.run(
                runner=None,  # type: ignore[arg-type]
                turn=TurnInput(caller=caller, agent_key="care", message="where is my order?"),
            )

        assert await _count(db, TENANT_A, conversations) == 1
        async with db.tenant_session(TENANT_A) as session:
            booked = await JobQueue(session).find_by_dedupe(
                TENANT_A, RETENTION_SWEEP, RETENTION, live_only=True
            )
        assert booked is not None
        assert booked.run_after > datetime.now(UTC) + timedelta(hours=23)


class TestTheRoute:
    """``POST /v1/observe/events``, with a real key, a real agreement and a real row."""

    @pytest.fixture
    def client(self, db: Database) -> Any:
        from neura_api.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client

    @staticmethod
    async def _key(db: Database, tenant_id: str) -> str:
        await _tenant(db, tenant_id)
        async with db.tenant_session(tenant_id) as session:
            _, issued = await ApiKeyRepository(session).issue(tenant_id, scopes=[OBSERVE_WRITE])
        return issued.token

    @staticmethod
    def _body(event_id: str = "01J8ZQ7Y3W5K2M9N4P6R8T0V1X", **extra: Any) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "session_id": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "type": "cart.added",
            "product_id": "1315",
            "occurred_at": datetime.now(UTC).isoformat(),
            **extra,
        }

    async def test_an_event_is_stored_once_and_its_deletion_is_booked(
        self, client: TestClient, db: Database
    ) -> None:
        token = await self._key(db, TENANT_A)
        headers = {"Authorization": f"Bearer {token}"}

        first = client.post("/v1/observe/events", json=self._body(), headers=headers)
        again = client.post("/v1/observe/events", json=self._body(), headers=headers)

        assert first.status_code == 202, first.text
        assert first.json()["data"]["stored"] is True
        assert again.json()["data"]["stored"] is False
        assert await _held(db, TENANT_A) == 1

        async with db.tenant_session(TENANT_A) as session:
            booked = await JobQueue(session).find_by_dedupe(
                TENANT_A, RETENTION_SWEEP, RETENTION, live_only=True
            )
            row = (
                (
                    await session.execute(
                        text("SELECT * FROM observed_events WHERE tenant_id = :t"), {"t": TENANT_A}
                    )
                )
                .mappings()
                .one()
            )
        assert booked is not None
        # Exactly §4's fields — and the key's tenant, never one the body named.
        assert set(row) == {
            "tenant_id",
            "event_id",
            "session_id",
            "event_type",
            "product_id",
            "occurred_at",
            "in_stock",
        }
        assert row["tenant_id"] == TENANT_A
        # A basket add carries no stock value: NULL, meaning "not applicable".
        assert row["in_stock"] is None

    async def test_a_sold_out_view_is_stored_as_sold_out(
        self, client: TestClient, db: Database
    ) -> None:
        """ADR-0049 — the fact ADR-0046 stage 1 will count."""
        token = await self._key(db, TENANT_A)
        body = self._body(type="product.viewed", in_stock=False)
        response = client.post(
            "/v1/observe/events", json=body, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 202, response.text
        async with db.tenant_session(TENANT_A) as session:
            stored = await session.scalar(
                text("SELECT in_stock FROM observed_events WHERE tenant_id = :t"), {"t": TENANT_A}
            )
        assert stored is False

    async def test_an_extra_field_is_refused_and_nothing_is_stored(
        self, client: TestClient, db: Database
    ) -> None:
        token = await self._key(db, TENANT_A)
        response = client.post(
            "/v1/observe/events",
            json=self._body(ip="203.0.113.9"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400
        assert await _held(db, TENANT_A) == 0

    async def test_a_withdrawn_agreement_refuses_a_key_that_was_valid(
        self, client: TestClient, db: Database
    ) -> None:
        token = await self._key(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            await TenantRepository(session).set_dpa_signed_at(TENANT_A, None)

        response = client.post(
            "/v1/observe/events", json=self._body(), headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "DPA_REQUIRED"
        assert await _held(db, TENANT_A) == 0

    async def test_a_key_without_the_scope_is_403(self, client: TestClient, db: Database) -> None:
        await _tenant(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            _, issued = await ApiKeyRepository(session).issue(TENANT_A, scopes=["stores:read"])
        response = client.post(
            "/v1/observe/events",
            json=self._body(),
            headers={"Authorization": f"Bearer {issued.token}"},
        )
        assert response.status_code == 403
        assert await _held(db, TENANT_A) == 0
