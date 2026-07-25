# Neura Agents

**Platform-agnostic AI agents for commerce.**

An AI customer-experience agent that connects to *any* commerce platform — Shopify, WooCommerce, Magento, Bagisto, or a store built in-house last month — and can run entirely on the customer's own infrastructure.

> **Status:** Pre-implementation. The documentation set is complete and under review; no code has been written yet. Start with [`docs/`](docs/).

---

## Why this exists

Every AI support product on the market is Shopify-first. Merchants on custom, regional or self-hosted platforms get a "contact sales" page and a six-week integration quote. That gap is the market.

Two things follow from it, and they shape the entire architecture:

1. **The integration layer is the product.** A canonical domain model plus a published spec any store can implement, so a custom store integrates without us writing a line of code for it.
2. **The whole stack runs locally.** Development uses local models because there is no LLM budget — and that same path ships as a *data sovereignty* tier for customers who cannot send customer data to a third-party cloud.

---

## Documentation

| Start here | |
|:--|:--|
| [Project State](docs/PROJECT_STATE.md) | **Where the project is right now** — read first; everything else describes the target |
| [Open Questions](docs/open-questions.md) | What is not yet decided |
| [Business Blueprint v2](docs/business/blueprint-v2.md) | What we are building, for whom, and what we deliberately are not building |
| [Architecture Overview](docs/architecture/overview.md) | System shape, package map, request lifecycle |
| [Roadmap](docs/roadmap.md) | Phased plan with honest estimates |
| [Glossary](docs/glossary.md) | Shared vocabulary — read before the others |

| Deep dives | |
|:--|:--|
| [Commerce Integration](docs/architecture/commerce-integration.md) | The core asset: canonical model, adapters, capability negotiation, sync |
| [LLM Abstraction](docs/architecture/llm-abstraction.md) | Model roles, local→cloud swap, the embedding-dimension trap |
| [Agent Runtime](docs/architecture/agent-runtime.md) | Graph, tools, policy engine, memory, shadow mode |
| [Security Model](docs/architecture/security-model.md) | Prompt injection, authorisation, PII, tenant isolation |
| [Evaluation Strategy](docs/architecture/evaluation-strategy.md) | Golden datasets, metrics, CI gates |
| [API Design](docs/architecture/api-design.md) | Versioning, envelopes, errors, idempotency, webhooks |
| [ADRs](docs/architecture/adr/) | Every significant decision, with its consequences |

`AGENTS.md` is the operating manual for anyone — human or AI — working in this repository.

---

## Architecture in one picture

```
        Shopper · Merchant · Support agent
                       │
              ┌────────┴────────┐
              │    neura-api    │   FastAPI · REST · WebSocket · widget
              └────────┬────────┘
                       │
   ┌───────────────────┼───────────────────┐
   │                   │                   │
neura-agent-core   neura-commerce     neura-adapters
 graph · tools      canonical model     ← the ONLY place a
 policy engine      capabilities          platform name appears
   │                   │
   └─────────┬─────────┘
             │
        neura-llm          Ollama (dev · sovereign) │ cloud API (prod)
             │
        neura-domain       pure Pydantic · zero I/O
             │
        neura-core         config · logging · OTel · crypto
```

Two properties are enforced in CI, because they are the whole thesis:

- **No commerce-platform name appears outside `packages/neura-adapters/`.** If it does, the platform-independence claim is false.
- **Dependencies point downward only**, checked by an `import-linter` contract.

---

## Current scope — NEURA-CARE MVP

Three intents: **order status**, **product Q&A**, **returns & shipping policy**.

**Read-only.** The agent cannot modify a store — no refunds, no cancellations, no address changes. That is a deliberate security property ([ADR-0010](docs/architecture/adr/0010-read-only-mvp-tools.md)), and it is what makes running on live traffic defensible from day one.

---

## Stack

Python 3.12 · uv workspace · FastAPI · LangGraph · PostgreSQL 16 + pgvector · Redis · Alembic · Ollama (dev/sovereign) → cloud API (prod) · OpenTelemetry + Langfuse · Ruff + mypy + pytest · GitHub Actions

---

## Getting started

Nothing to run yet. Implementation begins once the documentation is reviewed — see [roadmap §Phase 1](docs/roadmap.md).

Prerequisites when it does: `uv`, Docker (daemon running), and Ollama with `llama3.2:3b`, `qwen3.5:9b` and `nomic-embed-text` pulled.

---

*FiveNeurals — build better solutions with artificial intelligence.*
