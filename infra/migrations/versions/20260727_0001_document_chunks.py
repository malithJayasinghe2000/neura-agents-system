"""document_chunks — vectors, namespaced by (tenant_id, embedding_model)

The first migration in the project, so it also establishes the two conventions
every table after it follows:

**1. Row-Level Security, from the first table.** ADR-0008 commits to isolation
existing before there is a second tenant, because retrofitting it means
revisiting every query ever written. The policy below reads
``app.tenant_id``, which ``neura_core.Database.tenant_session`` sets per
transaction.

**2. FORCE ROW LEVEL SECURITY, not merely ENABLE.** PostgreSQL exempts a table's
*owner* from its own RLS policies unless forced. In development the application
connects as the database owner, so ``ENABLE`` alone would leave isolation
switched off exactly where it is being developed and tested — and switched on
only in production, where discovering a bug in it is expensive. ``FORCE`` means
the tests that prove cross-tenant reads return nothing are testing the thing
that runs.

The cost of FORCE is that maintenance queries by the owner are also filtered.
That is the correct trade: a maintenance query that needs to cross tenants
should have to say so.

Revision ID: 0001
Revises:
Created: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "document_chunks"
POLICY = "tenant_isolation"


def upgrade() -> None:
    # Present already via infra/docker/init-db.sql on a fresh container, but a
    # migration that only works on a database this repo created is not a
    # migration. A merchant's managed Postgres will not have run that file.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        # `embedding vector NOT NULL` is added below in raw DDL — SQLAlchemy has
        # no vector type and a dependency for one column is not worth it.
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(255), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "tenant_id",
            "embedding_model",
            "source_type",
            "source_id",
            "chunk_index",
            name="uq_document_chunks_namespace_source_chunk",
        ),
    )

    # Deliberately dimensionless: the reindex procedure requires vectors of two
    # different sizes to coexist while a new embedder is evaluated against the
    # old one (docs/architecture/llm-abstraction.md §5.2).
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN embedding vector NOT NULL")

    # Every read filters the namespace first. No HNSW/IVFFlat index here:
    # pgvector requires a fixed dimension for those, and this column has none by
    # design. At ADR-0005's stated scale a filtered scan inside one namespace is
    # fine, and this index is what keeps that scan small.
    op.create_index(
        "ix_document_chunks_namespace_source_type",
        TABLE,
        ["tenant_id", "embedding_model", "source_type"],
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY} ON {TABLE}
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )

    # `true` above means "return NULL if unset" rather than raising. A
    # transaction that never set the tenant therefore compares against NULL and
    # matches nothing — the loud-but-recoverable failure, not the leak.

    # The dev stack's non-superuser app role (infra/docker/init-db.sql). Guarded
    # because a managed Postgres elsewhere will not have it, and a migration
    # that fails on a database it did not create is not portable.
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


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.drop_index("ix_document_chunks_namespace_source_type", table_name=TABLE)
    op.drop_table(TABLE)
