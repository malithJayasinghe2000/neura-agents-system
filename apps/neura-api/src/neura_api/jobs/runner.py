"""The worker loop: find whom to work for, then work for them.

The queue itself is ``neura_core.jobs``; this is the part that needs a clock, a
handler registry and a process to run in, all of which belong to the deployable
rather than to shared infrastructure. Same split as the webhook outbox and its
drainer.

**How this finds work under Row-Level Security.** No transaction can ask "which
jobs are due?" across tenants — a session that has not named a tenant matches no
row anywhere (ADR-0008) — and a ``job_queue`` table with a ``tenant_id`` column
does not change that. So the loop is two steps, and the first is the only place
in this system that crosses a tenant boundary:

1. ``due_tenants()`` — one ``SECURITY DEFINER`` function returning a list of
   tenant ids, and nothing else (ADR-0022).
2. For each id, an ordinary ``tenant_session``: claim, run, complete or fail.

**The worker is told nothing in advance.** It holds no tenant list, no
configuration per merchant, and no store credentials. A tenant created one second
ago, by a different process, is picked up on the next poll — which is the case
that was impossible before this existed.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from neura_core import Database, get_logger
from neura_core.jobs import DEFAULT_LEASE, Job, JobQueue, JobStatus, due_tenants

log = get_logger(__name__)

#: How often the loop wakes. Background work is not latency-critical — a
#: catalogue sync a few seconds late is a catalogue sync — and a tighter loop
#: would spend most of its time asking PostgreSQL for an empty list.
POLL_INTERVAL_S = 5.0

#: How many jobs one tenant may have claimed at once by one poll. A cap rather
#: than a fairness algorithm: it stops a tenant with ten thousand queued jobs
#: from occupying a whole sweep, and it is honest about being coarse (ADR-0022).
CLAIM_LIMIT = 5


@dataclass(frozen=True, slots=True)
class JobContext:
    """What a handler is given. Deliberately small.

    It gets the tenant, the payload, and a database it must scope itself. It does
    **not** get an open session: a sync of a real catalogue takes minutes, and a
    handler handed a transaction would hold a connection open for all of it.
    """

    db: Database
    tenant_id: str
    job: Job


Handler = Callable[[JobContext], Awaitable[str]]
"""Runs one job. Returns a one-line summary for the log. Raising means failure,
and the queue decides whether that is a retry or a dead letter."""


class UnknownJobKindError(Exception):
    """No handler is registered for this job's ``kind``.

    Its own exception because it is not a transient failure and it is not the
    tenant's fault: it means a row was written by a deployment that had a handler
    this one does not — a partial rollout, or a rollback. It fails the job like
    any other error, so it dead-letters visibly instead of being skipped.
    """


class JobRunner:
    """Runs whatever the queue holds, one tenant at a time."""

    def __init__(
        self,
        db: Database,
        *,
        poll_interval_s: float = POLL_INTERVAL_S,
        claim_limit: int = CLAIM_LIMIT,
        lease: timedelta = DEFAULT_LEASE,
    ) -> None:
        self._db = db
        self._poll_interval_s = poll_interval_s
        self._claim_limit = claim_limit
        self._lease = lease
        self._handlers: dict[str, Handler] = {}
        self._task: asyncio.Task[None] | None = None

    def register(self, kind: str, handler: Handler) -> None:
        """Attach a handler to a job kind.

        Registered by the deployable at startup rather than discovered, because a
        queue that imported its own handlers would be a queue that has to change
        every time a new kind of work appears.
        """
        self._handlers[kind] = handler

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(self._handlers)

    async def run_once(self, *, now: datetime | None = None) -> int:
        """One sweep. Returns how many jobs completed successfully."""
        moment = now or datetime.now(UTC)
        completed = 0
        for tenant_id in await due_tenants(self._db, now=moment):
            try:
                completed += await self.run_tenant(tenant_id, now=moment)
            except Exception as exc:  # one tenant must not stop the rest
                log.error("job_sweep_failed", tenant_id=tenant_id, error=str(exc))
                continue
        return completed

    async def run_tenant(self, tenant_id: str, *, now: datetime | None = None) -> int:
        """Claim and run this tenant's due jobs.

        The claim is its own transaction, and so is each completion. A handler
        that takes four minutes must not hold the transaction that claimed it —
        that is what the lease is for, and holding both would make the lease
        pointless while pinning a connection.
        """
        moment = now or datetime.now(UTC)
        async with self._db.tenant_session(tenant_id) as session:
            queue = JobQueue(session)
            await queue.release_expired(tenant_id, now=moment)
            claimed = await queue.claim(
                tenant_id, now=moment, limit=self._claim_limit, lease=self._lease
            )

        completed = 0
        for job in claimed:
            if await self._run(tenant_id, job):
                completed += 1
        return completed

    async def _run(self, tenant_id: str, job: Job) -> bool:
        handler = self._handlers.get(job.kind)
        started = datetime.now(UTC)

        try:
            if handler is None:
                raise UnknownJobKindError(
                    f"no handler registered for job kind {job.kind!r}; "
                    f"this deployment knows {sorted(self._handlers)}"
                )
            summary = await handler(JobContext(db=self._db, tenant_id=tenant_id, job=job))
        except Exception as exc:
            await self._fail(tenant_id, job, f"{type(exc).__name__}: {exc}")
            return False

        async with self._db.tenant_session(tenant_id) as session:
            await JobQueue(session).complete(job.id)

        log.info(
            "job_completed",
            tenant_id=tenant_id,
            job_id=job.id,
            kind=job.kind,
            attempt=job.attempts,
            duration_s=round((datetime.now(UTC) - started).total_seconds(), 3),
            summary=summary,
        )
        return True

    async def _fail(self, tenant_id: str, job: Job, error: str) -> None:
        async with self._db.tenant_session(tenant_id) as session:
            status = await JobQueue(session).fail(job, error=error)

        if status is JobStatus.DEAD:
            # ERROR so it reaches an operator, and the row stays readable in the
            # tenant's own session. Work that was asked for and never done, with
            # nobody told, is a dropped job — the same reasoning as a
            # dead-lettered webhook.
            log.error(
                "job_dead_lettered",
                tenant_id=tenant_id,
                job_id=job.id,
                kind=job.kind,
                attempts=job.attempts,
                last_error=error,
            )
            return

        log.warning(
            "job_failed",
            tenant_id=tenant_id,
            job_id=job.id,
            kind=job.kind,
            attempt=job.attempts,
            of=job.max_attempts,
            error=error,
        )

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the loop must outlive a bad poll
                # This is where a missing migration surfaces: `neura_due_tenants`
                # not existing raises here, every poll, in the log. It cannot
                # present as "nothing to do" — which is exactly how an empty
                # Redis set presented, and the reason P7's cost changed shape.
                log.error("job_runner_error", error=str(exc))
            await asyncio.sleep(self._poll_interval_s)


__all__ = [
    "CLAIM_LIMIT",
    "POLL_INTERVAL_S",
    "Handler",
    "JobContext",
    "JobRunner",
    "UnknownJobKindError",
]
