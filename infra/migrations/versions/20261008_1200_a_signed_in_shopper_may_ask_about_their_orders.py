"""customer_secrets — a signed-in shopper may ask about their orders

ADR-0057 §3. One table, tenant-scoped with the ordinary policy: the secret the
shop's server signs customer passes with, one per tenant, sealed exactly like
``shop_tokens``. Not a hash, because NEURA must use it to check a signature.
*Make a new one* overwrites the row.

**Holds no shopper.** The one person recorded is the merchant's own console user
who made the secret.

Revision ID: 3c8e5a1d9f42
Revises: 7b3d1f6e2a90
Create Date: 2026-10-08 12:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c8e5a1d9f42"
down_revision: str | None = "7b3d1f6e2a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_secrets",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("wrapped_dek", sa.Text(), nullable=False),
        sa.Column("made_by", sa.String(64), nullable=False),
        sa.Column(
            "made_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_customer_secrets")),
    )
    op.execute("ALTER TABLE customer_secrets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customer_secrets FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON customer_secrets
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON customer_secrets")
    op.drop_table("customer_secrets")
