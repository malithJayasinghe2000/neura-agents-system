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
