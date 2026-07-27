# Project State

> **This is a living document. Update it at the end of every working session.**
> It records where the project *is*. Every other document records where it is *going*.
> If the two disagree, this file is right about the present and the others are right about the intent.

**Last updated:** 2026-07-27
**Current phase:** Phase 1 — milestones 1.1–1.9 complete
**Next action:** Milestone 1.10 — the agent runtime. LangGraph explicit state machine with a
PostgreSQL checkpointer, the tool registry, and the policy engine.

> **Starting 1.10 cold?** Read [`../CLAUDE.md`](../CLAUDE.md) first, then this file, then
> [agent-runtime.md](architecture/agent-runtime.md) — the graph, the tool declaration, and the
> eight-check policy engine are all specified there. Rule 3 is the one that bites: authorisation
> is code, never a prompt.
>
> The `retrieve` node has something real to call now — `neura_agent_core.rag` is built and proved
> against the live catalogue (`make rag-check`). The database is no longer idle: Alembic is
> configured, one migration is applied, and **the app now connects as `neura_app`, not `neura`**
> (see the 1.9 log entry — connecting as the owner silently disabled RLS).

> New here? Read [GETTING_STARTED.md](GETTING_STARTED.md) — set up and run everything in ~15 minutes.

---

## 1. What exists right now

| | Status |
|:--|:--|
| Documentation | ✅ Complete — 29 files, plus the published interface spec in `docs/spec/` |
| Git repository | ✅ Initialised, branch `main` |
| Workspace | ✅ uv workspace, Python 3.12.13, 8 packages |
| `neura-core` | ✅ config · logging+redaction · errors · context · telemetry · crypto · ids · db |
| `neura-domain` | ✅ canonical models · enums · events (pure, verified) |
| `neura-api` | ✅ boots; `/v1/health`, `/v1/health/ready`, `/v1/agents`; error contract |
| Agent discovery | ✅ entry points working — `care` manifest discovered at startup |
| Infrastructure | ✅ docker-compose: Postgres 16 + pgvector, Redis 7 — both healthy |
| Guardrails | ✅ ruff · mypy strict · 6 import-linter contracts · platform-independence check |
| Eval harness | ✅ datasets · judge · metrics · runner · reports · CLI (`make eval`) |
| Golden datasets | ⚠️ 19 cases across 3 datasets — **all synthetic**, so not validation |
| `neura-llm` | ✅ roles · 4 role maps · provider · structured output + repair · cost metering |
| LLM verified live | ✅ `make llm-check` green against real Ollama — chat, schema, embeddings, tool calling |
| `neura-commerce` | ✅ adapter Protocol · capability negotiation · cursor pagination · identity map · registry · conformance suite |
| `neura-adapters` | ✅ `GenericAdapter` (Tier 2) · signed webhooks · reference store · `neura-conformance` CLI |
| Published spec | ✅ [docs/spec/](spec/) — OpenAPI 3.1 **generated** from the canonical models; drift fails a test |
| Real platform conformed | ✅ **the abstraction is proven** — a real commerce platform passes conformance with 0 failures, 0 warnings, via a bridge in its own repo. Zero core changes here. |
| Signed webhooks | ✅ verified end to end over Redis: shop signs → client verifies; forged, unsigned and replayed requests all rejected |
| Sync engine | ✅ backfill (resumable) · incremental · webhook refresh · reconciliation · per-tenant rate limiting. Verified against the real shop (`make sync-check`) |
| Sync persistence | ⚠️ still in-memory — the seam (`EntityStore`, `SyncStateStore`) is defined and tested. **Not** done in 1.9: that milestone persisted *vectors*, not entities |
| Platform independence | ✅ proved: a fictional platform integrates with **zero** core changes |
| Migrations | ✅ Alembic configured; `document_chunks` applied, reversible, no model drift (`alembic check`) |
| Database seam | ✅ `neura_core.db` — pooled async engine, `tenant_session()` setting `app.tenant_id` per transaction |
| Multi-tenant isolation | ✅ **RLS live and verified** — forced on `document_chunks`; cross-tenant read returns nothing, cross-tenant write is rejected. A test fails if any `tenant_id` table lacks a forced policy |
| `neura-agent-core` | ⚠️ `rag` built; graph runtime, tools and policy engine are 1.10 |
| RAG | ✅ render · chunk (skipping records with nothing to index, and naming them) · embed · pgvector namespaced by `(tenant_id, embedding_model)` · retrieval · reindex path. Verified against the real shop (`make rag-check`) |
| Tests | ✅ 263 unit + 13 integration passing |
| CI | ✅ workflow written — **not yet run** (no remote) |
| Design partner | ❌ None — top project risk |

