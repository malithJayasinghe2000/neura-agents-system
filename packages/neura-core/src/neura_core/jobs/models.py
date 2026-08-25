"""What a background job *is*, independently of how it is stored or run."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    PENDING = "pending"
    """Queued, or waiting out a backoff. The only status the dispatcher looks
    for."""

    RUNNING = "running"
    """Claimed, with a lease. A worker that dies leaves a row here whose
    ``locked_until`` is in the past — see :func:`Job.is_claimable`."""

    DONE = "done"

    DEAD = "dead"
    """Every attempt was used. Kept and readable in the tenant's own session, for
    the reason a dead-lettered webhook is kept: work that vanishes quietly is a
    defect a merchant finds."""


class Job(BaseModel):
    """One unit of background work, for one tenant."""

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    #: Free-form, and matched against a handler registry at run time. Never an
    #: enum: a deployment that has not shipped a handler for a kind must still be
    #: able to read the row and dead-letter it (ADR-0022 §6).
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    run_after: datetime = Field(default_factory=lambda: datetime.now(UTC))
    attempts: int = 0
    max_attempts: int = 5
    locked_until: datetime | None = None
    last_error: str = ""
    dedupe_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def is_claimable(self, *, now: datetime) -> bool:
        """Whether this row would be picked up by a claim running at ``now``.

        The rule is one sentence: **the time has come and no live lease holds
        it.** ``running`` is included on purpose — a worker killed mid-job leaves
        a row in that status, and a definition that excluded it would strand the
        job forever by the mechanism meant to recover it.

        Expressed here as well as in SQL because it is the definition of the
        lease, and a test that checks the Python against the SQL is checking two
        statements of one rule rather than one statement twice.
        """
        if self.status not in (JobStatus.PENDING, JobStatus.RUNNING):
            return False
        if self.run_after > now:
            return False
        return self.locked_until is None or self.locked_until <= now


#: How long a claimed job is reserved for. Long enough that an ordinary sync of
#: a real catalogue finishes inside it; short enough that a worker killed mid-run
#: does not strand its job for an afternoon. Exceeding it does not cancel the
#: work — it makes the job claimable again, which is exactly the at-least-once
#: cost ADR-0022 §5 accepts rather than hides.
DEFAULT_LEASE = timedelta(minutes=10)

#: First retry after 30s, then 1m, 2m, 4m… capped. Same ladder as the webhook
#: outbox, because it is the same question — how long before a transient failure
#: is worth trying again — and two different answers in one system would be two
#: things to reason about for no gain.
BACKOFF_BASE_S = 30

#: Beyond about ten minutes a retry is no longer riding out a blip; it is waiting
#: for a human. The cap keeps a job that will eventually succeed from being
#: scheduled hours out because it failed six times in a bad minute.
BACKOFF_MAX_S = 600


def backoff_for(attempts: int) -> timedelta:
    """How long to wait before attempt number ``attempts + 1``."""
    seconds = BACKOFF_BASE_S * (2 ** max(attempts - 1, 0))
    return timedelta(seconds=min(seconds, BACKOFF_MAX_S))


__all__ = [
    "BACKOFF_BASE_S",
    "BACKOFF_MAX_S",
    "DEFAULT_LEASE",
    "Job",
    "JobStatus",
    "backoff_for",
]
