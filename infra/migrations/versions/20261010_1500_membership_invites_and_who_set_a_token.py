"""membership_invites, and who set a connected shop's token

ADR-0058 §4 and §6.

``membership_invites``: an Owner's invitation to one person, for one shop, with
one role. **Tenant-scoped and forced**, like ``memberships``: only a shop's own
Owner can make one, so no shop can invite anyone into another (§5). The token is
never stored, only its hash. One open invite per email per shop (a partial
unique index), so a second invite replaces the first instead of racing it.

``tenant_stores.credentials_set_by``: the console user who made the token a
connected shop now uses, so Shop connection can say *Made [date] by [name]*.
Empty for every connection made before this, and for one made by a command:
the screen then names nobody rather than guessing.

Revision ID: 8d1f4b6a2c75
Revises: 5a7c2e9b4d13
Create Date: 2026-10-10 15:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8d1f4b6a2c75"
down_revision: str | None = "5a7c2e9b4d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "membership_invites",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by", sa.String(64), nullable=False),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.String(64), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'support', 'developer')", name=op.f("ck_membership_invites_role")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_membership_invites")),
        sa.UniqueConstraint("token_hash", name="uq_membership_invites_token_hash"),
    )
    op.create_index(
        "uq_membership_invites_open_email",
        "membership_invites",
        ["tenant_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND cancelled_at IS NULL"),
    )

    # Isolation, copied from `memberships`: forced, because migrations run as the
    # owner and the owner is otherwise exempt.
    op.execute("ALTER TABLE membership_invites ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE membership_invites FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON membership_invites
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON membership_invites TO neura_app;
            END IF;
        END
        $$
        """
    )

    op.add_column("tenant_stores", sa.Column("credentials_set_by", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_stores", "credentials_set_by")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON membership_invites")
    op.drop_index("uq_membership_invites_open_email", table_name="membership_invites")
    op.drop_table("membership_invites")
