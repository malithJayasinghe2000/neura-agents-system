"""neura-agent-core — the engine every agent runs on.

Design is settled in docs/architecture/agent-runtime.md and
docs/architecture/adr/0004-langgraph-explicit-graph.md.

* ``graph`` ✅ (1.10) — an explicit LangGraph state machine, not an open agent
  loop, with a PostgreSQL checkpointer of our own (LangGraph's has no
  ``tenant_id`` and needs a second driver). The builder *refuses to compile* a
  graph where ``respond`` is reachable without ``verify``, or that has no
  ``escalate``, or that guards after routing.
* ``graph.nodes`` ✅ — ``guard`` (1.12: deterministic injection rules + PII
  tokenisation, ADR-0011), ``retrieve``, ``act``, ``verify``, ``escalate``,
  ``blocked``.
* ``tools`` ✅ — declaration, capability filtering, bounded execution. A WRITE
  tool **cannot be registered** (ADR-0010, structurally).
* ``policy`` ✅ — the security boundary. Eight checks, in code, never a prompt.
* ``audit`` ✅ — append-only and hash-chained; tampering and deletion detected.
* ``rag`` ✅ (1.9) — chunking, embedding, the pgvector ``VectorStore`` promised
  by ADR-0005, retrieval, and the reindex path.
* ``conversations`` ✅ (1.14) — the durable transcript, which is the
  *conversation* memory tier of agent-runtime.md §5.
* ``serving`` ✅ (1.14) — the seam a transport drives an agent through, so the
  API can run an agent without knowing which agents exist.
* Session memory (Redis) and cross-agent shared memory ⬜.
* Shadow mode ⬜ (1.15).

HARD RULE: this package must never learn an agent's name. It must not import
neura_agent_care or any other agent — same rule, same reason, as neura_commerce
not knowing Shopify exists. Enforced by an import-linter contract in CI.
"""

from neura_agent_core import conversations, policy, rag, serving, shadow, tools

__all__ = ["conversations", "policy", "rag", "serving", "shadow", "tools"]
