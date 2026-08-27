# AGENTS.md — Operating Manual

How to work in this repository. Applies to human and AI contributors alike.

> **Starting a fresh session?** Read [`CLAUDE.md`](CLAUDE.md) first — it covers the reading
> order, the anti-invention rule, and the facts new sessions most often get wrong.
> Then [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) for where the project actually is,
> and [`docs/glossary.md`](docs/glossary.md), whose terms have exactly one meaning each.

---

## The four rules

Everything else is detail. These four are not negotiable, because each one protects a claim the product depends on.

### 1. No platform names outside `packages/neura-adapters/`

`bagisto`, `shopify`, `woocommerce`, `magento` — none of these strings may appear in `neura-domain`, `neura-commerce`, `neura-agent-core`, `neura-llm`, `neura-core` or `apps/`.

A CI grep enforces this. It is the single most important check in the repository: if it fails, platform independence — the entire market position — is no longer true.

*Need platform-specific behaviour in the core? You don't. Add a `Capability` instead.*

### 2. Dependencies point downward only

```
apps → agent-core / commerce / adapters → llm → domain → core
```

`neura-domain` imports **only Pydantic and the stdlib**. No database, no HTTP, no LLM. Enforced by `import-linter`.

### 3. Authorisation is code, never a prompt

Anything deciding what the agent *may* do belongs in the policy engine. A system prompt is guidance; a persuasive user message competes with it on equal terms. If your safety argument is "the prompt tells it not to", you have no safety argument.

### 4. Nothing merges without an eval

Changes to prompts, graph nodes, tools or model config are behaviour changes. `make eval` runs and must not regress. Injection resistance must stay at **1.00** — that one is a release blocker, not a target.

---

## Layout

Three categories: **libraries**, **products**, **deployables**.

```
packages/                   LIBRARIES — shared, no product identity
  neura-core/               config · logging · OTel · errors · crypto · db
                            tenancy/ — tenants · API keys · budgets · metering
  neura-domain/             canonical models + events   (PURE — no I/O)
  neura-llm/                provider abstraction · roles · structured output
  neura-commerce/           adapter Protocol · capabilities · sync engine
  neura-agent-core/         graph · shared nodes · tools · policy · checkpointer · audit · rag
  neura-adapters/           the only place platform names live

agents/                     PRODUCTS — one folder per sellable agent
  care/                     ✅ designed and built
  sell/                     ✅ DESIGNED, not built — docs/agents/sell.md +
                            ADR-0023. Read-only, 2 intents, 5 tools, and
                            3 surfaces of which only one has a graph.
                            Scaffold within that scope, not beyond it
  mind/ grow/ guard/        ⬜ NOT DESIGNED — see docs/agents/README.md

apps/neura-api/             DEPLOYABLE — FastAPI app + worker entrypoint
                            auth · rate limits · idempotency · metering ·
                            chat + WebSocket · webhook outbox drainer
  jobs/                     the worker loop and its handlers. Finds work through
                            neura_due_tenants() — the ONE read in this system
                            that crosses a tenant boundary (ADR-0022)
  widget/                   the embeddable chat element. THE ONLY JAVASCRIPT
                            IN THIS REPOSITORY — one file, no build step, no
                            package.json anywhere (ADR-0019). A test fails if
                            one appears

evals/                      eval runner — finds agents and their datasets by
                            entry point, and never learns an agent's name
infra/                      docker-compose · Dockerfiles · Alembic
tests/                      integration + e2e
```

Each agent: `manifest.py` · `graph.py` · `nodes/` · `tools/` · `prompts/` ·
`serving.py` · `evals/datasets/`.
Full detail in [docs/architecture/tenancy-and-packaging.md](docs/architecture/tenancy-and-packaging.md).

---

## Commands

