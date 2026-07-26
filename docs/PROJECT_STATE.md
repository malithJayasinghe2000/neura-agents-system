# Project State

> **This is a living document. Update it at the end of every working session.**
> It records where the project *is*. Every other document records where it is *going*.
> If the two disagree, this file is right about the present and the others are right about the intent.

**Last updated:** 2026-07-26
**Current phase:** Phase 1 — milestones 1.1–1.8 complete
**Next action:** Milestone 1.9 — RAG. Chunk and embed the synced catalogue, store vectors in pgvector namespaced by `(tenant_id, embedding_model)`, and build retrieval + the reindex path.

> **Starting 1.9 cold?** Read [`../CLAUDE.md`](../CLAUDE.md) first, then this file, then
> [llm-abstraction.md §5](architecture/llm-abstraction.md) — the embedding-namespace trap is
> documented there and it is the one that degrades retrieval *silently*, with no error.
> There is a real synced catalogue to embed (see §6) and `neura-llm` already speaks to a live
> embedder (`make llm-check`). Postgres+pgvector is running on port 5433 and has been idle
> since 1.1; **Alembic is still not configured**, so the first migration is part of this work.

> New here? Read [GETTING_STARTED.md](GETTING_STARTED.md) — set up and run everything in ~15 minutes.

---

## 1. What exists right now

| | Status |
|:--|:--|
| Documentation | ✅ Complete — 29 files, plus the published interface spec in `docs/spec/` |
| Git repository | ✅ Initialised, branch `main` |
| Workspace | ✅ uv workspace, Python 3.12.13, 8 packages |
| `neura-core` | ✅ config · logging+redaction · errors · context · telemetry · crypto · ids |
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
| Sync persistence | ⚠️ in-memory — the seam (`EntityStore`, `SyncStateStore`) is defined and tested; PostgreSQL lands with the database work |
| Platform independence | ✅ proved: a fictional platform integrates with **zero** core changes |
| Tests | ✅ 218 unit tests passing |
| CI | ✅ workflow written — **not yet run** (no remote) |
| `neura-agent-core` | ❌ documented stub only |
| Migrations | ❌ Alembic declared, not configured |
| Design partner | ❌ None — top project risk |

**The agent does not exist yet.** The foundation runs and can be measured; no conversation has ever been handled. Every eval case currently reports "no agent wired up", which is correct.

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
1.9  RAG                        ⬜   ← NEXT
1.10 Agent runtime              ⬜
1.11 CARE agent                 ⬜
1.12 Guard (injection + PII)    ⬜
1.13 Multi-tenancy              ⬜
1.14 API                        ⬜
1.15 Shadow mode                ⬜
1.16 Widget                     ⬜
1.17 Deploy                     ⬜
```

**Exit criteria (two met):** `neura-conformance` passes against the bridge ✅ · zero platform names outside `packages/neura-adapters/` ✅. Remaining: conformance passes · zero platform names outside adapters · evals green on both role maps · injection resistance 1.00 · cross-tenant isolation passes · end-to-end conversation working · shadow mode producing graded conversations.

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
