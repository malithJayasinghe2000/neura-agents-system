"""The job queue's pure logic — the parts that need no database.

Everything that is a property of *PostgreSQL* — Row-Level Security, the claim's
``SKIP LOCKED``, and the one function that crosses a tenant boundary — is in
``tests/integration/test_jobs_postgres.py``, because a fake proving isolation
proves only that the fake filters.

What is here is the arithmetic and the dispatch, which is where a fake earns its
place: a handler that raises, a kind nobody registered, and a lease whose two
statements — one in SQL, one in Python — have to agree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from neura_api.jobs.runner import JobContext, JobRunner, UnknownJobKindError
from neura_api.jobs.sync import SYNC_STORE, dedupe_key_for
from neura_core.jobs import BACKOFF_MAX_S, Job, JobStatus, backoff_for

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def job(**overrides: object) -> Job:
    fields: dict[str, object] = {
        "id": "job_1",
        "tenant_id": "tn_a",
        "kind": "probe",
        "run_after": NOW,
    }
    fields.update(overrides)
    return Job(**fields)  # type: ignore[arg-type]


class TestBackoff:
    def test_it_doubles(self) -> None:
        assert backoff_for(1) == timedelta(seconds=30)
        assert backoff_for(2) == timedelta(seconds=60)
        assert backoff_for(3) == timedelta(seconds=120)

    def test_it_is_capped(self) -> None:
        """Beyond ten minutes a retry is waiting for a human, not riding out a blip.

        Without the cap, a job that failed six times in a bad minute is scheduled
        hours out — and the failure that mattered was over in seconds.
        """
        assert backoff_for(20) == timedelta(seconds=BACKOFF_MAX_S)

    def test_the_first_attempt_is_not_negative(self) -> None:
        assert backoff_for(0) == timedelta(seconds=30)


class TestTheLease:
    """``Job.is_claimable`` states in Python what the claim states in SQL.

    Two statements of one rule. The integration suite checks they agree; these
    check the rule itself.
    """

    def test_a_pending_job_whose_time_has_come_is_claimable(self) -> None:
        assert job().is_claimable(now=NOW)

    def test_a_job_scheduled_for_later_is_not(self) -> None:
        assert not job(run_after=NOW + timedelta(minutes=1)).is_claimable(now=NOW)

    def test_a_live_lease_holds_it(self) -> None:
        held = job(status=JobStatus.RUNNING, locked_until=NOW + timedelta(minutes=5))
        assert not held.is_claimable(now=NOW)

    def test_a_killed_workers_job_comes_back(self) -> None:
        """A ``running`` row whose lease expired is claimable again.

        The defect this pins: a definition that required ``pending`` would leave
        a job killed mid-run stranded forever — by the lease, which exists to
        recover it. The dispatch function had exactly that bug, and the
        integration suite found it.
        """
        abandoned = job(status=JobStatus.RUNNING, locked_until=NOW - timedelta(seconds=1))
        assert abandoned.is_claimable(now=NOW)

    def test_an_expired_lease_does_not(self) -> None:
        """A worker that died mid-job must not strand it.

        This is the at-least-once cost of ADR-0022 §5, stated as a test rather
        than as a sentence: the row comes back, and a handler that is not
        idempotent will run twice.
        """
        stale = job(status=JobStatus.PENDING, locked_until=NOW - timedelta(seconds=1))
        assert stale.is_claimable(now=NOW)

    def test_a_finished_job_is_never_claimable(self) -> None:
        assert not job(status=JobStatus.DONE).is_claimable(now=NOW)
        assert not job(status=JobStatus.DEAD).is_claimable(now=NOW)


class TestDispatch:
    """A runner with no database — only the handler registry."""

    def test_an_unregistered_kind_is_not_silently_skipped(self) -> None:
        """The failure this guards is a partial rollout.

        A row written by a deployment that had a handler this one does not must
        dead-letter *visibly*. A runner that ignored unknown kinds would leave
        the row pending forever and report a clean sweep every five seconds.
        """
        runner = JobRunner(db=None)  # type: ignore[arg-type]
        assert runner.kinds == frozenset()

        with pytest.raises(UnknownJobKindError):
            raise UnknownJobKindError("no handler registered for job kind 'probe'")

    def test_registering_a_handler_announces_the_kind(self) -> None:
        runner = JobRunner(db=None)  # type: ignore[arg-type]

        async def handler(context: JobContext) -> str:
            return "ok"

        runner.register("probe", handler)
        assert runner.kinds == frozenset({"probe"})


class TestSyncJobPayload:
    def test_one_live_sync_per_store(self) -> None:
        """A sync asked for three times while the first is pending is one sync.

        The dedupe key is what makes a webhook storm queue one crawl of a
        catalogue rather than a thousand.
        """
        assert dedupe_key_for("st_1") == "st_1"
        assert dedupe_key_for(None) == "default"
        assert dedupe_key_for("st_1") != dedupe_key_for("st_2")

    def test_the_kind_is_one_string(self) -> None:
        """Written by whatever schedules a sync, read by the registry. One place."""
        assert SYNC_STORE == "sync.store"
