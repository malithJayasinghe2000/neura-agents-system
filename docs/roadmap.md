# Roadmap

> **Status:** Draft for review · **Last updated:** 2026-07-25

## On the estimates

The original blueprint scheduled all five agents across 24 weeks. That is optimistic by roughly **3×** for one developer, and the gap comes from what those schedules never include: multi-tenancy, evaluation, security, the integration layer, and debugging non-deterministic behaviour.

Estimates below are in **focused work-weeks** (≈30 productive hours). Part-time, divide accordingly. They are planning inputs, not commitments — and they will be wrong. The sequencing matters more than the numbers.

---

## Phase 1 — Foundation + NEURA-CARE MVP

**Goal:** a support agent answering three intents against any conforming store, with the platform-independence claim proven.
**Estimate:** 10–14 work-weeks.

| # | Milestone | Deliverable | Est. |
|:--|:--|:--|--:|
| 1.1 | **Workspace** | uv workspace, Python 3.12, Ruff, mypy, pre-commit, Makefile, docker-compose (Postgres+pgvector, Redis), Alembic, CI skeleton | 1w |
| 1.2 | **Domain** | `neura-domain` canonical models + event schemas; `neura-core` config, logging, OTel, errors, crypto | 1w |
| 1.3 | **LLM layer** | `neura-llm`: provider abstraction, model roles, capability tiers, structured output + repair loop, usage metering | 1.5w |
| 1.4 | **Eval harness** | `evals/` runner, first golden dataset, `make eval`, `make eval-compare` | 1w |
| 1.5 | **Commerce layer** | `neura-commerce`: adapter Protocol, capabilities, registry, entity mapping | 1w |
| 1.6 | **Generic Interface** ✅ | OpenAPI spec + `GenericAdapter` + `neura-conformance` CLI | 1.5w |
| 1.7 | **Bagisto bridge** ✅ | Laravel package in the Bagisto install conforming to the spec; Redis queue; webhooks | 1.5w |
| 1.8 | **Sync engine** | Backfill, incremental, event-driven, reconciliation, per-tenant rate limiting | 1.5w |
| 1.9 | **RAG** | Chunking, embedding, pgvector with `(tenant, model)` namespacing, retrieval, reindex path | 1w |
| 1.10 | **Agent runtime** | `neura-agent-core`: graph, tool registry, policy engine, memory tiers | 2w |
| 1.11 | **CARE agent** | 3 intents, 7 tools, prompts, escalation handoff | 1.5w |
| 1.12 | **Guard** | Injection detection, PII redaction/rehydration, output filtering | 1w |
| 1.13 | **Multi-tenancy** | Tenants, API keys, RLS, per-tenant config, budgets, usage metering | 1.5w |
| 1.14 | **API** | REST `/v1/*`, WebSocket, webhooks, OpenAPI, error contract, idempotency | 1.5w |
| 1.15 | **Shadow mode** | Parallel execution, review queue, scorecard | 1w |
| 1.16 | **Widget** | Embeddable chat, client-side rendered, AI disclosure, origin-locked keys | 1w |
| 1.17 | **Deploy** | Dockerfiles, staging deploy, Langfuse, alerting, runbook | 1w |

**Exit criteria — all must hold:**
- [ ] `neura-conformance` passes against the Bagisto bridge
- [ ] **Zero** commerce-platform names outside `packages/neura-adapters/` and `docs/`
- [ ] Eval suite green on both the Ollama and a cloud role map, with the delta reported
- [ ] Injection resistance = **1.00**
- [ ] Cross-tenant isolation test passes
- [ ] End-to-end conversation working over REST and WebSocket
- [ ] Shadow mode producing graded conversations

### Suggested order

1.1 → 1.2 → 1.3 → **1.4** → 1.5 → 1.6 → 1.7 → 1.8 → 1.9 → 1.10 → 1.11 → 1.12 → 1.13 → 1.14 → 1.15 → 1.16 → 1.17

Two deliberate placements: **the eval harness comes before the agent** (1.4 before 1.10) — you cannot tune what you cannot measure, and with local models you will be tuning constantly. And **the integration layer comes before the agent** (1.5–1.8 before 1.10), because building the agent first would quietly shape the canonical model around whatever the agent happened to need.

