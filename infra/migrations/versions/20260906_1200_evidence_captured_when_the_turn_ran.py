"""evidence captured when the turn ran

[ADR-0034]. One table holding what a shadowed turn actually saw at the store
boundary, so a graded turn can be promoted into an eval case that *runs* rather
than one that asserts a merchant's facts against the July fixture shop.

**Written by hand, like every tenant table here.** SQLAlchemy does not model
Row-Level Security, so ``--autogenerate`` cannot write the policy below and
``tests/integration/test_migrations.py`` is what stops that being forgotten. It
takes the plain ``tenant_id = current_setting('app.tenant_id')`` policy: an
evidence row is written by a request that has already authenticated, so nothing
here needs the widening ``api_keys`` required for the authentication bootstrap
(ADR-0014).

**Deliberately not in the audit log.** That table is append-only and
hash-chained because it records our own conduct for somebody auditing it. This
holds a *merchant's catalogue*, it must die with the shadow turn it belongs to
under the merchant's retention policy, and in a hash chain a lawful deletion is
indistinguishable from tampering.

Revision ID: 8c31d4a70f52
Revises: 3f8a6c04d1b7
Created: 2026-09-06 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8c31d4a70f52"
down_revision: str | None = "3f8a6c04d1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("shadow_evidence",)


def upgrade() -> None:
    op.create_table(
        "shadow_evidence",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("shadow_turn_id", sa.String(length=64), nullable=False),
        # The data model permits several stores per tenant, and two of them may
        # use the same external_id for different products. A bundle that could
        # not say which store it came from is a quiet way to replay the wrong
        # catalogue (ADR-0034 §7).
        sa.Column("store_id", sa.String(length=64), nullable=False),
        # Not unique: two turns may legitimately capture the same shop, and they
        # then share one exported fixture file (ADR-0034 §4).
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("bundle", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "shadow_turn_id", name=op.f("pk_shadow_evidence")),
    )
    op.create_index(
        "ix_shadow_evidence_hash",
        "shadow_evidence",
        ["tenant_id", "content_hash"],
        unique=False,
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
    op.drop_index("ix_shadow_evidence_hash", table_name="shadow_evidence")
    op.drop_table("shadow_evidence")
