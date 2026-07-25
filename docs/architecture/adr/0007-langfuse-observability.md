# ADR-0007 — Langfuse + OpenTelemetry, Not LangSmith

**Status:** Accepted · **Date:** 2026-07-25

## Context

Agent behaviour is unobservable without LLM-specific tracing: prompts, completions, token counts, cost, latency, and tool decisions per conversation. Both the original blueprint and `implementation_plan_1` specified LangSmith.

Two constraints push against that: development runs entirely on local Ollama models with no budget, and the **sovereign** tier must run with no third-party data egress at all.

## Decision

**OpenTelemetry** for general distributed tracing (HTTP → graph node → tool → LLM), and **Langfuse, self-hosted**, for LLM-specific observability.

## Consequences

**Good**
- Free and self-hostable — works on day one with zero budget.
- **Compatible with the sovereign tier**, where no trace containing customer data may leave the customer's boundary. A hosted-only tracer would rule that product tier out entirely.
- Works well with local models; it is not built around a single cloud provider's API shape.
- OpenTelemetry is vendor-neutral, so the backend (Jaeger, Grafana, a cloud APM) stays a deployment choice.
- One `trace_id` spans HTTP request, agent node, tool call and LLM call — and it is the same `request_id` returned to API clients ([api-design.md §3](../api-design.md)), so a customer complaint maps directly to a trace.

**Bad / accepted**
- Self-hosting is one more service to run. Optional in development; a real operational task in production.
- Langfuse's evaluation and dataset tooling is less mature than LangSmith's. Accepted because our eval harness is deliberately our own ([evaluation-strategy.md](../evaluation-strategy.md)) rather than delegated to a vendor.
- Traces contain prompts, which contain customer text, so **PII redaction must happen before traces are stored**, and trace retention (30 days) is part of the deletion fan-out ([security-model.md §6.2](../security-model.md)).

## Alternatives considered

- **LangSmith** (originally planned) — best-in-class LangGraph integration, but hosted-only in practice, priced per trace, and incompatible with the sovereign tier.
- **OpenTelemetry alone** — no LLM-specific views: no prompt/completion inspection, no cost per conversation, no side-by-side run comparison. Not enough for debugging agent behaviour.
- **Custom logging only** — cheapest, and it becomes a bad tracing product within a month.
