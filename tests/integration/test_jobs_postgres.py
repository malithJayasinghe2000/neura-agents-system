"""The job queue and the dispatch function, against a real PostgreSQL.

None of this can be a unit test, and a fake would defeat the purpose. Every
claim here is a property of *PostgreSQL* rather than of our code:

* **Row-Level Security filtering a queue**, which is ADR-0008 applied to the one
  table a background worker reads. A fake "proving" isolation proves only that
  the fake filters.
* **``FOR UPDATE SKIP LOCKED``** making two workers on one tenant safe. In
  Python there is nothing to skip.
* **The exemption, and its bounds.** ``neura_due_tenants`` is the first
  deliberate cross-tenant read in this system (ADR-0022). The tests that matter
  most here are the ones that pin what it *cannot* do: an unscoped session still
  reads no rows, ``neura_app`` still sees only its own tenant, and the dispatch
  role holds no grant on ``payload``.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).

**These only mean anything because the application connects as a role RLS
applies to.** If that regresses to the owner or a superuser they all pass while
isolating nothing, so ``ping()`` is asserted first.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from neura_api.jobs.runner import JobContext, JobRunner
from neura_api.jobs.sync import SYNC_STORE, enqueue_sync
from neura_api.jobs.webhooks import WEBHOOK_DRAIN, WebhookDrainHandler, enqueue_drain
from neura_api.webhooks import WebhookDrainer
from neura_core import Database, get_settings
from neura_core.jobs import CrossTenantJobWriteError, JobQueue, JobStatus
from neura_core.jobs import due_tenants as all_due_tenants
from neura_core.jobs.schema import DUE_TENANTS_FUNCTION, JOB_QUEUE_TABLE, SCHEDULER_ROLE
from neura_core.webhooks import PendingEvent, WebhookEvent, WebhookRepository

pytestmark = pytest.mark.integration

TENANT_A = "tn_ijob_a"
TENANT_B = "tn_ijob_b"
#: A tenant no fixture creates and no test enqueues for. Used to show that
#: `due_tenants` names exactly whom it should and nobody else.
TENANT_QUIET = "tn_ijob_quiet"

KIND = "probe"


async def due_tenants(db: Database, *, now: datetime | None = None) -> list[str]:
    """``due_tenants``, narrowed to the tenants this file creates.

    The suite runs against the development database, where the test shops live
    too, and one of their real jobs coming due made an exact-list assertion here
    fail (CONNECTING_A_NEW_SHOP_LOG.md G43). The function itself is still called
    unfiltered, across every tenant; only the comparison ignores tenants this
    file does not own. ``TENANT_QUIET`` still proves nobody extra is named.
    """
    return [t for t in await all_due_tenants(db, now=now) if t.startswith("tn_ijob_")]


#: 32 random bytes, base64. Webhook signing secrets are envelope-encrypted and
#: the placeholder KEK is refused on purpose.
KEK = "iC0hbmk6b18lBhVRDDeQZ6mXpvNhpjJUM7ScE3wp0Ss="


@pytest.fixture
async def db():
    # A real KEK before anything encrypts a webhook signing secret, and settings
    # are cached for the process lifetime. Set here rather than relied upon from
    # another module's fixture: a suite that only passes in a particular file
    # order is a suite that fails the first time someone runs one test.
    os.environ["NEURA_KEK"] = KEK
    get_settings.cache_clear()

    database = Database.from_settings()

    # A database that is not running is a skip: not everyone has Docker up.
    # A database connected as a role RLS does not apply to is a FAILURE and
    # deliberately not a skip — skipping it is how a suite reports green while
    # the isolation it claims to prove was never in effect.
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")

    await _clear(database)
    yield database
    await _clear(database)
    await database.dispose()


async def _clear(database: Database) -> None:
    for tenant in (TENANT_A, TENANT_B, TENANT_QUIET):
        async with database.tenant_session(tenant) as session:
            for table in (JOB_QUEUE_TABLE, "webhook_deliveries", "webhook_endpoints"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tenant}
                )


async def enqueue(db: Database, tenant: str, **kwargs: object) -> object:
    async with db.tenant_session(tenant) as session:
        return await JobQueue(session).enqueue(tenant, KIND, **kwargs)  # type: ignore[arg-type]


class TestTenantIsolation:
    """ADR-0008's acceptance criterion, applied to the queue a worker reads."""

    async def test_the_connected_role_is_subject_to_rls(self, db: Database) -> None:
        """Everything below is meaningless if this is false."""
        await db.assert_isolation_applies()

    async def test_a_tenant_cannot_read_another_tenants_jobs(self, db: Database) -> None:
        created = await enqueue(db, TENANT_A, dedupe_key="k1")

        async with db.tenant_session(TENANT_B) as session:
            queue = JobQueue(session)
            assert await queue.get(created.id) is None  # type: ignore[attr-defined]
            assert await queue.list_for(TENANT_A) == []
            assert await queue.find_by_dedupe(TENANT_A, KIND, "k1") is None

    async def test_a_tenant_cannot_write_another_tenants_job(self, db: Database) -> None:
        """The ``WITH CHECK`` half.

        Filtering reads alone would let a bug queue work against one merchant's
        store under another merchant's credentials — and then run it, correctly,
        for the wrong shop.
        """
        with pytest.raises(CrossTenantJobWriteError):
            async with db.tenant_session(TENANT_B) as session:
                await JobQueue(session).enqueue(TENANT_A, KIND)

    async def test_a_tenant_cannot_claim_another_tenants_job(self, db: Database) -> None:
        """The one that would matter most if it broke.

        A claim is an ``UPDATE``. If RLS let it cross, one tenant's worker would
        run another tenant's work rather than merely read about it.
        """
        await enqueue(db, TENANT_A)

        async with db.tenant_session(TENANT_B) as session:
            assert await JobQueue(session).claim(TENANT_A) == []

        async with db.tenant_session(TENANT_A) as session:
            still_pending = await JobQueue(session).list_for(TENANT_A, status=JobStatus.PENDING)
        assert len(still_pending) == 1
        assert still_pending[0].attempts == 0


