"""RAG — chunking, embedding, storage and retrieval.

Milestone 1.9. The rest of ``neura-agent-core`` (graph runtime, tools, policy
engine) is milestone 1.10 and does not exist yet; this subpackage is
self-contained and usable without it, which is how the retrieval path gets
proved against a real catalogue before an agent depends on it.

The one invariant everything here is arranged around: **a vector belongs to a
namespace of (tenant_id, embedding_model), and nothing may read or write outside
one.** Both halves are load-bearing, and the failure mode for getting either
wrong is silent — see ``store.py``.
"""

from neura_agent_core.rag.chunking import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_OVERLAP_CHARS,
    INDEXABLE_TYPES,
    INDEXED_PRODUCT_STATUSES,
    Chunk,
    chunk_entity,
    missing_content,
    not_for_sale,
    render,
    split,
)
from neura_agent_core.rag.indexer import Indexer, IndexOutcome
from neura_agent_core.rag.postgres import DatabaseVectorStore, PostgresVectorStore
from neura_agent_core.rag.reindex import (
    Comparison,
    ComparisonRow,
    ReindexError,
    backfill_namespace,
    compare,
    retire_namespace,
)
from neura_agent_core.rag.retrieval import (
    DEFAULT_LIMIT,
    DEFAULT_MIN_SCORE,
    RetrievalResult,
    Retriever,
)
from neura_agent_core.rag.schema import TABLE_NAME, document_chunks
from neura_agent_core.rag.store import (
    CrossTenantWriteError,
    DimensionMismatchError,
    EmbeddedChunk,
    InMemoryVectorStore,
    Namespace,
    RetrievedChunk,
    VectorStore,
    VectorStoreError,
    WriteResult,
)

__all__ = [
    "DEFAULT_CHUNK_CHARS",
    "DEFAULT_LIMIT",
    "DEFAULT_MIN_SCORE",
    "DEFAULT_OVERLAP_CHARS",
    "INDEXABLE_TYPES",
    "INDEXED_PRODUCT_STATUSES",
    "TABLE_NAME",
    "Chunk",
    "Comparison",
    "ComparisonRow",
    "CrossTenantWriteError",
    "DatabaseVectorStore",
    "DimensionMismatchError",
    "EmbeddedChunk",
    "InMemoryVectorStore",
    "IndexOutcome",
    "Indexer",
    "Namespace",
    "PostgresVectorStore",
    "ReindexError",
    "RetrievalResult",
    "RetrievedChunk",
    "Retriever",
    "VectorStore",
    "VectorStoreError",
    "WriteResult",
    "backfill_namespace",
    "chunk_entity",
    "compare",
    "document_chunks",
    "missing_content",
    "not_for_sale",
    "render",
    "retire_namespace",
    "split",
]
