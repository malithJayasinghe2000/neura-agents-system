"""The pgvector store, against a real PostgreSQL.

These cannot be unit tests, and substituting a fake would defeat their purpose.
Everything here is a property of *PostgreSQL* rather than of our code:

* Row-Level Security actually filtering, which is the entire tenant-isolation
  argument in ADR-0008. A fake store "proving" isolation proves only that the
  fake filters.
* ``ON CONFLICT`` on the natural key making a re-run an upsert rather than an
  append.
* Two vector sizes coexisting in one dimensionless column — the thing that makes
  the reindex procedure possible at all.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).

**The cross-tenant tests here are the ones to keep working.** They are the check
ADR-0008 asks for by name, and they only mean anything because the application
connects as a role RLS applies to — if that ever regresses to the owner or a
superuser, every one of these passes while isolating nothing. ``ping()`` is
asserted first, for exactly that reason.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from neura_agent_core.rag import (
    CrossTenantWriteError,
    DimensionMismatchError,
    EmbeddedChunk,
    Namespace,
    PostgresVectorStore,
)
from neura_agent_core.rag.chunking import Chunk
from neura_commerce import EntityType
from neura_core import Database

pytestmark = pytest.mark.integration

NOW = datetime(2026, 7, 27, tzinfo=UTC)
TENANT_A = "tn_itest_a"
TENANT_B = "tn_itest_b"
MODEL = "itest-embed"


def chunk(tenant: str, source_id: str, index: int, content: str) -> Chunk:
    return Chunk(
        tenant_id=tenant,
        source_type=EntityType.PRODUCT,
        source_id=source_id,
        chunk_index=index,
        content=content,
        metadata={"title": content[:20]},
    )


def embedded(tenant: str, source_id: str, index: int, content: str, vector: list[float]):
    return EmbeddedChunk(chunk=chunk(tenant, source_id, index, content), embedding=vector)


@pytest.fixture
async def db():
    database = Database.from_settings()

    # A database that is not running is a skip: not everyone has Docker up.
    # A database connected as a role RLS does not apply to is a FAILURE, and
    # deliberately not a skip — skipping it is how a suite ends up reporting
    # green while the isolation it claims to prove was never in effect.
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")

    yield database

    for tenant in (TENANT_A, TENANT_B):
        async with database.tenant_session(tenant) as session:
            await session.execute(
                text("DELETE FROM document_chunks WHERE tenant_id = :t"), {"t": tenant}
            )
    await database.dispose()


class TestTenantIsolation:
    """ADR-0008's own acceptance criterion: cross-tenant reads must fail."""

    async def test_the_connected_role_is_subject_to_rls(self, db: Database) -> None:
        """Everything below is meaningless if this is false.

        A superuser or BYPASSRLS connection ignores every policy, so the
        isolation tests would pass while isolating nothing — the most
        reassuring possible way to have no security at all.
        """
        await db.assert_isolation_applies()

    async def test_a_tenant_cannot_read_another_tenants_chunks(self, db: Database) -> None:
        ns_a = Namespace(TENANT_A, MODEL)

        async with db.tenant_session(TENANT_A) as session:
            await PostgresVectorStore(session).upsert(
                ns_a, [embedded(TENANT_A, "p1", 0, "tenant a secret", [1.0, 0.0, 0.0])]
            )

        async with db.tenant_session(TENANT_B) as session:
            store = PostgresVectorStore(session)
            assert await store.count(ns_a) == 0
            assert await store.search(ns_a, [1.0, 0.0, 0.0]) == []
            assert await store.models_for(TENANT_A) == {}

    async def test_a_tenant_cannot_write_into_another_tenants_namespace(self, db: Database) -> None:
        """Rejected by the database, then named by us.

        A driver-level error here would surface as a 500 with a stack trace.
        This is a security event and reads like one.
        """
        async with db.tenant_session(TENANT_B) as session:
            with pytest.raises(CrossTenantWriteError):
                await PostgresVectorStore(session).upsert(
                    Namespace(TENANT_A, MODEL),
                    [embedded(TENANT_A, "p9", 0, "smuggled", [1.0, 0.0, 0.0])],
                )

    async def test_a_tenant_cannot_delete_another_tenants_chunks(self, db: Database) -> None:
        ns_a = Namespace(TENANT_A, MODEL)

        async with db.tenant_session(TENANT_A) as session:
            await PostgresVectorStore(session).upsert(
                ns_a, [embedded(TENANT_A, "p1", 0, "still here", [1.0, 0.0, 0.0])]
            )

        async with db.tenant_session(TENANT_B) as session:
            assert await PostgresVectorStore(session).drop_namespace(ns_a) == 0

        async with db.tenant_session(TENANT_A) as session:
            assert await PostgresVectorStore(session).count(ns_a) == 1

    async def test_a_session_without_a_tenant_is_refused_outright(self, db: Database) -> None:
        with pytest.raises(Exception, match="tenant_id"):
            async with db.tenant_session(""):
                pass


