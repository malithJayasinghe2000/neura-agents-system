"""The ``retention.sweep`` job — the settings in ``.env`` become deletions that run.

[ADR-0042 §3](../../../../../docs/architecture/adr/0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md)
requires the first feature that holds personal data to ship *"a job, not a
documented intention"*. [ADR-0044](../../../../../docs/architecture/adr/0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)
phase 1 is that feature. One pass deletes, for one tenant:

* **observed events** older than ``RETENTION_OBSERVED_EVENTS_DAYS`` — or **all**
  of them, if the tenant has no data-processing agreement on record. That is
  removal on resolution: without an agreement there is no reason to hold any.
* **conversations** untouched for ``RETENTION_CONVERSATIONS_DAYS``, with their
  messages and checkpointed state (``ConversationRepository.delete_older_than``).

**How it keeps running without a cron.** ADR-0022 has no recurring schedule, on
purpose, and this adds none. It uses the pattern ``webhook.drain`` already
proved: **one live job per tenant that re-arms itself while there is anything
left to expire**, and finishes when there is not. Every write that creates
something to expire — a new conversation, a stored event — enqueues it inside
its own transaction, and the dedupe key folds that onto the live job. So:

    **nothing can be written that no sweep is booked to delete.**

A tenant holding nothing has no job at all, and the first thing it stores books
one. The sweep, the *"is anything left?"* read and the job's next state share a
transaction, for the race ``webhook.drain`` documents: a write committed between
a separate read and a separate completion would attach to a job about to finish.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from neura_agent_core.conversations import ConversationRepository
from neura_api.jobs.runner import JobContext
from neura_core import Settings, get_logger
from neura_core.jobs import Job, JobQueue
from neura_core.observation import ObservedEventRepository
from neura_core.tenancy import TenantRepository

log = get_logger(__name__)

#: The job kind. Written by whatever stored something, read by the registry.
RETENTION_SWEEP = "retention.sweep"

#: One live sweep per tenant. There is one set of tables to sweep, so a key per
#: write would queue a job per page view and have each of them sweep the same
#: rows.
RETENTION = "retention"

#: How often a tenant holding anything is swept. Retention is counted in days,
#: so a daily pass holds a row at most one day past its period — and a tighter
#: loop would spend most of its passes deleting nothing.
SWEEP_INTERVAL = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class SweepResult:
    events_deleted: int
    conversations_deleted: int
    #: ``True`` when the tenant had no agreement, so every event went.
    no_agreement: bool
    #: Whether anything is left for a later pass — decides whether it re-arms.
    remaining: bool

    def summary(self) -> str:
        why = " (no agreement: all)" if self.no_agreement and self.events_deleted else ""
        return (
            f"{self.events_deleted} observed event(s){why} · "
            f"{self.conversations_deleted} conversation(s) deleted"
            + ("" if self.remaining else " · nothing left, not re-armed")
        )


async def enqueue_sweep(session: Any, tenant_id: str, *, now: datetime | None = None) -> Job:
    """Book a sweep, **inside the caller's transaction**. A no-op if one is live.

    Called by every write that creates something to expire. Taking a session
    rather than a ``Database`` is what makes the property above true: the row and
    the booking commit together, or neither does.
    """
    return await JobQueue(session).enqueue(
        tenant_id,
        RETENTION_SWEEP,
        dedupe_key=RETENTION,
        run_after=(now or datetime.now(UTC)) + SWEEP_INTERVAL,
    )


async def sweep(session: Any, tenant_id: str, *, now: datetime, settings: Settings) -> SweepResult:
    """One pass for one tenant, in the caller's (tenant-scoped) transaction."""
    tenant = await TenantRepository(session).get(tenant_id)
    events = ObservedEventRepository(session)
    no_agreement = tenant is None or not tenant.may_hold_personal_data
    if no_agreement:
        events_deleted = await events.delete_all(tenant_id)
    else:
        events_deleted = await events.delete_older_than(
            tenant_id, now - timedelta(days=settings.retention_observed_events_days)
        )

    conversations = ConversationRepository(session)
    conversations_deleted = await conversations.delete_older_than(
        tenant_id, now - timedelta(days=settings.retention_conversations_days)
    )

    remaining = await events.any_for(tenant_id) or await conversations.any_for(tenant_id)
    return SweepResult(
        events_deleted=events_deleted,
        conversations_deleted=conversations_deleted,
        no_agreement=no_agreement,
        remaining=remaining,
    )


class RetentionSweepHandler:
    """Runs one ``retention.sweep`` job, then re-arms or finishes."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(self, context: JobContext) -> str:
        now = datetime.now(UTC)
        async with context.db.tenant_session(context.tenant_id) as session:
            result = await sweep(session, context.tenant_id, now=now, settings=self._settings)
            queue = JobQueue(session)
            if result.remaining:
                await queue.reschedule(context.job.id, run_after=now + SWEEP_INTERVAL)
            else:
                # `complete` is guarded on `running`, so the runner's own
                # completion afterwards is a no-op — as in `webhook.drain`.
                await queue.complete(context.job.id)

        if result.events_deleted or result.conversations_deleted:
            log.info(
                "retention_swept",
                tenant_id=context.tenant_id,
                observed_events=result.events_deleted,
                conversations=result.conversations_deleted,
                no_agreement=result.no_agreement,
            )
        return result.summary()


__all__ = [
    "RETENTION",
    "RETENTION_SWEEP",
    "SWEEP_INTERVAL",
    "RetentionSweepHandler",
    "SweepResult",
    "enqueue_sweep",
    "sweep",
]
