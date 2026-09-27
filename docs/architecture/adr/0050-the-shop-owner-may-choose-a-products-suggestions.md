# ADR-0050 — The Shop Owner May Choose A Product's Suggestions, And Their Choice Wins

**Status:** **Accepted** — owner decision, 2026-09-27 · **Date:** 2026-09-27 · **Amends:** [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md) §3 (a second heading) and §4 (the category rule does not bind an owner's choice); [ADR-0045](0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md) (a computed pairing yields to an owner's) · **Related:** [ADR-0010](0010-read-only-mvp-tools.md), [ADR-0026](0026-the-merchant-console-and-the-first-human-in-the-system.md)

> **This is also the answer to "upsell".** The next step on the plan was an ADR for suggesting a
> better version of the same product, which ADR-0040 §4's category rule forbids. The owner chose not
> to have the system decide what "better" means: **the shop owner decides, per product.**

## Context

A paired suggestion is the same for every shopper: one list per product, chosen from the merchant's
own words or computed once by a model (ADR-0045). **The owner cannot see it and cannot correct it.**
The hand-graded pass on 2026-09-26 found suggestions that were plainly worse than the owner would
have picked — and a wrong suggestion on a basket page costs the merchant trust in the whole product.

Separately, ADR-0040 §4 refuses a product from the anchor's own category, which is right for an
automatic pairing — a boot beside a boot is a mistake — and is exactly what makes upsell impossible.

The owner's proposal, 2026-09-27: **show the suggestions in the dashboard, and let the owner change
them.**

## Decision

> **For any product, the shop owner may choose the list of products suggested with it, or reset it
> to automatic. Their choice wins over the model and over the words, and it is the same for every
> shopper.**

### 1. The three rules the owner approved

1. **The owner's choice always wins.** No model computation and no word search replaces it.
2. **Same for every shopper.** Nothing about a shopper's behaviour enters; ADR-0040 §3's
   prohibition on behavioural ranking is untouched.
3. **It changes only our suggestions.** Nothing is written to the shop — no product, price or stock
   ([ADR-0010](0010-read-only-mvp-tools.md) untouched).

### 2. What a choice is

An ordered list of **up to four** product ids from the merchant's own synced catalogue — or an
**empty** list, which means *show nothing for this product*. Resetting deletes the choice and the
automatic path answers again. Who chose and when are recorded, because *"why was I shown this?"*
now has a person as its answer.

### 3. What still applies to an owner's choice, and what does not

| rule | automatic | owner's choice |
|:--|:--:|:--:|
| buyable **right now** — active and in stock, checked live | ✅ | ✅ |
| never a product already on the page | ✅ | ✅ |
| at most two shown ([ADR-0040 §6](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)) | ✅ | ✅ — the first two buyable, in the owner's order |
| **not from the anchor's own category** (§4) | ✅ | ❌ — **this is how upsell happens**, and it is the owner's call |

### 4. When the choice cannot be honoured, nothing is shown

If every product the owner chose is unbuyable, **the block is empty** — it does not fall back to the
automatic path, which could bring back the very product the owner removed. The same when the choice
cannot be read (a database error): empty, not automatic. An empty block costs a shopper nothing
(ADR-0040 §4); contradicting the owner costs the merchant's trust.

### 5. A second heading, still written by the server

`"Goes well with your {product}"` is wrong over an alternative — a cashmere jumper does not *go
with* a cotton one. An owner-chosen block says **`"Recommended with your {product}"`**: true,
because the shop recommended it. Still built in code, never by the page or a model, and still none
of ADR-0040 §3's forbidden claims (*often bought together*, *customers also bought*, *trending*).

### 6. Who may do it

A person with console access to the shop, through the same session and membership check as every
other console screen, **and only for a shop that has SELL enabled**. The screen is served by SELL's
own routes, so the entitlement check stays inside the agent and `neura-api` still never learns an
agent's name.

## Consequences

**The console gains a seventh screen**, *Suggestions*. [console.md §2](../../console.md)'s
*"the discipline is five"* is broken a third time, deliberately.

**Rule 4 and evals.** No prompt, model or tool changes; the request path gains one deterministic
branch, covered by unit tests and a real-shop run. `pairing.yaml`'s cases are unaffected: they run
products with no owner choice.

**A choice can go stale.** A chosen product that is withdrawn or sold out is simply not shown, and
the screen says which chosen products it cannot find in the catalogue.

**Reversible.** Delete the table and the branch; every product returns to automatic.

## What this ADR does NOT decide

* **Per-shopper suggestions** — still excluded. Choosing by what a shopper viewed is a privacy
  decision of its own ([ADR-0044 §8](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)).
* **Suggestions inside the chat.** This changes the basket block only.
* **Bulk editing, rules by category, or scheduled choices.** One product at a time.