```bash
make dev            # docker compose up + API with reload
make test           # unit + the widget's JS logic
make test-widget    # `node --test` — Node ships the runner, so no npm and no install
make widget-check   # drive the REAL widget in REAL headless Chrome. No models, no cost —
                    # the browser half is not reachable from pytest or from node --test
make console-check EMAIL=…   # ALL FIVE console screens in REAL headless Chrome: sign in
                             # through a real link, read the evidence, grade a withheld turn,
                             # open a transcript, and check no credential or invented number
                             # reaches a page. 33 checks. No models, no cost — __Host-,
                             # HttpOnly and "did the screen actually render it" are browser
                             # facts and nothing else can assert them (docs/console.md §6).
                             # It seeds its own rows and removes exactly those
make widget-check-live SHOP=… TOKEN=… [SHADOW=1]   # the same file against a running API
                                                   # and a real shop. One turn, not an eval
make lint           # ruff + mypy
make eval           # run the agent against its golden datasets (needs Ollama)
make eval-fast      # datasets + harness only — no agent, no models. In `make check`
make eval-guard-off # the same suite with the guard disabled — see below
make eval-compare A=ollama-dev B=cloud-prod
make migrate        # alembic upgrade head
make tenant-new NAME="Acme Store" AGENTS=care   # create a tenant
make key-new TENANT=tn_… SCOPES=care:chat:write # issue a key — printed ONCE
make tenant-show TENANT=tn_…                    # tenant, keys, usage
make tenant-usage TENANT=tn_…                  # what a tenant actually spent today
make webhook-drain TENANT=tn_…                 # send queued webhooks now (open question P7)
make rag-check URL=… TOKEN=…   # index a real shop with real embeddings (KEEP=1 to leave the data)
make rag-ask Q="…" [SHOW=1]    # search what is indexed — answers "why did it retrieve that?"
make agent-check               # run the agent runtime end to end on real models
make care-check URL=… TOKEN=…  # hold real conversations with CARE against a real shop
make care-ask Q="…" URL=… TOKEN=… [CUSTOMER=385]   # one question, every step printed —
                                                   # the "why did it say that?" tool
make verify-probe [MODEL=… CLOUD=1]   # does `verify` catch a fabricated fact? Four arms;
                                      # two are controls the verifier MUST refuse and two
                                      # it must NOT. All four, or the model does not hold
                                      # the GUARD role (ADR-0018). `llama3.2:3b` misses
                                      # both fabrications 10/10 — this is why GUARD is not
                                      # the router's 3B.
make router-probe [MODEL=… ROLE_MAP=…]  # A11: can this model hold the ROUTER role?
                                      # 5 messages, 3 budget arms. Capping a reasoning
                                      # model is a QUALITY change: max_tokens=512 broke
                                      # structured output on 4 of 5 cases.
make api-check URL=… TOKEN=…   # the whole request path against a real shop: a real key
                               # authenticating, a store decrypted from the database, a
                               # usage row written, an audit entry for a blocked turn,
                               # and the same turn over REST and over a WebSocket
make check          # everything CI runs
```

**Two database URLs, on purpose.** `DATABASE_URL` is the unprivileged app role;
`DATABASE_MIGRATION_URL` is the owner. Row-Level Security does not apply to
superusers, so pointing the app at the owner disables tenant isolation with no
error anywhere. `Database.ping()` refuses to report ready if it detects that.

**`make eval-guard-off` is not an optional extra.** The `guard` node ends a turn
before any tool is proposed, so a blocked case has zero unauthorised tool calls
by arithmetic — a guard that blocks can *manufacture* the injection-resistance
gate. That run disables every rule and measures the structural defence alone, and
**injection resistance must be 1.00 in it**. If it is not, what broke is the
policy engine, and no rule in the guard is the fix ([ADR-0011](docs/architecture/adr/0011-deterministic-guard-not-classifier.md)).

---

## Conventions

**Python.** 3.12, `uv` only (never bare `pip`). Ruff for lint and format. mypy strict on `packages/`. Async by default in I/O paths — one blocking call in an async handler stalls the event loop for every tenant.

**Types.** Pydantic v2 for anything crossing a boundary. `Decimal` for money, never `float`. Timezone-aware UTC datetimes, always. External IDs are `str`, always — platforms disagree, and normalising at the boundary removes a class of bug.

**Errors.** Raise from the `neura-core` hierarchy. Never let a platform-specific exception escape an adapter; translate it to `AdapterError` or a subclass.

**Logging.** Structured, with `trace_id`, `tenant_id`, `conversation_id`. **Never log credentials, PII or prompt content** — the redaction filter is a safety net, not permission to be careless.

