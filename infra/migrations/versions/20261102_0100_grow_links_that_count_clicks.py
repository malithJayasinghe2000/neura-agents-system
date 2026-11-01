"""links, link_clicks, and neura_follow_link(): links that count their clicks

ADR-0074. Two tables, each tenant-scoped with the ordinary policy:

* ``links``: one row per link, a plan's (one post, one place, one product) or
  the owner's own (a name). ``code`` is unique across every shop.
* ``link_clicks``: one number per link per day, and nothing about who tapped
  (§5, R118).

``neura_follow_link(code, count)``: a tap on ``/go/<code>`` carries a code and
nothing else, so the shop is not known until the link is found. The answer is
the one ADR-0022 gave the job dispatcher and the sign-up list repeated: a
``SECURITY DEFINER`` function owned by a ``NOLOGIN`` role, ``neura_link_follower``,
that may read a link's few columns, a catalogue product's document, and add to a
day's count, returning **the address to send the shopper to and nothing else**
(§7). The address is the product's page from the catalogue now, or, when the
product is gone, the front page of the address the link was made with (§3);
the campaign labels are added either way (§4). Never an address from the
request.

Revision ID: 7b3d5e9a2c41
Revises: 3f7c1a9e5b84
Create Date: 2026-11-02 01:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b3d5e9a2c41"
down_revision: str | None = "3f7c1a9e5b84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("links", "link_clicks")
FOLLOWER_ROLE = "neura_link_follower"
FOLLOW = "neura_follow_link"


def upgrade() -> None:
    op.create_table(
        "links",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("product_id", sa.String(255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("labels", sa.Text(), nullable=False),
        sa.Column("place", sa.String(16), nullable=False),
        sa.Column("date_key", sa.String(80), nullable=True),
        sa.Column("day", sa.Date(), nullable=True),
        sa.Column("campaign", sa.String(60), nullable=True),
        sa.Column("post", sa.String(16), nullable=True),
        sa.Column("name", sa.String(60), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "place IN ('facebook', 'instagram', 'whatsapp', 'email', 'other')",
            name=op.f("ck_links_place"),
        ),
        sa.CheckConstraint(
            "post IS NULL OR post IN ('teaser', 'launch', 'last_chance', 'email')",
            name=op.f("ck_links_post"),
        ),
        sa.CheckConstraint("(post IS NULL) <> (name IS NULL)", name=op.f("ck_links_post_or_name")),
        sa.CheckConstraint(
            "post IS NULL OR (date_key IS NOT NULL AND day IS NOT NULL AND campaign IS NOT NULL)",
            name=op.f("ck_links_post_has_date"),
        ),
        sa.PrimaryKeyConstraint("tenant_id", "id", name=op.f("pk_links")),
    )
    op.create_index("uq_links_code", "links", ["code"], unique=True)
    op.create_index(
        "uq_links_post",
        "links",
        ["tenant_id", "date_key", "day", "post", "place", "product_id"],
        unique=True,
        postgresql_where=sa.text("post IS NOT NULL AND removed_at IS NULL"),
    )

    op.create_table(
        "link_clicks",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("link_id", sa.String(64), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("clicks", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "link_id", "day", name=op.f("pk_link_clicks")),
    )

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

    # ── The follower role ────────────────────────────────────────────────────
    # Created unconditionally, as the registrar is: a deploy that cannot create
    # it should stop, not forward every tap to "no longer active".
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{FOLLOWER_ROLE}') THEN
                CREATE ROLE {FOLLOWER_ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT {FOLLOWER_ROLE} TO CURRENT_USER")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {FOLLOWER_ROLE}")
    # A link's few columns: never who made it, its name or its campaign.
    op.execute(
        f"GRANT SELECT (tenant_id, id, code, product_id, url, labels, removed_at) "
        f"ON links TO {FOLLOWER_ROLE}"
    )
    op.execute(
        f"GRANT SELECT (tenant_id, link_id, day, clicks), INSERT, UPDATE (clicks) "
        f"ON link_clicks TO {FOLLOWER_ROLE}"
    )
    op.execute(
        f"GRANT SELECT (tenant_id, entity_type, external_id, document, updated_at) "
        f"ON synced_entities TO {FOLLOWER_ROLE}"
    )
    # Each scoped `TO neura_link_follower`, so none widens anything for neura_app.
    op.execute(f"CREATE POLICY follower_read ON links FOR SELECT TO {FOLLOWER_ROLE} USING (true)")
    op.execute(
        f"CREATE POLICY follower_count ON link_clicks FOR ALL TO {FOLLOWER_ROLE} "
        f"USING (true) WITH CHECK (true)"
    )
    # Products only: never an order, a customer or a policy page.
    op.execute(
        f"CREATE POLICY follower_products ON synced_entities FOR SELECT TO {FOLLOWER_ROLE} "
        f"USING (entity_type = 'product')"
    )
    op.execute(
        """
        CREATE FUNCTION neura_follow_link(p_code text, p_count boolean)
            RETURNS text
            LANGUAGE plpgsql
            VOLATILE
            SECURITY DEFINER
            SET search_path = public, pg_temp
        AS $$
        DECLARE
            found_link record;
            address text;
            fragment text := '';
        BEGIN
            SELECT l.tenant_id, l.id, l.product_id, l.url, l.labels, l.removed_at
              INTO found_link
              FROM links AS l
             WHERE l.code = p_code;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            -- The product's page now (a sync may have moved it, §3).
            SELECT e.document ->> 'url'
              INTO address
              FROM synced_entities AS e
             WHERE e.tenant_id = found_link.tenant_id
               AND e.entity_type = 'product'
               AND e.external_id = found_link.product_id
             ORDER BY e.updated_at DESC
             LIMIT 1;
            IF address IS NULL OR address !~* '^https?://[^/?#]+' THEN
                -- Gone from the catalogue: the shop's front page, not an error.
                address := substring(found_link.url FROM '^(https?://[^/?#]+)') || '/';
            END IF;
            IF address IS NULL THEN
                RETURN NULL;
            END IF;

            IF p_count AND found_link.removed_at IS NULL THEN
                INSERT INTO link_clicks AS c (tenant_id, link_id, day, clicks)
                VALUES (found_link.tenant_id, found_link.id, (now() AT TIME ZONE 'UTC')::date, 1)
                ON CONFLICT (tenant_id, link_id, day) DO UPDATE SET clicks = c.clicks + 1;
            END IF;

            -- The labels go before any '#part' of the address (§4).
            IF position('#' IN address) > 0 THEN
                fragment := substr(address, position('#' IN address));
                address := substr(address, 1, position('#' IN address) - 1);
            END IF;
            IF found_link.labels <> '' THEN
                address := address
                    || CASE WHEN position('?' IN address) > 0 THEN '&' ELSE '?' END
                    || found_link.labels;
            END IF;
            RETURN address || fragment;
        END
        $$
        """
    )
    op.execute(f"ALTER FUNCTION {FOLLOW}(text, boolean) OWNER TO {FOLLOWER_ROLE}")
    # Revoked from PUBLIC first, then granted to exactly one role.
    op.execute(f"REVOKE ALL ON FUNCTION {FOLLOW}(text, boolean) FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'neura_app') THEN
                GRANT EXECUTE ON FUNCTION {FOLLOW}(text, boolean) TO neura_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f"DROP FUNCTION IF EXISTS {FOLLOW}(text, boolean)")
    op.execute("DROP POLICY IF EXISTS follower_products ON synced_entities")
    op.execute("DROP POLICY IF EXISTS follower_count ON link_clicks")
    op.execute("DROP POLICY IF EXISTS follower_read ON links")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{FOLLOWER_ROLE}') THEN
                DROP OWNED BY {FOLLOWER_ROLE};
                DROP ROLE {FOLLOWER_ROLE};
            END IF;
        END
        $$
        """
    )
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("link_clicks")
    op.drop_index("uq_links_post", table_name="links")
    op.drop_index("uq_links_code", table_name="links")
    op.drop_table("links")
