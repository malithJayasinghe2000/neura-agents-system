"""page_gaps, page_gap_fixes, page_gap_scans — GROW's Missing from your pages

ADR-0064. Three tables, each tenant-scoped with the ordinary policy:

* ``page_gaps``: one row per reply NEURA-GROW's nightly job found could not
  answer a fact the shop's pages could state (handed over, or answered only
  half): the conversation, the product it looked at (or none, for a fact about
  the shop), a short label and a short question, both checked in code first.
* ``page_gap_fixes``: *I added it*, per product and label, and who pressed it.
* ``page_gap_scans``: how far the job has read each shop's chats.

**A gap is derived from a shopper's words, so it goes with its conversation**
(ADR-0042 §3: the deletion ships with the storage, in the same change):
``ConversationRepository.delete_older_than`` deletes it, and shop removal knows
all three tables (G76).

Revision ID: 7a3d5c9e1b20
Revises: 4f1c7d2e8a63
Create Date: 2026-10-25 16:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7a3d5c9e1b20"
down_revision: str | None = "4f1c7d2e8a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("page_gaps", "page_gap_fixes", "page_gap_scans")


def upgrade() -> None:
    op.create_table(
        "page_gaps",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("message_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("product_id", sa.String(128), nullable=True),
        sa.Column("fact", sa.String(40), nullable=False),
        sa.Column("question", sa.String(60), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_revision", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "kind IN ('handed_over', 'half_answered')", name=op.f("ck_page_gaps_kind")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "message_id", name=op.f("pk_page_gaps")),
    )
    op.create_index("ix_page_gaps_recent", "page_gaps", ["tenant_id", "asked_at"])
    op.create_index("ix_page_gaps_conversation", "page_gaps", ["tenant_id", "conversation_id"])

    op.create_table(
        "page_gap_fixes",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("product_key", sa.String(128), nullable=False),
        sa.Column("fact", sa.String(40), nullable=False),
        sa.Column(
            "fixed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("fixed_by", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "product_key", "fact", name=op.f("pk_page_gap_fixes")),
    )

    op.create_table(
        "page_gap_scans",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("scanned_until", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_page_gap_scans")),
    )

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
            """
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("page_gap_scans")
    op.drop_table("page_gap_fixes")
    op.drop_index("ix_page_gaps_conversation", table_name="page_gaps")
    op.drop_index("ix_page_gaps_recent", table_name="page_gaps")
    op.drop_table("page_gaps")
