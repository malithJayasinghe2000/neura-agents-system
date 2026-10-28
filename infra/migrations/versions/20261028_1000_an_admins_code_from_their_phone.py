"""admin_codes — the code from a FiveNeurals admin's phone

ADR-0067. One row per admin: the authenticator key (encrypted, bound to the
admin's user id), when setup was finished, the last step that matched, and the
wrong-code count. No ``tenant_id``, like ``platform_admins``. The admin reader
role (ADR-0061 §6) gets no grant on it.

Revision ID: 5d1b7e3a9c42
Revises: 2c8e6a4f9d31
Create Date: 2026-10-28 10:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d1b7e3a9c42"
down_revision: str | None = "2c8e6a4f9d31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_codes",
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_step", sa.BigInteger(), nullable=True),
        sa.Column("wrong", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stopped_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_admin_codes")),
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON admin_codes TO neura_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.drop_table("admin_codes")
