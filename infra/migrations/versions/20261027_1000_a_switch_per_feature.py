"""tenant_switches — FiveNeurals may switch off one feature for one shop

ADR-0065. One row per shop and feature key that an admin has changed; no row
means on. Tenant-scoped with the ordinary policy, like every shop table, and
removed with its shop by ``remove_tenant``, which reads every table with a
``tenant_id``.

Revision ID: 2c8e6a4f9d31
Revises: 7a3d5c9e1b20
Create Date: 2026-10-27 10:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c8e6a4f9d31"
down_revision: str | None = "7a3d5c9e1b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_switches",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_by", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "key", name=op.f("pk_tenant_switches")),
    )
    op.execute("ALTER TABLE tenant_switches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_switches FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON tenant_switches
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_switches")
    op.drop_table("tenant_switches")
