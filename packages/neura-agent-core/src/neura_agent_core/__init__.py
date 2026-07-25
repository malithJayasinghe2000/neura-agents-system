"""neura-agent-core — the engine every agent runs on.

NOT YET IMPLEMENTED. Phase 1 milestone 1.10 — see docs/roadmap.md.

Design is settled in docs/architecture/agent-runtime.md and
docs/architecture/adr/0004-langgraph-explicit-graph.md. Planned contents:

* Graph runtime (LangGraph + PostgreSQL checkpointer) — explicit state machine,
  not an open agent loop. Debuggable, resumable, and viable on small local models.
* Shared nodes every agent reuses: ``guard`` (injection + PII), ``retrieve`` (RAG),
  ``verify`` (groundedness), ``escalate`` (human handoff with full context).
* Tool registry — tools declare JSON schema, required capabilities, scopes and
  side-effect class.
* Policy engine — the security boundary. Every tool call is authorised here, in
  code, on eight independent checks. Never by a prompt.
* Memory tiers: working (checkpoint) / session (Redis) / conversation (Postgres) /
  semantic (pgvector).
* Shadow mode, budgets, immutable audit log.

HARD RULE: this package must never learn an agent's name. It must not import
neura_agent_care or any other agent — same rule, same reason, as neura_commerce
not knowing Shopify exists. Enforced by an import-linter contract in CI.
"""

__all__: list[str] = []
