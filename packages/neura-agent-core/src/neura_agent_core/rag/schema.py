"""The ``document_chunks`` table.

Defined against ``neura_core.metadata`` so Alembic can diff it. The DDL that
actually creates it — including the Row-Level Security policy, which SQLAlchemy
does not model — lives in the migration.

Two columns beyond the sketch in docs/architecture/llm-abstraction.md §5.1, both
earning their place:

* ``content_hash`` — so a reindex re-embeds only text that changed. Without it
  every run costs a full catalogue of inference calls.
* ``chunk_index`` — part of the natural key. An entity splits into an ordered
  sequence of chunks, and "the third chunk of product 42" has to be addressable
  for a write to be an upsert rather than an append.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import UserDefinedType

from neura_core import metadata

TABLE_NAME = "document_chunks"


class Vector(UserDefinedType[list[float]]):
    """pgvector's ``vector`` type, declared without a fixed dimension.

    Deliberate. A dimension in the column type would mean one deployment could
    hold vectors from one embedding model — but the reindex procedure requires
    768-dimensional and 1536-dimensional vectors to *coexist* while a new
    embedder is evaluated against the old one
    (docs/architecture/llm-abstraction.md §5.2).

    The cost is that no HNSW or IVFFlat index can be built here: pgvector needs
    a fixed dimension for those. At the scale ADR-0005 sizes for — thousands to
    low hundreds of thousands of chunks per tenant — a filtered scan within one
    namespace is fine, and the btree index below is what keeps that scan small.
    When a tenant outgrows it, the fix is a per-namespace partial index with the
    dimension pinned, not a change to this contract.
    """

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "vector"


document_chunks = Table(
    TABLE_NAME,
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(64), nullable=False),
    Column("embedding_model", String(128), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("embedding", Vector, nullable=False),
    Column("content", Text, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("source_type", String(32), nullable=False),
    Column("source_id", String(255), nullable=False),
    Column("chunk_index", Integer, nullable=False),
    Column("metadata", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # The upsert key. Re-running an index run must overwrite, not append —
    # webhooks fire twice and reconciles re-read everything.
    UniqueConstraint(
        "tenant_id",
        "embedding_model",
        "source_type",
        "source_id",
        "chunk_index",
        name="uq_document_chunks_namespace_source_chunk",
    ),
    # Every read filters on the namespace first. This index is what keeps the
    # unindexable vector comparison confined to one tenant's one model.
    Index(
        "ix_document_chunks_namespace_source_type",
        "tenant_id",
        "embedding_model",
        "source_type",
    ),
)
