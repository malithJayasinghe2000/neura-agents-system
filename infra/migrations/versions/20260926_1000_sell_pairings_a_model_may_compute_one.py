"""sell_pairings — a pairing may be computed by a model, but never while a shopper waits

ADR-0045. One row per (tenant, store, product): the ids a background computation
found, the kinds it searched for, and the fingerprint of the product text it read.

**It holds a pairing, never an availability.** No price, no stock level, no
status and no title — all four are read live from the merchant's shop on the
request that renders them, so this table cannot state a fact about a catalogue
that has since moved. `source_hash` is what expires it: when the merchant
rewrites the description, the hash stops matching and the row stops being used.

**And never a shopper.** The key is a product, not a person. There is no
session, visitor or cookie column here, because what is cached is *what goes
with a walking boot* — the same answer for everyone who has one in a basket
(ADR-0042).

The ordinary tenant policy, and nothing else: `sell_pairings` carries
`tenant_id`, so the ADR-0008 protection test covers it automatically — enabled,
forced, and a policy, or the integration suite fails. There is no second policy
here, unlike `sell_feeds`: nothing reads a pairing without already knowing whose
it is.

Revision ID: 2a9f5d07c3b1
Revises: 5b7e2c1904af
Create Date: 2026-09-26 10:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2a9f5d07c3b1"
down_revision: str | None = "5b7e2c1904af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "sell_pairings"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column(
            "suggested_ids", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("kinds", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("prompt_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("note", sa.Text, nullable=False, server_default=""),
        # One pairing per product per store. The upsert infers this constraint
        # by name, so a recomputation replaces the row rather than accumulating
        # a history nothing reads.
        sa.UniqueConstraint("tenant_id", "store_id", "product_id", name="uq_sell_pairings_product"),
    )
    op.create_index(
        "ix_sell_pairings_tenant_store_product", TABLE, ["tenant_id", "store_id", "product_id"]
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
    op.drop_index("ix_sell_pairings_tenant_store_product", table_name=TABLE)
    op.drop_table(TABLE)