**The agent does not exist yet.** The foundation runs and can be measured; no conversation has ever been handled. Every eval case currently reports "no agent wired up", which is correct.

**Retrieval, however, does exist and has been measured** — see the 1.9 log entry. It answers real questions about a real catalogue, which is the first time any part of this system has produced an answer rather than a passing test.

---

## 2. Phase 1 progress

17 milestones — see [roadmap.md](roadmap.md) for detail.

```
1.1  Workspace bootstrap        ✅ done
1.2  neura-domain + neura-core  ✅ done
1.3  neura-llm                  ✅ done  (verified live against Ollama)
1.4  Eval harness               ✅ done  (deliberately before the agent)
1.5  neura-commerce             ✅ done
1.6  Generic Commerce Interface ✅ done
1.7  Bagisto bridge             ✅ done
1.8  Sync engine                ✅ done
1.9  RAG                        ✅ done  (verified against the real catalogue)
1.10 Agent runtime              ⬜   ← NEXT
1.11 CARE agent                 ⬜
1.12 Guard (injection + PII)    ⬜
1.13 Multi-tenancy              ⬜
1.14 API                        ⬜
1.15 Shadow mode                ⬜
1.16 Widget                     ⬜
1.17 Deploy                     ⬜
```

**Exit criteria (three met):** `neura-conformance` passes against the bridge ✅ · zero platform names outside `packages/neura-adapters/` ✅ · cross-tenant isolation passes ✅ (proved against real PostgreSQL for the one table that exists; each new table is covered by the same test). Remaining: evals green on both role maps · injection resistance 1.00 · end-to-end conversation working · shadow mode producing graded conversations.

---

## 3. Decided — do not relitigate without an ADR

| Decision | Where |
|:--|:--|
| Python 3.12, uv workspace monorepo | [ADR-0001](architecture/adr/0001-python-monorepo-uv.md) |
| Modular monolith, one deployable | [ADR-0002](architecture/adr/0002-modular-monolith.md) |
| Canonical domain model + adapter protocol | [ADR-0003](architecture/adr/0003-canonical-domain-model.md) |
| Explicit LangGraph state machine | [ADR-0004](architecture/adr/0004-langgraph-explicit-graph.md) |
| pgvector, not Qdrant | [ADR-0005](architecture/adr/0005-pgvector-not-qdrant.md) |
| LLM abstraction by model role | [ADR-0006](architecture/adr/0006-llm-model-roles.md) |
| Langfuse + OTel, not LangSmith | [ADR-0007](architecture/adr/0007-langfuse-observability.md) |
| Multi-tenancy via RLS from day 1 | [ADR-0008](architecture/adr/0008-multi-tenancy-rls.md) |
| Generic Commerce Interface first | [ADR-0009](architecture/adr/0009-generic-commerce-interface.md) |
| READ-only tools in MVP | [ADR-0010](architecture/adr/0010-read-only-mvp-tools.md) |

Product-level decisions: NEURA-CARE is the first agent, scoped to **three intents** · Bagisto is a **test harness**, not a target platform · Ollama is dev **and** the sovereign product tier, not a placeholder.

---

## 4. Not decided — see [open-questions.md](open-questions.md)

Highest impact: the ICP is **proposed, not confirmed** · no design partner exists · geography/market undecided · cloud LLM provider deliberately deferred to swap time · agents 2–5 are **undesigned**.

---

## 5. Known deviations from the archived plan

`docs/archive/implementation_plan_1.md` is superseded in these specific ways. A fresh session reading the archive without this list will be misled:

| Archive says | Now |
|:--|:--|
| Separate `api-gateway` + `agent-care` services | One deployable ([ADR-0002](architecture/adr/0002-modular-monolith.md)) |
| Qdrant | pgvector ([ADR-0005](architecture/adr/0005-pgvector-not-qdrant.md)) |
| OpenAI + Anthropic | Role-based abstraction; Ollama dev, cloud prod ([ADR-0006](architecture/adr/0006-llm-model-roles.md)) |
| LangSmith | Langfuse ([ADR-0007](architecture/adr/0007-langfuse-observability.md)) |
| Shopify/Woo/Magento adapters first | Generic Commerce Interface first ([ADR-0009](architecture/adr/0009-generic-commerce-interface.md)) |
| Railway deployment | Undecided; Railway has no GPU path |
| No security model, no eval strategy, no Alembic | All added |
| Timeline in weeks | Restated ~3× longer, honestly |

---

## 6. Environment facts

Verified 2026-07-25 on this machine:

