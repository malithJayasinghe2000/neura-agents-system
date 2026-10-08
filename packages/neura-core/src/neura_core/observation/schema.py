"""The ``observed_events`` table — ADR-0044 phase 1, in DDL.

**Few columns, and the absent ones are the design.** §4 stores an opaque
session id, an event type, the product it refers to and a timestamp; ADR-0049
adds whether that product was in stock — a fact about the product, not the
shopper. There is no IP, no user agent, no customer id, no email and no URL here, and
adding any of them is an ADR rather than a migration — the same shape of rule as
``sell_pairings`` having no visitor column.

**No link to a customer record** (§4). ``session_id`` joins to nothing.

**``occurred_at`` is what expires a row.** The retention sweep deletes on it,
which is why the route refuses a timestamp in the future: a date the shop chose
would otherwise decide how long we hold the row.

It carries ``tenant_id``, so the ADR-0008 protection test covers it
automatically: enabled, forced, and a policy, or the integration suite fails.
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Index, String, Table

from neura_core.db import metadata

OBSERVED_EVENTS = "observed_events"

observed_events = Table(
    OBSERVED_EVENTS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    #: The shop's own id for the event, so a retried delivery is one row.
    Column("event_id", String(64), primary_key=True),
    Column("session_id", String(128), nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("product_id", String(128), nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    #: Whether the product could be bought at that moment (ADR-0049). Set on
    #: every view, ``NULL`` on a basket add — and ``NULL`` means *unknown*,
    #: never *sold out*.
    Column("in_stock", Boolean, nullable=True),
    # The sweep: "this tenant's rows older than the cutoff".
    Index("ix_observed_events_tenant_occurred", "tenant_id", "occurred_at"),
)

__all__ = ["OBSERVED_EVENTS", "observed_events"]
