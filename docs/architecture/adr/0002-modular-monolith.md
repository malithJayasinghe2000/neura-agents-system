# ADR-0002 — Modular Monolith, Single Deployable

**Status:** Accepted · **Date:** 2026-07-25

## Context

`implementation_plan_1` proposed separate deployable services: an `api-gateway` and an `agent-care` service, communicating over the network, with an event bus between agents.

The system currently has zero users, one agent, and one part-time developer.

## Decision

**One deployable process** (`neura-api`, FastAPI) plus **one worker process** (`neura-worker`, for sync and webhook delivery). The package boundaries of [ADR-0001](0001-python-monorepo-uv.md) are preserved and enforced, but nothing crosses a network hop internally.

## Consequences

**Good**
- No inter-service serialization, no partial-failure handling, no distributed-transaction reasoning, no second deployment pipeline — none of which buy anything at this scale.
- A single stack trace covers a whole request. Debugging an agent is hard enough without a network boundary in the middle of it.
- One `docker compose up` is the entire development environment.
- Because the package seams already exist and are CI-enforced, extracting `neura-worker` — or later an agent service — is a change to entrypoints and configuration, not a redesign.

**Bad / accepted**
- Components cannot be scaled independently. Accepted: we have no scaling problem, and CPU-bound inference is external.
- A crash takes down API and agent together. Mitigated by process supervision and the escalate-only degradation path.
- There is a real risk of the boundaries rotting into a big ball of mud. This is precisely why the `import-linter` contract and the "no platform names outside adapters" grep are **blocking CI checks** rather than guidelines.

## Alternatives considered

- **Microservices from day one** (as originally planned) — all of the operational cost, none of the benefit, at zero traffic. The most common way a solo-built platform never ships.
- **Serverless functions** — cold starts are poor for LLM request patterns, and LangGraph's stateful checkpointing fits a long-lived process better.

## Revisit when

Any of: sustained CPU contention between request handling and sync; agent #3 shipping with genuinely different scaling characteristics; or a customer requiring an isolated single-tenant deployment topology.
