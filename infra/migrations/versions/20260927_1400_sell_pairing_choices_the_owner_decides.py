"""sell_pairing_choices — the shop owner may choose a product's suggestions

ADR-0050. One row per (tenant, store, product) the owner has chosen for: an
ordered list of their own product ids, or an empty list meaning *show nothing*.
No row means automatic — the model's stored pairing or the word path.

Separate from ``sell_pairings`` because the lifecycles are opposite: a computed
pairing is overwritten on recomputation and ignored when the product's text
changes, and an owner's choice must survive both.

**Holds no shopper.** Keyed by a product, like ``sell_pairings``; the one person
recorded is the merchant's own console user who made the choice. The ordinary
tenant policy, and the ADR-0008 protection test covers it automatically.

Revision ID: 5e2a9c4d8b17
Revises: 3c8e6f1a9d24
Create Date: 2026-09-27 14:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5e2a9c4d8b17"
down_revision: str | None = "3c8e6f1a9d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "sell_pairing_choices"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column(
            "chosen_ids", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("chosen_by", sa.String(64), nullable=False),
        sa.Column(
            "chosen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id", "store_id", "product_id", name=op.f("pk_sell_pairing_choices")
        ),
    )

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {TABLE}
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_table(TABLE)
