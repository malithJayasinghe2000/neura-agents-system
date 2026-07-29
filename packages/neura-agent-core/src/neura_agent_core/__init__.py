"""neura-agent-core — the engine every agent runs on.

PARTIALLY IMPLEMENTED. ``rag`` landed in milestone 1.9; the graph runtime is
1.10 — see docs/roadmap.md.

Design is settled in docs/architecture/agent-runtime.md and
docs/architecture/adr/0004-langgraph-explicit-graph.md.

* ``rag`` ✅ — chunking, embedding, the pgvector ``VectorStore`` promised by
  ADR-0005, retrieval, and the reindex path. The ``retrieve`` node calls it.
* Graph runtime (LangGraph + PostgreSQL checkpointer) ⬜ — explicit state
  machine, not an open agent loop. Debuggable, resumable, and viable on small
  local models.
* Remaining shared nodes ⬜: ``guard`` (injection + PII), ``verify``
  (groundedness), ``escalate`` (human handoff with full context).
* Tool registry ⬜ — tools declare JSON schema, required capabilities, scopes
  and side-effect class.
* Policy engine ⬜ — the security boundary. Every tool call is authorised here,
  in code, on eight independent checks. Never by a prompt.
* Memory tiers ⬜: working (checkpoint) / session (Redis) / conversation
  (Postgres) / semantic (pgvector — the ``rag`` subpackage).
* Shadow mode, budgets, immutable audit log ⬜.

HARD RULE: this package must never learn an agent's name. It must not import
neura_agent_care or any other agent — same rule, same reason, as neura_commerce
not knowing Shopify exists. Enforced by an import-linter contract in CI.
"""

from neura_agent_core import policy, rag, tools

__all__ = ["policy", "rag", "tools"]
