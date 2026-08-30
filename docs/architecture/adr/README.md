# Architecture Decision Records

Each ADR captures one significant decision: the context that forced it, the decision itself, and the consequences we accept — including the bad ones.

**Format:** Context · Decision · Consequences · Alternatives considered.
**Rule:** ADRs are immutable once accepted. A reversal is a *new* ADR that supersedes the old one; the original stays, so future readers can see why we once thought otherwise.

| # | Decision | Status |
|:--|:--|:--|
| [0001](0001-python-monorepo-uv.md) | Python 3.12 + `uv` workspace monorepo | Accepted |
| [0002](0002-modular-monolith.md) | Modular monolith, single deployable | Accepted |
| [0003](0003-canonical-domain-model.md) | Canonical domain model + adapter protocol | Accepted |
| [0004](0004-langgraph-explicit-graph.md) | Explicit LangGraph state machine, not an agent loop | Accepted |
| [0005](0005-pgvector-not-qdrant.md) | pgvector in PostgreSQL, not a separate vector DB | Accepted |
| [0006](0006-llm-model-roles.md) | LLM abstraction by model role | Accepted |
| [0007](0007-langfuse-observability.md) | Langfuse + OpenTelemetry, not LangSmith | Accepted |
| [0008](0008-multi-tenancy-rls.md) | Multi-tenancy via PostgreSQL RLS from day 1 | Accepted |
| [0009](0009-generic-commerce-interface.md) | Generic Commerce Interface as the primary integration tier | Accepted |
| [0010](0010-read-only-mvp-tools.md) | READ-only tools in the MVP | Accepted |
| [0011](0011-deterministic-guard-not-classifier.md) | The guard is deterministic code, not a classifier | Accepted |
| [0012](0012-block-cheaply-escalate-on-uncertainty.md) | A recognised attack is blocked; everything else escalates | Accepted |
| [0013](0013-tenant-record-and-configuration.md) | The tenant record: one table, typed where it is enforced | Accepted |
| [0014](0014-api-keys-and-the-rls-bootstrap.md) | API keys: SHA-256, and reading one row before the tenant is known | Accepted |
| [0015](0015-usage-rollups-and-budget-degradation.md) | Usage is a daily rollup; a budget degrades rather than errors | Accepted |
| [0016](0016-stream-only-after-verify.md) | The WebSocket streams the turn, not the draft — nothing reaches a shopper before `verify` | Accepted |
| [0017](0017-rate-limit-subjects.md) | Rate limits: several subjects at once, the narrowest binds | Accepted |
| [0018](0018-guard-model-must-refuse.md) | The `GUARD` model must be able to refuse, and is chosen by measurement | Accepted |
| [0019](0019-widget-no-build-step.md) | The widget is a dependency-free custom element, served by the API | Accepted |
| [0020](0020-a-withheld-turn-says-so.md) | A withheld turn says so, and the server supplies the words | Accepted |
| [0021](0021-synced-entities-are-documents.md) | A synced entity is stored as its canonical document, not as a second schema | Accepted |
| [0022](0022-scheduling-under-rls.md) | A durable job queue, and the one read that crosses tenants | Accepted |
| [0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) | Agent #2 is SELL, read-only, and every protocol is an output format | Accepted |
| [0024](0024-the-feed-is-opt-in-and-addressed-by-a-rotatable-secret.md) | The product feed is opt-in, and addressed by a rotatable secret | Accepted |
| [0025](0025-verify-sees-only-what-the-draft-cites.md) | `verify` Reads Only What The Draft Cites | Accepted |
| [0026](0026-the-merchant-console-and-the-first-human-in-the-system.md) | The Merchant Console, And The First Human In The System | Accepted |
| [0027](0027-a-constraint-miss-is-not-an-empty-store.md) | A Constraint Miss Is Not An Empty Store | Accepted |
| [0028](0028-only-the-catalogue-may-say-what-a-store-sells.md) | Only The Catalogue May Say What A Store Sells | Accepted |
| [0029](0029-the-index-may-name-a-candidate-never-describe-one.md) | The Index May Name A Candidate, Never Describe One | Accepted |
| [0030](0030-a-product-card-is-data-the-widget-draws.md) | A Product Card Is Data The Widget Draws | Accepted |
| [0031](0031-the-shopper-never-chooses-the-agent.md) | The Shopper Never Chooses The Agent | Accepted — **design only, nothing is built** |