| | |
|:--|:--|
| Ollama | 0.31.1, running. Models: `llama3.2:3b`, `llama3.1:8b`, `qwen3.5:9b`, `nomic-embed-text`, `qwen2.5-coder:7b/32b`, `deepseek-r1:14b` |
| Python | 3.14.6 installed — **we pin 3.12 via uv**, do not use the system interpreter |
| uv | Installed at `~/.local/bin` — not always on a non-interactive PATH |
| Docker | `neura-postgres` (pgvector) on **5433** and `neura-redis` on **6379**, both running |
| Postgres roles | App connects as **`neura_app`** (no superuser, no BYPASSRLS — RLS applies). Migrations connect as the owner `neura` via `DATABASE_MIGRATION_URL`. Getting this wrong disables tenant isolation silently |
| Schema | One migration applied: `document_chunks`, with forced RLS. `make migrate` · `make revision M="…"` |
| Node | v24.15.0 |
| Test shop | `/Users/malithjayasinghe/Developer/bagisto` — 2.4.x-dev, Laravel 12, MySQL on **3307**, `QUEUE_CONNECTION=redis` (moved in 1.7), served at `http://bagisto.test` |

### The live test shop

A real platform conformed to the spec in milestone 1.7. It is reachable **now**, with real data:

```bash
make conformance URL=http://bagisto.test/neura/v1 TOKEN=<NEURA_API_TOKEN from the shop's .env>
make sync-check  URL=http://bagisto.test/neura/v1 TOKEN=<same>
make sync-watch  URL=... TOKEN=...   # remembers between runs; edit the shop and re-run
```

The token lives in the shop's `.env` as `NEURA_API_TOKEN` (gitignored, local dev only). Contents: **29 products with real written descriptions**, 6 categories, 8 customers, 26 orders across every status with tracking numbers, and 11 policy pages with real text.

**Use it.** Anything that touches commerce data can be tested against a real shop rather than a fixture, and every bug worth finding so far has been found that way.

The bridge itself lives in the shop's repository at `packages/Webkul/NeuraBridge/` — not here, deliberately. Webhooks need `php artisan queue:work redis` running in that directory.

---

## 7. Session log

Newest first. One short entry per session — what changed, what was decided, what is next.

### 2026-07-27 — RAG, and the database's first real use (milestone 1.9)

- **`neura_agent_core.rag` built**: render → chunk → embed → pgvector, retrieval, and the reindex path from [llm-abstraction §5.2](architecture/llm-abstraction.md). The `VectorStore` interface ADR-0005 promised now exists, with a PostgreSQL implementation and an in-memory one.
- **Alembic is configured** and the first migration is applied — `document_chunks`, reversible, with `alembic check` reporting no drift between the SQLAlchemy tables and the migration. `neura_core.db` is the new seam: a pooled async engine and `tenant_session()`, which is the *only* way to get a session and sets `app.tenant_id` per transaction.
- **Verified against the real shop** (`make rag-check URL=… TOKEN=…`): 48 entities → 48 chunks, embedded by real `nomic-embed-text`, written to real pgvector. A second identical run embedded **nothing** (48 unchanged), proving the content hash. Retrieval answered real questions — "what is your returns policy?" → Refund Policy @ 0.746; "how much does delivery cost?" → Shipping Policy @ 0.680; "I need something waterproof for hiking" → the Waterproof Hiking Shoe @ 0.750.

**A real bug, and the most expensive one found so far:**

- **The shipped `DATABASE_URL` pointed at the database *owner*, so Row-Level Security did not apply at all.** PostgreSQL exempts superusers and `BYPASSRLS` roles from every policy — so the first cross-tenant test wrote one tenant's row from another tenant's session and *succeeded*. `init-db.sql` had created the unprivileged `neura_app` role back in 1.1 and documented exactly why; nothing ever connected as it. Every "isolation works" test would have passed while isolating nothing.
  - Fixed: `DATABASE_URL` is now `neura_app`; a second `DATABASE_MIGRATION_URL` holds the owner, because `CREATE TABLE` and `CREATE POLICY` are precisely the privileges the serving process must not have.
  - `Database.ping()` now **refuses** a connection whose role is superuser or `BYPASSRLS`, so `/v1/health/ready` fails rather than a deployment quietly serving traffic with isolation off. The integration fixture treats that as a failure and never a skip.
  - **The general lesson: an RLS policy that exists is not an RLS policy that applies.** Any future table inherits this; a test now fails if any table carrying a `tenant_id` lacks RLS *enabled, forced and policied*.
- **Decided: `FORCE ROW LEVEL SECURITY`, not merely `ENABLE`.** Without `FORCE` the table owner is exempt — so isolation would be off in development, where it is written and tested, and on only in production, where discovering a bug in it is expensive.