---

## Phase 2 — First Design Partner

**Goal:** one real merchant, on real traffic, paying.
**Estimate:** 6–8 work-weeks. **Gate:** Phase 1 exit criteria met.

| Milestone | Notes |
|:--|:--|
| Merchant console | Config, shadow review, escalation queue, usage — Next.js |
| Human escalation console | Where a support person actually works |
| Approval queue + WRITE tools | Address change, order notes. Unlocks [ADR-0010](architecture/adr/0010-read-only-mvp-tools.md) tier 2 |
| **MCP server** | Same tool layer re-exposed. Cheap, and an unusually strong demo |
| Email channel | Second channel; validates the channel abstraction |
| Cloud LLM swap | Execute [llm-abstraction §8](architecture/llm-abstraction.md) with a full comparison report |
| First native adapter | WooCommerce or Shopify — decided by the design partner, not by us |
| Docs site | Public API docs, integration guide, `llms.txt` |
| Legal | ToS, privacy policy, DPA, AI disclosure copy |
| Production hardening | Backups, runbooks, status page, on-call |

**Exit:** one merchant live, renewing, and a measured deflection rate we are willing to publish.

---

## Phase 3 — Second Agent

**Estimate:** 8–10 work-weeks. **Gate:** a paying, renewing customer.

Which agent is decided by **what design partners ask for**, not by this document. Two candidates:

- **NEURA-SELL** via [agent-readiness](business/blueprint-v2.md#41-agent-readiness--making-a-store-sellable-to-ai-agents) — new revenue channel, easier sale, reuses the tool layer.
- **NEURA-MIND** via natural-language analytics over already-synced canonical data — cheapest to build, since the data is already there.

Also in Phase 3: the **event bus and shared memory** — the first point at which the [ecosystem effect](business/blueprint-v2.md#22-the-ecosystem-moat-is-real-but-it-is-a-later-moat) is more than a diagram. Event schemas already exist in `neura-domain` from Phase 1, so the seam is waiting.

**Exit:** cross-agent context demonstrably outperforms either agent alone. If it does not, the ecosystem thesis needs revisiting — and that is worth knowing.

---

## Phase 4 — Sovereign + Scale

**Estimate:** 10–12 work-weeks. **Gate:** 3–5 paying customers.

Sovereign deployment package (install guide, hardware sizing, support model) · more native adapters · agentic-commerce protocol output formats · AEO/GEO measurement · billing and self-serve onboarding · SOC 2 readiness if enterprise demand is real.

---

## Phase 5+ — Full Ecosystem

Remaining agents (GROW, GUARD as products), agent marketplace, fine-tuned models, partner integrations. Deliberately unplanned — planning it now would be fiction.

---

## What we are deliberately not doing

| Not doing | Why |
|:--|:--|
| Five agents in parallel | The reliable way to ship none of them |
| Voice | Expensive, and there is no evidence the ICP wants it |
| Fine-tuning | Needs data we do not have; a prompt and retrieval fix usually beats it |
| Mobile SDKs | REST works; build when someone asks |
| Enterprise features (SSO, SCIM) | No enterprise customers |
| Shopify App Store launch | We compete badly there ([blueprint-v2 §3.3](business/blueprint-v2.md)) |

---

## Risks

| Risk | Impact | Mitigation |
|:--|:--|:--|
| **No design partner** | Deflection rate stays synthetic and unsellable | Actively recruit during Phase 1. This is the top project risk. |
| Local model quality blocks development | Slow iteration, misleading evals | Capability tiers, eval-driven; a small paid budget for the judge model only |
| Canonical model proves wrong | Rework across layers | Validated early by making Bagisto conform in 1.7 |
| Scope creep back toward 5 agents | Nothing ships | Phase gates; ADRs record what was excluded and why |
| Solo bandwidth | Everything slips | Sequencing is chosen so each phase ends in something demonstrable |
| An incumbent moves down-market | The wedge closes | Sovereign tier and agent-readiness are harder for them to copy than feature parity |
