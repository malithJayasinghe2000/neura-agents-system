# ADR-0049 — A Product View Records Whether The Product Could Be Bought At That Moment

**Status:** **Accepted** — owner decision, 2026-09-27 · **Date:** 2026-09-27 · **Amends:** [ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md) §4 and [ADR-0048](0048-observation-phase-1-what-the-build-decided.md) §3 — one field added to what is stored · **Needed by:** [ADR-0046](0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md) stage 1

> **One field, and it is about the product, not the shopper.** Everything else in 0044 §4 and 0048 §3
> stands: no IP, no user agent, no customer, no search text.

## Context

ADR-0046 stage 1 counts **views of a product that could not be bought when it was viewed**. Phase 1's
events cannot answer *"when it was viewed"* — 0044 §4 fixed the fields, and stock is not one of them.

The owner was shown the case that decides it:

| day | what happens |
|:--|:--|
| Monday | the jumper is sold out; 10 people open its page |
| Friday | it is restocked |
| Saturday | the owner opens the sold-out list |

**Checking stock on Saturday** says nobody wanted it while it was sold out — the product is in stock
*now*. That is wrong exactly for the products the list exists for: the ones people wanted enough that
the merchant restocked them. **Recording it on Monday**, with each view, says 10.

## Decision

> **A `product.viewed` event carries `in_stock`: whether the product could be bought at the moment the
> page was viewed.**

1. **The same word, the same meaning.** `in_stock` is already the canonical model's term
   (`ProductVariant.in_stock`), and the bridge computes both from one function. For a product, **in
   stock means at least one variant is** — a jumper sold out in medium and available in large is not
   sold out.
2. **Required on `product.viewed`, refused on `cart.added`.** A view without it cannot be counted
   either way, so it is a 400 rather than a guess. A basket add is in stock by definition, so the field
   there could only be contradictory.
3. **Worked out by the shop's server, at the moment of the view** — including when the page comes out
   of the full-page cache ([ADR-0048](0048-observation-phase-1-what-the-build-decided.md) §6), where the
   cached page shows the stock of whenever it was rendered and not of now.
4. **It is not personal data and changes nothing about retention.** It is a fact about the merchant's
   product that happens to be recorded beside a view. The row is still deleted after seven days.

## Consequences

**ADR-0046 stage 1 becomes a count with no lookup:** views where `in_stock` is false, per product, in
the window. No call to the shop at count time, and no answer that changes because stock moved since.

**Events stored before this field existed have no value** and are treated as *unknown*, never as
sold out. There are none today — phase 1's six test events were deleted on 2026-09-26.

**A cost on cache hits.** A page served from the cache no longer costs the shop nothing: the bridge
reads the product's stock once per view. One indexed query, after the page is sent.

## What this ADR does NOT decide

* It does not build the sold-out screen. That is ADR-0046 stage 1.
* It does not record *how many* were in stock, a price, or anything else about the product. Sold out or
  not is the whole question 0046 asks.
