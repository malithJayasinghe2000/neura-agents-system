# ADR-0045 — A Pairing May Be Computed By A Model, But Never While A Shopper Waits

**Status:** **Accepted** — owner decision, 2026-09-25 · **not built** · **Date:** 2026-09-25 · **Amends:** [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md) §5 · **Related:** [ADR-0010](0010-read-only-mvp-tools.md), [ADR-0011](0011-deterministic-guard-not-classifier.md), [ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md), [ADR-0029](0029-the-index-may-name-a-candidate-never-describe-one.md)

> **This puts a model into the one surface whose title says it has none.** ADR-0040 §5 is amended, not
> superseded: **§3's ban on behavioural claims, §4's category rule and empty-is-a-result, and §6's
> parameters all stand unchanged.** What changes is *when* a model may run — never between a shopper
> and an answer.
>
> **Nothing here is built.** The model has never been called, the cache does not exist, and §7's new
> risk is a risk this surface does not currently carry.

## Context

**Term selection was fixed on 2026-09-24 and the result was small: 18 of 29 products produce a
suggestion, up from 18 — one net product.** Measuring it also showed the remaining misses are not
word-selection failures. They are the honest limit of matching words at all:

* **`1330` Leather Loafer** — `leather` now finds the Chelsea Boot, and §4 correctly drops it: both sit
  in category 36. Nothing is shown, and nothing *should* be. But a loafer genuinely pairs with socks,
  a belt, or shoe care, and **no word in its description says so.**
* **`1320` Cashmere Crew Jumper** — `cashmere` matches one product: itself.

**Word matching finds products that are described alike. A pairing needs products that go together.**
Those are different relations, and no amount of better term selection closes the gap — the Rain Shell
and the Hiking Shoe paired because both descriptions happened to contain *waterproof*, which ADR-0040
§4 already called luck.

**Three ways out were considered:**

| approach | verdict |
|:--|:--|
| **Purchase history** — "bought together" | The industry standard, and unavailable: `ORDER` has no rows, [ADR-0040 §3](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md) bans behavioural ranking, and **a new shop has zero orders on day one** |
| **Embeddings** — nearest neighbour in meaning | Available (pgvector, an embedder). **Wrong relation**: a rain shell's nearest neighbour is another rain shell, which §4 then excludes. Similarity is the thing we already have too much of |
| **The merchant sets pairs by hand** | Works, and pushes the work onto the person the product is supposed to save work for |

**A model knows that a loafer goes with socks.** That is ordinary world knowledge, it needs no history,
and it works on a shop's first day — which is the property that made this surface shippable.

**The objection ADR-0040 §5 raised is still correct**, and it is about *when*: the cart page loads for
every visitor, so a model call per page view is slow and is billed per view. **That objection does not
apply to a model call that happens once and is kept.**

**And the owner sharpened it further, which is what this ADR actually records.** Computing every
product's pairing at sync time wastes most of the work: a 10,000-product catalogue would spend 10,000
calls, and most of those products are never added to a cart at all. **Compute on first use instead.**

## Decision

> **A model may compute a product's pairing — once, on the first request that needs it, in the
> background — and the result is stored and reused. No shopper ever waits for a model on this surface,
> and no request triggers more than one computation.**

### 1. What ADR-0040 §5 becomes

**Was:** *no model runs in it.*

**Now:** **no model runs between a shopper and an answer.** Every other property §5 was defending is
kept by §§4–7 below.

### 2. Lazy, not eager — and the reason is the owner's

```
request for product P
   │
   ├── a stored pairing exists?  → use it. No model, no search.
   │
   └── none?                     → answer NOW from the existing word path
                                   (or with nothing, which §4 already permits)
                                 → queue a background computation for P
                                 → the next request for P gets the good answer
```

**Nothing is precomputed at sync.** A catalogue of 10,000 products where 200 are ever added to a cart
costs **200 computations, not 10,000** — and the 200 are exactly the products that matter, because
popularity is what puts a product in a cart in the first place. The cache warms itself in the right
order with no ranking logic anywhere.

**The first shopper is never punished.** They get today's word-matched answer, which is the current
product and not a regression. **A slow path that a shopper waits on is not permitted at all**, not
even once.

### 3. What the model is asked, and what it may return

**It is asked what *kinds* of product go with this one** — "waterproof footwear", "wool socks" — and
nothing else. **It is never given the catalogue to choose from and never asked to name a product.**

The kinds are then searched in the merchant's own catalogue by the existing `search_products` path, and
**only ids that come back from that search are ever stored.** A model that hallucinates *"Dry Bag Pro
2000"* produces a search that finds nothing, which is an empty result — the outcome ADR-0040 §4 already
treats as correct.

**This is [ADR-0029](0029-the-index-may-name-a-candidate-never-describe-one.md)'s rule applied one
layer earlier**: the model may suggest what to look for; only the store may say what exists.

