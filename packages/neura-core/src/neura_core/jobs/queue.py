"""Reading and writing the job queue, for one tenant.

Every method takes a session that is already tenant-scoped, so none of them
relies on its own ``WHERE tenant_id`` for safety — Row-Level Security does that,
and a hand-written filter would be the second-best of two defences pretending to
be the first. The explicit predicates that *are* here keep the planner on the
index.

**Nothing in this file crosses a tenant boundary.** Finding out *which* tenants
have work is :mod:`neura_core.jobs.dispatch`, which is one function, one column,
and the only place in the system that does (ADR-0022).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.errors import ConflictError, NeuraError
from neura_core.ids import JOB, new_id
from neura_core.jobs.models import DEFAULT_LEASE, Job, JobStatus, backoff_for
from neura_core.jobs.schema import job_queue

_JOBS = job_queue.c


class CrossTenantJobWriteError(NeuraError):
    """A job write was refused because it names another tenant.

    Row-Level Security doing its job, not a bug in it. Named because it is a
    security event: something upstream resolved the tenant one way and built a
    job another way, and that deserves an alert rather than a driver stack
    trace. Same reasoning, and the same shape, as the sync store's
    ``CrossTenantWriteError``.
    """

    code = "JOB_CROSS_TENANT_WRITE"
    error_type = "permission_error"
    http_status = 403


class JobQueue:
    """The queue, for one tenant, inside one transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(
        self,
        tenant_id: str,
        kind: str,
        *,
        payload: dict[str, Any] | None = None,
        run_after: datetime | None = None,
        max_attempts: int = 5,
        dedupe_key: str | None = None,
        job_id: str | None = None,
    ) -> Job:
        """Queue one job.

        **Called inside the transaction that decided the work is needed**, which
        is the property a Redis set could not have: a `sadd` after a commit
        strands the work if the process dies in between, and here the job row and
        the reason for it commit together or not at all.

        With a ``dedupe_key``, a second enqueue while the first is still live
        returns the *existing* job rather than adding a duplicate — "sync this
        store" asked for twice in a minute is one sync. Without one, every call
        is a distinct job, because PostgreSQL treats NULLs in a unique constraint
        as distinct and that is the behaviour wanted here rather than a quirk
        being tolerated.
        """
        record_id = job_id or new_id(JOB)
        values: dict[str, Any] = {
            "id": record_id,
            "tenant_id": tenant_id,
            "kind": kind,
            "payload": payload or {},
            "status": JobStatus.PENDING.value,
            "run_after": run_after or datetime.now(UTC),
            "max_attempts": max_attempts,
            "dedupe_key": dedupe_key,
        }

        try:
            if dedupe_key is None:
                await self._session.execute(pg_insert(job_queue).values(**values))
            else:
                result = await self._session.execute(
                    pg_insert(job_queue)
                    .values(**values)
                    .on_conflict_do_nothing(
                        index_elements=["tenant_id", "kind", "dedupe_key"],
                    )
                    .returning(_JOBS.id)
                )
                won = result.first()
                if won is None:
                    existing = await self.find_by_dedupe(tenant_id, kind, dedupe_key)
                    if existing is not None:
                        return existing
                    # The row that won the conflict has since been cleared. Rare,
                    # and retrying once is the whole of the recovery — reported
                    # rather than looped, because a loop here would spin against
                    # a tenant deleting their own jobs.
                    raise ConflictError(
                        "A job with this dedupe key was created and removed concurrently. Retry.",
                        details={"kind": kind, "dedupe_key": dedupe_key},
                    )
        except IntegrityError as exc:
            raise ConflictError(
                "A job with this dedupe key already exists for this tenant.",
                details={"kind": kind, "dedupe_key": dedupe_key},
            ) from exc
        except DBAPIError as exc:
            raise _translate(exc) from exc

        stored = await self.get(record_id)
        if stored is None:  # pragma: no cover — RLS would have raised first
            raise CrossTenantJobWriteError(
                "the job was inserted but is not readable; this session is "
                "scoped to a different tenant than the job."
            )
        return stored

    async def claim(
        self,
        tenant_id: str,
        *,
        now: datetime | None = None,
        limit: int = 10,
        lease: timedelta = DEFAULT_LEASE,
        kinds: Sequence[str] | None = None,
    ) -> list[Job]:
        """Take up to ``limit`` due jobs and hold them for ``lease``.

        ``FOR UPDATE SKIP LOCKED`` is what makes two workers on one tenant safe:
        the second skips the rows the first is taking rather than blocking behind
        them or claiming them twice.

        **``attempts`` increments here, at claim, and not at failure.** A worker
        that is killed mid-job never reports anything, so a failure-time counter
        would let a job that crashes the process be retried forever. Charging the
        attempt when the work starts means a poison job dead-letters like any
        other.

        A ``running`` row whose lease has expired is claimable, which is what
        makes a killed worker cost a delay rather than a lost job — and is the
        same predicate ``neura_due_tenants`` uses, because a dispatcher that
        named fewer tenants than the claim can serve would strand work it could
        see.
        """
        moment = now or datetime.now(UTC)
        due = (
            select(_JOBS.id)
            .where(_JOBS.tenant_id == tenant_id)
            .where(_JOBS.status.in_((JobStatus.PENDING.value, JobStatus.RUNNING.value)))
            .where(_JOBS.run_after <= moment)
            .where(or_(_JOBS.locked_until.is_(None), _JOBS.locked_until <= moment))
        )
        if kinds is not None:
            due = due.where(_JOBS.kind.in_(list(kinds)))
        due = due.order_by(_JOBS.run_after).limit(limit).with_for_update(skip_locked=True)

        rows = (
            await self._session.execute(
                update(job_queue)
                .where(_JOBS.id.in_(due.scalar_subquery()))
                .values(
                    status=JobStatus.RUNNING.value,
                    locked_until=moment + lease,
                    attempts=_JOBS.attempts + 1,
                    updated_at=func.now(),
                )
                .returning(job_queue)
            )
        ).all()
        return sorted((_job_from_row(row) for row in rows), key=lambda job: job.run_after)

    async def complete(self, job_id: str, *, at: datetime | None = None) -> None:
        await self._session.execute(
            update(job_queue)
            .where(_JOBS.id == job_id)
            .values(
                status=JobStatus.DONE.value,
                locked_until=None,
                last_error="",
                updated_at=at or func.now(),
            )
        )

    async def fail(
        self,
        job: Job,
        *,
        error: str,
        at: datetime | None = None,
    ) -> JobStatus:
        """Record a failed run and schedule — or abandon — the next.

        Returns the resulting status so the caller does not re-derive the retry
        arithmetic in order to log what happened.
        """
        moment = at or datetime.now(UTC)
        exhausted = job.attempts >= job.max_attempts
        status = JobStatus.DEAD if exhausted else JobStatus.PENDING

        await self._session.execute(
            update(job_queue)
            .where(_JOBS.id == job.id)
            .values(
                status=status.value,
                # A dead job keeps its last scheduled time rather than gaining a
                # future one nothing will honour.
                run_after=job.run_after if exhausted else moment + backoff_for(job.attempts),
                locked_until=None,
                # Truncated: a handler raising with a whole HTTP response body
                # in the message would otherwise put a document in a column
                # somebody renders.
                last_error=error[:500],
                updated_at=func.now(),
            )
        )
        return status

    async def get(self, job_id: str) -> Job | None:
        row = (await self._session.execute(select(job_queue).where(_JOBS.id == job_id))).first()
        return None if row is None else _job_from_row(row)

    async def find_by_dedupe(self, tenant_id: str, kind: str, dedupe_key: str) -> Job | None:
        row = (
            await self._session.execute(
                select(job_queue)
                .where(_JOBS.tenant_id == tenant_id)
                .where(_JOBS.kind == kind)
                .where(_JOBS.dedupe_key == dedupe_key)
            )
        ).first()
        return None if row is None else _job_from_row(row)

    async def list_for(
        self,
        tenant_id: str,
        *,
        status: JobStatus | None = None,
        limit: int = 50,
    ) -> list[Job]:
        query = select(job_queue).where(_JOBS.tenant_id == tenant_id)
        if status is not None:
            query = query.where(_JOBS.status == status.value)
        rows = (
            await self._session.execute(query.order_by(_JOBS.created_at.desc()).limit(limit))
        ).all()
        return [_job_from_row(row) for row in rows]

    async def purge_finished(self, tenant_id: str, *, older_than: datetime) -> int:
        """Drop completed rows. Dead ones stay.

        The queue is a queue, not a log — the audit log is the log. Dead letters
        are the exception because they are the only record that work was asked
        for and never done.
        """
        result = await self._session.execute(
            delete(job_queue)
            .where(_JOBS.tenant_id == tenant_id)
            .where(_JOBS.status == JobStatus.DONE.value)
            .where(_JOBS.updated_at < older_than)
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def release_expired(self, tenant_id: str, *, now: datetime | None = None) -> int:
        """Return leases that have run out to the pending pool.

        Not strictly required — :meth:`claim` already treats an expired lease as
        claimable — but a row left ``running`` for a day reads as work in
        progress to anyone looking at the table, and a status that lies to an
        operator is its own defect.
        """
        moment = now or datetime.now(UTC)
        result = await self._session.execute(
            update(job_queue)
            .where(_JOBS.tenant_id == tenant_id)
            .where(_JOBS.status == JobStatus.RUNNING.value)
            .where(and_(_JOBS.locked_until.is_not(None), _JOBS.locked_until <= moment))
            .values(status=JobStatus.PENDING.value, locked_until=None, updated_at=func.now())
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)


def _job_from_row(row: Any) -> Job:
    return Job(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        kind=str(row.kind),
        payload=dict(row.payload or {}),
        status=JobStatus(row.status),
        run_after=row.run_after,
        attempts=int(row.attempts),
        max_attempts=int(row.max_attempts),
        locked_until=row.locked_until,
        last_error=str(row.last_error or ""),
        dedupe_key=None if row.dedupe_key is None else str(row.dedupe_key),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _translate(exc: DBAPIError) -> NeuraError:
    detail = str(getattr(exc, "orig", exc)).lower()
    if "row-level security" in detail or "row level security" in detail:
        return CrossTenantJobWriteError(
            "the database refused a job write — this transaction is scoped to a "
            "different tenant than the job being written. Row-Level Security "
            "worked; something upstream resolved the tenant inconsistently."
        )
    return NeuraError(f"job queue write failed: {exc}")


__all__ = ["CrossTenantJobWriteError", "JobQueue"]