class TestPersistence:
    async def test_re_running_an_index_updates_rather_than_appends(self, db: Database) -> None:
        ns = Namespace(TENANT_A, MODEL)

        async with db.tenant_session(TENANT_A) as session:
            store = PostgresVectorStore(session)
            first = await store.upsert(
                ns, [embedded(TENANT_A, "p1", 0, "original text", [1.0, 0.0, 0.0])]
            )
            second = await store.upsert(
                ns, [embedded(TENANT_A, "p1", 0, "edited text", [0.0, 1.0, 0.0])]
            )
            unchanged = await store.upsert(
                ns, [embedded(TENANT_A, "p1", 0, "edited text", [0.0, 1.0, 0.0])]
            )

            assert (first.created, second.updated, unchanged.unchanged) == (1, 1, 1)
            assert await store.count(ns) == 1

            hits = await store.search(ns, [0.0, 1.0, 0.0], limit=5)
            assert hits[0].content == "edited text"

    async def test_similarity_is_a_similarity_and_not_a_distance(self, db: Database) -> None:
        """pgvector's ``<=>`` returns distance. Returning it unconverted would
        make every ``>= threshold`` filter select the worst matches."""
        ns = Namespace(TENANT_A, MODEL)

        async with db.tenant_session(TENANT_A) as session:
            store = PostgresVectorStore(session)
            await store.upsert(
                ns,
                [
                    embedded(TENANT_A, "near", 0, "near", [1.0, 0.0, 0.0]),
                    embedded(TENANT_A, "far", 0, "far", [-1.0, 0.0, 0.0]),
                ],
            )

            hits = await store.search(ns, [1.0, 0.0, 0.0], limit=2, min_score=-2.0)

            assert [h.source_id for h in hits] == ["near", "far"]
            assert hits[0].score == pytest.approx(1.0, abs=1e-6)
            assert hits[1].score == pytest.approx(-1.0, abs=1e-6)

    async def test_metadata_survives_the_round_trip(self, db: Database) -> None:
        ns = Namespace(TENANT_A, MODEL)

        async with db.tenant_session(TENANT_A) as session:
            store = PostgresVectorStore(session)
            await store.upsert(
                ns, [embedded(TENANT_A, "p1", 0, "a product with metadata", [1.0, 0.0, 0.0])]
            )
            hits = await store.search(ns, [1.0, 0.0, 0.0])

            assert hits[0].metadata["title"] == "a product with metadata"[:20]

    async def test_pruning_removes_only_the_tail(self, db: Database) -> None:
        ns = Namespace(TENANT_A, MODEL)

        async with db.tenant_session(TENANT_A) as session:
            store = PostgresVectorStore(session)
            await store.upsert(
                ns,
                [embedded(TENANT_A, "p1", i, f"chunk {i}", [1.0, 0.0, 0.0]) for i in range(4)],
            )

            removed = await store.prune(ns, EntityType.PRODUCT, "p1", keep_upto=2)

            assert removed == 2
            assert await store.count(ns) == 2


class TestNamespacesInOneColumn:
    async def test_two_vector_sizes_coexist(self, db: Database) -> None:
        """What makes the reindex procedure possible: 768-dim and 1536-dim rows
        live side by side while a new embedder is evaluated
        (llm-abstraction.md §5.2)."""
        small = Namespace(TENANT_A, "small-model")
        large = Namespace(TENANT_A, "large-model")

        async with db.tenant_session(TENANT_A) as session:
            store = PostgresVectorStore(session)
            await store.upsert(small, [embedded(TENANT_A, "p1", 0, "text", [1.0, 0.0, 0.0])])
            await store.upsert(
                large, [embedded(TENANT_A, "p1", 0, "text", [1.0, 0.0, 0.0, 0.0, 0.0])]
            )

            assert await store.count(small) == 1
            assert await store.count(large) == 1
            assert await store.models_for(TENANT_A) == {"small-model": 1, "large-model": 1}

            # And each namespace is queried in its own dimensionality.
            assert len(await store.search(small, [1.0, 0.0, 0.0])) == 1
            assert len(await store.search(large, [1.0, 0.0, 0.0, 0.0, 0.0])) == 1

    async def test_one_namespace_refuses_two_vector_sizes(self, db: Database) -> None:
        """Caught before the write. A mixed namespace produces no error at query
        time — only answers that quietly got worse."""
        ns = Namespace(TENANT_A, "shifty-model")

        async with db.tenant_session(TENANT_A) as session:
            store = PostgresVectorStore(session)
            await store.upsert(ns, [embedded(TENANT_A, "p1", 0, "text", [1.0, 0.0, 0.0])])

            with pytest.raises(DimensionMismatchError):
                await store.upsert(ns, [embedded(TENANT_A, "p2", 0, "other", [1.0, 0.0, 0.0, 0.0])])
