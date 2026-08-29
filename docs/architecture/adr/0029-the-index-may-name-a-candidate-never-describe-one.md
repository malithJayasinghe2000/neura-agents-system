# ADR-0029 — The Index May Name A Candidate, Never Describe One

**Status:** Accepted · **Date:** 2026-08-28 · **Builds on:** [ADR-0009](0009-generic-commerce-interface.md), [ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md), [ADR-0028](0028-only-the-catalogue-may-say-what-a-store-sells.md) · **Closes:** [A16](../../open-questions.md)

## Context

Measured by hand against the real test shop, on `gemini-3.6-flash`, after ADR-0027 and ADR-0028 had both landed:

> **Shopper:** *"do you sell jackets?"*
> **Reply:** *"I've looked through this store's catalogue and I can't find anything matching that."*

The shop stocks **four jackets**. And the turn's own trace shows we had already found one:

```
RETRIEVE  found  ['category:35#0', …, 'product:1311#0']   ← the Waxed Cotton Field Jacket
PLAN      chose  search_products({'query': 'jackets'})
ACT       store said: no available products matching 'jackets'
NO_MATCH  "I can't find anything matching that"
```

The merchant's search is a literal text match with no stemming. Measured against the same endpoint:

| query | results | why |
|:--|--:|:--|
| `trousers` | **4** | titles read *"Halden Cargo **Trousers**"* |
| `jackets` | **0** | titles read *"Waxed Cotton Field **Jacket**"* |
| `shoes` | **0** | same — singular in the title |
| `shoe` | 1 | |

**One letter decides the turn**, and every gate downstream reads green: the tool succeeded, `shortlist` saw a successful lookup that returned nothing, and `no_match` said the honest thing about a search that had failed for a reason nobody could see.

### Why the previous two ADRs made this the binding constraint

ADR-0027 stripped the price phrase from the query and ADR-0028 stopped the router deciding what a merchant sells. Both made the query **more faithful to the shopper**. A more faithful query is worth nothing to an engine that cannot match a plural — so the ceiling on SELL's quality is now, unambiguously, the merchant's search engine. That is [A16](../../open-questions.md), and it is no longer a background concern.

### Why "just use our index" was not already the answer

`tools/catalogue.py` says it plainly, and the reasoning holds:

> **Read live, deliberately.** […] a feed is cached and may be an hour old; an agent about to recommend a purchase is making a claim about *now*, and stock is the field that goes stale fastest.

Recommending a product that sold out this morning is its own failure, and worse in a way the shopper discovers at checkout. The synced copy is also only as fresh as the last sync — and Stage 3 of the testing log records that **nothing fires sync on a timer yet**, so "recent" is not a property this system can currently promise.

## Decision

**When the merchant's search returns nothing, the synced index may supply candidate *identifiers* — and nothing else. Every fact about those candidates is then fetched live from the store.**

`search_products` gains one fallback branch, taken only when the store's own search yields no sellable product:

1. Search our index for **products only**, using the same query text.
2. Take the product ids out of the retrieved chunks, in order, bounded by `MAX_RESULTS`.
3. **Fetch each one from the store**, live, exactly as `get_product_details` does.
4. Keep the ones the store still returns as `ACTIVE`. Render those as candidates.

**The split is the whole decision.** The index answers *"which products might be worth looking at?"* — a question about meaning, which it is good at and which does not go stale in a way that can mislead. The store answers *"what is this product, what does it cost, can it be bought?"* — every claim a shopper acts on. A product deleted, withdrawn or sold out since the last sync **fails step 4 and disappears**, so the freshness guarantee in `catalogue.py` is preserved rather than traded away.

Put another way: **a stale index can now cost us a wasted lookup. It cannot put a wrong fact in front of a shopper.**

### The fallback fires only when the merchant's own words justify it

**Amended 2026-08-29, before this shipped anywhere, because the first version regressed the case it was not thinking about.**

The index always returns its nearest neighbours, and *"nearest"* in a 29-product catalogue is not *"relevant"*. Measured: **`fishing rods` returns a jacket at 0.528 against a best of 0.545** — noise indistinguishable from signal, and `DEFAULT_MIN_SCORE` is **0.3**, so every one of them would have passed. The first version of this decision would have answered *"do you sell fishing rods?"* with five things that are not fishing rods, which is **worse than the behaviour it replaced**.

