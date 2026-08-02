# ADR-0015 — Usage Is a Daily Rollup, and a Budget Degrades Rather Than Errors

**Status:** Accepted · **Date:** 2026-08-02

## Context

[security-model.md §7](../security-model.md) lists eight cost controls and ends with the sentence this ADR is mostly about: *"Every limit degrades to escalate-only rather than erroring. An attacker gets a human handoff; a legitimate customer never sees a wall."* [llm-abstraction.md §6](../llm-abstraction.md) sets the same ladder for tenant spend: soft ceiling → degrade, hard ceiling → escalate-only.

None of it was implemented. `ConversationBudget` caps tool calls within one turn, and that is the whole of it — there was no record of what a tenant had consumed, so there was nothing for a daily ceiling to be measured against, and `BudgetExceededError` had been declared since milestone 1.2 without ever being raised.

Two questions: what shape does the usage record take, and what does a budget *do* when it bites.

## Decision

### 1. A rollup row per `(tenant, day, agent)`, incremented in SQL

```sql
INSERT INTO tenant_usage (…) VALUES (…)
ON CONFLICT (tenant_id, usage_date, agent_key)
DO UPDATE SET turns = tenant_usage.turns + excluded.turns, …
```

PostgreSQL performs that atomically, so two turns finishing in the same millisecond cannot lose a count and no application-level lock has to be remembered. An integration test runs twenty concurrent turns and asserts twenty.

**Not an append-only event log aggregated on read.** That is what a billing system eventually wants, and it is more than this needs: there is no design partner, no invoice, and no query that wants per-turn granularity. The rollup is what every current reader wants anyway, and adding an event stream later is strictly easier than keeping a rollup correct — the events can be written alongside and the rollup rebuilt from them.

**Days are UTC.** A billing boundary that moves with a merchant's timezone is a boundary two systems will eventually disagree about, in front of a customer holding an invoice.

**`agent_key` is part of the key**, because "billed for CARE only" ([tenancy-and-packaging.md §3](../tenancy-and-packaging.md)) is only true if the rows say which agent. It is never an agent name known to `neura-core`; it arrives from whatever agent ran.

`cost_usd` is `NUMERIC(14,6)`, never a float. Per-token pricing makes one call cost fractions of a cent, and rounding those to zero is how a cost model quietly reports that inference is free.

### 2. The ladder is expressed as ceilings, not as an error

| Spend today | Admission | What actually changes |
|:--|:--|:--|
| below soft | `NORMAL` | nothing |
| soft → hard | `DEGRADED` | tool-call ceiling drops to the tenant's `degraded_max_tool_calls` (default 2) |
| at or above hard | `ESCALATE_ONLY` | tool allowlist is **empty**; no tool is permitted |

`resolve_runtime_policy()` returns those two values, and `RuntimePolicy.runtime_kwargs()` hands them to `build_runtime` as the parameters it already accepts.

**Escalate-only needs no new code in the agent, and that is the point.** An empty allowlist is check 4 of the policy engine — the same mechanism a merchant uses to disable one tool, taken to its limit. Every proposed call is rejected, no tool is offered to the model, and CARE does what it already does when it cannot act: it hands over to a person. A dedicated "budget exhausted" branch in the graph would be a second path to write, a second path to get wrong, and a behaviour change that the golden suite would have to be re-run to trust.

A misconfiguration with the hard ceiling below the soft one resolves to the **safer** rung. Both are mistakes; spending money is the worse way to resolve one.

### 3. Nothing enforced here changes behaviour for an unconfigured tenant

A tenant with no `config` gets the platform defaults, and a caller that passes no policy gets exactly the runtime it got before this milestone. That is deliberate and it is what makes 1.13 landable without re-measuring the agent: no prompt, node, tool or model configuration changed, so the golden-suite numbers cannot move.

## Consequences

**Good**

- Cost per tenant per day per agent is now a measurable thing rather than an unknown. Open question B7 (unit economics — "do not publish prices until all four are known") has one of its four inputs available for the first time, once the recording call is wired.
- The cheapest possible response to a cost-denial attack: the attacker gets a handover, and the ceiling that stopped them is a number in a row rather than a deploy.
- `make tenant-usage TENANT=…` reads it, so the rows are not written into a void.
- The atomic increment is proven against real PostgreSQL rather than assumed.

**Bad / accepted**

- **Nothing calls `UsageMeter.record` yet.** The recording point is the request path, and the request path is milestone 1.14. This is the same shape as open question S5 — an event written by nothing is a seam, not a control — and it is recorded as **open question P5** rather than left as an intention, because "we will wire it when we have the API" is how a dependency gets discovered on the day it blocks. Until then the ladder is testable and untriggered: `spend_today` is always zero, so every tenant is `NORMAL`.
- **`DEGRADED` is a thin rung.** Lowering the tool ceiling is real but modest; the more valuable degradation — switching to a cheaper role map — belongs to whoever constructs the LLM client, which is again 1.14. Stated rather than implied, because a rung that does almost nothing while appearing to do something is worse than one that is honestly named.
- **A rollup cannot answer "which conversation cost the most?"** Accepted. The audit log holds per-call records, and that is where a forensic answer comes from.
- **The daily boundary is a cliff.** A tenant that exhausts its budget at 09:00 is escalate-only until midnight UTC. A rolling window would be gentler and is harder to explain on an invoice; revisit with a design partner who has an opinion.

## Alternatives considered

- **Per-turn usage events, aggregated on read.** Rejected for now, above. It is the migration path, not the starting point.
- **Redis counters for the hot path, flushed to Postgres.** Rejected: it introduces a way for usage to be lost on a restart, in exchange for a write that PostgreSQL handles trivially at this scale, and it puts billing numbers in a store we treat as a cache.
- **`BudgetExceededError` at the boundary — a 429 with a clear message.** Rejected, and this is the decision the section header names: it makes the merchant's *shopper* pay for the merchant's budget with a visible failure. `BudgetExceededError` remains in the hierarchy for callers that genuinely have no conversation to degrade — a bulk sync or a reindex — where failing is the correct outcome.
- **Counting tokens instead of dollars.** Rejected: local inference is free and cloud inference is not, the role map decides which is which, and a merchant's ceiling is naturally denominated in money. Tokens are recorded too, so a token-denominated limit remains possible.
