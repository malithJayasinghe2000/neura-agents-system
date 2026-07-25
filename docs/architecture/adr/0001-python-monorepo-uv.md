# ADR-0001 — Python 3.12 + `uv` Workspace Monorepo

**Status:** Accepted · **Date:** 2026-07-25

## Context

The platform is a Python AI system with several logical components (domain, LLM, commerce, agents, adapters, API) that must stay separable as it grows to five agents and many adapters. It is built by one developer, part of whose goal is to learn industry-standard practice.

Python 3.14.6 is installed on the build machine. `uv` is not installed.

## Decision

A single repository, structured as a **`uv` workspace** with real package boundaries under `packages/` and a deployable under `apps/`. **Python pinned to 3.12.**

Layering is enforced mechanically by an `import-linter` contract in CI, not by convention.

## Consequences

**Good**
- One clone, one lockfile, atomic cross-package changes.
- Boundaries are explicit and enforced, so extracting a service later is a deployment change rather than a redesign.
- `uv` is substantially faster than pip/poetry and has native workspace support.
- mypy strict on `packages/` makes the boundaries verifiable rather than aspirational.

**Bad / accepted**
- `uv` must be installed as a setup step.
- **Python 3.12, not the installed 3.14.** Several ML and agent libraries still lack 3.14 wheels; discovering that mid-build would be an avoidable stall. `uv` manages the interpreter, so the system Python is untouched.
- A monorepo needs discipline: without the CI layering check, boundaries erode within weeks.

## Alternatives considered

- **Multiple repos** — real isolation, but cross-cutting changes become multi-PR chores. Wrong for one developer at this stage.
- **Flat single package** — simplest, but there is then nothing to stop the agent runtime importing an adapter, which destroys the platform-independence claim that is the product.
- **Poetry** — mature, but slower and its workspace story is weaker.
