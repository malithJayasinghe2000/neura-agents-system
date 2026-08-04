"""The pgvector-backed ``VectorStore``.

ADR-0005: vectors live in the primary database, not a separate service. That
buys transactional consistency with the source data, one backup, one thing to
run in a sovereign deployment — and, most usefully here, tenant isolation that
is the *same* Row-Level Security protecting every other table rather than a
second implementation to get right.

Two properties this file is responsible for:

* **Every statement runs inside a tenant-scoped transaction.** The caller passes
  an ``AsyncSession`` from ``Database.tenant_session``; RLS then makes a missing
  ``WHERE tenant_id`` return nothing instead of leaking. The explicit tenant
  predicates below are belt *and* braces — they also keep the query planner on
  the namespace index.
* **A namespace holds one vector size.** Checked before writing, because a mixed
  namespace produces no error at query time, only worse answers.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from typing import cast as cast_typing

from sqlalchemy import Result, String, bindparam, cast, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from neura_agent_core.rag.schema import Vector, document_chunks
from neura_agent_core.rag.store import (
    CrossTenantWriteError,
    DimensionMismatchError,
    EmbeddedChunk,
    Namespace,
    RetrievedChunk,
    VectorStoreError,
    WriteResult,
)
from neura_commerce import EntityType
from neura_core import new_id
from neura_core.ids import CHUNK

_COLUMNS = document_chunks.c
_METADATA = _COLUMNS["metadata"]


class PostgresVectorStore:
    """Vectors in PostgreSQL. One instance per tenant-scoped session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Writing ──────────────────────────────────────────────────────────────

    async def upsert(self, ns: Namespace, chunks: Sequence[EmbeddedChunk]) -> WriteResult:
        result = WriteResult()
        if not chunks:
            return result

        await self._require_one_dimension(ns, chunks)

        existing = await self.content_hashes(ns)
        now = datetime.now(UTC)
        rows = []

        for item in chunks:
            chunk = item.chunk
            key = (chunk.source_type.value, chunk.source_id, chunk.chunk_index)
            previous = existing.get(key)

            if previous == chunk.content_hash:
                # Same text, same model — the vector would be identical. This
                # branch is the reason a nightly reindex is cheap.
                result.unchanged += 1
                continue

            if previous is None:
                result.created += 1
            else:
                result.updated += 1

            rows.append(
                {
                    "id": new_id(CHUNK),
                    "tenant_id": ns.tenant_id,
                    "embedding_model": ns.embedding_model,
                    "dimensions": item.dimensions,
                    "embedding": _to_vector(item.embedding),
                    "content": chunk.content,
                    "content_hash": chunk.content_hash,
                    "source_type": chunk.source_type.value,
                    "source_id": chunk.source_id,
                    "chunk_index": chunk.chunk_index,
                    "metadata": chunk.metadata,
                    "created_at": now,
                    "updated_at": now,
                }
            )

        if rows:
            statement = insert(document_chunks).values(rows)
            upsert = statement.on_conflict_do_update(
                constraint="uq_document_chunks_namespace_source_chunk",
                set_={
                    "embedding": statement.excluded.embedding,
                    "dimensions": statement.excluded.dimensions,
                    "content": statement.excluded.content,
                    "content_hash": statement.excluded.content_hash,
                    "metadata": statement.excluded.metadata,
                    "updated_at": statement.excluded.updated_at,
                },
            )
            try:
                await self._session.execute(upsert)
            except DBAPIError as exc:
                raise _translate(exc, ns) from exc

        return result

    async def delete_source(self, ns: Namespace, source_type: EntityType, source_id: str) -> int:
        result = await self._session.execute(
            delete(document_chunks).where(
                _COLUMNS.tenant_id == ns.tenant_id,
                _COLUMNS.embedding_model == ns.embedding_model,
                _COLUMNS.source_type == source_type.value,
                _COLUMNS.source_id == source_id,
            )
        )
        return _rowcount(result)

    async def prune(
        self, ns: Namespace, source_type: EntityType, source_id: str, keep_upto: int
    ) -> int:
        result = await self._session.execute(
            delete(document_chunks).where(
                _COLUMNS.tenant_id == ns.tenant_id,
                _COLUMNS.embedding_model == ns.embedding_model,
                _COLUMNS.source_type == source_type.value,
                _COLUMNS.source_id == source_id,
                _COLUMNS.chunk_index >= keep_upto,
            )
        )
        return _rowcount(result)

    async def drop_namespace(self, ns: Namespace) -> int:
        result = await self._session.execute(
            delete(document_chunks).where(
                _COLUMNS.tenant_id == ns.tenant_id,
                _COLUMNS.embedding_model == ns.embedding_model,
            )
        )
        return _rowcount(result)

    # ── Reading ──────────────────────────────────────────────────────────────

    async def search(
        self,
        ns: Namespace,
        embedding: Sequence[float],
        *,
        limit: int = 5,
        source_types: Sequence[EntityType] | None = None,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        """Nearest neighbours within one namespace.

        ``<=>`` is pgvector's cosine *distance*; callers everywhere else in this
        codebase reason in similarity, so it is converted here and exactly here.
        Quietly handing a caller a distance where they expect a similarity is
        how a ``>= 0.7`` filter ends up selecting the worst matches.

        ``min_score`` is applied *after* the limit, so it trims a top-k rather
        than widening the search — a question with no good answer should return
        nothing, not the next five things.
        """
        distance = _COLUMNS.embedding.op("<=>")(
            cast(bindparam("q", value=_to_vector(embedding), type_=String), Vector())
        ).label("distance")

        statement = (
            select(
                _COLUMNS.source_type,
                _COLUMNS.source_id,
                _COLUMNS.chunk_index,
                _COLUMNS.content,
                _METADATA.label("meta"),
                distance,
            )
            .where(
                _COLUMNS.tenant_id == ns.tenant_id,
                _COLUMNS.embedding_model == ns.embedding_model,
            )
            .order_by(distance.asc())
            .limit(limit)
        )

        if source_types:
            statement = statement.where(_COLUMNS.source_type.in_([t.value for t in source_types]))

        rows = (await self._session.execute(statement)).all()

        found = [
            RetrievedChunk(
                source_type=EntityType(row.source_type),
                source_id=row.source_id,
                chunk_index=row.chunk_index,
                content=row.content,
                score=1.0 - float(row.distance),
                metadata=dict(row.meta or {}),
            )
            for row in rows
        ]
        return [chunk for chunk in found if chunk.score >= min_score]

    async def content_hashes(self, ns: Namespace) -> dict[tuple[str, str, int], str]:
        rows = (
            await self._session.execute(
                select(
                    _COLUMNS.source_type,
                    _COLUMNS.source_id,
                    _COLUMNS.chunk_index,
                    _COLUMNS.content_hash,
                ).where(
                    _COLUMNS.tenant_id == ns.tenant_id,
                    _COLUMNS.embedding_model == ns.embedding_model,
                )
            )
        ).all()
        return {(r.source_type, r.source_id, r.chunk_index): r.content_hash for r in rows}

    async def count(self, ns: Namespace) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(document_chunks)
            .where(
                _COLUMNS.tenant_id == ns.tenant_id,
                _COLUMNS.embedding_model == ns.embedding_model,
            )
        )
        return int(total or 0)

    async def models_for(self, tenant_id: str) -> dict[str, int]:
        rows = (
            await self._session.execute(
                select(_COLUMNS.embedding_model, func.count())
                .where(_COLUMNS.tenant_id == tenant_id)
                .group_by(_COLUMNS.embedding_model)
            )
        ).all()
        return {row[0]: int(row[1]) for row in rows}

    # ── Internals ────────────────────────────────────────────────────────────

    async def _require_one_dimension(self, ns: Namespace, chunks: Sequence[EmbeddedChunk]) -> None:
        sizes = {item.dimensions for item in chunks}

        stored = (
            (
                await self._session.execute(
                    select(_COLUMNS.dimensions)
                    .where(
                        _COLUMNS.tenant_id == ns.tenant_id,
                        _COLUMNS.embedding_model == ns.embedding_model,
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        sizes.update(int(d) for d in stored)

        if len(sizes) > 1:
            raise DimensionMismatchError(
                f"namespace {ns} would hold vectors of {sorted(sizes)} dimensions. "
                "Vectors of different sizes are not comparable — the model behind "
                f"{ns.embedding_model!r} has changed. Reindex under a new name "
                "(docs/architecture/llm-abstraction.md §5.2).",
                details={"namespace": str(ns), "dimensions": sorted(sizes)},
            )


def _rowcount(result: Result[Any]) -> int:
    """How many rows a DELETE touched.

    ``Result`` is the declared return type of ``session.execute``; only the
    ``CursorResult`` it actually is carries ``rowcount``. Narrowed here once
    rather than ignored at each call site.
    """
    return int(cast_typing(CursorResult[Any], result).rowcount or 0)


def _translate(exc: DBAPIError, ns: Namespace) -> VectorStoreError:
    """Turn a driver error into something a caller can act on.

    Only one case is special, and it is the one that matters: PostgreSQL
    rejecting a row because the RLS ``WITH CHECK`` clause did not match. That
    means the transaction is scoped to one tenant and the namespace names
    another — a bug with security consequences, which deserves better than a
    driver stack trace.
    """
    detail = str(getattr(exc, "orig", exc)).lower()
    if "row-level security" in detail or "row level security" in detail:
        return CrossTenantWriteError(
            f"the database refused a write to namespace {ns} — this transaction "
            "is scoped to a different tenant. Row-Level Security worked; "
            "something upstream resolved the tenant inconsistently.",
            details={"namespace": str(ns)},
        )
    return VectorStoreError(f"vector store write failed: {exc}", details={"namespace": str(ns)})


def _to_vector(embedding: Sequence[float]) -> str:
    """pgvector's text input form.

    Sent as a string and cast in SQL rather than through a driver type, so this
    package needs no pgvector Python dependency for a format that is two
    brackets and some commas.
    """
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


class DatabaseVectorStore:
    """A :class:`VectorStore` that opens its own session per operation.

    ``PostgresVectorStore`` needs a live session, which is right for indexing —
    a backfill writes thousands of chunks and wants one transaction. It is wrong
    for *serving*: a turn takes seconds, and holding a pooled connection open
    across a model call would let a handful of concurrent shoppers exhaust the
    pool while the fix looks like "make the pool bigger".

    So this wraps a :class:`~neura_core.db.Database` and gives each call a short
    transaction of its own. Retrieval during a turn is one search and, when that
    search finds nothing, two diagnostic reads — three brief transactions rather
    than one long one.

    Reads only in practice, but the whole protocol is implemented rather than
    the two methods retrieval happens to use: a partial implementation of a
    Protocol type-checks and then fails at runtime the first time a caller does
    something reasonable.
    """

    def __init__(self, db: Any, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def upsert(self, ns: Namespace, chunks: Sequence[EmbeddedChunk]) -> WriteResult:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresVectorStore(session).upsert(ns, chunks)

    async def search(
        self,
        ns: Namespace,
        embedding: Sequence[float],
        *,
        limit: int = 5,
        source_types: Sequence[EntityType] | None = None,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresVectorStore(session).search(
                ns, embedding, limit=limit, source_types=source_types, min_score=min_score
            )

    async def content_hashes(self, ns: Namespace) -> dict[tuple[str, str, int], str]:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresVectorStore(session).content_hashes(ns)

    async def delete_source(self, ns: Namespace, source_type: EntityType, source_id: str) -> int:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresVectorStore(session).delete_source(ns, source_type, source_id)

    async def prune(
        self, ns: Namespace, source_type: EntityType, source_id: str, keep_upto: int
    ) -> int:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresVectorStore(session).prune(ns, source_type, source_id, keep_upto)

    async def count(self, ns: Namespace) -> int:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresVectorStore(session).count(ns)

    async def models_for(self, tenant_id: str) -> dict[str, int]:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresVectorStore(session).models_for(tenant_id)
