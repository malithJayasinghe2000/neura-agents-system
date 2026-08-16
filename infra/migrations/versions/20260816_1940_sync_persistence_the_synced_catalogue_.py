"""sync persistence: the synced catalogue survives a restart

Two tables, both carrying a ``tenant_id`` and therefore protected by hand below:
SQLAlchemy does not model Row-Level Security, so ``--autogenerate`` cannot write
the policies and ``tests/integration/test_migrations.py`` is what stops that
being forgotten. Both take the plain
``tenant_id = current_setting('app.tenant_id')`` policy — a sync runs for a
tenant that is already known, so nothing here needs the widening ``api_keys``
required for the authentication bootstrap (ADR-0014).

**This closes the seam that has been open since milestone 1.8.** ``EntityStore``
and ``SyncStateStore`` existed with only in-memory implementations, so a restart
lost the whole synced catalogue and every backfill started from zero.

``synced_entities.document`` is the canonical entity as ``neura-domain``
serialises it, not a column per field (ADR-0021). The alternative would make
PostgreSQL a second definition of the domain model, and nothing queries a synced
entity's contents: RAG has ``document_chunks``, and orders and customers are
read live through the adapter rather than synced.

**Both primary keys are natural and composite**, matching ``EntityKey`` and
``SyncKey`` exactly. A surrogate id would allow two rows for one entity — the
one failure the store contract says must be structurally impossible, given that
webhooks arrive twice and backfills overlap incrementals. No secondary index on
either table: every read filters on a prefix of the primary key.

Revision ID: ee39cb6df54d
Revises: 1e66abd53607
Created: 2026-08-16 19:40:37.909108
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ee39cb6df54d"
down_revision: str | None = "1e66abd53607"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("synced_entities", "sync_checkpoints")


def upgrade() -> None:
    op.create_table(
        "sync_checkpoints",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.Column("updated_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_count", sa.Integer(), server_default="0", nullable=False),
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
        sa.PrimaryKeyConstraint(
            "tenant_id", "platform", "entity_type", name=op.f("pk_sync_checkpoints")
        ),
    )
    op.create_table(
        "synced_entities",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("neura_id", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint(
            "tenant_id", "platform", "entity_type", "external_id", name=op.f("pk_synced_entities")
        ),
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
            """
        )
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO neura_app;
                END IF;
            END
            $$
            """
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("synced_entities")
    op.drop_table("sync_checkpoints")
