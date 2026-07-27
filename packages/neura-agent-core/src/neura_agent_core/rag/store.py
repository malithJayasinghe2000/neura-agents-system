"""Where vectors live.

``VectorStore`` is the interface ADR-0005 promises: pgvector today, swappable
later, with the swap being mechanical because nothing above this file knows what
a ``vector`` column is.

**Every method takes a namespace, and there is no method that does not.** A
namespace is ``(tenant_id, embedding_model)`` — both halves, always:

* Drop ``tenant_id`` and one merchant's catalogue answers another's shopper.
* Drop ``embedding_model`` and vectors from different models are compared to
  each other. Cosine similarity between a 768-dimensional vector and a
  1536-dimensional one is not a smaller number, it is a meaningless one — and
  where dimensions happen to match, it is meaningless *without erroring*. That
  is the failure mode this whole design exists to prevent
  (docs/architecture/llm-abstraction.md §5).

Making the namespace a required argument rather than a filter callers remember
to add is the difference between a rule and a hope.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from neura_agent_core.rag.chunking import Chunk
from neura_commerce import EntityType
from neura_core import NeuraError, new_id
from neura_core.ids import CHUNK


class VectorStoreError(NeuraError):
    code = "VECTOR_STORE_ERROR"


class CrossTenantWriteError(VectorStoreError):
    """A write was attempted for a tenant the transaction is not scoped to.

    The database refused it — this is Row-Level Security doing its job, not a
    bug in it. It is named rather than left as a driver exception because it is
    a security event: something in the call path resolved a tenant one way and
    built a namespace another way, and that is worth an alert rather than a
    stack trace nobody reads.
    """

    code = "CROSS_TENANT_WRITE_REJECTED"
    http_status = 403


class DimensionMismatchError(VectorStoreError):
    """A namespace was asked to hold two different vector sizes.

    Raised rather than tolerated. Two sizes under one model name means the model
    behind that name changed, and every vector written before the change is now
    incomparable with every vector written after it — with no error to say so.
    """

    code = "VECTOR_DIMENSION_MISMATCH"


@dataclass(frozen=True, slots=True)
class Namespace:
    """The isolation unit. Both halves are load-bearing."""

    tenant_id: str
    embedding_model: str

    def __post_init__(self) -> None:
        if not self.tenant_id or not self.embedding_model:
            raise ValueError("a namespace needs both a tenant_id and an embedding_model")

    def __str__(self) -> str:
        return f"{self.tenant_id}/{self.embedding_model}"


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """A chunk with its vector, ready to store."""

    chunk: Chunk
    embedding: list[float]

    @property
    def dimensions(self) -> int:
        return len(self.embedding)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A chunk that came back from a search, with how well it matched."""

    source_type: EntityType
    source_id: str
    chunk_index: int
    content: str
    score: float
    metadata: dict[str, object] = field(default_factory=dict)

    def as_untrusted(self) -> str:
        """Render for a prompt, explicitly marked as untrusted input.

        Merchant catalogue text is user-generated content and is a real indirect
        injection vector — a product description can contain instructions
        (docs/architecture/security-model.md §2.3). The delimiter is not a
        security boundary on its own; it is what makes the guard node's job and
        a human reviewer's job possible.
        """
        return (
            f'<untrusted source="retrieved_document" '
            f'id="{self.source_type.value}:{self.source_id}#{self.chunk_index}">\n'
            f"{self.content}\n"
            f"</untrusted>"
        )


@dataclass(slots=True)
class WriteResult:
    """What an index run actually changed.

    ``unchanged`` earns its place: it is how a nightly reindex proves it did not
    re-embed a catalogue nobody edited, and embedding is the expensive part.
    """

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0

    @property
    def written(self) -> int:
        return self.created + self.updated

    def merge(self, other: WriteResult) -> None:
        self.created += other.created
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.deleted += other.deleted


class VectorStore(Protocol):
    """Persistence for embedded chunks, always namespaced."""

    async def upsert(self, ns: Namespace, chunks: Sequence[EmbeddedChunk]) -> WriteResult: ...

    async def search(
        self,
        ns: Namespace,
        embedding: Sequence[float],
        *,
        limit: int = 5,
        source_types: Sequence[EntityType] | None = None,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]: ...

    async def content_hashes(self, ns: Namespace) -> dict[tuple[str, str, int], str]:
        """Existing text, keyed by ``(source_type, source_id, chunk_index)``.

        The indexer reads this before embedding anything, so unchanged text
        costs a hash comparison instead of an inference call.
        """
        ...

    async def delete_source(
        self, ns: Namespace, source_type: EntityType, source_id: str
    ) -> int: ...

    async def prune(
        self, ns: Namespace, source_type: EntityType, source_id: str, keep_upto: int
    ) -> int:
        """Drop chunks at index >= ``keep_upto`` for one source.

        An entity whose description was shortened produces fewer chunks than
        last time. Without this, the tail of the old version stays indexed and
        keeps being retrieved — text the merchant deleted, quoted back at their
        customers.
        """
        ...

    async def count(self, ns: Namespace) -> int: ...

    async def models_for(self, tenant_id: str) -> dict[str, int]:
        """Every embedding model this tenant has vectors under, and how many.

        Exists for one diagnosis: a search that returns nothing. That is either
        "no matching content" or "you are querying a namespace nothing was ever
        written to", and the two look identical without this.
        """
        ...

    async def drop_namespace(self, ns: Namespace) -> int:
        """Delete a whole namespace. The last step of a reindex."""
        ...


