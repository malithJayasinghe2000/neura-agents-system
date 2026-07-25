# ADR-0006 — LLM Abstraction by Model Role

**Status:** Accepted · **Date:** 2026-07-25

## Context

There is no budget for LLM APIs during development, so development runs on local Ollama models. Production needs cloud-model quality. Additionally, a **sovereign** deployment tier runs entirely on customer hardware ([blueprint-v2 §4.3](../../business/blueprint-v2.md)) — so the local path is a shipping product, not throwaway scaffolding.

Three deployment modes must therefore share one codebase, and the differences between them are large: an 8B local model is materially worse at tool calling and strict JSON than a frontier model.

## Decision

Application code requests a **role** — `ROUTER`, `REASONER`, `GUARD`, `EMBEDDER`, `SUMMARIZER` — never a model name. Roles map to `(provider, model, params)` in configuration.

All providers are driven through the **OpenAI-compatible API surface**, which Ollama also exposes, so there is one code path. Providers declare capabilities (`NATIVE_TOOL_CALLING`, `JSON_SCHEMA_MODE`, …) and the runtime adapts rather than assuming.

**Every swap is gated on an eval comparison** ([ADR-0011 / evaluation-strategy](../evaluation-strategy.md)).

## Consequences

**Good**
- Dev → prod is a configuration change, and the quality delta is measured rather than hoped for.
- **Hybrid maps fall out for free**: keep routing and embedding local (high volume, cheap, privacy-sensitive), send only `REASONER` to a cloud API. Likely the best production cost/quality point.
- Cost optimisation becomes per-role, not all-or-nothing.
- No vendor lock-in — provider choice stays deferrable and reversible.
- Local calls still record tokens and latency (at `cost_usd = 0`), so a workload's cloud cost can be modelled *before* switching.

**Bad / accepted**
- An abstraction over provider APIs will occasionally hide a provider-specific feature. Accepted: portability matters more here than any single feature.
- Capability tiers add branching in `chat_structured()` — three fallback tiers rather than one call.
- **The embedding-dimension trap is now on our critical path.** 768-dim local vs 1536/3072-dim cloud embeddings are not interchangeable, and mixing them degrades retrieval *silently*. This forces namespaced vector collections and a documented reindex procedure ([llm-abstraction.md §5](../llm-abstraction.md)) — real complexity, accepted because the alternative is a silent production failure.

## Alternatives considered

- **Hard-code one provider** — simplest, and it forfeits both the zero-cost dev path and the sovereign tier. The sovereign tier alone rules it out.
- **LiteLLM proxy** — genuinely good, and would supply much of this. Rejected for now: it adds a service to deploy ([ADR-0002](0002-modular-monolith.md)), and the abstraction we need is thin enough to own. Reconsider if provider count grows past three.
- **LangChain's model wrappers** — available via LangGraph, but too leaky for capability-tiered structured output and per-call cost metering.
