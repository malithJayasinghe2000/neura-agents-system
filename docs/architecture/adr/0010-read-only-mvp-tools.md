# ADR-0010 — READ-Only Tools in the MVP

**Status:** Accepted · **Date:** 2026-07-25

## Context

NEURA-CARE could plausibly cancel orders, change shipping addresses, issue refunds and apply discount codes. The original blueprint assumed autonomous action throughout — *"SELL blocks the transaction"* — with no approval gate, audit trail or rollback path described.

Meanwhile the agent will be exposed to anonymous shoppers who can type anything, and prompt injection must be assumed to succeed ([security-model.md §2.1](../security-model.md)).

## Decision

The MVP registers **`READ` tools only**. Every tool declares a side-effect class, and only `READ` is enabled:

| Class | MVP | Gate when enabled |
|:--|:--|:--|
| `READ` | ✅ | capability + scope + ownership verification |
| `WRITE` | ❌ Phase 2 | + human approval before execution |
| `IRREVERSIBLE` | ❌ Phase 3 | + explicit per-action merchant approval |

Correspondingly, the [Generic Commerce Interface](0009-generic-commerce-interface.md) v1 defines read endpoints only.

## Consequences

**Good**
- **The agent physically cannot damage a store or a customer relationship.** A fully successful prompt injection achieves nothing, because the tool it would need was never registered.
- This is what makes an early pilot on live traffic defensible, and makes shadow mode genuinely zero-risk.
- It matches where the value actually is: order status, product questions and policy questions dominate real ticket volume and none of them require a write.
- A merchant's real objection to AI support is "what if it does something stupid to my orders." "It has no ability to change anything" ends that conversation.
- The Tier-2 spec stays small enough to implement in an afternoon, which is the adoption argument.

**Bad / accepted**
- Some conversations that could have been fully resolved will escalate — an address change becomes a handoff. Accepted: escalation is a correct outcome, and deflection is measured honestly with those excluded.
- Deflection rate will be lower than it eventually becomes. Better to publish a real lower number than an unsafe higher one.
- The approval-queue infrastructure is designed now but not built, so Phase 2 carries that cost.

## Alternatives considered

- **Writes with LLM-judged confidence thresholds** — a confidence score is a model output, and model outputs are exactly what an injection controls. Using one as an authorisation control is circular.
- **Writes behind approval from day one** — safe, but it requires the approval queue, the merchant console and the notification path before anything ships. Too much for an MVP.
- **Writes on a per-tenant opt-in** — pushes a security decision onto a merchant who has no basis to make it. Wrong default.

## Revisit when

Shadow-mode and pilot data show which write actions are actually requested and how often, and the approval queue with its audit trail is built and tested.
