"""neura-llm — LLM provider abstraction by model role.

NOT YET IMPLEMENTED. Phase 1 milestone 1.3 — see docs/roadmap.md.

Design is settled in docs/architecture/llm-abstraction.md and
docs/architecture/adr/0006-llm-model-roles.md. When implementing, the shape is:

* ``LLMProvider`` protocol: ``chat``, ``chat_stream``, ``chat_structured``, ``embed``
* Roles — ROUTER, REASONER, GUARD, EMBEDDER, SUMMARIZER — bound to
  ``(provider, model, params)`` in config. Application code names roles, never models.
* Every provider driven through the OpenAI-compatible surface (Ollama exposes /v1),
  so there is one code path rather than a branch per vendor.
* Capability-tiered structured output with a bounded repair loop.
* Usage and cost metered on every call, including local calls at cost 0.

Two traps that must be handled, not discovered:
* local 8-9B models are materially worse at multi-step tool calling;
* embedding dimensions differ between models and are NOT interchangeable —
  mixing them degrades retrieval silently. Namespace by (tenant, embedding_model).
"""

__all__: list[str] = []
