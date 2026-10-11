"""sign_up_requests, tenants.website, and the list of shops waiting for approval

ADR-0058 §7, R14 to R17.

``sign_up_requests``: a sign-up waiting for its email link. **No ``tenant_id``**,
like ``login_tokens``: there is no shop yet. The token is never stored, only its
hash; one request per email (a second replaces the first).

``tenants.website``: the shop's web address as typed at sign up, read by
FiveNeurals before approving. Empty for every shop made before this, and for one
made with a command.

``neura_waiting_tenants()``: the ids of the shops waiting for approval, for
``make tenant-waiting``. A tenant-scoped session sees one shop, so listing them
crosses a tenant boundary, and the answer is the one ADR-0022 gave the job
dispatcher: a ``SECURITY DEFINER`` function owned by a ``NOLOGIN`` role that may
read three columns of ``tenants`` and only the rows that wait, returning ids and
nothing else. The caller then opens each shop's own session.

Revision ID: 6e2b9c4d1a07
Revises: 8d1f4b6a2c75
Create Date: 2026-10-11 12:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6e2b9c4d1a07"
down_revision: str | None = "8d1f4b6a2c75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REGISTRAR_ROLE = "neura_registrar"
WAITING_TENANTS = "neura_waiting_tenants"


def upgrade() -> None:
    op.create_table(
        "sign_up_requests",
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("shop_name", sa.String(100), nullable=False),
        sa.Column("website", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("requested_ip", sa.String(64), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sign_up_requests")),
        sa.UniqueConstraint("email", name="uq_sign_up_requests_email"),
        sa.UniqueConstraint("token_hash", name="uq_sign_up_requests_token_hash"),
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON sign_up_requests TO neura_app;
            END IF;
        END
        $$
        """
    )

    op.add_column("tenants", sa.Column("website", sa.String(255), nullable=True))

    # ── The registrar role ───────────────────────────────────────────────────
    # Created unconditionally, as the scheduler role is (ADR-0022): a deploy
    # that cannot create it should stop, not list no waiting shops.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{REGISTRAR_ROLE}') THEN
                CREATE ROLE {REGISTRAR_ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {REGISTRAR_ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {REGISTRAR_ROLE}")
    # Three columns, never the name, the settings or the website.
    op.execute(f"GRANT SELECT (tenant_id, status, created_at) ON tenants TO {REGISTRAR_ROLE}")
    # Scoped `TO neura_registrar`, so it widens nothing for neura_app; and only
    # the rows that wait, so the role cannot read even an id of any other shop.
    op.execute(
        f"""
        CREATE POLICY registrar_waiting ON tenants
            FOR SELECT TO {REGISTRAR_ROLE}
            USING (status = 'waiting')
        """
    )
    op.execute(
        """
        CREATE FUNCTION neura_waiting_tenants()
            RETURNS TABLE (tenant_id text)
            LANGUAGE sql
            STABLE
            SECURITY DEFINER
            SET search_path = public, pg_temp
        AS $$
            SELECT t.tenant_id::text
            FROM tenants AS t
            WHERE t.status = 'waiting'
            ORDER BY t.created_at, t.tenant_id
        $$
        """
    )
    op.execute(f"ALTER FUNCTION {WAITING_TENANTS}() OWNER TO {REGISTRAR_ROLE}")
    # Revoked from PUBLIC first, then granted to exactly one role.
    op.execute(f"REVOKE ALL ON FUNCTION {WAITING_TENANTS}() FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT EXECUTE ON FUNCTION {WAITING_TENANTS}() TO neura_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {WAITING_TENANTS}()")
    op.execute("DROP POLICY IF EXISTS registrar_waiting ON tenants")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{REGISTRAR_ROLE}') THEN
                DROP OWNED BY {REGISTRAR_ROLE};
                DROP ROLE {REGISTRAR_ROLE};
            END IF;
        END
        $$
        """
    )
    op.drop_column("tenants", "website")
    op.drop_table("sign_up_requests")