**Decisions worth not relitigating:**

- **The namespace is an argument, not a filter.** Every `VectorStore` method takes `Namespace(tenant_id, embedding_model)`; there is no method that does not. A filter callers must remember to add is a hope, not a rule.
- **An empty retrieval is diagnosed, never returned bare.** If the namespace is empty but the tenant has vectors under another model, the result says so and names the model. This is the AGENTS.md gotcha — "retrieval returns nothing → namespace mismatch" — turned from a week of "the agent got worse" into one line of output. Proved in the smoke run by deliberately querying a namespace nothing was written to.
- **The rendered text is the contract**, and it is content-hashed. Editing a renderer therefore re-embeds on the next run rather than leaving half an index produced by the old version — the failure that has no symptom.
- **Chunks are pruned when an entity shrinks.** A description cut in half leaves an orphaned tail that keeps being retrieved: text the merchant deleted, quoted back at their customers.
- **Orders and customers are refused by the indexer, not merely omitted.** A comment saying "don't pass orders here" is not a control.
- **The `vector` column is deliberately dimensionless**, which forgoes HNSW/IVFFlat indexes. That is the price of letting 768- and 1536-dimensional vectors coexist during a reindex, which §5.2 requires. Fine at ADR-0005's stated scale; the fix when a tenant outgrows it is a per-namespace partial index, not a change to the interface.
- **`retire_namespace` refuses to drop the live one.** Dropping the serving namespace is a one-command outage whose only symptom is an agent that has forgotten the catalogue.

**A bug found by inspecting the stored rows by hand, which no test would have caught:**

- **Two products in the shop have no title**, and the indexer embedded them anyway. `product_flat.name` is `NULL` for ids 1 and 1300 — abandoned demo records. They rendered to a structurally valid, semantically empty document (`Product:` / `Availability: out of stock` / `Status: active`), whose vector carries no meaning, sits near the origin, and can therefore surface for queries it has nothing to do with. Had the agent retrieved one, it would have recommended a nameless product to a shopper.
  - Fixed: `missing_content()` refuses to index a product with no title, a category with no name, or a policy with an empty body — and the outcome **names the records** (`product:1 (no title)`) so the merchant can fix them. Counted as `blank`, separately from `skipped`, because it is their data problem rather than our policy.
  - **The nastier half:** an entity that *becomes* blank must also lose the chunks a previous run wrote for it, or the old version stays retrievable forever, described by text the shop no longer has. `index()` deletes them.
  - **Deliberately not clever:** placeholder *prose* is still indexed. No rule reliably separates "Return Policy Page Content" from terse real prose, and a heuristic that guessed would drop genuine content. Emptiness is unambiguous; vagueness is the merchant's call.
  - **The general lesson: look at the rows.** Every count was green — 48 entities, 48 chunks, 48 embedded, idempotent on re-run. Only reading the actual stored text showed two of them were empty. The same lesson as 1.7's placeholder policy text, found the same way.

**Decided: a product that is not on sale is not indexed — but an *unmappable* status still is.**

Prompted by the two title-less products above, which the shop's admin showed as disabled while the bridge published `active`. `DRAFT` and `ARCHIVED` are now withheld from the index: the merchant has explicitly taken that product off sale, and an agent that recommends it wastes a shopper's time and leaves the merchant explaining a product they unpublished. Unpublishing also *removes* any chunks a previous run wrote, or the withdrawn product stays retrievable forever.

`UNKNOWN` is deliberately **still indexed**. It means the shop sent a status word we could not map — not that the product is unavailable. Excluding it would empty the index for any shop whose vocabulary we have not seen, and the only symptom would be an agent answering "I don't know" to everything. That is far worse than occasionally describing a product that turns out to be unavailable. Same call, same reasoning, as the adapter layer's "tolerate, then report" in 1.6. Every withheld product is counted and named, because "why can't the agent find my product?" is a support question that needs an answer.

**Open, not decided: whether a platform may be trusted about status at all.** On the test shop, a product with *no attribute data whatsoever* is reported `active`, because the platform's model falls back to a default of `1` when nothing is stored. The admin, reading its denormalised table, shows the same product as disabled. Two views of one shop disagreeing, and the bridge happens to ask the one that guesses. Nothing is broken today — the affected records had no title and were skipped for that reason first — but the general question ("is this platform's status claim load-bearing?") belongs with the same family as the `updated_at` lesson from 1.8, and should be verified against a real edit for every new adapter.

**Two honest findings from the real run, both for milestone 1.10/1.11:**

