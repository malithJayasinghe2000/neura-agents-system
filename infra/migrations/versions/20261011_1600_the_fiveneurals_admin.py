"""platform_admins, and the two functions the admin dashboard reads shops through

ADR-0061.

``platform_admins``: who may open ``/admin``. No ``tenant_id``, like ``users``:
an admin belongs to no shop. The application role may read it, add a row and
mark one removed; it is changed only by command, and never deleted.

``neura_admin_shops()`` and ``neura_admin_usage(since, until)``: every shop's
facts, and its AI use per day and assistant. A shop's own session sees one shop
(ADR-0008), so reading across shops takes the pattern ADR-0022 set: functions
``SECURITY DEFINER``, owned by a ``NOLOGIN`` role, ``neura_admin_reader``, that
holds **column** grants on exactly the shop facts of ADR-0061 §1 and nothing on
any table holding a conversation, a message, a shopper or a catalogue. Each
function answers **only a transaction opened for a live admin** (it reads
``app.user_id`` and ``platform_admins``), so one called from anywhere else
returns nothing.

Revision ID: 9b4e7a2c5d18
Revises: 6e2b9c4d1a07
Create Date: 2026-10-11 16:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b4e7a2c5d18"
down_revision: str | None = "6e2b9c4d1a07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READER = "neura_admin_reader"

#: ADR-0061 §1, column by column. A column not listed is unreadable to the role.
COLUMNS = {
    "tenants": "tenant_id, name, status, config, enabled_agents, website, created_at",
    "tenant_stores": "tenant_id, status",
    "tenant_usage": (
        "tenant_id, usage_date, agent_key, conversations, turns, llm_calls, escalations, "
        "blocked, prompt_tokens, completion_tokens, cost_usd"
    ),
    "memberships": "tenant_id, user_id, role, revoked_at, created_at",
    "users": "id, email",
    "platform_admins": "user_id, removed_at",
}

#: The tables under forced RLS among them: each needs a policy for the role.
RLS_TABLES = ("tenants", "tenant_stores", "tenant_usage", "memberships")

#: A live admin, named by the transaction (identity_session sets app.user_id).
_ADMIN = (
    "EXISTS (SELECT 1 FROM platform_admins a "
    "WHERE a.user_id = current_setting('app.user_id', true) AND a.removed_at IS NULL)"
)


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_platform_admins")),
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT SELECT, INSERT, UPDATE ON platform_admins TO neura_app;
            END IF;
        END
        $$
        """
    )

    # ── The reader role ──────────────────────────────────────────────────────
    # Created unconditionally, as the scheduler's is (ADR-0022): a deploy that
    # cannot create it should stop, not show an admin an empty dashboard.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{READER}') THEN
                CREATE ROLE {READER} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {READER} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {READER}")
    for table, columns in COLUMNS.items():
        op.execute(f"GRANT SELECT ({columns}) ON {table} TO {READER}")
    # Scoped `TO neura_admin_reader`: it widens nothing for neura_app, which
    # still sees one shop per transaction.
    for table in RLS_TABLES:
        op.execute(f"CREATE POLICY admin_reader ON {table} FOR SELECT TO {READER} USING (true)")

    op.execute(
        f"""
        CREATE FUNCTION neura_admin_shops()
            RETURNS TABLE (
                tenant_id text, name text, status text, mode text, enabled_agents jsonb,
                website text, created_at timestamptz, connected boolean, owners text[]
            )
            LANGUAGE sql
            STABLE
            SECURITY DEFINER
            SET search_path = public, pg_temp
        AS $$
            SELECT
                t.tenant_id::text, t.name::text, t.status::text, t.config->>'mode',
                t.enabled_agents, t.website::text, t.created_at,
                EXISTS (
                    SELECT 1 FROM tenant_stores s
                    WHERE s.tenant_id = t.tenant_id AND s.status = 'active'
                ),
                COALESCE(
                    (
                        SELECT array_agg(u.email::text ORDER BY m.created_at)
                        FROM memberships m JOIN users u ON u.id = m.user_id
                        WHERE m.tenant_id = t.tenant_id AND m.role = 'owner'
                          AND m.revoked_at IS NULL
                    ),
                    ARRAY[]::text[]
                )
            FROM tenants t
            WHERE {_ADMIN}
            ORDER BY (t.status <> 'waiting'), t.created_at DESC, t.tenant_id
        $$
        """  # noqa: S608 (built from this module's constants, never input)
    )
    op.execute(
        f"""
        CREATE FUNCTION neura_admin_usage(since date, until date)
            RETURNS TABLE (
                tenant_id text, agent_key text, conversations bigint, turns bigint,
                llm_calls bigint, escalations bigint, blocked bigint,
                prompt_tokens bigint, completion_tokens bigint, cost_usd numeric
            )
            LANGUAGE sql
            STABLE
            SECURITY DEFINER
            SET search_path = public, pg_temp
        AS $$
            SELECT
                u.tenant_id::text, u.agent_key::text,
                sum(u.conversations)::bigint, sum(u.turns)::bigint, sum(u.llm_calls)::bigint,
                sum(u.escalations)::bigint, sum(u.blocked)::bigint,
                sum(u.prompt_tokens)::bigint, sum(u.completion_tokens)::bigint,
                sum(u.cost_usd)
            FROM tenant_usage u
            WHERE u.usage_date BETWEEN since AND until AND {_ADMIN}
            GROUP BY 1, 2
            ORDER BY 1, 2
        $$
        """  # noqa: S608 (built from this module's constants, never input)
    )
    for signature in ("neura_admin_shops()", "neura_admin_usage(date, date)"):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {READER}")
        # Revoked from PUBLIC first, then granted to exactly one role.
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                    GRANT EXECUTE ON FUNCTION {signature} TO neura_app;
                END IF;
            END
            $$
            """
        )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS neura_admin_usage(date, date)")
    op.execute("DROP FUNCTION IF EXISTS neura_admin_shops()")
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS admin_reader ON {table}")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{READER}') THEN
                DROP OWNED BY {READER};
                DROP ROLE {READER};
            END IF;
        END
        $$
        """
    )
    op.drop_table("platform_admins")
