"""sell_feeds — publication is opt-in, and its address is a rotatable secret

ADR-0024. One row per published store catalogue, and **the absence of a row is
"off"** — there is no `enabled` column, so the default state is not a value any
migration, backfill or admin script can flip for every merchant at once.
Publication cannot be undone once a crawler has cached a document, so the switch
is deliberately not a switch.

The token is stored hashed exactly as an API key is, and resolved through the
**existing** ADR-0014 bootstrap: `credential_session` sets `app.api_key_hash`
and no `app.tenant_id`, so a caller may read the row for a credential they
already hold and nothing else. No new exemption is created here — the feed's
problem is authentication's problem, and reusing the answer keeps the number of
ways into this database at one.

Revision ID: 9e4d1f7a26c8
Revises: 7b3e5a2c81d4
Create Date: 2026-08-26 16:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9e4d1f7a26c8"
down_revision: str | None = "7b3e5a2c81d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "sell_feeds"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("store_id", sa.String(64), nullable=False),
        sa.Column("token_prefix", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_served_at", sa.DateTime(timezone=True), nullable=True),
        # Global rather than per-tenant, as `api_keys` does it: the same hash
        # under two tenants would make one URL resolve to either, and which one
        # you got would depend on the query plan.
        sa.UniqueConstraint("token_hash", name="uq_sell_feeds_token_hash"),
    )
    op.create_index("ix_sell_feeds_tenant_id_store_id", TABLE, ["tenant_id", "store_id"])

    # The ordinary tenant policy. `sell_feeds` carries `tenant_id`, so the
    # ADR-0008 protection test covers it automatically — enabled, forced, and a
    # policy, or the integration suite fails.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {TABLE}
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )

    # The bootstrap, and the reason it is safe is ADR-0014's reason unchanged.
    # Permissive policies are OR-ed, so this widens SELECT by exactly one row:
    # the one whose hash the caller presented. It cannot enumerate — the hash is
    # a SHA-256 of a 256-bit random token, so guessing it is guessing the URL
    # itself, which is the whole access control anyway.
    #
    # FOR SELECT only. A caller who has presented nothing but a URL must not be
    # able to write, and `credential_session` is READ ONLY besides — belt and
    # braces, because the two protect against different mistakes.
    op.execute(
        f"""
        CREATE POLICY feed_token_lookup ON {TABLE}
            FOR SELECT
            USING (token_hash = current_setting('app.api_key_hash', true))
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS feed_token_lookup ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_sell_feeds_tenant_id_store_id", table_name=TABLE)
    op.drop_table(TABLE)
