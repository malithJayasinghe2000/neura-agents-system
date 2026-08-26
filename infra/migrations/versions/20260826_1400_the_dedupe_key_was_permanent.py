"""job queue: a dedupe key must free itself when the job is over

**A defect, found by taking the mechanism to a second surface.** The job queue
shipped hours earlier with a plain
``UNIQUE (tenant_id, kind, dedupe_key)`` constraint, which reads as "one job per
key" and *means* "one job per key, ever". A finished row keeps the key forever,
so:

* a store could be synced exactly **once** — every later ``enqueue_sync`` would
  find the completed row and return it, reporting success while queueing nothing;
* and the webhook drainer, which is about to move onto this queue, would drain a
  tenant's outbox once and then never again.

The first surface hid it: ``make job-check`` asks twice *while the first job is
still live*, so the constraint and the intent agreed there and the check passed
for the wrong reason. Both readings look identical until a second event arrives
after the first job is done.

The fix is to say what was meant. Uniqueness applies to **in-flight rows only**,
so a completed or dead row stays as history without standing in the way of the
next one. The predicate is a partial-index predicate rather than application
logic, because a rule enforced in Python is a rule two concurrent workers can
both pass.

Revision ID: 7b3e5a2c81d4
Revises: 4c1a7d0b93ef
Created: 2026-08-26 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7b3e5a2c81d4"
down_revision: str | None = "4c1a7d0b93ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_job_queue_tenant_kind_dedupe", "job_queue", type_="unique")
    op.create_index(
        "uq_job_queue_live_dedupe",
        "job_queue",
        ["tenant_id", "kind", "dedupe_key"],
        unique=True,
        postgresql_where=op.f("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    # Reversible only if no two finished rows share a key, which is exactly what
    # the new index permits — so this can legitimately fail on a database that
    # has used the fix. That is stated rather than papered over: the repair is to
    # delete the finished duplicates, and deciding which of a merchant's job
    # records to drop is not a migration's call to make silently.
    op.drop_index("uq_job_queue_live_dedupe", table_name="job_queue")
    op.create_unique_constraint(
        "uq_job_queue_tenant_kind_dedupe", "job_queue", ["tenant_id", "kind", "dedupe_key"]
    )
