"""wanted_items, wanted_hides — GROW's Shoppers asked for

ADR-0068. Two tables, each tenant-scoped with the ordinary policy:

* ``wanted_items``: one row per reply NEURA-GROW's nightly job found said the
  shop does not have a kind of product the shopper asked for: the conversation,
  a short label and a short question, both checked in code first.
* ``wanted_hides``: *Hide*, per label, and who pressed it.

**A row is derived from a shopper's words, so it goes with its conversation**
(ADR-0042 §3: the deletion ships with the storage, in the same change):
``ConversationRepository.delete_older_than`` deletes it, and shop removal knows
both tables (G76).

Revision ID: 8e2a4c6f1d57
Revises: 5d1b7e3a9c42
Create Date: 2026-10-28 18:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e2a4c6f1d57"
down_revision: str | None = "5d1b7e3a9c42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("wanted_items", "wanted_hides")


def upgrade() -> None:
    op.create_table(
        "wanted_items",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("message_id", sa.String(64), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column("question", sa.String(60), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prompt_revision", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("tenant_id", "message_id", name=op.f("pk_wanted_items")),
    )
    op.create_index("ix_wanted_items_recent", "wanted_items", ["tenant_id", "asked_at"])
    op.create_index(
        "ix_wanted_items_conversation", "wanted_items", ["tenant_id", "conversation_id"]
    )

    op.create_table(
        "wanted_hides",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("label", sa.String(40), nullable=False),
        sa.Column(
            "hidden_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("hidden_by", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "label", name=op.f("pk_wanted_hides")),
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
    op.drop_table("wanted_hides")
    op.drop_index("ix_wanted_items_conversation", table_name="wanted_items")
    op.drop_index("ix_wanted_items_recent", table_name="wanted_items")
    op.drop_table("wanted_items")
