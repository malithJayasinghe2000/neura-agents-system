"""The ``webhook.drain`` job — and the retirement of the Redis tenant index.

**What moved, and what deliberately did not.** The outbox itself is unchanged:
``webhook_deliveries`` was always a durable, forced-RLS table, and a queue
pointing at a queue would be double bookkeeping. What was wrong was only the
*index* — the Redis set of "which tenants have queued work" that 1.14 kept
outside PostgreSQL because no transaction can enumerate tenants (ADR-0008).

That set carried one cost that was recorded and one that was not:

* **Recorded, as open question P7:** lose the set and the rows are safe but the
  schedule is not, *silently* — an empty ``SMEMBERS`` is indistinguishable from
  "no work".
* **Unrecorded, and worse:** the ``sadd`` had to happen **after** the
  transaction that wrote the deliveries, because an index entry written for a
  transaction that then rolled back would send the drainer looking for rows that
  do not exist. A process that died in between left deliveries with nothing
  pointing at them, permanently.

A job row has neither problem, because it is written **in the same transaction
as the deliveries it describes**. It cannot exist without them and they cannot
exist without it.

**One live drain job per tenant, and it re-arms itself.** A burst of forty
events queues one drain, not forty. When the pass ends with the outbox still
holding something — a delivery four minutes into its backoff, or a second batch
— the job puts *itself* back with ``run_after`` set to when that delivery is
next due, rather than queueing a new one. It finishes only when the outbox is
genuinely empty, which is the only moment the dedupe key is free again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from neura_api.jobs.runner import JobContext
from neura_api.webhooks import WebhookDrainer
from neura_core import get_logger
from neura_core.jobs import Job, JobQueue
from neura_core.webhooks import WebhookRepository

log = get_logger(__name__)

#: The job kind. One string, written by whatever queued the deliveries and read
#: by the registry that dispatches it.
WEBHOOK_DRAIN = "webhook.drain"

#: One live drain per tenant, whatever the event. There is only ever one outbox,
#: so a per-event key would queue a job per delivery and have each of them drain
#: the same table.
OUTBOX = "outbox"

#: The floor on a re-arm. A delivery already due — a second batch, or one whose
#: backoff elapsed while the first pass ran — would otherwise re-arm for *now*
#: and let one tenant hold the worker in a tight loop.
MIN_REARM = timedelta(seconds=2)


async def enqueue_drain(session: Any, tenant_id: str) -> Job:
    """Queue a drain, **inside the caller's transaction**.

    Takes a session rather than a ``Database`` for the property that is the
    whole reason this replaced a Redis set: the job commits with the deliveries,
    or neither does. A helper that opened its own transaction would give that
    away at the first call site — which is exactly how the old ``note()`` had to
    work, and exactly what it cost.
    """
    return await JobQueue(session).enqueue(tenant_id, WEBHOOK_DRAIN, dedupe_key=OUTBOX)


class WebhookDrainHandler:
    """Sends one tenant's due deliveries, then decides whether it is finished.

    A thin adapter over :class:`WebhookDrainer`, which still owns the HTTP
    client, the signing and the retry arithmetic. The drainer lost its loop and
    its index; it did not lose its job.
    """

    def __init__(self, drainer: WebhookDrainer) -> None:
        self._drainer = drainer

    async def __call__(self, context: JobContext) -> str:
        sent = await self._drainer.drain_tenant(context.tenant_id)

        # **The outbox read and the job's next state, in one transaction.**
        #
        # This is the part that has to be atomic, and the reason is a race that
        # would otherwise strand a delivery. `enqueue_drain` runs inside the
        # transaction that writes new deliveries, and dedupes onto whatever live
        # job it finds. If this handler decided "nothing left" in one
        # transaction and the runner closed the job in another, a delivery
        # committed in between would attach to a job that was about to finish.
        #
        # Doing both here closes it, and PostgreSQL is what closes it: the
        # dedupe index is partial on live rows, so an `ON CONFLICT` insert that
        # meets this row mid-update waits for this transaction, re-checks, and
        # finds the row no longer in the index — and inserts its own job.
        async with context.db.tenant_session(context.tenant_id) as session:
            next_due = await WebhookRepository(session).next_due_at(context.tenant_id)
            queue = JobQueue(session)
            if next_due is None:
                # The only state in which this may finish. `complete` is guarded
                # on `running`, so the runner's own completion afterwards is a
                # no-op either way.
                await queue.complete(context.job.id)
            else:
                await queue.reschedule(
                    context.job.id,
                    run_after=max(next_due, datetime.now(UTC) + MIN_REARM),
                )

        # **A failed delivery is not a failed job**, and this returning normally
        # is how that is expressed. The outbox already owns retries — per
        # delivery, with its own backoff ladder and its own dead letter — so
        # raising here would stack a second, coarser retry on top: one
        # unreachable endpoint would drag every other delivery for that tenant
        # into the job's backoff, then dead-letter the *job* while the deliveries
        # were still perfectly alive. The job's only failure is being unable to
        # run at all.
        return f"{sent} delivered" + ("" if next_due is None else f", next due {next_due:%H:%M:%S}")


__all__ = ["MIN_REARM", "OUTBOX", "WEBHOOK_DRAIN", "WebhookDrainHandler", "enqueue_drain"]