- **A pronoun cannot be embedded into a match.** "what colours does it come in?" retrieved the Payment Policy at 0.502 — "it" has no referent without the previous turn. Retrieval cannot fix this; the agent must rewrite the query from conversation history before calling it. The probe is kept in the smoke test *as a failing case* rather than deleted.
- **Similarity does not cleanly separate relevant from irrelevant on this embedder.** A correct match (payment question → Payment Policy) scored 0.583 and a meaningless one scored 0.502. So `DEFAULT_MIN_SCORE = 0.3` is left as an informed starting point and **not** tuned against seven probes; the `verify` node, not a threshold, is the real defence against ungrounded answers. Recalibrate on a labelled set.
- **`/v1/health/ready` now really checks Postgres**, having reported `not_implemented` since 1.1. A privileged database role is reported as `down` with the reason rather than raised — a 503 an orchestrator can act on beats a 500 nobody can. Serving traffic with tenant isolation silently off is worse than not serving at all.
- **Two smaller things the API tests were hiding.** The test client was built without its context manager, so the app's lifespan never ran — startup validation and agent discovery were untested, and the connection pool the readiness probe opens was never closed, which surfaced as an intermittent `make check` failure and a stray "coroutine was never awaited". The fixture now runs the lifespan, and the lifespan disposes the pool.
- **Not done, deliberately:** entity persistence. 1.9 persisted *vectors*; `EntityStore`/`SyncStateStore` are still in-memory, so `make rag-check` syncs and indexes in one process. Whichever milestone needs a sync that survives a restart replaces those two classes and nothing else.
- 263 unit + 13 integration tests pass; mypy strict on 68 files; 6 contracts kept; platform check green; `make check` exits 0 five runs in a row.
- **Next:** milestone 1.10 — the agent runtime. The `retrieve` node now has something real to call.

### 2026-07-26 — Sync engine (milestone 1.8)

- **`neura_commerce.sync` built**: resumable backfill, incremental polling, webhook-driven refresh of one entity, and a reconciliation pass — plus a per-tenant token bucket that honours `Retry-After`.
- **Verified against the real shop**, not only against fakes (`make sync-check URL=… TOKEN=…`): 31 products, 6 categories and 11 policies backfilled in 4 pages; a second identical crawl wrote **nothing** (31 unchanged), proving the upsert key; a deliberately corrupted local copy was detected and repaired by reconcile; a second reconcile found nothing left to fix.
- **Decided: orders and customers are not synced.** Only catalogue, categories and policy text are kept locally. An order's status changes fast, and "out for delivery" being an hour stale is a worse failure than a 400ms lookup — so those are read live through the adapter ([commerce-integration §6.1](architecture/commerce-integration.md)). `SYNCED_TYPES` encodes it and a test asserts orders are absent from a routine run.
- **Decided: content fingerprints, not timestamps, decide what changed.** `updated_at` is a claim a platform makes and not every platform updates it on every edit. A hash over the canonical fields — excluding `synced_at` and `raw` — means a reconcile reports real drift only, and a shop upgrading its software does not trigger a full re-embed.
- **Every degradation is reported, never silent.** A shop without `INCREMENTAL_SYNC` gets a full backfill *and a note saying so*; a shop lacking a capability syncs nothing *and says which*; a crawl that will not terminate stops at `MAX_PAGES` and reports it. Syncing nothing quietly looks identical to a shop where nothing changed.
- **A test exposed a real property of incremental sync**: the fake shop edited a product without bumping `updated_at`, and incremental correctly did not see it. That is not a bug to fix but the reason reconciliation exists — recorded in the fixture's comment and covered by its own test.
- **A bug only a real platform could show, found by running the demo by hand.** The bridge published `products.updated_at` as "when this product changed" — but on this platform a product's name, description and price live in attribute tables, so renaming a product leaves that column untouched. Incremental sync therefore missed ordinary edits and only the nightly reconcile caught them, turning a minutes-fresh answer into a day-stale one. The bridge now reports and filters on the later of the product row and its denormalised row. Confirmed: the same edit that produced `~0` now produces `~1`, with reconcile finding nothing left to repair. **The general lesson for any future adapter: a platform's `updated_at` is a claim, and it must be verified against a real edit before `sync.incremental` is declared.**
- **Persistence is deliberately deferred.** `EntityStore` and `SyncStateStore` are Protocols with in-memory implementations, as `EntityMap` was in 1.5. The engine is fully exercised; PostgreSQL replaces two classes and nothing else.
- 218 tests pass; mypy strict on 59 files; 6 contracts kept; platform check green.
- **Next:** milestone 1.9 — RAG. There is now a real, synced catalogue with genuine product descriptions to embed, and `(tenant, embedding_model)` namespacing is the trap to get right.