**Prompts.** Files under `prompts/`, never inline strings. Content-hashed; the hash is recorded per conversation so any past answer can be traced to the exact prompt that produced it.

**Tests.** Real Postgres and Redis; stub the LLM. If a test needs a live model, it is an eval or a `*-check` smoke script, not a test. Integration tests currently use the `docker compose` stack (`make up` + `make migrate`) and **skip** if it is not reachable — but never skip on a misconfiguration, only on an absent database. A suite that skips its own security checks reports green for the wrong reason.

---

## Recipes

### Add a commerce platform

1. `packages/neura-adapters/<platform>/adapter.py` implementing `CommerceAdapter`.
2. Declare `capabilities` — be honest; over-declaring produces tools that fail at runtime.
3. Map payloads to canonical models, **including the status enum** (unmappable → `UNKNOWN` + warning; never leak a platform string into agent reasoning).
4. Register in the adapter registry.
5. Run the shared adapter conformance suite.

No change to `neura-domain`, the agent, any tool, or the API. If you find yourself needing one, that is a design defect — raise it rather than working around it.

### Add a tool

1. Declare with `@tool` — `requires`, `side_effect`, `scopes`, `pii_output`.
2. `READ` only unless the approval queue exists.
3. Add golden cases covering success, failure and the abuse path.
4. Add an injection case if the tool touches customer data.

The policy engine, capability filtering, audit logging and budget accounting come for free.

### Add an agent

> **First check [`docs/agents/README.md`](docs/agents/README.md).** CARE and SELL are designed; MIND, GROW and GUARD are not. If the agent has no design document, stop and propose a design session — do not invent one. If it *has* one, build inside it: SELL's excluded scope (checkout, cart recovery, behavioural ranking) is excluded by [ADR-0023](docs/architecture/adr/0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) and reopening it is a superseding ADR, not a pull request.

Once designed, create `agents/<name>/` with the standard five parts:

1. `manifest.py` — key, version, `requires_capabilities`, `scopes`, `route_prefix`.
2. `graph.py` — reusing `guard`, `retrieve`, `verify`, `escalate` from `neura-agent-core`.
3. `tools/` — declared as above.
4. `prompts/` — files, never inline.
5. `evals/datasets/` — no agent ships without one, plus the `EvalTarget` that runs them.

Register it via entry points in its `pyproject.toml` — two groups, both discovered
rather than imported by name:

```toml
[project.entry-points."neura.agents"]
<name> = "neura_agent_<name>:MANIFEST"          # the API mounts it at startup

[project.entry-points."neura.eval_targets"]
<name> = "neura_agent_<name>.evals:build_target"  # `make eval` measures it

[project.entry-points."neura.agent_runners"]
<name> = "neura_agent_<name>.serving:build_runner"  # a request becomes a turn
```

**Three groups, all discovered rather than imported by name, for one reason.**
`neura-api` must not learn that an agent called "care" exists, or adding agent #2
becomes an edit to the deployable and the "one codebase, five products" claim
stops being structural. A runner's `key` must equal its manifest key — the API
refuses a mismatch at startup, because the key decides which routes it is
mounted under, which entitlement is checked, and **which agent is billed**.

**A runner must stream even when nobody is listening.** `CareRunner` uses
`astream` whether or not a progress sink was supplied, so REST and WebSocket
execute one code path. Invoking one way and streaming the other would create the
second code path api-design.md §8 forbids, and the golden suite would then be
evidence about only one of them ([ADR-0016](docs/architecture/adr/0016-stream-only-after-verify.md) §4).

**Copy `agents/care/` rather than this list.** It is the only built agent and it
is deliberately the worked example: six nodes, seven tools, seven prompt files, a
fixture store and 47 golden cases, and not one line of policy, audit, checkpoint,
ownership, injection-detection or PII code.

**Wire `guard` first or not at all.** It is inherited like `verify`, and the
builder enforces the position rather than trusting the author: a guard reached
after routing has already handed the raw message to a model, so its redaction is
redaction of something already disclosed — and it looks exactly like a guard that
works. An agent that routes to `guard` must also have `blocked`, and `blocked`
must be terminal.

