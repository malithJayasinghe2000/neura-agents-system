# Agents — Design Status

> ## ⛔ Read before doing anything with agents 3–5
>
> **NEURA-CARE and NEURA-SELL are both designed and built** — SELL's **four** surfaces all exist
> (the fourth added 2026-09-21 by [ADR-0040](../architecture/adr/0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md))
> ([`sell.md`](sell.md), [ADR-0023](../architecture/adr/0023-sell-is-read-only-and-a-protocol-is-an-output-format.md),
> designed and built 2026-08-26). Built is not the same as shippable: SELL's release gate is
> unmet at escalation precision 0.43 (**A14**), and the table below is the current position.
>
> **MIND, GROW and GUARD have a *product* description in
> [blueprint-v2 §5](../business/blueprint-v2.md) and no technical design at all** —
> no graph, no tools, no data requirements, no evaluation set.
>
> If asked to build, extend or scaffold MIND, GROW or GUARD:
> **say they are undesigned and propose a design session first.** Do not invent a design
> and proceed. An invented agent design will look plausible, contradict the
> blueprint's tiering, and be expensive to unwind.
>
> **SELL is a different case now, and a narrower one.** It has all seven things below and is
> built — anything further stays **only within the scope its design fixes**. Agent-facing checkout and
> cart recovery are writes, are excluded by [ADR-0010](../architecture/adr/0010-read-only-mvp-tools.md),
> and building the approval queue to unblock them is a milestone rather than a step.
> **MIND was considered as agent #2 and rejected**; the reasoning is in ADR-0023 and in
> [`PROJECT_STATE.md`](../PROJECT_STATE.md), and it is recorded so it is not re-litigated.

---

## Status

| Agent | Folder | Product scope | Technical design | Built | Notes |
|:--|:--|:--|:--|:--|:--|
| **NEURA-CARE** | `agents/care/` | ✅ [blueprint §5.1](../business/blueprint-v2.md) | ✅ [agent-runtime.md](../architecture/agent-runtime.md) | ✅ **milestone 1.11** | 3 intents, 7 tools, read-only. `guard`/`blocked` land in 1.12 |
| **NEURA-SELL** | `agents/sell/` | ✅ [blueprint §5.2](../business/blueprint-v2.md) + [§4.1](../business/blueprint-v2.md) | ✅ [sell.md](sell.md) | ✅ **2026-08-26** | **Agent #2** ([ADR-0023](../architecture/adr/0023-sell-is-read-only-and-a-protocol-is-an-output-format.md)). 2 intents, 5 tools, 3 surfaces, read-only. Feed + MCP + graph all built. **10/14 golden, escalation precision unmet (A14)** |
| **NEURA-MIND** | `agents/mind/` | ⚠️ tiers only | ❌ **none** | ❌ | **Considered as agent #2 and rejected** — needs an adapter-protocol change SELL does not |
| **NEURA-GROW** | `agents/grow/` | ⚠️ tiers, and its first surface | ✅ **first surface** [grow.md](grow.md), [ADR-0064](../architecture/adr/0064-grow-shows-what-shoppers-asked-that-the-shop-s-pages-do-not-say.md) | ❌ | First surface designed and accepted 2026-10-20 (*Missing from your pages*, R42), **built 2026-10-27** (ADR-0066); a second, *Shoppers asked for*, designed and **built 2026-10-28** (ADR-0068, ADR-0069); a third, the *Marketing calendar*, designed and **built 2026-11-01** (ADR-0072, ADR-0073); the rest of v1 (AEO/GEO) undesigned |
| **NEURA-GUARD** | `agents/guard/` | ⚠️ tiers only | ❌ **none** | ❌ | MVP portion is *platform infrastructure*, not an agent — see below |

Folder structure, manifests, entitlements and how agents are sold individually: [tenancy-and-packaging.md](../architecture/tenancy-and-packaging.md). Only `agents/care/` exists. `agents/sell/` is now permitted and has simply not been created yet; `mind/`, `grow/` and `guard/` are not, because creating them would imply a design that does not exist.

**SELL is designed against CARE, and the design says where it departs and why.** It supplies
seven nodes, five tools and two intents — and **three of its four** surfaces have no graph at all,
which is stated plainly in [`sell.md §1.1`](sell.md) rather than smoothed over.

**CARE is the worked example of what the five parts cost.** It supplies a graph, five nodes, seven tools, five prompt files and a golden dataset — and inherits the policy engine, audit log, checkpointer, capability filtering and ownership enforcement without writing any of them. Read `agents/care/` before designing agent #2; the shape of the work is more useful than any description of it.

---

## Why they are undesigned, deliberately

Which agent comes second should be decided by **what a real merchant asks for**, not by us guessing today ([roadmap Phase 3](../roadmap.md)). Designing all five now would produce four documents built on assumptions no customer has tested — and the single largest risk to this project is scope, not capability ([blueprint §2](../business/blueprint-v2.md)).

**That condition was not met when SELL was designed, and the design says so rather than pretending otherwise.** There is still no design partner (**B2**), so the choice was made on the only evidence available: what the codebase supports today without asking anything of a merchant. SELL's read-only half needs no adapter change at all; MIND's headline question needs one on every merchant's bridge. That asymmetry decided it, not a product opinion — and [ADR-0023](../architecture/adr/0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) records it as a decision to revisit **the moment a real merchant can be asked**. The remaining three stay undesigned for exactly the reason above.

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
5. **Data requirements** — including the [cold-start ramp](../business/blueprint-v2.md#6-the-cold-start-problem) if the agent is predictive. Most of SELL and MIND are — but **SELL's designed cut deliberately is not**, and [`sell.md §5.3`](sell.md) argues that excluding everything predictive is precisely what made it buildable before a design partner exists.
6. **Golden dataset** — no agent ships without one ([evaluation-strategy.md](../architecture/evaluation-strategy.md)).
7. **An ADR** recording why this agent, now, and what was excluded.

Output goes in `docs/agents/<name>.md`, and this table gets updated.

[`sell.md`](sell.md) is the first document written to this list, and is the worked example of it.
Two of its sections are not on the list and should be: **§11** registers the open questions the
design refused to settle alone, and **§12** states what it deliberately did not decide. A design
that names neither is a design that decided them silently.
