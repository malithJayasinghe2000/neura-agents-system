"""calendar_settings, calendar_dates, calendar_plans: GROW's Marketing calendar

ADR-0072. Three tables, each tenant-scoped with the ordinary policy:

* ``calendar_settings``: where the shop is (Sri Lanka or another country, G119),
  and who said so. No row means Sri Lanka.
* ``calendar_dates``: the shop's dates. A suggested date has a row per year once
  that year's list is saved (ticked or not, and a moving date's day if the owner
  set it); an own date has one row (name, day, every year or not).
* ``calendar_plans``: one campaign plan per kept date and day: the model's
  checked answer, the owner's edits, when it was made and by which prompt,
  whether the last try failed, and *Make it again* waiting.

**No shopper's data** (ADR-0072 §8): labels and counts only. A plan is deleted
30 days after its date by the retention sweep, in the same change (ADR-0042 §3);
shop removal knows all three tables (G76).

Revision ID: 3f7c1a9e5b84
Revises: 8e2a4c6f1d57
Create Date: 2026-11-01 22:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3f7c1a9e5b84"
down_revision: str | None = "8e2a4c6f1d57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("calendar_settings", "calendar_dates", "calendar_plans")


def upgrade() -> None:
    op.create_table(
        "calendar_settings",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("country", sa.String(16), nullable=False),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("changed_by", sa.String(64), nullable=False),
        sa.CheckConstraint("country IN ('lk', 'other')", name=op.f("ck_calendar_settings_country")),
        sa.PrimaryKeyConstraint("tenant_id", name=op.f("pk_calendar_settings")),
    )

    op.create_table(
        "calendar_dates",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(32), nullable=True),
        sa.Column("name", sa.String(60), nullable=True),
        sa.Column("day", sa.Date(), nullable=True),
        sa.Column("kept", sa.Boolean(), nullable=False),
        sa.Column("every_year", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("changed_by", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "(key IS NULL) <> (name IS NULL)", name=op.f("ck_calendar_dates_key_or_name")
        ),
        sa.CheckConstraint(
            "name IS NULL OR day IS NOT NULL", name=op.f("ck_calendar_dates_own_has_day")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_calendar_dates")),
    )
    op.create_index(
        "uq_calendar_dates_suggested",
        "calendar_dates",
        ["tenant_id", "year", "key"],
        unique=True,
        postgresql_where=sa.text("key IS NOT NULL"),
    )

    op.create_table(
        "calendar_plans",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("date_key", sa.String(80), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("answer", postgresql.JSONB(), nullable=True),
        sa.Column("edits", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("made_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_revision", sa.String(64), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.String(64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_by", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_calendar_plans")),
    )
    op.create_index(
        "uq_calendar_plans_date", "calendar_plans", ["tenant_id", "date_key", "day"], unique=True
    )
    op.create_index("ix_calendar_plans_day", "calendar_plans", ["tenant_id", "day"])

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
    op.drop_index("ix_calendar_plans_day", table_name="calendar_plans")
    op.drop_index("uq_calendar_plans_date", table_name="calendar_plans")
    op.drop_table("calendar_plans")
    op.drop_index("uq_calendar_dates_suggested", table_name="calendar_dates")
    op.drop_table("calendar_dates")
    op.drop_table("calendar_settings")