**Two hard rules:** `neura-agent-core` must not learn your agent's name, and your agent must not import another agent. Cross-agent communication goes through the event bus.

Everything else — policy engine, audit log, memory, budgets, shadow mode, tenancy — is inherited.

### Change the embedding model

**Do not just edit the config.** Follow the reindex procedure in [llm-abstraction §5.2](docs/architecture/llm-abstraction.md) — dimensions differ between models and mixing them degrades retrieval *silently*, with no error to alert you.

`neura_agent_core.rag.reindex` implements steps 2, 3 and 5; steps 1 and 4 are role-map edits.

```python
await backfill_namespace(store, candidate_llm, tenant_id=..., entities=...)  # 2
report = await compare(store, live_llm, candidate_llm, tenant_id=..., queries=[...])  # 3
await retire_namespace(store, tenant_id=..., embedding_model="old", live=promoted_llm)  # 5
```

`retire_namespace` refuses to drop the namespace currently configured, and `compare` refuses to run against an unpopulated candidate. Both refusals exist because the mistake they prevent produces no error, only worse answers.

---

## Gotchas

| Symptom | Likely cause |
|:--|:--|
| Query returns nothing that should return rows | RLS — `app.tenant_id` not set on the transaction. Use `Database.tenant_session()`; it is the only way to get one |
| Cross-tenant reads *succeed* | Worse than the above. `DATABASE_URL` points at a superuser or `BYPASSRLS` role, so no policy applies. `Database.ping()` refuses this — if you bypassed it, don't |
| Retrieval returns nothing | Embedding-model namespace mismatch. `RetrievalResult.diagnosis` says which model the content *is* indexed under |
| `alembic` wants to drop a table you just added | Its module is not imported in `infra/migrations/env.py`, so it is absent from `neura_core.metadata` |
| Tool "exists" but the agent never calls it | Adapter does not declare the required capability |
| Ollama slow or thrashing | Too many distinct models loaded — check `OLLAMA_NUM_PARALLEL`, `OLLAMA_KEEP_ALIVE` |
| Structured output failing often | Provider lacks `JSON_SCHEMA_MODE`; check the repair-rate metric |
| Agent loops | `act` node cap — investigate why, don't just raise the cap |
| A security case "fails" because the shopper was never anonymous | A `make` variable name collided with a built-in. `AS` is the assembler and defaults to `as`, so `$(if $(AS),…)` is always true. Never name a make variable `AS`, `CC`, `CXX`, `AR`, `LD`, `RM` |
| Agent escalates every turn with "no draft to verify" | A reasoning model spent `max_tokens` thinking and emitted no content. `max_tokens` budgets *thinking plus answer*; raise it, or set `reasoning_effort="none"` |
| Retrieval or a tool search finds nothing a shopper would expect | The query still contains a pronoun. `route` writes a resolved `search_query`; anything reading `message` instead is asking about a subject that is not there |
| Agent route returns 403 | Tenant's `enabled_agents` does not include it — an entitlement, not a bug |
| An API key that exists authenticates as nobody | The lookup runs on `Database.credential_session`, not `tenant_session` — the tenant is not known yet. Any other session sees no `api_keys` row at all ([ADR-0014](docs/architecture/adr/0014-api-keys-and-the-rls-bootstrap.md)) |
| A tenant's agent suddenly calls no tools | It is over its **hard** daily budget, so its tool allowlist is empty and every turn escalates. By design — check `make tenant-usage TENANT=…`, not the graph |
| A `fn_pk_` key is refused from the merchant's own site | A public key with an empty origin allowlist permits *nothing*. Issue it with `PUBLIC=1 ORIGINS=https://…` |
| A key was issued and the token is gone | There is no command to show it again — only the hash is stored. Issue a new one and revoke the old |
| New agent not mounted at startup | Missing `[project.entry-points."neura.agents"]`, or not installed in the workspace |
| `GraphContractError: guard is reachable but the entry node is …` | A guard that runs after routing has already shown the raw message to a model. Make `guard` the entry, or do not route to it |
| An order lookup fails and the trace shows `[PHONE_1]` where the reference was | A PII detector matched an order or tracking number. The detectors require structure a reference does not have (`+`, leading zero, separators; Luhn for cards) — add the shape to `tests/unit/test_guard.py` and narrow the pattern, never widen it |
| `verify` passes a draft that states a wrong date or status | The `GUARD` model cannot discriminate. `make verify-probe` measures exactly this, in under a minute and for nothing. `llama3.2:3b` misses both an invented delivery date and a contradicted status 10/10, which is why `GUARD` is `llama3.1:8b` ([ADR-0018](docs/architecture/adr/0018-guard-model-must-refuse.md)). Changing it back, or forward, is a **Rule 4** change: n≥3 either side |
| `verify` escalates on "shall I pass you to a colleague?" | A refusal of something the prompt exempts as a non-claim. Measured 2026-08-13: `llama3.2:3b` did this 11 times in 3 suite runs while missing every fabrication. Read it as the model failing to discriminate, not as a prompt that needs another rule |
| A real customer's message was refused with no handover | A guard rule false-positived. Add the sentence to the **benign** half of the corpus in `tests/unit/test_guard.py` — it is a hard gate, so the fix cannot be forgotten |
| `[EMAIL_9]` appears in a reply | The model invented a redaction token. Rehydration leaves unknown tokens visible on purpose: a silently deleted one is a sentence that changed meaning with nobody the wiser |
| A chat request 404s with `NO_STORE_CONNECTED` | The tenant has no `tenant_stores` row. `POST /v1/stores` first — a tenant, a key and an agent are not enough to answer "where is my order?" |
| A `POST /v1/care/chat` returns 409 | An `Idempotency-Key` was reused with a *different* body. That is a client bug and surfacing it beats silently doing the wrong thing. The same key **in flight** is also a 409, and that one is retryable |
| Rate limits appear not to apply | Redis is unreachable, and the limiter **fails open on purpose** ([ADR-0017](docs/architecture/adr/0017-rate-limit-subjects.md) §3). It logs `rate_limit_unavailable` on every request and `/v1/health/ready` reports redis `degraded`. The daily budget still applies — it is a Postgres rollup |
| A limit is enforced ~N× higher than configured | An in-process counter across N workers. There is no in-process counter here; if one is ever added, this is the symptom |
| Webhooks stop being delivered after a restart | The drainer's tenant index lives in Redis (open question **P7**). Rows are safe, the schedule is not — `make webhook-drain TENANT=…` |
| A webhook endpoint quietly stops receiving events | 20 consecutive failures auto-disables it. Check `GET /v1/webhooks` for `status: disabled`, and `GET /v1/webhooks/deliveries?status=dead` for what was lost |
| A WebSocket delivers the whole reply at once with no `token` frames | The turn was blocked or escalated. Those replies are fixed text delivered whole — typing out a refusal is theatre (ADR-0016) |
| `AGENT_NOT_RUNNABLE` (403) rather than 404 | The agent declares `neura.agents` and not `neura.agent_runners`, or its `build_runner` raised at startup. "We have it and it is broken" is a different problem from "we do not have it" |

---

## Decisions

Every significant choice is in [`docs/architecture/adr/`](docs/architecture/adr/) with its context and its downsides.

**ADRs are immutable.** Disagreeing with one is fine — write a new ADR that supersedes it. Do not edit the old one; future readers need to see why we once thought otherwise.

If something here seems wrong, it may well be. Say so, in an ADR.

**Two that a session touching the API will meet immediately:**

- **[ADR-0019](docs/architecture/adr/0019-widget-no-build-step.md)** — the widget is one dependency-free custom element served from our own origin, WebSocket-first with a REST fallback. There is no JavaScript toolchain and `tests/unit/test_widget.py` fails if a `package.json` appears. **CORS is decided by the presented key, not by `WIDGET_ALLOWED_ORIGINS`** — that setting now covers only endpoints with no key to consult.
- **[ADR-0020](docs/architecture/adr/0020-a-withheld-turn-says-so.md)** — a turn that withholds its reply carries `fallback_message`, and an empty reply with an empty fallback is a bug rather than a quiet turn. If you add a mode that withholds, it is that field you populate, not `reply`.