### 4. Everything ADR-0040 decided about *what a shopper sees* is untouched

* **The heading is still built server-side** by `select.heading_for`, still verbatim, and **the model
  never writes a word that reaches a shopper.** §3's ban on "often bought together" / "customers also
  bought" / "trending" is still enforced by code rather than by a prompt.
* **The anchor's own category is still excluded** (§4), applied to the model's candidates exactly as to
  the word path's.
* **An uncategorised product still returns nothing.**
* **Stock and status are still checked live**, on every request, against the stored ids — a product
  that sold out yesterday is not suggested today. **The cache holds a pairing, never an availability.**
* **Empty is still a result.** No model failure, timeout or refusal turns into an error on a cart page.

### 5. Invalidation

A stored pairing is discarded when the product's own text changes — the sync engine already
content-hashes renderings for exactly this reason — and when the pairing's target is no longer
returned by the catalogue at all. **A stale pairing is a wrong suggestion with a long life**, which is
worse than no cache.

### 6. Rule 4 now applies to this surface, and that is the largest cost in this ADR

`test_sell_pairing.py` records that its cases are **tests, not evals**, because there is no model here
that can regress — and [E8](../../open-questions.md) registers that reasoning. **This ADR ends that.**

A model choosing what a shopper is shown is a behaviour, and
[Rule 4](../../../AGENTS.md) applies without exception: eval cases for the pairing prompt, and
**injection resistance stays at 1.00**. Building this without them is not permitted, and the eval is
not an afterthought to the feature — it is most of it.

### 7. A new risk this surface has never carried: indirect injection

**ADR-0040's safety argument was that there is no model to persuade.** That argument is now gone, and
the input is merchant catalogue text — which [the glossary](../../glossary.md) classifies as
**untrusted content**, precisely because a product description can be written by anyone with a
merchant admin login.

**What bounds the damage, structurally rather than by prompt:**

1. The model's output is **kinds, not products** — it cannot name anything the store does not return.
2. It has **no tools**, no retrieval and no write. It reads one product's text and returns a short list.
3. **Nothing it produces reaches a shopper as words.** Every visible string is either the merchant's
   own product data or `heading_for`'s server-built sentence.
4. It runs **in the background**, so a slow or hostile input delays nothing a shopper is waiting for.

**The worst case is therefore a bad suggestion, not a fabricated claim, a leaked tool call or a lost
turn.** That is a real degradation and an eval case, not a security incident — and saying so honestly
is only defensible because points 1–4 are code.

### 8. The parameters, and they are guesses

| parameter | value | why it is a guess |
|:--|:--|:--|
| how long a pairing is kept | **until the product text changes** | plausible; no shop has been observed |
| kinds requested per product | **3** | matches `MAX_TERMS`, for no measured reason |
| model role | **`REASONER`** | the only role with the world knowledge this needs; not measured against `ROUTER` |

**None is tuned.** The same standing rule applies as to ADR-0040 §6: do not repeat these as measured.

### 9. The falsification test

**Measure coverage against the word path on the same real catalogue, before and after.** The word path
produces 19 of 29. **If the model path does not beat that by a margin worth the eval suite it drags
behind it, delete it and keep the words** — the words cost nothing, cannot be injected, and need no
eval.

## Consequences

**The title of ADR-0040 stops being literally true**, and that is worth the discomfort it should cause.
SELL now has **three** surfaces with no model of ours and one with a model that runs off the request
path. Anyone quoting *"no model in it"* about pairing after this ships is quoting a claim the product
no longer supports.

**The cheapest surface in the product becomes one of the more expensive ones to maintain**: a prompt,
a cache, an invalidation path, an eval suite, and a provider dependency on a surface that currently
has none. A provider outage must remain invisible — §4's empty-is-a-result is what makes that true.

**What it buys**: pairings for products whose descriptions do not happen to share a word — the Leather
Loafer, the Cashmere Jumper, and the ten others — and it buys them on a shop's first day, with no
orders and no tracking.

**Reversible.** Drop the table, delete the prompt, and the word path is still there underneath. That is
the main argument for building it this way rather than replacing `select.py`.

## What this ADR does NOT decide

* **It does not allow a model call on the request path**, not even once, not even for the first shopper.
* **It does not replace term selection.** `pairing_terms` stays as the day-one path and as the
  fallback; this adds a layer above it.
* **It does not authorise purchase-history ranking.** [ADR-0040 §3](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)
  stands, `ORDER` sync stays off, and "customers also bought" remains a claim this system may not make.
* **It does not let the model write anything a shopper reads.** Headings stay in `heading_for`.
* **It does not pick a model or a role map.** §8's `REASONER` is a starting point, decided by eval at
  build time like every other role choice ([ADR-0006](0006-llm-model-roles.md)).
* **It does not set the eval's cases or its thresholds.** Those are written with the feature, and
  injection resistance is the one that blocks.