class InMemoryVectorStore:
    """In-memory implementation. Correct, not durable, no SQL.

    Used by unit tests, which is what lets the indexer, the retriever and the
    reindex path be tested without a database — and lets the PostgreSQL
    implementation be checked against a second opinion rather than against
    itself.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, str, int], _Row] = {}

    async def upsert(self, ns: Namespace, chunks: Sequence[EmbeddedChunk]) -> WriteResult:
        result = WriteResult()
        _require_one_dimension(ns, chunks, existing=self._dimensions(ns))

        for item in chunks:
            key = _key(ns, item.chunk)
            existing = self._rows.get(key)

            if existing is None:
                result.created += 1
            elif existing.content_hash == item.chunk.content_hash:
                result.unchanged += 1
                continue
            else:
                result.updated += 1

            self._rows[key] = _Row(
                id=existing.id if existing else new_id(CHUNK),
                source_type=item.chunk.source_type,
                source_id=item.chunk.source_id,
                chunk_index=item.chunk.chunk_index,
                content=item.chunk.content,
                content_hash=item.chunk.content_hash,
                embedding=list(item.embedding),
                metadata=dict(item.chunk.metadata),
            )

        return result

    async def search(
        self,
        ns: Namespace,
        embedding: Sequence[float],
        *,
        limit: int = 5,
        source_types: Sequence[EntityType] | None = None,
        min_score: float = 0.0,
    ) -> list[RetrievedChunk]:
        wanted = set(source_types) if source_types else None
        scored: list[tuple[float, _Row]] = []

        for key, row in self._rows.items():
            if key[0] != ns.tenant_id or key[1] != ns.embedding_model:
                continue
            if wanted is not None and row.source_type not in wanted:
                continue
            if len(row.embedding) != len(embedding):
                raise DimensionMismatchError(
                    f"namespace {ns} holds {len(row.embedding)}-dimensional vectors "
                    f"but the query vector has {len(embedding)}.",
                    details={"namespace": str(ns)},
                )
            scored.append((_cosine(row.embedding, embedding), row))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            RetrievedChunk(
                source_type=row.source_type,
                source_id=row.source_id,
                chunk_index=row.chunk_index,
                content=row.content,
                score=score,
                metadata=dict(row.metadata),
            )
            for score, row in scored[:limit]
            if score >= min_score
        ]

    async def content_hashes(self, ns: Namespace) -> dict[tuple[str, str, int], str]:
        return {
            (row.source_type.value, row.source_id, row.chunk_index): row.content_hash
            for key, row in self._rows.items()
            if key[0] == ns.tenant_id and key[1] == ns.embedding_model
        }

    async def delete_source(self, ns: Namespace, source_type: EntityType, source_id: str) -> int:
        doomed = [
            key
            for key, row in self._rows.items()
            if key[0] == ns.tenant_id
            and key[1] == ns.embedding_model
            and row.source_type is source_type
            and row.source_id == source_id
        ]
        for key in doomed:
            del self._rows[key]
        return len(doomed)

    async def prune(
        self, ns: Namespace, source_type: EntityType, source_id: str, keep_upto: int
    ) -> int:
        doomed = [
            key
            for key, row in self._rows.items()
            if key[0] == ns.tenant_id
            and key[1] == ns.embedding_model
            and row.source_type is source_type
            and row.source_id == source_id
            and row.chunk_index >= keep_upto
        ]
        for key in doomed:
            del self._rows[key]
        return len(doomed)

    async def count(self, ns: Namespace) -> int:
        return sum(
            1 for key in self._rows if key[0] == ns.tenant_id and key[1] == ns.embedding_model
        )

    async def models_for(self, tenant_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for key in self._rows:
            if key[0] == tenant_id:
                counts[key[1]] = counts.get(key[1], 0) + 1
        return counts

    async def drop_namespace(self, ns: Namespace) -> int:
        doomed = [
            key for key in self._rows if key[0] == ns.tenant_id and key[1] == ns.embedding_model
        ]
        for key in doomed:
            del self._rows[key]
        return len(doomed)

    def _dimensions(self, ns: Namespace) -> int | None:
        for key, row in self._rows.items():
            if key[0] == ns.tenant_id and key[1] == ns.embedding_model:
                return len(row.embedding)
        return None


@dataclass(slots=True)
class _Row:
    id: str
    source_type: EntityType
    source_id: str
    chunk_index: int
    content: str
    content_hash: str
    embedding: list[float]
    metadata: dict[str, object]


def _key(ns: Namespace, chunk: Chunk) -> tuple[str, str, str, str, int]:
    return (
        ns.tenant_id,
        ns.embedding_model,
        chunk.source_type.value,
        chunk.source_id,
        chunk.chunk_index,
    )


def _require_one_dimension(
    ns: Namespace, chunks: Sequence[EmbeddedChunk], *, existing: int | None
) -> None:
    """A namespace holds exactly one vector size, and this is where that is enforced.

    Checked on the way in rather than at query time: a mixed namespace is
    already corrupt by then, and the row that caused it is long gone.
    """
    sizes = {item.dimensions for item in chunks}
    if existing is not None:
        sizes.add(existing)
    if len(sizes) > 1:
        raise DimensionMismatchError(
            f"namespace {ns} would hold vectors of {sorted(sizes)} dimensions. "
            "Vectors of different sizes are not comparable — reindex under a new "
            "embedding model name instead (docs/architecture/llm-abstraction.md §5.2).",
            details={"namespace": str(ns), "dimensions": sorted(sizes)},
        )


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(math.fsum(x * x for x in a))
    norm_b = math.sqrt(math.fsum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
