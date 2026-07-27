"""Synced entities → vectors in a namespace.

The pipeline docs/architecture/commerce-integration.md §6.3 draws:

    entity ──► render ──► chunk ──► embed ──► pgvector
                                                 │
                            namespace: (tenant_id, embedding_model)

Three things this stage is responsible for, each protecting something specific:

* **Not re-embedding unchanged text.** Embedding is the expensive step and a
  catalogue mostly does not change between runs. The store already knows every
  chunk's content hash, so an unchanged chunk costs a dictionary lookup.
* **Removing what shrank.** An entity whose description was cut in half produces
  fewer chunks than last time. Without pruning the tail, deleted text stays
  indexed and keeps being retrieved — the merchant sees text they removed being
  quoted at their customers, which is worse than the agent not knowing.
* **Never claiming to have indexed what it skipped.** Every skip is counted and
  named. An index run that quietly embedded nothing looks exactly like one where
  nothing changed, and the difference only shows up as an agent that has stopped
  knowing about half the catalogue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from neura_agent_core.rag.chunking import (
    DEFAULT_CHUNK_CHARS,
    DEFAULT_OVERLAP_CHARS,
    INDEXABLE_TYPES,
    Chunk,
    chunk_entity,
    missing_content,
    not_for_sale,
)
from neura_agent_core.rag.store import EmbeddedChunk, Namespace, VectorStore, WriteResult
from neura_commerce import EntityType
from neura_core import get_logger
from neura_domain import CanonicalEntity, Category, Policy, Product
from neura_llm import LLMClient

log = get_logger(__name__)

#: Texts per embedding request. Small enough that a failure re-does little work,
#: large enough that a catalogue is not thousands of round trips. Local
#: inference serves few concurrent requests (llm-abstraction.md §9), so a bigger
#: batch here would not help.
DEFAULT_BATCH_SIZE = 32

Indexable = Product | Category | Policy


@dataclass(slots=True)
class IndexOutcome:
    """What one index run did. Reported, not only logged."""

    namespace: str
    entities: int = 0
    chunks: int = 0
    embedded: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    pruned: int = 0
    skipped: int = 0
    #: Entities of an indexable type that had nothing worth indexing — a product
    #: with no title, a policy with an empty body. Counted separately from
    #: ``skipped`` because this is a **merchant-facing data problem**, not our
    #: policy: those records exist in their shop and can never be found.
    blank: int = 0
    #: Products the merchant has taken off sale. Not a problem — the correct
    #: outcome — but counted, because "why can't the agent find my product?"
    #: is a support question and "you unpublished it" is the answer.
    withheld: int = 0
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return self.error is None

    @property
    def written(self) -> int:
        """Rows that actually changed. Named as on ``WriteResult`` and ``SyncOutcome``."""
        return self.created + self.updated

    def absorb(self, result: WriteResult) -> None:
        self.created += result.created
        self.updated += result.updated
        self.unchanged += result.unchanged

    def summary(self) -> str:
        return (
            f"{self.namespace}: {self.entities} entities → {self.chunks} chunks "
            f"(+{self.created} ~{self.updated} ={self.unchanged} -{self.pruned}), "
            f"{self.embedded} embedded"
            + (f", {self.blank} blank" if self.blank else "")
            + (f", {self.withheld} off sale" if self.withheld else "")
        )


class Indexer:
    """Embeds entities into one namespace.

    The namespace is derived from the client's configured ``EMBEDDER``, never
    passed in loose. Application code that could name its own embedding model
    could name the wrong one, and the resulting index would be wrong in the way
    that produces no error.
    """

    def __init__(
        self,
        store: VectorStore,
        llm: LLMClient,
        *,
        tenant_id: str,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_chars: int = DEFAULT_CHUNK_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ) -> None:
        self._store = store
        self._llm = llm
        self._namespace = Namespace(tenant_id=tenant_id, embedding_model=llm.embedding_model)
        self._batch_size = batch_size
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars

    @property
    def namespace(self) -> Namespace:
        return self._namespace

    async def index(self, entities: Sequence[CanonicalEntity]) -> IndexOutcome:
        """Index a batch of entities. Idempotent.

        Running this twice over an unchanged catalogue must produce zero writes
        and zero embedding calls the second time — the same property the sync
        engine has, for the same reason.
        """
        outcome = IndexOutcome(namespace=str(self._namespace))

        indexable, withdrawn = self._filter(entities, outcome)

        # An entity that *became* unindexable — a merchant clearing a title,
        # or unpublishing a product — must lose the chunks a previous run
        # wrote for it. Skipping it alone would leave the old version indexed
        # and retrievable forever: text the shop no longer has, or a product
        # it has deliberately taken off sale.
        for entity in withdrawn:
            outcome.pruned += await self._store.delete_source(
                self._namespace, _source_type(entity), entity.external_id
            )

        if not indexable:
            return outcome

        chunks: list[Chunk] = []
        for entity in indexable:
            produced = chunk_entity(
                entity, max_chars=self._max_chars, overlap_chars=self._overlap_chars
            )
            chunks.extend(produced)
            # Whatever the previous version of this entity left behind past the
            # end of the new one has to go, and it has to go here — nothing
            # downstream will ever look at it again.
            outcome.pruned += await self._store.prune(
                self._namespace,
                _source_type(entity),
                entity.external_id,
                keep_upto=len(produced),
            )

        outcome.entities = len(indexable)
        outcome.chunks = len(chunks)

        stale = await self._stale_only(chunks)
        outcome.unchanged += len(chunks) - len(stale)

        try:
            for batch in _batched(stale, self._batch_size):
                embedded = await self._embed(batch)
                outcome.embedded += len(embedded)
                outcome.absorb(await self._store.upsert(self._namespace, embedded))
        except Exception as exc:
            # Everything written before the failure stays written and stays
            # correct — chunks are independent. The next run re-reads the hashes
            # and picks up exactly where this one stopped.
            outcome.error = f"{type(exc).__name__}: {exc}"
            log.warning("rag_index_failed", namespace=str(self._namespace), error=str(exc))
            return outcome

        log.info(
            "rag_indexed",
            namespace=str(self._namespace),
            entities=outcome.entities,
            chunks=outcome.chunks,
            embedded=outcome.embedded,
            unchanged=outcome.unchanged,
        )
        return outcome

    async def forget(self, entity_type: EntityType, external_id: str) -> int:
        """Remove one source's chunks. The counterpart of a sync deletion.

        A product deleted from the shop but left in the index is the failure a
        shopper notices: the agent recommends something that cannot be bought.
        """
        return await self._store.delete_source(self._namespace, entity_type, external_id)

    # ── Internals ────────────────────────────────────────────────────────────

    def _filter(
        self, entities: Sequence[CanonicalEntity], outcome: IndexOutcome
    ) -> tuple[list[Indexable], list[Indexable]]:
        """Keep what may be indexed, and say what was dropped.

        Two different reasons for dropping something, reported separately
        because they are somebody else's problem in each case:

        * **Wrong type.** Orders and customers are refused rather than ignored.
          Semantic search over a customer's order history is a data-protection
          problem before it is a retrieval problem, and the refusal belongs in
          code — a comment saying "don't pass orders here" is not a control.
        * **Nothing to index.** A product with no title, a policy with an empty
          body. That is a gap in the *merchant's data*, so it is named, counted
          and attributed to specific records they can go and fix.
        """
        kept: list[Indexable] = []
        withdrawn: list[Indexable] = []
        refused: set[str] = set()
        empty: list[str] = []
        off_sale: list[str] = []

        for entity in entities:
            if not isinstance(entity, Product | Category | Policy):
                refused.add(type(entity).__name__)
                outcome.skipped += 1
                continue

            reason = missing_content(entity)
            if reason is not None:
                empty.append(f"{_source_type(entity).value}:{entity.external_id} ({reason})")
                withdrawn.append(entity)
                outcome.blank += 1
                continue

            reason = not_for_sale(entity)
            if reason is not None:
                off_sale.append(f"{_source_type(entity).value}:{entity.external_id} ({reason})")
                withdrawn.append(entity)
                outcome.withheld += 1
                continue

            kept.append(entity)

        if refused:
            outcome.notes.append(
                f"refused to index {outcome.skipped} entities of type "
                f"{', '.join(sorted(refused))} — only "
                f"{', '.join(t.value for t in INDEXABLE_TYPES)} are indexed "
                "(docs/architecture/commerce-integration.md §6.1)"
            )

        if empty:
            # Loud on purpose. These records exist in the shop and can never be
            # found by a shopper, and nothing else in the system will ever
            # mention them again.
            outcome.notes.append(
                f"{len(empty)} records have nothing to index and were skipped — "
                f"they cannot be retrieved until fixed in the shop: "
                f"{', '.join(sorted(empty)[:10])}" + (" …" if len(empty) > 10 else "")
            )
            log.warning(
                "rag_blank_entities",
                namespace=str(self._namespace),
                count=len(empty),
                records=sorted(empty)[:10],
            )

        if off_sale:
            # Not a warning — this is the system doing the right thing. Reported
            # because "why can't the agent find my product?" has to have an
            # answer, and "you unpublished it" is a good one.
            outcome.notes.append(
                f"{len(off_sale)} products are not on sale and were not indexed — "
                f"the agent will not recommend what a shopper cannot buy: "
                f"{', '.join(sorted(off_sale)[:10])}" + (" …" if len(off_sale) > 10 else "")
            )

        return kept, withdrawn

    async def _stale_only(self, chunks: list[Chunk]) -> list[Chunk]:
        known = await self._store.content_hashes(self._namespace)
        return [
            chunk
            for chunk in chunks
            if known.get((chunk.source_type.value, chunk.source_id, chunk.chunk_index))
            != chunk.content_hash
        ]

    async def _embed(self, chunks: Sequence[Chunk]) -> list[EmbeddedChunk]:
        result = await self._llm.embed([chunk.content for chunk in chunks])

        if len(result.vectors) != len(chunks):
            # A provider returning a different number of vectors than texts sent
            # would otherwise pair each chunk with a neighbour's embedding — an
            # index that is wrong everywhere, with nothing to show for it.
            raise ValueError(
                f"embedder returned {len(result.vectors)} vectors for {len(chunks)} texts"
            )

        return [
            EmbeddedChunk(chunk=chunk, embedding=vector)
            for chunk, vector in zip(chunks, result.vectors, strict=True)
        ]


def _source_type(entity: Indexable) -> EntityType:
    if isinstance(entity, Product):
        return EntityType.PRODUCT
    if isinstance(entity, Category):
        return EntityType.CATEGORY
    return EntityType.POLICY


def _batched(items: Sequence[Chunk], size: int) -> list[Sequence[Chunk]]:
    return [items[i : i + size] for i in range(0, len(items), size)]
