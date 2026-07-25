# CLAUDE.md — Read This First

**Entry point for any new session.** You are starting with no memory of previous conversations. Everything you need is in this repository. Nothing you need is in your head.

---

## 1. Read these, in this order

| # | File | Why |
|:--|:--|:--|
| 1 | [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) | **Where the project actually is right now.** Always read this first — the other docs describe the target, not the position. |
| 2 | [`docs/glossary.md`](docs/glossary.md) | Terms have exactly one meaning here. Using them loosely produces bugs. |
| 3 | [`AGENTS.md`](AGENTS.md) | Four non-negotiable rules + conventions + recipes |
| 4 | [`docs/business/blueprint-v2.md`](docs/business/blueprint-v2.md) | What is being built, for whom, and what is deliberately excluded |
| 5 | [`docs/architecture/overview.md`](docs/architecture/overview.md) | System shape, then follow links as needed |
| 6 | [`docs/open-questions.md`](docs/open-questions.md) | Everything not yet decided — **do not decide these alone** |

---

## 2. The anti-invention rule

This project has a large documented vision and a deliberately small build scope. The failure mode for a fresh session is **filling the gap with plausible invention**.

> **If it is not written in `docs/`, it is not decided. Ask. Do not design it silently.**

Concretely:

| If asked to… | Correct response |
|:--|:--|
| Build NEURA-SELL / MIND / GROW / GUARD | **These are not designed.** See [`docs/agents/README.md`](docs/agents/README.md). Say so and propose a design session first. |
| Add a write/refund/cancel tool | Blocked by [ADR-0010](docs/architecture/adr/0010-read-only-mvp-tools.md). Requires the approval queue, which does not exist. |
| Pick a cloud LLM provider | Deliberately undecided ([ADR-0006](docs/architecture/adr/0006-llm-model-roles.md)). Decided by eval results at swap time, not in advance. |
| Add a native Shopify/Woo adapter | Phase 2 ([ADR-0009](docs/architecture/adr/0009-generic-commerce-interface.md)). Tier 2 comes first, on purpose. |
| Quote a conversion or deflection number | **No measured numbers exist yet.** See §4 below. |
| Change an ADR | ADRs are immutable. Write a superseding one. |

Contradicting a documented decision is fine — but do it explicitly, in an ADR, not by quietly writing different code.

---

## 3. The four rules (full version in `AGENTS.md`)

1. **No commerce-platform name outside `packages/neura-adapters/`** — `bagisto`, `shopify`, `woocommerce`, `magento`. CI-enforced. This is the entire market position; if it breaks, the product claim is false.
2. **Dependencies point downward only.** `neura-domain` imports only Pydantic + stdlib.
3. **Authorisation is code, never a prompt.** If your safety argument is "the prompt says not to", you have no safety argument.
4. **Nothing merges without an eval.** Injection resistance must stay at 1.00.

---

## 4. Numbers in these docs are NOT measurements

Nothing has been built or measured. Every figure below is illustrative or a target, and **must not be repeated as fact** — to the user, in marketing, or in code comments:

- All eval scores in [evaluation-strategy.md](docs/architecture/evaluation-strategy.md) §6 and [llm-abstraction.md](docs/architecture/llm-abstraction.md) §8.1 — **illustrative report shapes**, not results.
- All metric thresholds — informed starting points, to be recalibrated after ~100 real conversations.
- All prices in [blueprint-v2.md](docs/business/blueprint-v2.md) §8 — proposals. Explicitly **not to be published** until pilot unit economics exist.
- All effort estimates in [roadmap.md](docs/roadmap.md) — planning inputs. They will be wrong.
- Deflection rate, cost per resolution, model quality deltas — **unknown**. Saying otherwise invents evidence.

---

## 5. Project facts a fresh session usually gets wrong

- **Bagisto is a test harness, not a customer and not a target platform.** It lives at `/Users/malithjayasinghe/Developer/bagisto`. We do **not** write a `BagistoAdapter` — Bagisto conforms to *our* spec via a bridge package. The reasoning is in [commerce-integration.md §5](docs/architecture/commerce-integration.md).
- **Ollama is for development and for the sovereign product tier.** It is not a placeholder to be ripped out. Production uses a cloud API; both paths ship.
- **Python is pinned to 3.12**, though 3.14 is installed on this machine. Deliberate — library wheel availability.
- **The MVP agent is read-only.** It cannot change anything in a store. That is a feature.
- **One deployable process**, not microservices ([ADR-0002](docs/architecture/adr/0002-modular-monolith.md)) — the earlier plan said otherwise and was changed.
- **There is no design partner and no real merchant yet.** The top project risk.

---

## 6. Before you finish a session

Update [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md): what changed, what is next, anything newly decided or newly blocked. That file is the handoff to the next session — including your own next session, which will remember none of this.
