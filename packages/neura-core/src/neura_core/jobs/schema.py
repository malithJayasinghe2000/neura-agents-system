"""The ``job_queue`` table.

Defined against ``neura_core.metadata`` so Alembic can diff it. The Row-Level
Security policies, the ``neura_scheduler`` role and the ``neura_due_tenants``
function live in the migration, because SQLAlchemy models none of them.

**This is an ordinary tenant table.** It takes the same
``tenant_id = current_setting('app.tenant_id')`` policy as the other sixteen,
and every read, claim and write of a job happens inside
``Database.tenant_session``. What is *not* ordinary is one function that reads a
single column across tenants so a worker can find out whom to open a session
for — that is ADR-0022, and it lives in the migration next to the policy it
qualifies.

**``kind`` is a string and ``payload`` is ``jsonb``**, for the reason ADR-0021
stored an entity as a document: a typed column per job kind would make
PostgreSQL a second definition of what a job is, and every new kind a migration.
The handler validates its own payload.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from neura_core.db import metadata

JOB_QUEUE_TABLE = "job_queue"

#: The dispatch function of ADR-0022 §2. Named here rather than inline at the
#: call site so that the one place the system crosses a tenant boundary is
#: greppable by name.
DUE_TENANTS_FUNCTION = "neura_due_tenants"

#: The role that owns it. Nothing connects as this — it has no LOGIN, and no
#: BYPASSRLS. Named here for the same reason.
SCHEDULER_ROLE = "neura_scheduler"

job_queue = Table(
    JOB_QUEUE_TABLE,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    # Never an enum: a deployment that has not shipped a handler for a kind must
    # still be able to read the row and dead-letter it, rather than fail to
    # parse a value its Python does not know.
    Column("kind", String(64), nullable=False),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("status", String(16), nullable=False, server_default="pending"),
    # When this becomes eligible. Backoff moves it forward; a job scheduled for
    # later is simply one whose run_after has not arrived.
    Column("run_after", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("max_attempts", Integer, nullable=False, server_default="5"),
    # The lease. A worker that dies leaves this in the past, and the job becomes
    # claimable again — which is why ADR-0022 §5 is at-least-once and says so.
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=False, server_default=""),
    # Optional. When set, one live job per (tenant, kind, key) — so "sync this
    # store" enqueued twice while the first is still pending is one job, and a
    # NULL key means "always a distinct job" because PostgreSQL treats NULLs as
    # distinct in a unique constraint.
    Column("dedupe_key", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("tenant_id", "kind", "dedupe_key", name="uq_job_queue_tenant_kind_dedupe"),
    # The dispatch scan: which tenants are due, across every tenant. Read only
    # by neura_due_tenants().
    Index("ix_job_queue_status_run_after", "status", "run_after"),
    # The claim, inside one tenant's session. A different query with a different
    # leading column, so a different index; neither is habit.
    Index("ix_job_queue_tenant_id_status_run_after", "tenant_id", "status", "run_after"),
)

__all__ = [
    "DUE_TENANTS_FUNCTION",
    "JOB_QUEUE_TABLE",
    "SCHEDULER_ROLE",
    "job_queue",
]
