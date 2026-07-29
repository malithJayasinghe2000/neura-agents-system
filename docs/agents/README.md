# Agents — Design Status

> ## ⛔ Read before doing anything with agents 2–5
>
> **Only NEURA-CARE is designed.** The other four have a *product* description in
> [blueprint-v2 §5](../business/blueprint-v2.md) and **no technical design at all** —
> no graph, no tools, no data requirements, no evaluation set.
>
> If asked to build, extend or scaffold SELL, MIND, GROW or GUARD:
> **say they are undesigned and propose a design session first.** Do not invent a design
> and proceed. An invented agent design will look plausible, contradict the
> blueprint's tiering, and be expensive to unwind.

---

## Status

| Agent | Folder | Product scope | Technical design | Built | Notes |
|:--|:--|:--|:--|:--|:--|
| **NEURA-CARE** | `agents/care/` | ✅ [blueprint §5.1](../business/blueprint-v2.md) | ✅ [agent-runtime.md](../architecture/agent-runtime.md) | ✅ **milestone 1.11** | 3 intents, 7 tools, read-only. `guard`/`blocked` land in 1.12 |
| **NEURA-SELL** | `agents/sell/` | ⚠️ tiers only | ❌ **none** | ❌ | Candidate for agent #2 |
| **NEURA-MIND** | `agents/mind/` | ⚠️ tiers only | ❌ **none** | ❌ | Candidate for agent #2 |
| **NEURA-GROW** | `agents/grow/` | ⚠️ tiers only | ❌ **none** | ❌ | Phase 4+ |
| **NEURA-GUARD** | `agents/guard/` | ⚠️ tiers only | ❌ **none** | ❌ | MVP portion is *platform infrastructure*, not an agent — see below |

Folder structure, manifests, entitlements and how agents are sold individually: [tenancy-and-packaging.md](../architecture/tenancy-and-packaging.md). Only `agents/care/` exists; the other four folders have not been created, because creating them would imply a design that does not exist.

**CARE is the worked example of what the five parts cost.** It supplies a graph, five nodes, seven tools, five prompt files and a golden dataset — and inherits the policy engine, audit log, checkpointer, capability filtering and ownership enforcement without writing any of them. Read `agents/care/` before designing agent #2; the shape of the work is more useful than any description of it.

---

## Why they are undesigned, deliberately

Which agent comes second should be decided by **what a real merchant asks for**, not by us guessing today ([roadmap Phase 3](../roadmap.md)). Designing all five now would produce four documents built on assumptions no customer has tested — and the single largest risk to this project is scope, not capability ([blueprint §2](../business/blueprint-v2.md)).

The seams for agent #2 already exist and are documented: shared graph nodes, the tool registry, capability negotiation, and event schemas in `neura-domain` ([agent-runtime §7](../architecture/agent-runtime.md)). What is missing is the *decision*, not the infrastructure.

---

## NEURA-GUARD is a special case

Its MVP scope is **already in Phase 1 — as platform infrastructure, not as an agent**: the prompt-injection defence, tool-authorisation policy engine, PII redaction and immutable audit log described in [security-model.md](../architecture/security-model.md).

So "build NEURA-GUARD" is ambiguous and must be clarified before acting:

- The **security infrastructure** → already specified, ships in Phase 1.
- The **sellable agent** (fake-review detection, DSAR automation, risk flags) → undesigned, Phase 4+.

Note also that GUARD was substantially re-scoped away from fraud detection. Anyone working from the archived v1 blueprint will have the wrong picture — see [blueprint §5.5](../business/blueprint-v2.md).

---

## What a design session must produce

When an agent is finally designed, it needs all seven of these before any code. Fewer is not a design.

1. **Product scope** — the MVP tier only, cut as narrowly as CARE's three intents.
2. **Graph** — nodes and transitions, reusing `guard` / `retrieve` / `verify` / `escalate`.
3. **Tools** — each with `requires` capabilities, `side_effect` class, scopes, `pii_output`.
4. **New capabilities** — anything the adapter protocol must gain, and what happens on platforms that lack it.
5. **Data requirements** — including the [cold-start ramp](../business/blueprint-v2.md#6-the-cold-start-problem) if the agent is predictive. Most of SELL and MIND are.
6. **Golden dataset** — no agent ships without one ([evaluation-strategy.md](../architecture/evaluation-strategy.md)).
7. **An ADR** recording why this agent, now, and what was excluded.

Output goes in `docs/agents/<name>.md`, and this table gets updated.