So the fallback additionally requires that **at least one confirmed product uses one of the shopper's own words**, in its title or description, singular and plural folded together.

**Not a score threshold, and that is the point.** A threshold needs a number, and the scales are not comparable across embedding models: measured on the same shop, `nomic-embed-text` runs **0.50 to 0.75** where `gemini-embedding-001` runs **0.53 to 0.66**. Any constant would be right for one model and wrong for the next, and it would be a number invented from one shop wearing a measurement's clothes — the thing CLAUDE.md §4 exists to prevent.

The word test asks the question this fallback actually rests on: **did the merchant's search miss this for a *word* reason?** `jackets` against *"Waxed Cotton Field **Jacket**"* is exactly that — a plural their engine could not stem. `fishing rods` against a catalogue of clothing is not.

It is deliberately **not** deciding whether a product *fits*; that is the `sell.md` §2.3 question and a language judgement this node may not make. And it fails to the pre-ADR behaviour: a shopper asking for *"a waterproof coat"* in a shop that calls it a shell shares no word, gets no fallback, and is told exactly what they were told before this decision existed.

### It is announced, not silent

The cost this decision was weighed against is *"two behaviours, one of which is invisible"* — a wrong recommendation six months from now being impossible to attribute. So the fallback is loud in three places:

* a `sell_search_fell_back_to_index` log line carrying the query, the ids the index proposed, and how many survived confirmation;
* the tool result opens with a line stating that the store's own search returned nothing and these came from the synced catalogue, so it is in the evidence a reviewer reads and in the eval's recorded tool output;
* `sell-ask` prints it, because the operator debugging a bad recommendation is the person who most needs to know which path answered.

### What it does not do

**It does not run when the store's search succeeds.** A store that returns one weak result keeps that result; the fallback is for *nothing*, not for *not enough*. Merging the two would be a relevance judgement made in code with no data behind it, which is the heuristic-pretending-to-be-a-rule that `shortlist` already refuses to make.

**It does not reach the MCP surface.** `routes.py` builds its own `ToolContext` for [ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md)'s protocol surface and passes no retriever, so that path is unchanged. Serving someone else's agent from our cache, rather than from the merchant's live store, is a separate decision and is not taken here.

**It does not fix the merchant's search.** A shop whose engine cannot match a plural still has an engine that cannot match a plural, and every other surface — the feed, MCP, a sync — still sees exactly what it saw before.

## Consequences

**Good.** The commonest silent failure in the system stops: a shopper asking for a product the shop stocks, in the plural, is no longer told the shop is empty. It uses work already done and already paid for — the index is built in Stage 4 whether or not anything reads it. And it degrades correctly: a tenant with no index, or an index under a different embedding model, simply has no fallback and behaves exactly as before.

**Costs, stated plainly.**

* **Two paths reach `compose`**, and that is a real complexity increase. Mitigated by making it loud rather than by pretending it is not there.
* **Up to `MAX_RESULTS` extra HTTP calls** on a failed search — the slowest turn gets slower, and it is the turn that was about to answer badly.
* **The index decides what is *considered*.** A product missing from the index because a sync never ran cannot be recovered by this. The fallback narrows the gap between our copy and the shop; it does not close it, and **the missing scheduler (Stage 3) is still the thing that matters most for freshness.**
* **A weak-relevance candidate can now reach `shortlist` from a second direction.** `no_match_001` — where a cap is admitted as a candidate for *"fishing rod"* — is a `sell.md` §2.3 question and this decision does not touch it. It may make it slightly easier to hit.

## Alternatives rejected

**Search our index instead of the store's, always.** One behaviour, best matching — and every recommendation becomes as fresh as the last sync, which nothing currently schedules. It trades a visible failure for an invisible one.

**Ask the merchant to fix their search.** Not available: [ADR-0009](0009-generic-commerce-interface.md) is a contract about the *shape* of nine endpoints, deliberately not about the quality of what is behind them, and every shop's engine will differ. Requiring stemming would be a conformance requirement most shops would fail.

**Retry the store with a singular form.** Cheap and tempting, and it is guessing at one engine's behaviour from one shop's data. English plurals are the least of it — the next merchant's engine will fail differently.
