#!/usr/bin/env python3
"""Run RAG end to end against a REAL shop, REAL embeddings and a REAL database.

    make rag-check URL=http://your-shop/neura/v1 TOKEN=xxx

Every unit test in ``tests/unit/test_rag.py`` uses a fake embedder whose vectors
are a hash of the words in the text. That is enough to prove the plumbing, and
not remotely enough to prove **retrieval works** — a real embedder is the only
thing that can tell whether "do you ship to Canada?" finds the shipping policy
rather than a product called Canada Goose.

So this reads a real catalogue, embeds it with a real model, stores it in a real
PostgreSQL, and asks real questions. Nothing is written to the shop; every
operation against it is a read.

The retrieval scores it prints are measurements — of one shop, one embedding
model, on one machine. They are not a benchmark and must not be quoted as one
(CLAUDE.md §4).
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from neura_adapters.generic import GenericAdapter
from neura_agent_core.rag import (
    Indexer,
    Namespace,
    PostgresVectorStore,
    Retriever,
)
from neura_commerce import EntityType
from neura_commerce.sync import InMemoryEntityStore, InMemorySyncStateStore, RateLimiter, SyncEngine
from neura_core import Database, configure_logging, load_env
from neura_domain import CanonicalEntity
from neura_llm import LLMClient

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
OFF = "\033[0m"

#: Questions a shopper would actually type, paired with the source type that
#: should answer them. Deliberately not phrased in the catalogue's own words —
#: matching a product title against itself proves nothing about retrieval.
#:
#: The last two are expected to fail, and are kept for that reason. A probe set
#: that scores 7/7 tells you nothing about where the limit is; these two say
#: exactly where it is. See the note printed under the results.
PROBES: list[tuple[str, EntityType]] = [
    ("what is your returns policy?", EntityType.POLICY),
    ("how long do I have to send something back?", EntityType.POLICY),
    ("how much does delivery cost?", EntityType.POLICY),
    ("do you take credit cards?", EntityType.POLICY),
    ("I need something waterproof for hiking", EntityType.PRODUCT),
    # A browse intent. Retrieval answers it with a *category*, which is arguably
    # right — the probe is strict on purpose, to keep the distinction visible.
    ("show me something I could wear to the office", EntityType.PRODUCT),
    # "it" has no referent without the previous turn. Nothing embedded can match
    # a pronoun, so this needs query rewriting from conversation history before
    # retrieval — an agent-runtime concern, not a retrieval one.
    ("what colours does it come in?", EntityType.PRODUCT),
]


def _role_map_name() -> str:
    """Which role map these hand-runs use — the configured one, by default.

    **Was hardcoded to `ollama-dev`, and that is a usability bug rather than a
    safety one.** Found 2026-08-28: the operator set `NEURA_ROLE_MAP=cloud-prod`
    in `.env` precisely so their laptop would stop running inference, and these
    scripts kept every model local anyway — silently, because nothing printed
    which map was in force.

    Deliberately *unlike* `neura-eval`, which pins `ollama-dev` on purpose so a
    suite can never cost money by accident. This is a single interactive
    question typed by a person who chose the setting, the models in use are
    printed on every run, and honouring `.env` is the least surprising thing it
    can do. `NEURA_ROLE_MAP=ollama-dev make ...` overrides it either way.
    """
    from neura_core import get_settings

    return get_settings().role_map


def tick(ok: bool) -> str:
    return f"{GREEN}✔{OFF}" if ok else f"{RED}✘{OFF}"


async def collect(engine: SyncEngine, entities: InMemoryEntityStore, tenant: str, platform: str):
    """Sync the shop, then hand back everything worth indexing."""
    print("  SYNC — reading the shop")
    for outcome in await engine.sync_all(incremental=False):
        print(f"    {tick(outcome.error is None)} {outcome.summary()}")
        for note in outcome.notes:
            print(f"        note: {note}")

    collected: list[CanonicalEntity] = []
    for entity_type in (EntityType.PRODUCT, EntityType.CATEGORY, EntityType.POLICY):
        for external_id in sorted(await entities.external_ids(tenant, platform, entity_type)):
            from neura_commerce import EntityKey

            entity = await entities.get(EntityKey(tenant, platform, entity_type, external_id))
            if entity is not None:
                collected.append(entity)
    return collected


async def run(url: str, token: str, tenant: str, keep: bool) -> int:
    llm = LLMClient.from_role_map_name(_role_map_name())
    database = Database.from_settings()
    adapter = GenericAdapter(base_url=url, tenant_id=tenant, token=token)
    entities = InMemoryEntityStore()

    print(f"\n  embedder  {llm.embedding_model}")
    print(f"  namespace {tenant}/{llm.embedding_model}\n")

    if not await database.ping():
        print(f"  {RED}no database — run `make up` and `make migrate`{OFF}\n")
        return 1

    engine = SyncEngine(
        adapter,
        tenant_id=tenant,
        entities=entities,
        state=InMemorySyncStateStore(),
        throttle=RateLimiter(rate_per_second=10, burst=10),
        page_size=10,
    )

    health = await adapter.health()
    print(f"  shop      {health.platform} · spec {health.spec_version}\n")
    if not health.usable:
        print(f"  {RED}shop is not usable — nothing to index{OFF}\n")
        return 1

    ok = True
    catalogue = await collect(engine, entities, tenant, adapter.platform)
    await adapter.aclose()

    # ── Index ────────────────────────────────────────────────────────────────
    # Start from an empty namespace. Left-over chunks from a previous run would
    # make this step report a cheerful ✔ having embedded nothing at all, which
    # is the sort of green that hides a broken embedder for a week.
    async with database.tenant_session(tenant) as session:
        stale = await PostgresVectorStore(session).drop_namespace(
            Namespace(tenant, llm.embedding_model)
        )
    if stale:
        print(f"  {DIM}cleared {stale} chunks from a previous run{OFF}")

    print(f"\n  INDEX — chunk, embed with {llm.embedding_model}, store in pgvector")
    async with database.tenant_session(tenant) as session:
        indexer = Indexer(PostgresVectorStore(session), llm, tenant_id=tenant)
        first = await indexer.index(catalogue)
    print(f"    {tick(first.completed)} {first.summary()}")
    for note in first.notes:
        print(f"        note: {note}")
    embedded_something = first.completed and first.chunks > 0 and first.embedded == first.chunks
    if not embedded_something:
        print("        expected every chunk to be embedded from an empty namespace")
    ok = ok and embedded_something

    # ── Idempotency ──────────────────────────────────────────────────────────
    print("\n  INDEX AGAIN — must embed nothing")
    async with database.tenant_session(tenant) as session:
        second = await Indexer(PostgresVectorStore(session), llm, tenant_id=tenant).index(catalogue)
    idempotent = second.embedded == 0 and second.written == 0
    print(f"    {tick(idempotent)} {second.summary()}")
    if not idempotent:
        print("        re-embedded an unchanged catalogue — the content hash is not stable")
    ok = ok and idempotent

    # ── Retrieval ────────────────────────────────────────────────────────────
    print("\n  RETRIEVE — real questions, real embeddings")
    hits = 0
    async with database.tenant_session(tenant) as session:
        retriever = Retriever(PostgresVectorStore(session), llm, tenant_id=tenant)
        for question, expected in PROBES:
            result = await retriever.search(question, limit=3)
            top = result.chunks[0] if result.chunks else None
            right_kind = top is not None and top.source_type is expected
            hits += int(right_kind)

            title = str(top.metadata.get("title", "?")) if top else "nothing retrieved"
            print(f"    {tick(right_kind)} {question}")
            print(
                f"        {DIM}→ {top.source_type.value if top else '—'} "
                f"{title[:48]!r} @ {result.top_score:.3f}{OFF}"
            )
            if result.diagnosis:
                print(f"        {RED}{result.diagnosis}{OFF}")

    print(f"\n    top-1 source type correct: {hits}/{len(PROBES)}")
    print(
        f"    {DIM}One shop, one embedding model, one machine. A measurement, not a benchmark.{OFF}"
    )
    print(
        f"    {DIM}The last two probes are expected to miss — see the comment on PROBES. "
        f"A pronoun with no referent cannot be embedded into a match.{OFF}"
    )

    # ── The trap ─────────────────────────────────────────────────────────────
    print("\n  NAMESPACE MISMATCH — querying a model nothing was indexed with")
    wrong = _with_embedding_model(llm, "a-different-embedder")
    async with database.tenant_session(tenant) as session:
        result = await Retriever(PostgresVectorStore(session), wrong, tenant_id=tenant).search(
            "returns policy"
        )
    diagnosed = not result and result.diagnosis is not None and "MISMATCH" in result.diagnosis
    print(f"    {tick(diagnosed)} empty result, and it says why:")
    print(f"        {DIM}{result.diagnosis}{OFF}")
    if not diagnosed:
        print("        an empty result with no explanation is the failure this guards against")
    ok = ok and diagnosed

    # ── Cleanup ──────────────────────────────────────────────────────────────
    if not keep:
        async with database.tenant_session(tenant) as session:
            store = PostgresVectorStore(session)
            removed = await store.drop_namespace(Namespace(tenant, llm.embedding_model))
        print(f"\n  cleaned up {removed} chunks (pass --keep to leave them for inspection)")
    else:
        print(f"\n  chunks left in place under tenant {tenant} — inspect with:")
        print(f"    {DIM}docker exec -it neura-postgres psql -U neura -d neura{OFF}")
        print(f"    {DIM}\\x on{OFF}")
        print(f"    {DIM}TABLE document_chunks LIMIT 3;{OFF}")

    await database.dispose()

    print()
    if ok:
        print(f"  {GREEN}RAG works against a real catalogue.{OFF}\n")
        return 0
    print(f"  {RED}Something failed above.{OFF}\n")
    return 1


def _with_embedding_model(llm: LLMClient, model: str) -> LLMClient:
    """A client claiming a different embedding model, to provoke the mismatch.

    Only its ``embedding_model`` matters here — the query is still embedded by
    the real model, which is precisely the production failure: the vectors are
    fine, the namespace they are looked up in is not.
    """

    class _Renamed(LLMClient):
        @property
        def embedding_model(self) -> str:
            return model

    shim = _Renamed.__new__(_Renamed)
    shim.__dict__.update(llm.__dict__)
    return shim


def main() -> None:
    # **Before anything reads a setting.** `roles.py` resolves cloud models
    # through raw `os.getenv`, so a `.env` that has not been loaded leaves the
    # whole cloud map "not configured" — which is what these three scripts did,
    # invisibly, for as long as they hardcoded `ollama-dev` and never needed it.
    load_env()
    parser = argparse.ArgumentParser(description="Run RAG against a real shop.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--tenant-id", default="tn_ragsmoke")
    parser.add_argument(
        "--keep", action="store_true", help="leave the chunks in the database afterwards"
    )
    args = parser.parse_args()

    configure_logging(level="ERROR", json_output=False)
    sys.exit(asyncio.run(run(args.url, args.token, args.tenant_id, args.keep)))


if __name__ == "__main__":
    main()
