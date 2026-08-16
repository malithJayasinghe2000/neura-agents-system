"""The ``synced_entities`` and ``sync_checkpoints`` tables.

Defined against ``neura_core.metadata`` so Alembic can diff them. The Row-Level
Security policies live in the migration, because SQLAlchemy does not model them.

**The entity is stored as its canonical document, not as a second schema**
(ADR-0021). ``neura_domain`` remains the only place a ``Product`` is defined;
this table holds the result of ``model_dump(mode="json")`` and knows nothing
about titles or prices. The alternative — a column per canonical field, five
times over — would make PostgreSQL a second definition of the domain model, and
every field added to ``Product`` a migration.

Nothing queries a synced entity's *contents*. Every read in the
:class:`~neura_commerce.sync.store.EntityStore` protocol filters on the key or a
prefix of it, RAG has ``document_chunks`` for search, and orders and customers
are read live through the adapter rather than synced at all. The day something
needs a SQL predicate over an entity's fields, that is a superseding ADR and not
a quietly added column.

**Both primary keys are natural and composite**, and that is the point of them:
``synced_entities``' key is exactly ``EntityKey``, ``sync_checkpoints``' is
exactly ``SyncKey``. A surrogate id on either would permit two rows for one
entity — the single failure ``store.py`` says must be structurally impossible,
since webhooks arrive twice and backfills overlap incrementals.

**Neither table carries a secondary index.** Every read filters on
``(tenant_id, platform, entity_type)`` or on the full key, both of which are
prefixes of the primary key. An index beyond that would be one nothing uses.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, Table, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from neura_core import metadata

ENTITIES_TABLE = "synced_entities"
CHECKPOINTS_TABLE = "sync_checkpoints"

synced_entities = Table(
    ENTITIES_TABLE,
    metadata,
    # The four parts of EntityKey. Dropping tenant_id allows cross-tenant
    # collisions; dropping platform breaks the day a merchant runs two stores.
    Column("tenant_id", String(64), primary_key=True),
    Column("platform", String(64), primary_key=True),
    Column("entity_type", String(32), primary_key=True),
    Column("external_id", String(255), primary_key=True),
    # Preserved across content changes — see PostgresEntityStore.upsert. An id
    # that changes when a merchant edits a product title is not a stable id.
    Column("neura_id", String(64), nullable=False),
    Column("fingerprint", String(32), nullable=False),
    # The canonical entity, exactly as neura_domain serialises it.
    Column("document", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Moved only when the fingerprint changed, so this answers "when did this
    # entity last actually change" rather than "when did a sync last run".
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

sync_checkpoints = Table(
    CHECKPOINTS_TABLE,
    metadata,
    # SyncKey.
    Column("tenant_id", String(64), primary_key=True),
    Column("platform", String(64), primary_key=True),
    Column("entity_type", String(32), primary_key=True),
    # Cursor.encode() — an opaque URL-safe string, which is the form
    # pagination.Cursor documents as the one that survives a checkpoint.
    Column("cursor", Text, nullable=True),
    Column("updated_through", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("last_run_count", Integer, nullable=False, server_default="0"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