### 2026-07-26 — The bridge, and the abstraction proven (milestone 1.7)

- **A real commerce platform now conforms to the published spec** — `neura-conformance` reports 20 passed, 0 failed, 0 warnings against `http://bagisto.test/neura/v1`. Everything Phase 1 has claimed so far rested on this being possible; it is no longer a claim.
- **Zero changes to any package here.** The bridge is ~700 lines of PHP living in the shop's own repository (`packages/Webkul/NeuraBridge/`), modifying no core file of the shop either. The generic client read the real catalogue, real orders, real customers and real policy text without knowing what platform it was talking to.
- **Webhooks verified end to end**, over a real Redis queue with a worker: the shop signs, our client verifies. A forged signature, a missing signature and a correctly-signed two-hour-old replay were all rejected. Dispatch cost the shopper's request 41ms — the queue exists precisely so it is not the HTTP call.
- **The shop's `QUEUE_CONNECTION` moved `sync` → `redis`.** On `sync`, a webhook would have been sent inside the shopper's checkout request, so a slow response from us would stall a purchase. Deliberately done at the *end* of this milestone, once a worker existed to drain the queue.

**Three findings, each a decision that will recur on every platform:**

- **A canonical status a real platform cannot produce.** The shop records dispatch and never hears back from the carrier, so nothing it sends can honestly mean `delivered`. Its bridge maps a completed order to `shipped` and stops. This is the canonical model being *right* — it has a state this platform lacks — and the bridge admitting a gap rather than the vocabulary bending to fit. `docs/spec/…-v1.md §9` records it for the next implementer.
- **The PHP empty-map trap.** `json_encode([])` emits a JSON array whether a list or a map was meant, so `options: {}` arrives as `options: []`. Most commerce platforms are PHP, so refusing it would fail a majority of correct implementations over a field nobody set. The client now accepts an empty list where a map belongs — an empty one only; a non-empty list is still a mapping error. Spec §4 warns implementers.
- **Placeholder policy text is worse than none.** The platform ships CMS pages reading literally "Return Policy Page Content". The bridge served them correctly and the agent would have quoted them at customers. Real returns, refund, shipping, payment and customer-service text now seeded — a bug in the *data* that no amount of correct code would have caught.

- Two bugs the real platform found immediately: `$page->locale` throws on this platform's translatable models (its `locale` is a relationship), and an order line's `product_type` holds a model class, not the product's type string — the latter 500'd the shop's own admin until fixed.
- **Decided: the bridge is not an authorisation boundary.** Filtering orders by email returns that email's orders to any caller holding the shop token. Proving the person in the chat window *is* that customer stays in the policy engine, where it is written once and can be audited, rather than separately in every shop's bridge.
- 193 tests pass; mypy strict on 54 files; 6 contracts kept; platform check green.
- **Next:** milestone 1.8 — the sync engine. There is now a real store to sync *from*, so backfill, incremental polling, webhook-driven refresh and nightly reconciliation can all be tested against data that was not written to make them pass.

### 2026-07-26 — Generic Commerce Interface (milestone 1.6)

- **The spec is published and machine-readable**: [docs/spec/generic-commerce-interface-v1.md](spec/generic-commerce-interface-v1.md) plus an OpenAPI 3.1 document **generated from the canonical Pydantic models** (`make spec`). A unit test fails if the committed document and the models disagree — a published contract that drifts is worse than none, because a merchant's developer implements the stale version and finds out in production.
- **`GenericAdapter` built** in `neura-adapters`: the nine read endpoints, opaque cursors, `updated_since`, error translation, and identity-map-backed stable ids.
- **`neura-conformance` CLI ships**: the shared adapter suite plus HTTP-level checks the adapter abstraction necessarily hides — anonymous access, wrong-token access, 404 semantics, `spec_version`, `limit`, and raw status vocabulary.
- **The check that matters most is a security one.** `auth.required` asks a store what it serves to a caller with no token; a `200` there means its customer list is public. No agent behaviour is involved, and nothing else in the suite could see it.
- **Decided: the spec is the canonical model minus provenance.** A store cannot know its `tenant_id` or our `neura_id`, and must not be trusted to assert `platform` — those five fields are stripped from anything received and filled in by us. A test proves a store claiming another tenant's id cannot make it stick.
- **Decided: tolerate, then report.** Unknown fields are dropped (kept in `raw`), unknown capabilities ignored, unknown statuses degraded to `UNKNOWN` — but each is a conformance warning. A contract that breaks when the other side adds a field cannot be evolved; one that silently absorbs bad data produces "unknown" answers to customers. So the runtime is lenient and the tool is loud. `additionalProperties: false` is stripped from the published schemas to match.
- **A design defect in 1.5 surfaced, as ADR-0009 predicted it would.** `CommerceAdapter.capabilities` was a `ClassVar`; one `GenericAdapter` class serves many stores that implement different subsets, so capabilities are per *store* and are read from `/health`. The protocol now declares an instance attribute — a class attribute still satisfies it, so native adapters are unaffected.
- **A real bug the fixtures caught:** an entity payload with no `external_id` made the identity map raise a bare `ValueError` out of the adapter. Now an `AdapterMappingError`. Nothing but an `AdapterError` may escape an adapter, or every caller above has to know which exceptions each integration can throw.
- Two more from writing the checks: `--self-test` runs the tool against a correct store **and** a deliberately broken one, and the status-vocabulary checks stay silent rather than green when the endpoint 500s — a check that passes because the endpoint is broken reads as reassurance.
- **Import contracts strengthened:** adapters now sit in their own layer above `neura_commerce`, and a new contract forbids every other package from importing `neura_adapters` at all. Six contracts, all kept.
- 191 tests pass; mypy strict on 54 files; platform check green.
- **Next:** milestone 1.7 — the bridge that makes the test store conform to this spec. That is the first time the spec meets a real platform, and the first honest test of whether the canonical model is right.

