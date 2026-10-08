"""shop_tokens and shop_checks — the shop owner connects their own shop

ADR-0052. Two tables, both tenant-scoped with the ordinary policy:

* ``shop_tokens`` — the shop token NEURA made before the shop is connected, one
  per tenant, sealed exactly like ``tenant_stores.credentials``. *Connect* moves
  it into ``tenant_stores`` and deletes the row.
* ``shop_checks`` — one run of the full check against a shop's bridge, kept
  because the job queue purges finished work and the screen still says when the
  shop last passed. ``store_id`` is NULL before the shop is connected.

**Holds no shopper.** The one person recorded is the merchant's own console user
who made the token or asked for the check.

Revision ID: 7b3d1f6e2a90
Revises: 5e2a9c4d8b17
Create Date: 2026-10-01 12:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7b3d1f6e2a90"
down_revision: str | None = "5e2a9c4d8b17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("shop_tokens", "shop_checks")


def upgrade() -> None:
    op.create_table(
        "shop_tokens",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("credentials", sa.Text(), nullable=False),
        sa.Column("wrapped_dek", sa.Text(), nullable=False),
        sa.Column("made_by", sa.String(64), nullable=False),
        sa.Column(
            "made_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_shop_tokens")),
    )
    op.create_table(
        "shop_checks",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=True),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("requested_by", sa.String(64), nullable=False),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shop_checks")),
    )
    op.create_index("ix_shop_checks_tenant_requested", "shop_checks", ["tenant_id", "requested_at"])

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
    op.drop_index("ix_shop_checks_tenant_requested", table_name="shop_checks")
    op.drop_table("shop_checks")
    op.drop_table("shop_tokens")