class TestTheDispatchFunction:
    """The exemption of ADR-0022 §2, and every bound placed on it."""

    async def test_a_worker_learns_of_a_tenant_it_was_never_told_about(self, db: Database) -> None:
        """The case that was impossible before this existed.

        Nothing in this test hands ``due_tenants`` a tenant id. It is given a
        database and a clock, and it names the two tenants with due work.
        """
        await enqueue(db, TENANT_A)
        await enqueue(db, TENANT_B)

        assert await due_tenants(db) == [TENANT_A, TENANT_B]

    async def test_it_names_nobody_whose_work_is_not_due(self, db: Database) -> None:
        later = datetime.now(UTC) + timedelta(hours=1)
        await enqueue(db, TENANT_A, run_after=later)

        assert await due_tenants(db) == []
        assert await due_tenants(db, now=later) == [TENANT_A]

    async def test_a_claimed_job_stops_naming_its_tenant(self, db: Database) -> None:
        """Otherwise every poll would re-open a session for work already running."""
        await enqueue(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            await JobQueue(session).claim(TENANT_A)

        assert await due_tenants(db) == []

    async def test_an_expired_lease_names_its_tenant_again(self, db: Database) -> None:
        """A worker that died must not strand its tenant's work.

        This is the recovery half of at-least-once (ADR-0022 §5), and it is the
        reason a killed process costs a delay rather than a lost job.
        """
        await enqueue(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            await JobQueue(session).claim(TENANT_A, lease=timedelta(seconds=1))

        assert await due_tenants(db) == []
        assert await due_tenants(db, now=datetime.now(UTC) + timedelta(seconds=2)) == [TENANT_A]

    async def test_a_finished_job_names_nobody(self, db: Database) -> None:
        job = await enqueue(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            claimed = await queue.claim(TENANT_A)
            await queue.complete(claimed[0].id)

        assert job is not None
        assert await due_tenants(db) == []


class TestTheBoundsOnTheExemption:
    """What the dispatch path still cannot do. The reason this is not BYPASSRLS."""

    async def test_the_dispatch_session_reads_no_rows_at_all(self, db: Database) -> None:
        """The structural claim, checked rather than asserted in a docstring.

        ``dispatch_session`` sets no ``app.tenant_id``. Every policy-protected
        table returns nothing to it, so the function call is the only statement
        in that transaction that can answer anything. If this ever returns a
        row, the exemption has stopped being narrow and became a role.
        """
        await enqueue(db, TENANT_A, payload={"secret": "merchant data"})

        async with db.dispatch_session() as session:
            for table in (JOB_QUEUE_TABLE, "tenants", "synced_entities", "conversations"):
                count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
                assert count == 0, f"the dispatch session read {table}"

    async def test_the_dispatch_session_cannot_write(self, db: Database) -> None:
        """``READ ONLY`` makes it structural rather than careful: dispatch cannot
        become a way to mutate anything before a tenant has been named."""
        async with db.dispatch_session() as session:
            with pytest.raises(Exception, match="read-only"):
                await session.execute(
                    text(
                        f"INSERT INTO {JOB_QUEUE_TABLE} (id, tenant_id, kind) "
                        "VALUES ('x', 'y', 'z')"
                    )
                )

    async def test_the_dispatch_role_holds_no_grant_on_the_payload(self, db: Database) -> None:
        """Column grant and policy must both pass, so this is the second bound.

        Even total compromise of ``neura_scheduler`` yields tenant ids and
        timing — never what a job is about. Asserted against the catalogue,
        because that is where the guarantee actually lives.
        """
        async with db.dispatch_session() as session:
            # Read from pg_catalog rather than information_schema:
            # `column_privileges` only shows grants the *current* role is party
            # to, so as neura_app it would return an empty set and this test
            # would pass by seeing nothing at all.
            granted = set(
                (
                    await session.execute(
                        text(
                            "SELECT a.attname FROM pg_attribute a, "
                            "aclexplode(a.attacl) acl "
                            "WHERE a.attrelid = CAST(:t AS regclass) "
                            "AND acl.grantee = CAST(:g AS regrole) "
                            "AND acl.privilege_type = 'SELECT'"
                        ),
                        {"t": JOB_QUEUE_TABLE, "g": SCHEDULER_ROLE},
                    )
                )
                .scalars()
                .all()
            )

        assert granted == {"tenant_id", "status", "run_after", "locked_until"}
        assert "payload" not in granted
        assert "last_error" not in granted

    async def test_the_dispatch_role_cannot_log_in(self, db: Database) -> None:
        """Nothing connects as it. It is reachable only as one function's definer."""
        async with db.dispatch_session() as session:
            row = (
                await session.execute(
                    text("SELECT rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname = :r"),
                    {"r": SCHEDULER_ROLE},
                )
            ).one()

        can_login, bypasses_rls = row
        assert can_login is False
        assert bypasses_rls is False, (
            "the dispatch role has BYPASSRLS — the exemption ADR-0022 bounded to "
            "one column of one table now covers every row of every table"
        )

    async def test_the_widening_policy_does_not_reach_the_application_role(
        self, db: Database
    ) -> None:
        """``scheduler_dispatch`` is scoped ``TO neura_scheduler``.

        Permissive policies are OR-ed, so a policy written without a role would
        have widened the table for *everyone*. This is the test that says it did
        not: the application's own session still sees one tenant.
        """
        await enqueue(db, TENANT_A)
        await enqueue(db, TENANT_B)

        async with db.tenant_session(TENANT_A) as session:
            visible = (
                await session.execute(text(f"SELECT count(*) FROM {JOB_QUEUE_TABLE}"))
            ).scalar()
        assert visible == 1

    async def test_the_function_is_not_executable_by_public(self, db: Database) -> None:
        """PUBLIC gets EXECUTE on a new function by default.

        The migration revokes it before granting to one role, and getting that
        order backwards is how a "restricted" function ends up callable by
        everyone. Checked, because nothing else would notice.
        """
        async with db.dispatch_session() as session:
            granted = (
                await session.execute(
                    text(
                        "SELECT has_function_privilege('public', p.oid, 'EXECUTE') "
                        "FROM pg_proc p WHERE p.proname = :n"
                    ),
                    {"n": DUE_TENANTS_FUNCTION},
                )
            ).scalar()
        assert granted is False


class TestClaiming:
    async def test_two_workers_on_one_tenant_do_not_take_the_same_job(self, db: Database) -> None:
        """``FOR UPDATE SKIP LOCKED``, which has no meaning outside a database.

        The second session must *skip* the row the first is holding rather than
        block behind it — a claim that waited would serialise every worker in the
        deployment behind the slowest tenant.
        """
        await enqueue(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as first:
            claimed_first = await JobQueue(first).claim(TENANT_A)
            assert len(claimed_first) == 1

            # A second connection, while the first transaction is still open.
            async with db.tenant_session(TENANT_A) as second:
                assert await JobQueue(second).claim(TENANT_A) == []

    async def test_an_attempt_is_charged_when_the_work_starts(self, db: Database) -> None:
        """Not when it fails.

        A worker killed mid-job never reports anything, so a failure-time counter
        would let a job that crashes the process be retried forever. This is what
        makes a poison job dead-letter like any other.
        """
        await enqueue(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            claimed = await JobQueue(session).claim(TENANT_A)
        assert claimed[0].attempts == 1

    async def test_the_sql_and_the_python_agree_about_the_lease(self, db: Database) -> None:
        """``Job.is_claimable`` and the claim's ``WHERE`` state one rule twice.

        Checked against each other rather than each against a hand-written
        expectation, because the failure that matters is them *drifting* — and
        two correct-looking statements of a rule is exactly how a job silently
        stops being picked up.
        """
        await enqueue(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            await JobQueue(session).claim(TENANT_A, lease=timedelta(seconds=1))

        before = datetime.now(UTC)
        after = before + timedelta(seconds=2)

        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            held = (await queue.list_for(TENANT_A))[0]
            assert held.is_claimable(now=before) is False
            assert await queue.claim(TENANT_A, now=before) == []

            assert held.is_claimable(now=after) is True
            assert len(await queue.claim(TENANT_A, now=after)) == 1

    async def test_a_lease_is_returned_to_the_pool_when_it_expires(self, db: Database) -> None:
        """``claim`` already treats an expired lease as claimable.

        ``release_expired`` exists so the *status column* stops saying "running"
        about a worker that died an hour ago — a status that lies to an operator
        is its own defect.
        """
        await enqueue(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            await JobQueue(session).claim(TENANT_A, lease=timedelta(seconds=-1))

        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            assert await queue.release_expired(TENANT_A) == 1
            rows = await queue.list_for(TENANT_A)
        assert rows[0].status is JobStatus.PENDING
        assert rows[0].locked_until is None


class TestFailure:
    async def test_a_failure_is_rescheduled_with_backoff(self, db: Database) -> None:
        await enqueue(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            claimed = await queue.claim(TENANT_A)
            status = await queue.fail(claimed[0], error="the shop returned 503")
            after = await queue.get(claimed[0].id)

        assert status is JobStatus.PENDING
        assert after is not None
        assert after.run_after > claimed[0].run_after
        assert after.last_error == "the shop returned 503"

    async def test_the_last_attempt_dead_letters_and_the_row_stays(self, db: Database) -> None:
        """Kept and readable, for the reason a dead-lettered webhook is kept.

        Work that was asked for and never done, with nobody told, is a dropped
        job. A merchant who cannot see what failed cannot fix it.
        """
        await enqueue(db, TENANT_A, max_attempts=1)

        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            claimed = await queue.claim(TENANT_A)
            status = await queue.fail(claimed[0], error="unreachable")
            after = await queue.get(claimed[0].id)

        assert status is JobStatus.DEAD
        assert after is not None
        assert after.status is JobStatus.DEAD
        assert after.last_error == "unreachable"
        assert await due_tenants(db) == []

    async def test_a_long_error_is_truncated(self, db: Database) -> None:
        """A handler raising with a whole HTML error page in the message would
        otherwise put a document in a column somebody renders."""
        await enqueue(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            claimed = await queue.claim(TENANT_A)
            await queue.fail(claimed[0], error="x" * 5000)
            after = await queue.get(claimed[0].id)

        assert after is not None
        assert len(after.last_error) == 500


class TestDeduplication:
    async def test_a_second_enqueue_returns_the_first_job(self, db: Database) -> None:
        """A sync asked for three times while the first is pending is one sync."""
        first = await enqueue(db, TENANT_A, dedupe_key="store-1")
        second = await enqueue(db, TENANT_A, dedupe_key="store-1")

        assert first.id == second.id  # type: ignore[attr-defined]

        async with db.tenant_session(TENANT_A) as session:
            assert len(await JobQueue(session).list_for(TENANT_A)) == 1

    async def test_a_finished_job_frees_its_key(self, db: Database) -> None:
        """The defect a plain unique constraint shipped with.

        "One job per key" and "one job per key, *ever*" look identical while the
        first job is still live, and the first surface only ever asked twice in
        that window — so the check passed for the wrong reason. Under the
        permanent constraint a store could be synced exactly once: every later
        enqueue would find the completed row and report success while queueing
        nothing.
        """
        first = await enqueue(db, TENANT_A, dedupe_key="store-1")
        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            claimed = await queue.claim(TENANT_A)
            await queue.complete(claimed[0].id)

        second = await enqueue(db, TENANT_A, dedupe_key="store-1")
        assert second.id != first.id  # type: ignore[attr-defined]
        assert await due_tenants(db) == [TENANT_A]

    async def test_a_dead_job_also_frees_its_key(self, db: Database) -> None:
        """A dead letter is a record, not a block.

        It stays readable — that is the whole reason it is kept — but a merchant
        whose endpoint has been fixed must be able to queue the next attempt.
        """
        first = await enqueue(db, TENANT_A, dedupe_key="store-1", max_attempts=1)
        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            claimed = await queue.claim(TENANT_A)
            assert await queue.fail(claimed[0], error="gone") is JobStatus.DEAD

        second = await enqueue(db, TENANT_A, dedupe_key="store-1")
        assert second.id != first.id  # type: ignore[attr-defined]

        async with db.tenant_session(TENANT_A) as session:
            rows = await JobQueue(session).list_for(TENANT_A)
        assert {r.status for r in rows} == {JobStatus.DEAD, JobStatus.PENDING}

    async def test_a_live_job_still_holds_its_key(self, db: Database) -> None:
        """The property the partial index must not have lost."""
        first = await enqueue(db, TENANT_A, dedupe_key="store-1")
        second = await enqueue(db, TENANT_A, dedupe_key="store-1")
        assert first.id == second.id  # type: ignore[attr-defined]

        async with db.tenant_session(TENANT_A) as session:
            await JobQueue(session).claim(TENANT_A)
        third = await enqueue(db, TENANT_A, dedupe_key="store-1")
        assert third.id == first.id  # type: ignore[attr-defined]

    async def test_two_tenants_may_use_the_same_dedupe_key(self, db: Database) -> None:
        """The constraint is per tenant. Two merchants both syncing "their first
        store" must not collide on a shared string."""
        await enqueue(db, TENANT_A, dedupe_key="default")
        await enqueue(db, TENANT_B, dedupe_key="default")

        assert await due_tenants(db) == [TENANT_A, TENANT_B]

    async def test_without_a_key_every_enqueue_is_a_distinct_job(self, db: Database) -> None:
        """PostgreSQL treats NULLs in a unique constraint as distinct. That is
        the behaviour wanted here, not a quirk being tolerated."""
        await enqueue(db, TENANT_A)
        await enqueue(db, TENANT_A)

        async with db.tenant_session(TENANT_A) as session:
            assert len(await JobQueue(session).list_for(TENANT_A)) == 2


class TestTheSyncJob:
    """The one handler that exists, and the helper that queues work for it."""

    async def test_the_helper_writes_what_the_handler_reads(self, db: Database) -> None:
        """Both halves of a contract nothing else checks.

        ``enqueue_sync`` and ``SyncStoreHandler`` are the only writer and the
        only reader of this payload. If they drift, nothing fails until a real
        sync silently crawls the wrong store — so they are checked against each
        other here rather than each against a literal.
        """
        async with db.tenant_session(TENANT_A) as session:
            queued = await enqueue_sync(session, TENANT_A, store_id="st_1", incremental=False)

        assert queued.kind == SYNC_STORE
        assert queued.payload == {"store_id": "st_1", "incremental": False}
        assert queued.dedupe_key == "st_1"

    async def test_it_takes_a_session_so_the_job_commits_with_its_reason(
        self, db: Database
    ) -> None:
        """The property a Redis index structurally could not have.

        A rolled-back transaction must leave no job behind. If this helper
        opened its own transaction, a sync would be scheduled for a store whose
        registration was abandoned.
        """
        try:
            async with db.tenant_session(TENANT_A) as session:
                await enqueue_sync(session, TENANT_A, store_id="st_rollback")
                raise RuntimeError("the caller changed its mind")
        except RuntimeError:
            pass

        async with db.tenant_session(TENANT_A) as session:
            assert await JobQueue(session).list_for(TENANT_A) == []

    async def test_one_live_sync_per_store(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            first = await enqueue_sync(session, TENANT_A, store_id="st_1")
            second = await enqueue_sync(session, TENANT_A, store_id="st_1")
            other = await enqueue_sync(session, TENANT_A, store_id="st_2")

        assert first.id == second.id
        assert other.id != first.id


class TestRescheduling:
    """A standing task that finished a pass and knows there is more to do."""

    async def test_a_reschedule_is_not_a_failure(self, db: Database) -> None:
        """``attempts`` resets, because the counter exists to dead-letter work
        that keeps failing and a completed pass is the opposite of that.

        Without the reset, a drain that re-armed five times would dead-letter
        for being useful.
        """
        await enqueue(db, TENANT_A)
        later = datetime.now(UTC) + timedelta(minutes=5)

        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            claimed = await queue.claim(TENANT_A)
            assert claimed[0].attempts == 1
            await queue.reschedule(claimed[0].id, run_after=later)
            after = await queue.get(claimed[0].id)

        assert after is not None
        assert after.status is JobStatus.PENDING
        assert after.attempts == 0
        assert after.locked_until is None
        assert after.run_after == later

    async def test_completing_a_job_you_no_longer_hold_does_nothing(self, db: Database) -> None:
        """The guard that lets a handler decide its own next state.

        The runner completes every job whose handler returned. A handler that
        put its own row back to ``pending`` must not then have it quietly
        finished — the work it queued itself for would vanish.
        """
        await enqueue(db, TENANT_A)
        async with db.tenant_session(TENANT_A) as session:
            queue = JobQueue(session)
            claimed = await queue.claim(TENANT_A)
            await queue.reschedule(claimed[0].id, run_after=datetime.now(UTC))
            await queue.complete(claimed[0].id)
            after = await queue.get(claimed[0].id)

        assert after is not None
        assert after.status is JobStatus.PENDING


class TestTheWebhookDrainJob:
    """The 1.14 Redis index, replaced. The outbox itself is unchanged."""

    async def test_the_drain_job_commits_with_the_deliveries(self, db: Database) -> None:
        """The property a Redis ``sadd`` structurally could not have.

        The old index had to be written *after* the transaction, or a rollback
        would point the drainer at rows that do not exist — so a process that
        died in between stranded the deliveries permanently. Here neither can
        exist without the other.
        """
        try:
            async with db.tenant_session(TENANT_A) as session:
                repository = WebhookRepository(session, kek=KEK)
                await repository.register(
                    TENANT_A,
                    url="https://127.0.0.1:9/hooks",
                    events=[WebhookEvent.CONVERSATION_RESOLVED],
                )
                await repository.enqueue(
                    TENANT_A, PendingEvent(event=WebhookEvent.CONVERSATION_RESOLVED)
                )
                await enqueue_drain(session, TENANT_A)
                raise RuntimeError("the turn failed after queuing")
        except RuntimeError:
            pass

        async with db.tenant_session(TENANT_A) as session:
            assert await JobQueue(session).list_for(TENANT_A) == []
            assert await WebhookRepository(session).list_deliveries(TENANT_A) == []
        assert await due_tenants(db) == []

    async def test_a_burst_of_events_queues_one_drain(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            repository = WebhookRepository(session, kek=KEK)
            await repository.register(
                TENANT_A,
                url="https://127.0.0.1:9/hooks",
                events=[WebhookEvent.CONVERSATION_RESOLVED],
            )
            for _ in range(5):
                await repository.enqueue(
                    TENANT_A, PendingEvent(event=WebhookEvent.CONVERSATION_RESOLVED)
                )
                await enqueue_drain(session, TENANT_A)

            jobs = await JobQueue(session).list_for(TENANT_A)
            deliveries = await WebhookRepository(session).list_deliveries(TENANT_A)

        assert len(deliveries) == 5
        assert len(jobs) == 1

    async def test_it_re_arms_while_the_outbox_still_holds_something(self, db: Database) -> None:
        """A delivery inside its backoff is not due *now* and is still
        outstanding. A job that finished on "nothing due this second" would
        leave it with nothing pointing at it."""
        async with db.tenant_session(TENANT_A) as session:
            repository = WebhookRepository(session, kek=KEK)
            await repository.register(
                TENANT_A,
                # Port 9 is discard: the connection is refused immediately, so
                # this is a real failed attempt and not a test waiting on a
                # timeout.
                url="https://127.0.0.1:9/hooks",
                events=[WebhookEvent.CONVERSATION_RESOLVED],
            )
            await repository.enqueue(
                TENANT_A, PendingEvent(event=WebhookEvent.CONVERSATION_RESOLVED)
            )
            job = await enqueue_drain(session, TENANT_A)

        drainer = WebhookDrainer(db)
        runner = JobRunner(db)
        runner.register(WEBHOOK_DRAIN, WebhookDrainHandler(drainer))
        try:
            assert await runner.run_once() == 1
        finally:
            await drainer.aclose()

        async with db.tenant_session(TENANT_A) as session:
            after = await JobQueue(session).get(job.id)
            [delivery] = await WebhookRepository(session).list_deliveries(TENANT_A)

        assert delivery.attempts == 1, "the endpoint was never actually tried"
        assert after is not None
        assert after.status is JobStatus.PENDING, "the outbox is not empty; the job must re-arm"
        assert after.run_after > datetime.now(UTC)
        assert after.attempts == 0, "a re-arm is not a failed attempt"

    async def test_it_finishes_when_the_outbox_is_empty(self, db: Database) -> None:
        """And only then — which is the moment the dedupe key frees itself and
        the next burst of events can queue a new drain."""
        async with db.tenant_session(TENANT_A) as session:
            job = await enqueue_drain(session, TENANT_A)

        drainer = WebhookDrainer(db)
        runner = JobRunner(db)
        runner.register(WEBHOOK_DRAIN, WebhookDrainHandler(drainer))
        try:
            await runner.run_once()
        finally:
            await drainer.aclose()

        async with db.tenant_session(TENANT_A) as session:
            after = await JobQueue(session).get(job.id)
            following = await enqueue_drain(session, TENANT_A)

        assert after is not None
        assert after.status is JobStatus.DONE
        assert following.id != job.id, "a finished drain must not block the next one"


class TestTheRunner:
    """The loop, against the real function and the real table."""

    async def test_it_runs_work_for_a_tenant_it_was_never_told_about(self, db: Database) -> None:
        """The whole point, end to end.

        The runner is constructed with a database and nothing else. It holds no
        tenant list. The tenant is discovered, a session is opened for it, and
        the handler runs — which is precisely what could not happen before
        ADR-0022, and why nothing scheduled a sync.
        """
        seen: list[str] = []

        async def handler(context: JobContext) -> str:
            seen.append(context.tenant_id)
            return f"ran for {context.tenant_id}"

        runner = JobRunner(db)
        runner.register(KIND, handler)

        await enqueue(db, TENANT_A, payload={"n": 1})
        assert await runner.run_once() == 1
        assert seen == [TENANT_A]

        async with db.tenant_session(TENANT_A) as session:
            rows = await JobQueue(session).list_for(TENANT_A)
        assert rows[0].status is JobStatus.DONE

    async def test_it_sweeps_every_due_tenant(self, db: Database) -> None:
        seen: list[str] = []

        async def handler(context: JobContext) -> str:
            seen.append(context.tenant_id)
            return "ok"

        runner = JobRunner(db)
        runner.register(KIND, handler)

        await enqueue(db, TENANT_A)
        await enqueue(db, TENANT_B)

        assert await runner.run_once() == 2
        assert sorted(seen) == [TENANT_A, TENANT_B]
        assert TENANT_QUIET not in seen

    async def test_a_raising_handler_leaves_the_job_for_another_attempt(self, db: Database) -> None:
        async def handler(context: JobContext) -> str:
            raise RuntimeError("the shop was down")

        runner = JobRunner(db)
        runner.register(KIND, handler)
        await enqueue(db, TENANT_A)

        assert await runner.run_once() == 0

        async with db.tenant_session(TENANT_A) as session:
            rows = await JobQueue(session).list_for(TENANT_A)
        assert rows[0].status is JobStatus.PENDING
        assert rows[0].attempts == 1
        assert "the shop was down" in rows[0].last_error

    async def test_a_kind_this_deployment_cannot_run_dead_letters_visibly(
        self, db: Database
    ) -> None:
        """A partial rollout, or a rollback.

        A runner that ignored unknown kinds would leave the row pending forever
        and report a clean sweep every five seconds. It fails like any other job
        instead, so somebody eventually sees it.
        """
        runner = JobRunner(db)  # no handlers registered at all
        await enqueue(db, TENANT_A, max_attempts=1)

        assert await runner.run_once() == 0

        async with db.tenant_session(TENANT_A) as session:
            rows = await JobQueue(session).list_for(TENANT_A)
        assert rows[0].status is JobStatus.DEAD
        assert "no handler registered" in rows[0].last_error

    async def test_one_failing_tenant_does_not_stop_the_others(self, db: Database) -> None:
        """A sweep is not a transaction. One merchant's broken store must not
        mean nobody else's catalogue is synced today."""
        ran: list[str] = []

        async def handler(context: JobContext) -> str:
            if context.tenant_id == TENANT_A:
                raise RuntimeError("boom")
            ran.append(context.tenant_id)
            return "ok"

        runner = JobRunner(db)
        runner.register(KIND, handler)
        await enqueue(db, TENANT_A)
        await enqueue(db, TENANT_B)

        assert await runner.run_once() == 1
        assert ran == [TENANT_B]

    async def test_two_runners_sweeping_at_once_run_a_job_once(self, db: Database) -> None:
        """Two API replicas, one queue. ``SKIP LOCKED`` through the whole loop."""
        ran: list[str] = []

        async def handler(context: JobContext) -> str:
            ran.append(context.job.id)
            return "ok"

        first, second = JobRunner(db), JobRunner(db)
        first.register(KIND, handler)
        second.register(KIND, handler)
        await enqueue(db, TENANT_A)

        completed = await asyncio.gather(first.run_once(), second.run_once())

        assert sum(completed) == 1
        assert len(ran) == 1