### 2026-07-26 — Commerce adapter layer (milestone 1.5)
- **`neura-commerce` built**: `CommerceAdapter` Protocol, capability negotiation, cursor pagination, identity map, adapter registry, and a shared conformance suite.
- **The product claim is now a passing test.** A fictional platform ("acme") satisfies the protocol structurally, passes conformance unmodified, and is reachable through the registry — with **zero** changes to any core package. `neura_commerce` contains no import of `neura_adapters`; verified.
- **Decided:** `Protocol`, not a base class. Structural matching means a third party can conform to the published spec without importing our package — which matters, since needing it would undercut the point of publishing a spec.
- **Decided:** the adapter is explicitly **not** an authorisation boundary. `get_order()` returns data regardless of who asks; ownership verification lives in the policy engine. Putting it in adapters would scatter a security control across every integration.
- Seven tests confirm the conformance suite **rejects** broken adapters (raising instead of returning `None`, erroring on empty search, declaring no capabilities, claiming `INCREMENTAL_SYNC` without honouring it, a cursor that never advances). A suite that passes everything is worse than none.
- Removed `Page.__iter__` — it shadowed Pydantic's own and would have broken `dict(page)` in ways surfacing far from the cause.
- 137 tests pass; mypy strict on 45 files; 5 contracts kept.
- **Next:** milestone 1.6 — the Generic Commerce Interface spec, `GenericAdapter`, and the `neura-conformance` CLI a merchant's developer runs against their own store.

### 2026-07-26 — LLM layer (milestone 1.3) + setup guide
- **`neura-llm` built**: `ModelRole` (router/reasoner/guard/embedder/summarizer), four role maps (`ollama-dev`, `cloud-prod`, `hybrid`, `sovereign`), one OpenAI-compatible provider covering local and cloud alike, capability-tiered structured output with a bounded repair loop, per-call usage and cost metering.
- **Verified live against real Ollama** (`make llm-check`): chat ✔ · structured output ✔ (first attempt) · embeddings ✔ 768-dim, similarity 0.651 · tool calling ✔ (`qwen3.5:9b` correctly called `get_order_status(order_ref="1001")`).
- **Confirmed:** Ollama's constrained decoding puts local models on the *strongest* structured-output tier. That is what makes the zero-budget development path genuinely viable rather than a compromise.
- Observation worth keeping: `llama3.2:3b` extracted the order reference as `"Order 1001"` rather than `"1001"`. Harmless here, but exactly the sort of small-model sloppiness the eval suite exists to quantify.
- Embedding dimension mismatch now **raises** rather than degrading silently — the trap that otherwise produces no error, only worse answers.
- **Wrote [GETTING_STARTED.md](GETTING_STARTED.md)** — full setup and verification walkthrough, plus exactly what shop data will be needed at milestone 1.7.
- 92 tests pass; lint, mypy strict (36 files), 5 contracts, platform check all green.
- **Next:** milestone 1.5 (`neura-commerce` adapter contract), then 1.6 (Generic Commerce Interface + conformance CLI).

