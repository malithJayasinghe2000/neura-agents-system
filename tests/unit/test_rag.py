"""RAG — chunking, indexing, retrieval and the reindex path.

The tests worth having here are not "does it store a vector". They are the
failures that produce **no error at all**: a namespace mismatch that returns
zero rows and reads as a bad question, a renderer edit that leaves half an index
embedded by the old version, an entity whose description shrank leaving deleted
text still retrievable, and a customer record quietly ending up in a semantic
index.

Every one of those degrades answers without failing anything. That is why they
are tested and "the happy path works" mostly is not.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from neura_agent_core.rag import (
    DimensionMismatchError,
    EmbeddedChunk,
    Indexer,
    InMemoryVectorStore,
    Namespace,
    ReindexError,
    Retriever,
    backfill_namespace,
    chunk_entity,
    compare,
    render,
    retire_namespace,
    split,
)
from neura_commerce import EntityType
from neura_domain import (
    Category,
    Customer,
    Money,
    Policy,
    PolicyKind,
    Product,
    ProductStatus,
    ProductVariant,
)

NOW = datetime(2026, 7, 27, tzinfo=UTC)
TENANT = "tn_rag"
OTHER_TENANT = "tn_other"
PLATFORM = "acme"


# ── Fixtures ─────────────────────────────────────────────────────────────────


def product(
    external_id: str = "p1",
    *,
    title: str = "Trail Runner GTX",
    description: str | None = "A waterproof trail shoe with an aggressive lug pattern.",
    tenant_id: str = TENANT,
    status: ProductStatus = ProductStatus.ACTIVE,
) -> Product:
    return Product(
        neura_id=f"ne_{external_id}",
        tenant_id=tenant_id,
        external_id=external_id,
        platform=PLATFORM,
        synced_at=NOW,
        title=title,
        description=description,
        status=status,
        url="https://shop.example/trail-runner",
        price_range_min=Money(amount=Decimal("120.00"), currency="USD"),
        price_range_max=Money(amount=Decimal("140.00"), currency="USD"),
        variants=[
            ProductVariant(external_id="v1", title="UK 9", options={"size": "9"}, in_stock=True),
            ProductVariant(external_id="v2", title="UK 10", options={"size": "10"}, in_stock=False),
        ],
    )


def policy(body: str = "Returns are accepted within 30 days of delivery.") -> Policy:
    return Policy(
        neura_id="ne_pol1",
        tenant_id=TENANT,
        external_id="pol1",
        platform=PLATFORM,
        synced_at=NOW,
        kind=PolicyKind.RETURNS,
        title="Our Returns Promise",
        body=body,
    )


def category() -> Category:
    return Category(
        neura_id="ne_cat1",
        tenant_id=TENANT,
        external_id="cat1",
        platform=PLATFORM,
        synced_at=NOW,
        name="Footwear",
        description="Shoes and boots for trail and road.",
    )


def customer() -> Customer:
    return Customer(
        neura_id="ne_c1",
        tenant_id=TENANT,
        external_id="c1",
        platform=PLATFORM,
        synced_at=NOW,
        email="shopper@example.com",
        first_name="Sam",
    )


class FakeEmbedder:
    """A deterministic stand-in for a real embedder.

    Vectors are derived from the words in the text, so semantically similar
    strings really are closer — enough to test ranking without an LLM, which
    AGENTS.md rules out of the unit suite anyway.
    """

    def __init__(self, model: str = "fake-embed-8", dimensions: int = 8) -> None:
        self.embedding_model = model
        self._dimensions = dimensions
        self.calls = 0
        self.texts_embedded = 0

    async def embed(self, texts: list[str]) -> FakeEmbeddingResult:
        self.calls += 1
        self.texts_embedded += len(texts)
        return FakeEmbeddingResult(
            vectors=[self._vector(t) for t in texts],
            model=self.embedding_model,
            dimensions=self._dimensions,
        )

    def _vector(self, text: str) -> list[float]:
        # sha256, not the builtin hash(): Python randomises string hashing per
        # process, which would make ranking assertions pass or fail depending on
        # the run. A flaky test about retrieval order is worse than none.
        vector = [0.0] * self._dimensions
        for word in text.lower().split():
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % self._dimensions
            vector[bucket] += 1.0
        return vector


class FakeEmbeddingResult:
    def __init__(self, vectors: list[list[float]], model: str, dimensions: int) -> None:
        self.vectors = vectors
        self.model = model
        self.dimensions = dimensions


# ── Rendering and chunking ───────────────────────────────────────────────────


class TestRendering:
    def test_a_product_renders_price_and_availability(self) -> None:
        """Shoppers ask about both constantly, and an embedding only finds what the text says."""
        text = render(product())
        assert "Price: 120.00 USD to 140.00 USD" in text
        assert "Availability: 1 of 2 variants in stock" in text
        assert "A waterproof trail shoe" in text

    def test_a_policy_renders_its_canonical_kind(self) -> None:
        """A merchant may title the page anything; `returns` is the only reliable word."""
        text = render(policy())
        assert text.startswith("Returns policy: Our Returns Promise")

    def test_rendering_is_stable(self) -> None:
        """Two renders of the same entity must be byte-identical.

        The content hash is what stops a nightly reindex re-embedding an
        unchanged catalogue. An unstable renderer — set iteration order, a
        timestamp — would defeat it silently, and the only symptom would be an
        embedding bill.
        """
        assert render(product()) == render(product())


class TestChunking:
    def test_short_text_is_one_chunk(self) -> None:
        assert len(chunk_entity(policy())) == 1

    def test_long_text_splits_with_overlap(self) -> None:
        long_body = "\n\n".join(f"Paragraph {i}. " + ("word " * 60) for i in range(10))
        chunks = chunk_entity(policy(body=long_body), max_chars=600, overlap_chars=100)

        assert len(chunks) > 1
        assert all(len(c.content) <= 600 for c in chunks)
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))

    def test_a_sentence_longer_than_a_chunk_is_still_indexed(self) -> None:
        """A wall of unpunctuated text must be split, not dropped."""
        chunks = chunk_entity(policy(body="word" * 2000), max_chars=300, overlap_chars=0)
        assert len(chunks) > 1
        assert sum(len(c.content) for c in chunks) >= 2000 * 4 - 300

    def test_chunk_ids_are_deterministic(self) -> None:
        first = chunk_entity(product())
        second = chunk_entity(product())
        assert [c.content_hash for c in first] == [c.content_hash for c in second]

    def test_editing_the_source_changes_the_hash(self) -> None:
        original = chunk_entity(product())[0]
        edited = chunk_entity(product(description="A completely different description."))[0]
        assert original.content_hash != edited.content_hash

    def test_metadata_stays_small(self) -> None:
        """Every field here costs tokens on every retrieval, forever."""
        chunk = chunk_entity(product())[0]
        assert set(chunk.metadata) <= {"part", "of", "title", "url", "kind"}

    def test_split_of_empty_text_produces_nothing(self) -> None:
        assert split("   ") == []


# ── The namespace, which is the whole point ──────────────────────────────────


class TestNamespaceIsolation:
    async def test_a_tenant_cannot_see_another_tenants_chunks(self) -> None:
        store = InMemoryVectorStore()
        embedder = FakeEmbedder()

        await Indexer(store, embedder, tenant_id=TENANT).index([product()])
        await Indexer(store, embedder, tenant_id=OTHER_TENANT).index(
            [product(tenant_id=OTHER_TENANT)]
        )

        assert await store.count(Namespace(TENANT, embedder.embedding_model)) == 1
        assert await store.count(Namespace(OTHER_TENANT, embedder.embedding_model)) == 1

        found = await Retriever(store, embedder, tenant_id=TENANT).search("trail shoe")
        assert found
        assert all(c.source_id == "p1" for c in found.chunks)

    async def test_two_embedding_models_coexist_without_mixing(self) -> None:
        """Both namespaces must be readable at once — the reindex procedure depends on it."""
        store = InMemoryVectorStore()
        old = FakeEmbedder("nomic-like", dimensions=8)
        new = FakeEmbedder("cloud-like", dimensions=16)

        await Indexer(store, old, tenant_id=TENANT).index([product()])
        await Indexer(store, new, tenant_id=TENANT).index([product()])

        assert await store.models_for(TENANT) == {"nomic-like": 1, "cloud-like": 1}

    async def test_a_namespace_refuses_two_vector_sizes(self) -> None:
        """The trap from llm-abstraction §5, made into an exception.

        Same model *name*, different dimensions, means the model behind the name
        changed. Every vector written before is now incomparable with every
        vector written after, and nothing would say so.
        """
        store = InMemoryVectorStore()
        ns = Namespace(TENANT, "shifty-model")
        chunk = chunk_entity(product())[0]

        await store.upsert(ns, [EmbeddedChunk(chunk=chunk, embedding=[0.1] * 8)])

        with pytest.raises(DimensionMismatchError):
            await store.upsert(
                ns, [EmbeddedChunk(chunk=chunk_entity(category())[0], embedding=[0.1] * 16)]
            )


class TestTheEmptyResultIsDiagnosed:
    """An empty retrieval is the symptom of three different problems.

    Without a diagnosis they are indistinguishable, and the expensive one — a
    namespace mismatch — reads as "the agent doesn't know that", which nobody
    investigates for weeks.
    """

    async def test_nothing_indexed_at_all_says_so(self) -> None:
        result = await Retriever(InMemoryVectorStore(), FakeEmbedder(), tenant_id=TENANT).search(
            "anything"
        )

        assert not result
        assert result.diagnosis is not None
        assert "not been indexed" in result.diagnosis

    async def test_a_namespace_mismatch_is_named_and_the_real_model_listed(self) -> None:
        store = InMemoryVectorStore()
        indexed_with = FakeEmbedder("nomic-embed-text")
        queried_with = FakeEmbedder("some-cloud-embedder")

        await Indexer(store, indexed_with, tenant_id=TENANT).index([product()])
        result = await Retriever(store, queried_with, tenant_id=TENANT).search("trail shoe")

        assert not result
        assert result.diagnosis is not None
        assert "NAMESPACE MISMATCH" in result.diagnosis
        assert "nomic-embed-text" in result.diagnosis

    async def test_a_genuinely_unmatched_query_is_reported_differently(self) -> None:
        store = InMemoryVectorStore()
        embedder = FakeEmbedder()
        await Indexer(store, embedder, tenant_id=TENANT).index([product()])

        result = await Retriever(store, embedder, tenant_id=TENANT).search(
            "quantum chromodynamics", min_score=0.99
        )

        assert not result
        assert result.diagnosis is not None
        assert "NAMESPACE MISMATCH" not in result.diagnosis
        assert "indexed" in result.diagnosis


# ── Indexing ─────────────────────────────────────────────────────────────────


class TestIndexing:
    async def test_reindexing_unchanged_content_embeds_nothing(self) -> None:
        """The property that makes a nightly reindex affordable."""
        store = InMemoryVectorStore()
        embedder = FakeEmbedder()
        indexer = Indexer(store, embedder, tenant_id=TENANT)

        first = await indexer.index([product(), category(), policy()])
        calls_after_first = embedder.calls

        second = await indexer.index([product(), category(), policy()])

        assert first.created == 3
        assert second.created == 0
        assert second.unchanged == 3
        assert second.embedded == 0
        assert embedder.calls == calls_after_first, "an unchanged catalogue was re-embedded"

    async def test_an_edit_re_embeds_only_what_changed(self) -> None:
        store = InMemoryVectorStore()
        embedder = FakeEmbedder()
        indexer = Indexer(store, embedder, tenant_id=TENANT)

        await indexer.index([product(), category()])
        outcome = await indexer.index(
            [product(description="Now a completely new blurb."), category()]
        )

        assert outcome.updated == 1
        assert outcome.unchanged == 1
        assert outcome.embedded == 1

    async def test_shrinking_an_entity_removes_its_orphaned_tail(self) -> None:
        """Deleted text must stop being retrievable immediately.

        Otherwise the agent keeps quoting a paragraph the merchant removed —
        which is the version of staleness a merchant actually notices, because
        it is their own words coming back at them.
        """
        store = InMemoryVectorStore()
        embedder = FakeEmbedder()
        indexer = Indexer(store, embedder, tenant_id=TENANT, max_chars=300, overlap_chars=0)
        ns = Namespace(TENANT, embedder.embedding_model)

        long_body = "\n\n".join(f"Section {i}. " + ("text " * 50) for i in range(6))
        await indexer.index([policy(body=long_body)])
        before = await store.count(ns)
        assert before > 1

        outcome = await indexer.index([policy(body="We now accept returns within 30 days.")])

        assert outcome.pruned == before - 1
        assert await store.count(ns) == 1

    async def test_customers_are_refused_and_the_refusal_is_reported(self) -> None:
        """Not a filter — a control. Semantic search over customer records is a
        data-protection problem before it is a retrieval problem."""
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)

        outcome = await indexer.index([product(), customer()])

        assert outcome.entities == 1
        assert outcome.skipped == 1
        assert any("refused to index" in note for note in outcome.notes)
        assert await store.count(indexer.namespace) == 1

    async def test_a_product_with_no_title_is_not_indexed(self) -> None:
        """Found on a real shop: two products whose name was never filled in.

        They render to `Product:\\nAvailability: out of stock\\nStatus: active` —
        structurally fine, semantically empty. Embedding that puts a meaningless
        vector in the index which can surface for unrelated queries, and if the
        agent ever retrieves it, it recommends a nameless product to a shopper.
        """
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)

        outcome = await indexer.index([product(), product("p2", title="   ")])

        assert outcome.entities == 1
        assert outcome.blank == 1
        assert await store.count(indexer.namespace) == 1

    async def test_a_blank_entity_is_named_so_the_merchant_can_fix_it(self) -> None:
        """Counted is not enough — "1 record skipped" is unactionable."""
        outcome = await Indexer(InMemoryVectorStore(), FakeEmbedder(), tenant_id=TENANT).index(
            [product("p9", title="")]
        )

        note = " ".join(outcome.notes)
        assert "product:p9" in note
        assert "no title" in note
        assert "cannot be retrieved" in note

    async def test_a_policy_with_an_empty_body_is_not_indexed(self) -> None:
        """A policy *is* its body. A title alone grounds no answer."""
        outcome = await Indexer(InMemoryVectorStore(), FakeEmbedder(), tenant_id=TENANT).index(
            [policy(body="   ")]
        )

        assert outcome.blank == 1
        assert "empty body" in " ".join(outcome.notes)

    async def test_an_entity_that_becomes_blank_loses_its_old_chunks(self) -> None:
        """The nastier half of the bug.

        A merchant clearing a product's title must not leave the previous
        version indexed and retrievable — text their shop no longer has, quoted
        back at their customers.
        """
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)

        await indexer.index([product()])
        assert await store.count(indexer.namespace) == 1

        outcome = await indexer.index([product(title="")])

        assert outcome.blank == 1
        assert outcome.pruned == 1
        assert await store.count(indexer.namespace) == 0

    async def test_a_product_with_a_title_but_no_description_is_still_indexed(self) -> None:
        """Sparse is not empty. Plenty of real catalogues have title-only rows,
        and "Ashford Slim Chinos" is a perfectly good match target."""
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)

        outcome = await indexer.index([product(description=None)])

        assert outcome.blank == 0
        assert await store.count(indexer.namespace) == 1

    async def test_placeholder_prose_is_still_indexed(self) -> None:
        """Deliberately not clever.

        No rule reliably separates "Return Policy Page Content" from terse real
        prose, and a heuristic that guessed would drop genuine content. Emptiness
        is unambiguous; vagueness is the merchant's call.
        """
        outcome = await Indexer(InMemoryVectorStore(), FakeEmbedder(), tenant_id=TENANT).index(
            [policy(body="Return Policy Page Content")]
        )

        assert outcome.blank == 0
        assert outcome.created == 1

    async def test_a_draft_product_is_not_indexed(self) -> None:
        """The merchant took it off sale. Recommending it wastes a shopper's time
        and leaves the merchant explaining a product they unpublished."""
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)

        outcome = await indexer.index([product(), product("p2", status=ProductStatus.DRAFT)])

        assert outcome.entities == 1
        assert outcome.withheld == 1
        assert "not on sale" in " ".join(outcome.notes)
        assert await store.count(indexer.namespace) == 1

    async def test_an_archived_product_is_not_indexed(self) -> None:
        outcome = await Indexer(InMemoryVectorStore(), FakeEmbedder(), tenant_id=TENANT).index(
            [product(status=ProductStatus.ARCHIVED)]
        )
        assert outcome.withheld == 1

    async def test_an_unknown_status_is_still_indexed(self) -> None:
        """The decision that matters most here, and the least obvious.

        `UNKNOWN` means the shop sent a status word we could not map — not that
        the product is unavailable. Excluding it would empty the index for any
        shop whose vocabulary we have not seen, and the only symptom would be an
        agent that answers "I don't know" to everything. Tolerate, then report —
        the same call the adapter layer made in 1.6.
        """
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)

        outcome = await indexer.index([product(status=ProductStatus.UNKNOWN)])

        assert outcome.withheld == 0
        assert await store.count(indexer.namespace) == 1

    async def test_unpublishing_a_product_removes_its_existing_chunks(self) -> None:
        """Otherwise the agent keeps recommending something withdrawn from sale."""
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)

        await indexer.index([product()])
        assert await store.count(indexer.namespace) == 1

        outcome = await indexer.index([product(status=ProductStatus.DRAFT)])

        assert outcome.withheld == 1
        assert outcome.pruned == 1
        assert await store.count(indexer.namespace) == 0

    async def test_categories_and_policies_have_no_sale_status(self) -> None:
        """Only products are purchasable. A page is present or deleted."""
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)

        outcome = await indexer.index([category(), policy()])

        assert outcome.withheld == 0
        assert await store.count(indexer.namespace) == 2

    async def test_a_deleted_product_can_be_forgotten(self) -> None:
        store = InMemoryVectorStore()
        indexer = Indexer(store, FakeEmbedder(), tenant_id=TENANT)
        await indexer.index([product()])

        removed = await indexer.forget(EntityType.PRODUCT, "p1")

        assert removed == 1
        assert await store.count(indexer.namespace) == 0

    async def test_an_embedder_returning_the_wrong_number_of_vectors_fails_loudly(self) -> None:
        """Silently pairing each chunk with a neighbour's vector would corrupt
        the whole index while every count still looked right."""

        class MiscountingEmbedder(FakeEmbedder):
            async def embed(self, texts: list[str]) -> FakeEmbeddingResult:
                result = await super().embed(texts)
                result.vectors = result.vectors[:-1]
                return result

        store = InMemoryVectorStore()
        outcome = await Indexer(store, MiscountingEmbedder(), tenant_id=TENANT).index(
            [product(), category()]
        )

        assert not outcome.completed
        assert outcome.error is not None
        assert "vectors" in outcome.error


# ── Retrieval ────────────────────────────────────────────────────────────────


class TestRetrieval:
    async def test_results_are_ordered_by_similarity(self) -> None:
        store = InMemoryVectorStore()
        embedder = FakeEmbedder(dimensions=64)
        await Indexer(store, embedder, tenant_id=TENANT).index([product(), category(), policy()])

        result = await Retriever(store, embedder, tenant_id=TENANT).search(
            "Returns policy: Our Returns Promise", min_score=0.0
        )

        assert result.chunks[0].source_type is EntityType.POLICY
        scores = [c.score for c in result.chunks]
        assert scores == sorted(scores, reverse=True)

    async def test_source_types_can_be_restricted(self) -> None:
        store = InMemoryVectorStore()
        embedder = FakeEmbedder(dimensions=64)
        await Indexer(store, embedder, tenant_id=TENANT).index([product(), policy()])

        result = await Retriever(store, embedder, tenant_id=TENANT).search(
            "returns", source_types=[EntityType.POLICY], min_score=0.0
        )

        assert all(c.source_type is EntityType.POLICY for c in result.chunks)

    async def test_retrieved_context_is_marked_untrusted(self) -> None:
        """Catalogue text is user-generated content and a real injection vector.

        The delimiter is not itself a defence — it is what lets the guard node
        and a human reviewer see where model-facing text came from.
        """
        store = InMemoryVectorStore()
        embedder = FakeEmbedder(dimensions=64)
        await Indexer(store, embedder, tenant_id=TENANT).index([product()])

        context = (
            await Retriever(store, embedder, tenant_id=TENANT).search("shoe", min_score=0.0)
        ).as_context()

        assert '<untrusted source="retrieved_document"' in context
        assert "</untrusted>" in context
        assert "Trail Runner GTX" in context

    async def test_an_empty_query_is_rejected_rather_than_embedded(self) -> None:
        embedder = FakeEmbedder()
        result = await Retriever(InMemoryVectorStore(), embedder, tenant_id=TENANT).search("  ")

        assert not result
        assert embedder.calls == 0

    async def test_sources_are_citable(self) -> None:
        store = InMemoryVectorStore()
        embedder = FakeEmbedder(dimensions=64)
        await Indexer(store, embedder, tenant_id=TENANT).index([product()])

        result = await Retriever(store, embedder, tenant_id=TENANT).search("shoe", min_score=0.0)

        assert result.sources == ["product:p1#0"]


# ── The reindex path ─────────────────────────────────────────────────────────


class TestReindex:
    async def test_a_candidate_backfill_leaves_the_live_namespace_serving(self) -> None:
        """Step 2 of llm-abstraction §5.2. Both namespaces must work throughout."""
        store = InMemoryVectorStore()
        live = FakeEmbedder("live-model", dimensions=8)
        candidate = FakeEmbedder("candidate-model", dimensions=16)

        await Indexer(store, live, tenant_id=TENANT).index([product(), policy()])
        await backfill_namespace(store, candidate, tenant_id=TENANT, entities=[product(), policy()])

        assert await Retriever(store, live, tenant_id=TENANT).search("shoe", min_score=0.0)
        assert await Retriever(store, candidate, tenant_id=TENANT).search("shoe", min_score=0.0)

    async def test_comparing_against_an_empty_candidate_is_refused(self) -> None:
        """It would measure whether step 2 ran, and report it as a model difference."""
        store = InMemoryVectorStore()
        live = FakeEmbedder("live-model")
        candidate = FakeEmbedder("candidate-model")
        await Indexer(store, live, tenant_id=TENANT).index([product()])

        with pytest.raises(ReindexError, match="empty"):
            await compare(store, live, candidate, tenant_id=TENANT, queries=["shoe"])

    async def test_comparison_reports_agreement_not_a_verdict(self) -> None:
        store = InMemoryVectorStore()
        live = FakeEmbedder("live-model", dimensions=64)
        candidate = FakeEmbedder("candidate-model", dimensions=64)
        entities = [product(), category(), policy()]

        await Indexer(store, live, tenant_id=TENANT).index(entities)
        await backfill_namespace(store, candidate, tenant_id=TENANT, entities=entities)

        report = await compare(
            store, live, candidate, tenant_id=TENANT, queries=["returns", "trail shoe"]
        )

        assert len(report.rows) == 2
        assert 0.0 <= report.mean_agreement <= 1.0
        assert "Agreement measures change, not quality" in report.render()

    async def test_dropping_the_live_namespace_is_refused(self) -> None:
        """The one-command outage this whole module exists to prevent."""
        store = InMemoryVectorStore()
        live = FakeEmbedder("live-model")
        await Indexer(store, live, tenant_id=TENANT).index([product()])

        with pytest.raises(ReindexError, match="currently configured"):
            await retire_namespace(store, tenant_id=TENANT, embedding_model="live-model", live=live)

        assert await store.count(Namespace(TENANT, "live-model")) == 1

    async def test_a_superseded_namespace_can_be_retired(self) -> None:
        store = InMemoryVectorStore()
        old = FakeEmbedder("old-model")
        promoted = FakeEmbedder("new-model")

        await Indexer(store, old, tenant_id=TENANT).index([product(), policy()])
        await Indexer(store, promoted, tenant_id=TENANT).index([product(), policy()])

        removed = await retire_namespace(
            store, tenant_id=TENANT, embedding_model="old-model", live=promoted
        )

        assert removed == 2
        assert await store.models_for(TENANT) == {"new-model": 2}


class TestNamespaceType:
    def test_both_halves_are_required(self) -> None:
        with pytest.raises(ValueError, match="tenant_id"):
            Namespace("", "some-model")
        with pytest.raises(ValueError, match="embedding_model"):
            Namespace(TENANT, "")
