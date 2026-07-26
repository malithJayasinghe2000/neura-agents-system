# Project State

> **This is a living document. Update it at the end of every working session.**
> It records where the project *is*. Every other document records where it is *going*.
> If the two disagree, this file is right about the present and the others are right about the intent.

**Last updated:** 2026-07-26
**Current phase:** Phase 1 — milestones 1.1, 1.2, 1.3, 1.4, 1.5 complete
**Next action:** Milestone 1.6 (Generic Commerce Interface spec + `GenericAdapter` + conformance CLI)

> New here? Read [GETTING_STARTED.md](GETTING_STARTED.md) — set up and run everything in ~15 minutes.

---

## 1. What exists right now

| | Status |
|:--|:--|
| Documentation | ✅ Complete — 29 files |
| Git repository | ✅ Initialised, branch `main` |
| Workspace | ✅ uv workspace, Python 3.12.13, 8 packages |
| `neura-core` | ✅ config · logging+redaction · errors · context · telemetry · crypto · ids |
| `neura-domain` | ✅ canonical models · enums · events (pure, verified) |
| `neura-api` | ✅ boots; `/v1/health`, `/v1/health/ready`, `/v1/agents`; error contract |
| Agent discovery | ✅ entry points working — `care` manifest discovered at startup |
| Infrastructure | ✅ docker-compose: Postgres 16 + pgvector, Redis 7 — both healthy |
| Guardrails | ✅ ruff · mypy strict · 5 import-linter contracts · platform-independence check |
| Eval harness | ✅ datasets · judge · metrics · runner · reports · CLI (`make eval`) |
| Golden datasets | ⚠️ 19 cases across 3 datasets — **all synthetic**, so not validation |
| `neura-llm` | ✅ roles · 4 role maps · provider · structured output + repair · cost metering |
| LLM verified live | ✅ `make llm-check` green against real Ollama — chat, schema, embeddings, tool calling |
| `neura-commerce` | ✅ adapter Protocol · capability negotiation · cursor pagination · identity map · registry · conformance suite |
| Platform independence | ✅ proved: a fictional platform integrates with **zero** core changes |
| Tests | ✅ 137 unit tests passing |
| CI | ✅ workflow written — **not yet run** (no remote) |
| `neura-agent-core` / adapters | ❌ documented stubs only |
| Sync engine | ❌ milestone 1.8 |
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
1.6  Generic Commerce Interface ⬜   ← NEXT
1.7  Bagisto bridge             ⬜
1.8  Sync engine                ⬜
1.9  RAG                        ⬜
1.10 Agent runtime              ⬜
1.11 CARE agent                 ⬜
1.12 Guard (injection + PII)    ⬜
1.13 Multi-tenancy              ⬜
1.14 API                        ⬜
1.15 Shadow mode                ⬜
1.16 Widget                     ⬜
1.17 Deploy                     ⬜
```

**Exit criteria (none met):** conformance passes · zero platform names outside adapters · evals green on both role maps · injection resistance 1.00 · cross-tenant isolation passes · end-to-end conversation working · shadow mode producing graded conversations.

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
| uv | **Not installed** — setup step |
| Docker | CLI 29.4.3 installed, **daemon not running** — must be started before `make dev` |
| Node | v24.15.0 |
| Bagisto | `/Users/malithjayasinghe/Developer/bagisto` — 2.4.x-dev, Laravel 12, MySQL on port **3307**, `QUEUE_CONNECTION=sync` (must move to Redis before webhooks) |

---

## 7. Session log

Newest first. One short entry per session — what changed, what was decided, what is next.

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
