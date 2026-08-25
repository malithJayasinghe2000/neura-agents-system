"""job queue: durable background work, and the one read that crosses tenants

One table and three schema objects that are not a table.

``job_queue`` carries a ``tenant_id`` and is therefore protected by hand below —
SQLAlchemy does not model Row-Level Security, so ``--autogenerate`` cannot write
the policy and ``tests/integration/test_migrations.py`` is what stops that being
forgotten. It takes the plain
``tenant_id = current_setting('app.tenant_id')`` policy, like the other sixteen.

**The rest of this file is the answer to open question P7**, and it is the first
deliberate cross-tenant read in the system. Under ADR-0008 no transaction can
enumerate tenants, so a worker cannot ask "whose work is due?" — and a job table
with a ``tenant_id`` column does not change that. It makes the *data* safe and
leaves the *dispatch* exactly as impossible. The second half is:

* ``neura_scheduler`` — a role with **no LOGIN and no BYPASSRLS**, holding a
  column-level ``SELECT`` grant on ``job_queue`` that **excludes ``payload``**.
  Nothing connects as it.
* ``scheduler_dispatch`` — a policy granting that role, and only that role, rows
  regardless of tenant. Column grant and policy must *both* pass, so the role
  can see that a job exists and never what it is about.
* ``neura_due_tenants(as_of)`` — ``SECURITY DEFINER``, owned by that role,
  returning ``SETOF text``. One column. A few lines of static SQL, no dynamic
  statement, pinned ``search_path``. ``neura_app`` may ``EXECUTE`` it and has no
  other route to the exemption.

**Its predicate includes ``running`` rows whose lease has expired**, and that is
not tidiness. A worker killed mid-job leaves a row in ``running``; a dispatcher
that looked only at ``pending`` would never name that tenant again, and the job
would be stranded forever by the very mechanism meant to recover it. The rule is
one sentence — *the time has come and no live lease holds it* — and it is stated
three times, in this function, in ``JobQueue.claim`` and in ``Job.is_claimable``,
with a test that they agree.

Everything after that call happens in an ordinary tenant-scoped session. The
accepted cost is stated in ADR-0022 rather than buried: a role exists that can
see, for every tenant, that a job is pending and when — tenant ids and timing,
no merchant content.

Revision ID: 4c1a7d0b93ef
Revises: ee39cb6df54d
Created: 2026-08-26 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4c1a7d0b93ef"
down_revision: str | None = "ee39cb6df54d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "job_queue"
SCHEDULER_ROLE = "neura_scheduler"
DUE_TENANTS = "neura_due_tenants"

#: Everything the dispatch role may read. `payload` and `last_error` are absent
#: on purpose: one carries a job's contents, the other can carry a fragment of a
#: merchant's server response.
SCHEDULER_COLUMNS = "tenant_id, status, run_after, locked_until"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), server_default="", nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_queue")),
        sa.UniqueConstraint(
            "tenant_id", "kind", "dedupe_key", name="uq_job_queue_tenant_kind_dedupe"
        ),
    )
    # The dispatch scan, across tenants. Read only by neura_due_tenants().
    op.create_index("ix_job_queue_status_run_after", TABLE, ["status", "run_after"], unique=False)
    # The claim, inside one tenant's session — a different leading column, so a
    # different index. Neither is habit.
    op.create_index(
        "ix_job_queue_tenant_id_status_run_after",
        TABLE,
        ["tenant_id", "status", "run_after"],
        unique=False,
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {TABLE}
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON {TABLE} TO neura_app;
            END IF;
        END
        $$
        """
    )

    # ── The dispatch role ────────────────────────────────────────────────────
    #
    # Created unconditionally, and the migration FAILS if the role cannot be
    # created. Every other role reference in this repository is guarded with
    # `IF EXISTS` because a missing `neura_app` only means a developer is running
    # as the owner. This one is different: skipping it would leave a deployment
    # whose scheduler silently finds no work, which is precisely the silent
    # failure mode ADR-0022 exists to remove. A migration role without
    # CREATEROLE should stop the deploy and say so.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{SCHEDULER_ROLE}') THEN
                CREATE ROLE {SCHEDULER_ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    # Reassigning ownership below requires membership unless we are a superuser.
    op.execute(f"GRANT {SCHEDULER_ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {SCHEDULER_ROLE}")
    # Column-level. The role cannot read `payload` at all, so the exemption is
    # bounded by the grant as well as by the function body.
    op.execute(f"GRANT SELECT ({SCHEDULER_COLUMNS}) ON {TABLE} TO {SCHEDULER_ROLE}")
    # Permissive policies are OR-ed. This one is scoped `TO neura_scheduler`, so
    # it widens nothing for neura_app — the role the application connects as
    # still sees only its own tenant's rows, and a bug in application code cannot
    # reach across.
    op.execute(
        f"""
        CREATE POLICY scheduler_dispatch ON {TABLE}
            FOR SELECT TO {SCHEDULER_ROLE}
            USING (true)
        """
    )

    # ── The one function that crosses a tenant boundary ──────────────────────
    # A plain string, not an f-string: a migration describes the schema as it
    # stood at this revision, and a constant here would let a later rename
    # silently change what this revision did.
    op.execute(
        """
        CREATE FUNCTION neura_due_tenants(as_of timestamptz)
            RETURNS SETOF text
            LANGUAGE sql
            STABLE
            SECURITY DEFINER
            SET search_path = public, pg_temp
        AS $$
            SELECT DISTINCT tenant_id
            FROM job_queue
            WHERE status IN ('pending', 'running')
              AND run_after <= as_of
              AND (locked_until IS NULL OR locked_until <= as_of)
        $$
        """
    )
    op.execute(f"ALTER FUNCTION {DUE_TENANTS}(timestamptz) OWNER TO {SCHEDULER_ROLE}")
    # PUBLIC gets EXECUTE on a new function by default. Revoked first, then
    # granted to exactly one role — the order matters, and getting it backwards
    # is how a "restricted" function ends up callable by everyone.
    op.execute(f"REVOKE ALL ON FUNCTION {DUE_TENANTS}(timestamptz) FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT EXECUTE ON FUNCTION {DUE_TENANTS}(timestamptz) TO neura_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {DUE_TENANTS}(timestamptz)")
    op.execute(f"DROP POLICY IF EXISTS scheduler_dispatch ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_job_queue_tenant_id_status_run_after", table_name=TABLE)
    op.drop_index("ix_job_queue_status_run_after", table_name=TABLE)
    op.drop_table(TABLE)
    # The role outlives the table only if something else came to depend on it.
    # `DROP OWNED` first, or the DROP fails on the grants we just made.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{SCHEDULER_ROLE}') THEN
                DROP OWNED BY {SCHEDULER_ROLE};
                DROP ROLE {SCHEDULER_ROLE};
            END IF;
        END
        $$
        """
    )