### 2026-07-26 — Eval harness (milestone 1.4, built before the agent)
- **`evals/` package**: YAML dataset schema, judge, metrics, runner, reports, `neura-eval` CLI. `make eval`, `make eval-fast`, `make eval-one D=<name>`.
- **19 synthetic cases** across `order_status`, `injection`, `out_of_scope`. All marked `synthetic: true` — the harness refuses to call a fully-synthetic run "validation".
- **Judge**: any OpenAI-compatible endpoint. Decided to use **Gemini's free tier** — it needs no special code, since that interface is what the whole system already speaks.
- **Trust is reported, never assumed.** Every run states its judge and a trust level; untrusted or judge-free runs print a warning banner. Reason: an untrusted score looks identical to a real one, and that resemblance is how a project ends up quoting its own guesses.
- **`EvalTarget` protocol** is the seam — the agent plugs in at 1.11 with no change to the harness. Until then a `NotImplementedTarget` returns an explicit error rather than a plausible empty response.
- Two schema rules enforced in code: an adversarial case **must** assert `unauthorised_tool_calls` (a reply can sound like a refusal while a tool was invoked, so text matching is not a safety test), and duplicate case ids are rejected.
- **The platform-independence checker caught my own YAML** naming a platform in a dataset description. Reworded — eval datasets must be platform-neutral, or they quietly undo the abstraction.
- **Documented, important:** free judge tiers may train on submitted content. Fine now (invented data); **must move to a paid tier before real customer conversations enter the datasets**. Tracked as open question E2.
- 63 tests pass; lint, mypy strict, 5 layering contracts, platform check all green.
- **Next:** milestone 1.3 (`neura-llm`) — and it now lands with measurement already in place.

### 2026-07-26 — Foundation built (milestones 1.1 + 1.2)
- Installed `uv` 0.11.32, pinned Python 3.12.13, `git init` on `main`, started Docker.
- uv workspace with 8 packages: 6 libraries, 1 agent (`agents/care`), 1 deployable.
- **`neura-core`** built: settings (fail-fast, rejects placeholder secrets outside dev), structured logging with a redaction processor, one error hierarchy, request context, OTel, envelope encryption, prefixed ULIDs.
- **`neura-domain`** built: `Product`/`Order`/`Customer`/`Policy` etc., canonical enums, event schemas. Verified pure.
- **`neura-api`** boots. `/v1/health`, `/v1/health/ready`, `/v1/agents`, single error shape, `X-Request-Id` on every response. Verified over real HTTP, not only TestClient.
- **Agent discovery works** — `agents/care` registers via entry points and is found at startup with no central registry file.
- Infra: Postgres 16 + pgvector and Redis 7 both healthy; `neura_app` confirmed **not** a superuser (RLS would silently not apply otherwise).
- Guardrails live: ruff, mypy strict (28 files clean), 5 import-linter contracts, platform-independence checker. 42 tests pass.
- **Decisions:** dev Postgres moved to **port 5433** (5432 was occupied on this machine; a dev stack should not fight the host). `PermissionError_` renamed `ForbiddenError`. The platform checker scans **code only**, skipping comments and docstrings — prose cannot contain coupling, and the exemption is itself covered by tests so it is not a loophole.
- **Next:** milestone 1.3 (`neura-llm`) or 1.4 (eval harness). Doing 1.4 first would mean the LLM layer lands with measurement already in place.

### 2026-07-25 — Tenancy & packaging (same session, follow-up)
- **Gap found:** the package map had **no home for agent code**, and nothing explained how a customer buys one agent from a single deployment. Both would have been invented — differently each time — by a future session.
- Added [tenancy-and-packaging.md](architecture/tenancy-and-packaging.md): `agents/` as a top-level category, per-agent manifests, entry-point discovery, the `enabled_agents` entitlement layer, and three delivery modes (shared cloud · dedicated · sovereign).
- **Decided:** agents live in `agents/<name>/` as separate workspace packages, not under `packages/`. Two new hard rules — agents never import each other, and `neura-agent-core` never learns an agent's name.
- Updated the package maps in `overview.md` and `AGENTS.md` to match; added terms to the glossary.

### 2026-07-25 — Documentation foundation
- Analysed the original blueprint and `implementation_plan_1`; archived both verbatim to `docs/archive/`.
- Wrote the full documentation set: business blueprint v2, 7 architecture docs, 10 ADRs, roadmap, glossary.
- **Decided:** Bagisto is a test harness only, not a target platform — the adapter layer became the centrepiece. Ollama for dev + sovereign tier, cloud for production. Modular monolith over the previously planned multi-service split. MVP scoped to NEURA-CARE, 3 intents, read-only.
- **Added** for future-session continuity: `CLAUDE.md`, this file, `open-questions.md`, `docs/agents/`.
- **Next:** user review of the docs, then milestone 1.1.
