"""waiting_answers — a handed-over shopper may leave an email

ADR-0062. One table, tenant-scoped with the ordinary policy: one row per chat a
shop's team may answer later, by email, from the shop's own email app. Either an
address the shopper typed after the handover (``reach = 'email'``), or a
signed-in customer whose address the shop already holds (``reach = 'customer'``,
with nothing of theirs copied here: a check constraint keeps ``email`` empty).

**The only shopper data is ``email``, and it does not outlive its purpose:**
*Mark as answered* sets it to ``NULL``, and the ``retention.sweep`` job deletes an
unanswered row after ``RETENTION_HANDOVER_EMAILS_DAYS`` (30); a deleted
conversation takes its row with it (ADR-0042 §3: the deletion ships with the
storage, in the same change).

Revision ID: 4f1c7d2e8a63
Revises: 9b4e7a2c5d18
Create Date: 2026-10-11 20:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4f1c7d2e8a63"
down_revision: str | None = "9b4e7a2c5d18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "waiting_answers",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("reach", sa.String(16), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_by", sa.String(64), nullable=True),
        sa.CheckConstraint("reach IN ('email', 'customer')", name=op.f("ck_waiting_answers_reach")),
        sa.CheckConstraint(
            "reach = 'email' OR email IS NULL",
            name=op.f("ck_waiting_answers_customer_has_no_email"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "conversation_id", name=op.f("pk_waiting_answers")),
    )
    op.create_index(
        "ix_waiting_answers_open",
        "waiting_answers",
        ["tenant_id", "answered_at", "created_at"],
    )
    op.execute("ALTER TABLE waiting_answers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE waiting_answers FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON waiting_answers
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON waiting_answers")
    op.drop_index("ix_waiting_answers_open", table_name="waiting_answers")
    op.drop_table("waiting_answers")
