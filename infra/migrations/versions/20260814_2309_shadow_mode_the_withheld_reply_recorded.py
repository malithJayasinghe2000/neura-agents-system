"""shadow mode — the withheld reply, recorded

Milestone 1.15. One table, carrying a ``tenant_id`` and therefore protected by
hand below: SQLAlchemy does not model Row-Level Security, so ``--autogenerate``
cannot write the policies and ``tests/integration/test_migrations.py`` is what
stops that being forgotten. It takes the plain
``tenant_id = current_setting('app.tenant_id')`` policy — a shadow row is written
by a request that has already authenticated, so nothing here needs the widening
``api_keys`` required for the authentication bootstrap (ADR-0014).

**This table holds text a shopper never saw, and that is the point of it.** A
shadow turn's draft is kept out of ``conversation_messages`` deliberately: a reply
nobody read must not become history the next turn answers against. The retention
consequence is the same as the transcript's, though, and is honoured the same way
— the draft is stored **tokenised**, so a queue a merchant reads for six weeks
does not become a long-term store of card numbers (security-model.md §6.2).

Revision ID: d925127b574b
Revises: cefdd346a90b
Created: 2026-08-14 23:09:06.013211
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d925127b574b"
down_revision: str | None = "cefdd346a90b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("shadow_turns",)


def upgrade() -> None:
    op.create_table(
        "shadow_turns",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("agent_key", sa.String(length=64), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("draft", sa.Text(), nullable=False),
        sa.Column("escalated", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=True),
        sa.Column("verify_reason", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "tools", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False
        ),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prompt_revision", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_shadow_turns")),
    )
    op.create_index(
        "ix_shadow_turns_tenant_recent",
        "shadow_turns",
        ["tenant_id", "created_at", "id"],
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
    op.drop_index("ix_shadow_turns_tenant_recent", table_name="shadow_turns")
    op.drop_table("shadow_turns")
