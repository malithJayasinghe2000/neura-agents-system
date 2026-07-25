# ADR-0004 — Explicit LangGraph State Machine, Not an Agent Loop

**Status:** Accepted · **Date:** 2026-07-25

## Context

Two ways to build a tool-using agent:

1. **Agent loop** — hand the model every tool and let it iterate until it decides it is done.
2. **Explicit graph** — named nodes, defined transitions, each step doing one thing.

The loop is far less code and is what most tutorials show. But development runs on 8–9B local models ([ADR-0006](0006-llm-model-roles.md)), the agent handles other people's customers and order data, and every answer must be explainable.

## Decision

**LangGraph with an explicit node graph and a PostgreSQL checkpointer.** `guard` and `verify` are structural nodes, not prompt instructions. Tool calls per turn are capped.

## Consequences

**Good**
- **Explainable.** "Why did it say that?" is answered by a recorded state trace — required for EU AI Act traceability and for every support conversation about a bad answer.
- **Enforcement is structural.** Injection scanning and groundedness verification are steps in the flow; a model cannot be talked out of a graph edge.
- **Local models become viable.** Small models drift and loop given open-ended agency; a constrained flow with a call cap is what makes the zero-budget dev path work at all.
- **Cheaper.** Each node uses the smallest adequate model role — routing on a 3B model instead of the reasoner.
- **Resumable.** Postgres checkpoints survive restarts and deploys mid-conversation.

**Bad / accepted**
- More code, and a new graph to design per agent. Mitigated by shared nodes (`guard`, `retrieve`, `verify`, `escalate`) living in `neura-agent-core`.
- Less flexible on genuinely novel requests — the graph handles what it was designed for and escalates otherwise. For customer support, escalating is the correct behaviour anyway.
- LangGraph is a dependency with its own release cadence. Accepted; the graph concept is portable if it ever needs replacing.

## Alternatives considered

- **Plain agent loop** — fastest to write, unexplainable, unsafe with tools, unreliable on local models. Rejected on all four.
- **Hand-rolled state machine** — no dependency, but we would rebuild checkpointing, streaming and interrupts badly.
- **CrewAI / AutoGen** — role-play multi-agent framing, weaker state control and observability than we need for a production support path.
