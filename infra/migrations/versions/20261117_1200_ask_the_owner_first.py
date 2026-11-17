"""calendar_plans: the AI's suggestion, the owner's choice, and *Skip this date*

D21, ADR-0078. 28 days before a kept date the AI suggests what its plan is about
(products that fit, or a greeting only); the owner chooses, and only then is the
plan written. Every plan made before this keeps ``NULL`` in all five columns and
stays a products plan.

Revision ID: 4f8a1c6e2b90
Revises: 9c4e2a7b1d36
Create Date: 2026-11-17 12:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4f8a1c6e2b90"
down_revision: str | None = "9c4e2a7b1d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("calendar_plans", sa.Column("suggestion", postgresql.JSONB(), nullable=True))
    op.add_column(
        "calendar_plans", sa.Column("suggested_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("calendar_plans", sa.Column("plan_kind", sa.String(16), nullable=True))
    op.add_column(
        "calendar_plans", sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("calendar_plans", sa.Column("skipped_by", sa.String(64), nullable=True))


def downgrade() -> None:
    for column in ("skipped_by", "skipped_at", "plan_kind", "suggested_at", "suggestion"):
        op.drop_column("calendar_plans", column)
