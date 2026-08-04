"""The two tables outbound webhooks are made of.

Both carry a ``tenant_id`` and are therefore covered, automatically, by the test
that fails when a ``tenant_id`` table has no forced Row-Level Security policy.
That is the whole reason no table in this system is ever created with a
"control plane" exemption (ADR-0014).

**Why deliveries are a table rather than a background task's memory.**
api-design.md §9 promises at-least-once delivery with backoff and a dead-letter
queue the merchant can see. A retry loop living only in a process satisfies none
of that: a deploy loses every in-flight event, and "we tried six times" becomes a
claim nobody can check. The row is written in the **same transaction as the turn
that caused it**, so an event exists exactly when the thing it describes
happened — the same rule the audit log follows, for the same reason.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from neura_core.db import metadata

WEBHOOK_ENDPOINTS = "webhook_endpoints"
WEBHOOK_DELIVERIES = "webhook_deliveries"


#: A merchant's registered destination.
#:
#: ``secret`` is AES-256-GCM ciphertext and ``wrapped_dek`` is the tenant's data
#: key under the KEK, exactly as ``tenant_stores`` does it. It cannot be a hash:
#: signing requires the plaintext. The consequence is stated in the ADR trail
#: rather than hidden — a database dump plus the KEK yields signing secrets,
#: which is why the KEK is not in this database.
webhook_endpoints = Table(
    WEBHOOK_ENDPOINTS,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("url", Text, nullable=False),
    Column("events", JSONB, nullable=False, server_default="[]"),
    Column("description", String(255), nullable=False, server_default=""),
    Column("secret", Text, nullable=False),
    Column("wrapped_dek", Text, nullable=False),
    Column("status", String(32), nullable=False, server_default="active"),
    #: Reset on every success. An endpoint that has been failing for a day is a
    #: merchant who changed their URL and did not tell us; retrying it forever
    #: is a slow denial of service against ourselves.
    Column("consecutive_failures", Integer, nullable=False, server_default="0"),
    Column("last_delivery_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("ix_webhook_endpoints_tenant_id", "tenant_id"),
)


#: The outbox. One row per (event, endpoint) pair.
#:
#: Fanning out at write time rather than at send time is deliberate: an endpoint
#: registered a second after the event occurred must not receive it, and an
#: endpoint deleted a second after must still show what it was owed. Both
#: questions have an answer only if the fan-out is a fact rather than a query.
webhook_deliveries = Table(
    WEBHOOK_DELIVERIES,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("endpoint_id", String(64), nullable=False),
    Column("event_type", String(64), nullable=False),
    #: Stable across attempts — it is the merchant's dedupe key, and a value
    #: that changed on retry would make at-least-once delivery indistinguishable
    #: from duplicate events.
    Column("event_id", String(64), nullable=False),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Column("status", String(32), nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("next_attempt_at", DateTime(timezone=True), nullable=True),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    Column("last_error", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # The drainer's only query: "what is due?". Ordered by when it became due so
    # a backlog is worked oldest-first rather than by whichever row the planner
    # happened to like.
    Index("ix_webhook_deliveries_due", "tenant_id", "status", "next_attempt_at"),
)
