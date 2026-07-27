"""Changing the embedding model, without going dark.

docs/architecture/llm-abstraction.md §5.2 specifies the procedure. It is a
migration, and the reason it is written down at all is that the obvious
alternative — edit the config, restart — degrades retrieval silently: the query
gets embedded by the new model, every stored vector came from the old one, and
nothing matches. No error. Just an agent that has stopped knowing things.

    1. add the new model as `embedder_next`, leaving `embedder` serving traffic
    2. backfill under the new namespace — both now coexist
    3. run retrieval evals against both; compare recall@k
    4. promote embedder_next → embedder
    5. keep the old namespace for one release, then drop it

Steps 1 and 4 are configuration — a role map swap, no code. This module covers
2, 3 and 5, and refuses to let 5 happen before 4:
:func:`retire_namespace` will not delete the namespace that is currently
serving. Dropping the live namespace is a one-command outage that looks exactly
like the failure this whole design exists to avoid.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from neura_agent_core.rag.indexer import DEFAULT_BATCH_SIZE, Indexer, IndexOutcome
from neura_agent_core.rag.retrieval import DEFAULT_LIMIT, Retriever
from neura_agent_core.rag.store import Namespace, VectorStore
from neura_core import NeuraError, get_logger
from neura_domain import CanonicalEntity
from neura_llm import LLMClient

log = get_logger(__name__)


class ReindexError(NeuraError):
    code = "REINDEX_ERROR"


@dataclass(slots=True)
class ComparisonRow:
    query: str
    current_sources: list[str] = field(default_factory=list)
    candidate_sources: list[str] = field(default_factory=list)
    current_top_score: float = 0.0
    candidate_top_score: float = 0.0

    @property
    def agreement(self) -> float:
        """Overlap of the two result sets, as a fraction of the current one.

        Not a quality score — neither side is ground truth here. It is a change
        detector: 1.0 means the swap moved nothing and can be judged on cost and
        latency alone; a low number means the swap changed what the agent will
        see, and that needs a labelled set before anyone promotes it.
        """
        if not self.current_sources:
            return 1.0 if not self.candidate_sources else 0.0
        overlap = len(set(self.current_sources) & set(self.candidate_sources))
        return overlap / len(self.current_sources)


@dataclass(slots=True)
class Comparison:
    """Side-by-side retrieval under two embedding models."""

    current: str
    candidate: str
    rows: list[ComparisonRow] = field(default_factory=list)

    @property
    def mean_agreement(self) -> float:
        return sum(row.agreement for row in self.rows) / len(self.rows) if self.rows else 0.0

    def render(self) -> str:
        lines = [
            f"Embedding model: {self.current}  →  {self.candidate}",
            "",
        ]
        for row in self.rows:
            lines.append(f"  {row.query}")
            lines.append(f"    current   {row.current_top_score:.3f}  {row.current_sources}")
            lines.append(f"    candidate {row.candidate_top_score:.3f}  {row.candidate_sources}")
            lines.append(f"    agreement {row.agreement:.2f}")
        lines.append("")
        lines.append(f"  mean agreement {self.mean_agreement:.2f}")
        lines.append(
            "  Agreement measures change, not quality. Promote on a labelled "
            "recall@k set, not on this number."
        )
        return "\n".join(lines)


async def backfill_namespace(
    store: VectorStore,
    candidate: LLMClient,
    *,
    tenant_id: str,
    entities: Sequence[CanonicalEntity],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> IndexOutcome:
    """Step 2 — embed everything under the candidate model's namespace.

    The live namespace is untouched: a different ``embedding_model`` is a
    different set of rows. Traffic keeps being served by the old vectors
    throughout, which is what makes this reversible.
    """
    indexer = Indexer(store, candidate, tenant_id=tenant_id, batch_size=batch_size)
    outcome = await indexer.index(entities)
    log.info("rag_reindex_backfilled", namespace=outcome.namespace, chunks=outcome.chunks)
    return outcome


async def compare(
    store: VectorStore,
    current: LLMClient,
    candidate: LLMClient,
    *,
    tenant_id: str,
    queries: Sequence[str],
    limit: int = DEFAULT_LIMIT,
) -> Comparison:
    """Step 3 — run the same queries against both namespaces.

    Both must already be populated. Comparing against an empty candidate would
    report a dramatic difference caused entirely by step 2 not having been run,
    so that is refused rather than reported.
    """
    if current.embedding_model == candidate.embedding_model:
        raise ReindexError(
            "current and candidate use the same embedding model "
            f"({current.embedding_model!r}); there is nothing to compare.",
        )

    candidate_ns = Namespace(tenant_id=tenant_id, embedding_model=candidate.embedding_model)
    if await store.count(candidate_ns) == 0:
        raise ReindexError(
            f"namespace {candidate_ns} is empty — run backfill_namespace first. "
            "Comparing against an unpopulated namespace measures the backfill, "
            "not the model.",
            details={"namespace": str(candidate_ns)},
        )

    current_retriever = Retriever(store, current, tenant_id=tenant_id)
    candidate_retriever = Retriever(store, candidate, tenant_id=tenant_id)
    comparison = Comparison(current=current.embedding_model, candidate=candidate.embedding_model)

    for query in queries:
        before = await current_retriever.search(query, limit=limit)
        after = await candidate_retriever.search(query, limit=limit)
        comparison.rows.append(
            ComparisonRow(
                query=query,
                current_sources=before.sources,
                candidate_sources=after.sources,
                current_top_score=before.top_score,
                candidate_top_score=after.top_score,
            )
        )

    return comparison


async def retire_namespace(
    store: VectorStore,
    *,
    tenant_id: str,
    embedding_model: str,
    live: LLMClient,
) -> int:
    """Step 5 — drop a superseded namespace.

    Refuses to drop the one currently configured. That check is the whole value
    of this function: the failure it prevents has no error message, only an
    agent that has forgotten the catalogue, and by the time anyone notices the
    vectors are gone and re-embedding is the only way back.
    """
    if embedding_model == live.embedding_model:
        raise ReindexError(
            f"{embedding_model!r} is the embedding model currently configured. "
            "Dropping it would leave every retrieval empty. Promote the "
            "replacement in the role map first (llm-abstraction.md §5.2 step 4).",
            details={"embedding_model": embedding_model},
        )

    removed = await store.drop_namespace(
        Namespace(tenant_id=tenant_id, embedding_model=embedding_model)
    )
    log.info("rag_namespace_retired", tenant_id=tenant_id, model=embedding_model, removed=removed)
    return removed
