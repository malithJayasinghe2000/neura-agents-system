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
  neura-core/               config · logging · OTel · errors · auth · crypto · db
  neura-domain/             canonical models + events   (PURE — no I/O)
  neura-llm/                provider abstraction · roles · structured output
  neura-commerce/           adapter Protocol · capabilities · sync engine
  neura-agent-core/         graph · shared nodes · tools · policy · checkpointer · audit · rag
  neura-adapters/           the only place platform names live

agents/                     PRODUCTS — one folder per sellable agent
  care/                     ✅ the only designed agent
  sell/ mind/ grow/ guard/  ⬜ NOT DESIGNED — see docs/agents/README.md

apps/neura-api/             DEPLOYABLE — FastAPI app + worker entrypoint

evals/                      eval runner — finds agents and their datasets by
                            entry point, and never learns an agent's name
infra/                      docker-compose · Dockerfiles · Alembic
tests/                      integration + e2e
```

Each agent: `manifest.py` · `graph.py` · `nodes/` · `tools/` · `prompts/` · `evals/datasets/`.
Full detail in [docs/architecture/tenancy-and-packaging.md](docs/architecture/tenancy-and-packaging.md).

---

## Commands

```bash
make dev            # docker compose up + API with reload
make test           # unit + integration
make lint           # ruff + mypy
make eval           # run the agent against its golden datasets (needs Ollama)
make eval-fast      # datasets + harness only — no agent, no models. In `make check`
make eval-compare A=ollama-dev B=cloud-prod
make migrate        # alembic upgrade head
make rag-check URL=… TOKEN=…   # index a real shop with real embeddings (KEEP=1 to leave the data)
make rag-ask Q="…" [SHOW=1]    # search what is indexed — answers "why did it retrieve that?"
make agent-check               # run the agent runtime end to end on real models
make care-check URL=… TOKEN=…  # hold real conversations with CARE against a real shop
make care-ask Q="…" URL=… TOKEN=… [CUSTOMER=385]   # one question, every step printed —
                                                   # the "why did it say that?" tool
make check          # everything CI runs
```

**Two database URLs, on purpose.** `DATABASE_URL` is the unprivileged app role;
`DATABASE_MIGRATION_URL` is the owner. Row-Level Security does not apply to
superusers, so pointing the app at the owner disables tenant isolation with no
error anywhere. `Database.ping()` refuses to report ready if it detects that.

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

> **First check [`docs/agents/README.md`](docs/agents/README.md).** Only CARE is designed. If the agent has no design document, stop and propose a design session — do not invent one.

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
```

**Copy `agents/care/` rather than this list.** It is the only built agent and it
is deliberately the worked example: five nodes, seven tools, five prompt files, a
fixture store and 35 golden cases, and not one line of policy, audit, checkpoint
or ownership code.

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
| New agent not mounted at startup | Missing `[project.entry-points."neura.agents"]`, or not installed in the workspace |

---

## Decisions

Every significant choice is in [`docs/architecture/adr/`](docs/architecture/adr/) with its context and its downsides.

**ADRs are immutable.** Disagreeing with one is fine — write a new ADR that supersedes it. Do not edit the old one; future readers need to see why we once thought otherwise.

If something here seems wrong, it may well be. Say so, in an ADR.
