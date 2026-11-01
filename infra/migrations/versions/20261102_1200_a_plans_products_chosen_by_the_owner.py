"""calendar_plans.owner_products: the products the owner chose for a plan

D20 (R124 to R127), ADR-0076. On a ready plan the owner may add, replace or
remove products, 1 to 3, sold out or not, and the plan is written again around
them. They are kept on the plan, so a later *Make it again* keeps them too.
``NULL``, every plan made before this and every plan the owner has not changed:
the AI chooses from the products in stock (ADR-0072 §5).

Revision ID: 9c4e2a7b1d36
Revises: 7b3d5e9a2c41
Create Date: 2026-11-02 12:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c4e2a7b1d36"
down_revision: str | None = "7b3d5e9a2c41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("calendar_plans", sa.Column("owner_products", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("calendar_plans", "owner_products")
