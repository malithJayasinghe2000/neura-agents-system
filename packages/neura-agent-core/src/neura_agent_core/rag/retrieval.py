"""Query → chunks the agent may ground an answer in.

The ``retrieve`` node of every agent graph runs through here
(docs/architecture/agent-runtime.md §2).

**The thing this module exists to prevent is an empty result that says nothing.**
AGENTS.md lists it as a gotcha — "retrieval returns nothing → embedding-model
namespace mismatch" — and that is exactly the shape of the bug: the query is
embedded with model B, the catalogue was embedded with model A, every filter
matches zero rows, and the agent politely says it does not know. No exception,
no log line, no failed health check. It reads as a bad question.

So an empty result is *diagnosed* rather than returned bare. If the namespace is
empty but the tenant has vectors under other models, the result says so and
names them. That turns a week of "the agent got worse" into one line of output.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from neura_agent_core.rag.store import Namespace, RetrievedChunk, VectorStore
from neura_commerce import EntityType
from neura_core import get_logger
from neura_llm import LLMClient

log = get_logger(__name__)

#: How many chunks a graph node asks for by default. Small: a local model's
#: context is the scarce resource (llm-abstraction.md §9), and the retrieval
#: recall@5 metric in the evaluation strategy is defined at this k.
DEFAULT_LIMIT = 5

#: Below this cosine similarity a chunk is noise. Deliberately low — retrieval
#: hands evidence to a ``verify`` node whose job is to reject ungrounded claims,
#: so an over-strict threshold here loses answers the agent could have given,
#: while a loose one costs tokens and is caught downstream.
#:
#: A starting point, not a measurement. Recalibrate against a labelled set
#: (docs/architecture/evaluation-strategy.md §3).
DEFAULT_MIN_SCORE = 0.3


@dataclass(slots=True)
class RetrievalResult:
    """What retrieval found, and — when it found nothing — why."""

    namespace: str
    query: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    #: Set when the result is empty for a reason the caller can act on.
    diagnosis: str | None = None

    def __bool__(self) -> bool:
        return bool(self.chunks)

    def __len__(self) -> int:
        return len(self.chunks)

    @property
    def top_score(self) -> float:
        return self.chunks[0].score if self.chunks else 0.0

    @property
    def sources(self) -> list[str]:
        """Stable references an answer can cite and a reviewer can look up."""
        return [f"{c.source_type.value}:{c.source_id}#{c.chunk_index}" for c in self.chunks]

    def as_context(self) -> str:
        """The retrieved evidence, rendered for a prompt.

        Every chunk is wrapped in an ``<untrusted>`` element. Merchant catalogue
        text is user-generated content and a real indirect-injection vector — a
        product description can contain "ignore previous instructions"
        (docs/architecture/security-model.md §2.3). The delimiter does not make
        that safe by itself; it makes it *visible*, to the guard node and to a
        human reading the trace.
        """
        return "\n\n".join(chunk.as_untrusted() for chunk in self.chunks)


class Retriever:
    """Semantic search over one tenant's indexed content."""

    def __init__(self, store: VectorStore, llm: LLMClient, *, tenant_id: str) -> None:
        self._store = store
        self._llm = llm
        self._tenant_id = tenant_id
        # Derived from the same role map the indexer used. Both sides reading
        # the configured EMBEDDER is what makes the namespaces line up; a
        # caller-supplied model name is a mismatch waiting to happen.
        self._namespace = Namespace(tenant_id=tenant_id, embedding_model=llm.embedding_model)

    @property
    def namespace(self) -> Namespace:
        return self._namespace

    async def search(
        self,
        query: str,
        *,
        limit: int = DEFAULT_LIMIT,
        source_types: Sequence[EntityType] | None = None,
        min_score: float = DEFAULT_MIN_SCORE,
    ) -> RetrievalResult:
        result = RetrievalResult(namespace=str(self._namespace), query=query)

        if not query.strip():
            result.diagnosis = "empty query"
            return result

        embedded = await self._llm.embed([query])
        result.chunks = await self._store.search(
            self._namespace,
            embedded.vectors[0],
            limit=limit,
            source_types=source_types,
            min_score=min_score,
        )

        if not result.chunks:
            result.diagnosis = await self._diagnose(min_score)

        log.info(
            "rag_retrieved",
            namespace=str(self._namespace),
            hits=len(result.chunks),
            top_score=round(result.top_score, 4),
            diagnosis=result.diagnosis,
        )
        return result

    async def _diagnose(self, min_score: float) -> str:
        """Distinguish "nothing matched" from "nothing is there".

        These are different problems with identical symptoms. The first is a
        question outside the catalogue and is fine. The second is a
        configuration fault that silently disables retrieval for every
        conversation, and it needs to be said out loud the first time it
        happens.
        """
        indexed = await self._store.count(self._namespace)
        if indexed > 0:
            return f"no chunk scored at or above {min_score} among {indexed} indexed"

        by_model = await self._store.models_for(self._tenant_id)
        if by_model:
            others = ", ".join(f"{model} ({count})" for model, count in sorted(by_model.items()))
            return (
                f"NAMESPACE MISMATCH: nothing is indexed under embedding model "
                f"{self._llm.embedding_model!r} for this tenant, but vectors exist "
                f"under {others}. The configured EMBEDDER does not match what the "
                f"catalogue was indexed with — reindex, or point the role map back. "
                f"See docs/architecture/llm-abstraction.md §5.2."
            )

        return (
            f"nothing is indexed for tenant {self._tenant_id} under any embedding "
            f"model — the catalogue has not been indexed yet"
        )
