"""observed_events, and the data-processing agreement as a row in the tenant record

ADR-0044 phase 1 — collect, prove the pipe, show nothing — and ADR-0042 §2's
precondition, which phase 1 is the first feature to need.

**``tenants.dpa_signed_at``.** ADR-0042 §2: *"no tenant stores personal data
under this ADR until a data-processing agreement is in place with that tenant.
It is a row in the tenant record, not a handshake."* Nullable, and NULL for
every existing tenant, because none has one: that is the true state, and a
default of ``now()`` would record an agreement nobody signed.

**``observed_events``.** Exactly §4's fields — an opaque session id, the event
type, the product, a timestamp — plus the shop's own event id, which makes a
retried delivery one row. No IP, no user agent, no customer id, no URL. The
ordinary tenant policy and nothing else: nothing reads an event without already
knowing whose it is, and it carries ``tenant_id``, so the ADR-0008 protection
test covers it automatically.

**Deletion ships in the same change, as ADR-0042 §3 requires**: the
``retention.sweep`` job in ``neura_api.jobs.retention``, booked by every write.
The grants come from the schema's default privileges (``neura_app`` gets
``arwd`` on new tables), which is how ``sell_pairings`` got them too.

Revision ID: 7d4e1b9a2c60
Revises: 2a9f5d07c3b1
Create Date: 2026-09-26 18:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d4e1b9a2c60"
down_revision: str | None = "2a9f5d07c3b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "observed_events"


def upgrade() -> None:
    op.add_column("tenants", sa.Column("dpa_signed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        TABLE,
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "event_id", name=op.f("pk_observed_events")),
    )
    op.create_index("ix_observed_events_tenant_occurred", TABLE, ["tenant_id", "occurred_at"])

    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {TABLE}
            USING (tenant_id = current_setting('app.tenant_id', true))
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.drop_index("ix_observed_events_tenant_occurred", table_name=TABLE)
    op.drop_table(TABLE)
    op.drop_column("tenants", "dpa_signed_at")
