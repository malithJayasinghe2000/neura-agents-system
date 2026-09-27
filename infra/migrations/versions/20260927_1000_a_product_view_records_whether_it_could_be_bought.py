"""observed_events.in_stock — a product view records whether it could be bought

ADR-0049. ADR-0046 stage 1 counts views of a product that was sold out *when it
was viewed*, and that cannot be worked out afterwards: a product restocked on
Friday reads as in stock on Saturday, which would erase exactly the demand the
count exists to show.

Nullable, and NULL means **unknown**, never sold out: a basket add has no value
(it is in stock by definition), and an event stored before this column existed
has none either. There are no such rows today — phase 1's test events were
deleted on 2026-09-26.

Revision ID: 3c8e6f1a9d24
Revises: 7d4e1b9a2c60
Create Date: 2026-09-27 10:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c8e6f1a9d24"
down_revision: str | None = "7d4e1b9a2c60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("observed_events", sa.Column("in_stock", sa.Boolean, nullable=True))


def downgrade() -> None:
    op.drop_column("observed_events", "in_stock")
