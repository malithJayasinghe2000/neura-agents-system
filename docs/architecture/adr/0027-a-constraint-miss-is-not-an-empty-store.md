# ADR-0027 — A Constraint Miss Is Not An Empty Store

**Status:** Accepted · **Date:** 2026-08-27 · **Builds on:** [ADR-0010](0010-read-only-mvp-tools.md), [ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) · **Closes:** [A15](../../open-questions.md) · **Touches:** A16

## Context

Found by hand, in Stage 6 and again in Stage 9 of [the testing log](../../TESTING_LOG.md), against a real shop rather than a fixture.

A shopper typed **"I need trousers under 40"**. The shop stocks four kinds of trousers. The shopper was told:

> *"I've looked through this store's catalogue and I can't find anything that matches what you're after — **this shop doesn't appear to carry it**."*

That sentence is false, and it is false in the most expensive possible direction: a shopper reads it as *"this shop does not sell trousers"* and leaves. Measured on the test shop, the same catalogue also holds an **Everyday Jogger at 39.00 USD** — inside the stated budget.

### The chain that produced it

| step | what happened |
|:--|:--|
| `route` | extracted `budget 40.0` **and** left the price in the need statement: `'trousers under 40'` |
| `plan` | searched `search_products("trousers under 40")` |
| the shop | returned **0** rows — its search is keyword-based, and no product contains the token `40` |
| `shortlist` | saw a *successful* tool call, so `catalogue_answered` was true |
| `no_match` | said the store does not carry it |

Measured directly against the same endpoint:

| query | results |
|:--|--:|
| `trousers` | **4** |
| `trousers under 40` | **0** |

**One adjective destroyed the turn**, and every gate in the system read green.

### Why the prompt was not the problem

`plan.md` already says, in as many words:

> *"Search for the **thing**, not the sentence."*
> *"**Do not try to filter by price yourself** — that is handled elsewhere, exactly."*

The model was told precisely the right thing and did the other thing. **This is AGENTS.md rule 3 arriving from the inside**: a behaviour that matters, defended only by a sentence in a prompt, is not defended. The fix therefore may not be a better prompt — the prompt is already correct.

### What `shortlist` was actually checking

[A15](../../open-questions.md) named it: `shortlist` asks *"did the store reply?"* and never *"did we ask it a question it could answer?"* **A search returning zero rows counts as the store having answered.** So the guarantee in `sell.md` §2.3 holds against an outage and not against a bad query, which is the far commoner case.

There is also a third situation with no voice of its own. `shortlist` already distinguishes *"the catalogue returned nothing"* from *"products came back and the shopper's own constraint excluded them"* — it logs `sell_all_candidates_excluded` separately — and then routes both to the identical sentence. The most useful thing SELL could say was being computed and thrown away.

## Decision

**Three changes, in the order they take effect.**

### 1. A price constraint is stripped from the search query, in code

`search_products` removes price-comparison phrases (`under 40`, `below £40`, `less than $40`, `up to 40`, `max 40`, `cheaper than 40`) from the query text before it reaches the merchant's search engine, and logs when it does.

The tool boundary, not the node, because it is the last point we control the string and it applies no matter which model or which node produced it. The ceiling is not lost: `route` extracts it structurally and `shortlist` enforces it exactly, which is what makes the phrase redundant in the query rather than merely unhelpful.

Bare numbers are untouched — `size 40`, `40 denier`, `SPF 40` do not match. Only a comparison word bound to a number.

### 2. "Your constraint excluded them" becomes its own message

`shortlist` now reports **why** nothing survived, and `no_match` renders a different fixed sentence for each case:

| situation | what the shopper is told |
|:--|:--|
| products found, all outside the stated constraint | *"We do carry trousers — I found 4 — but none under 40.00 USD. The closest is 44.00 USD."* |
| the search returned nothing at all | *"I couldn't find anything matching that in the catalogue."* |
| the catalogue was never read | escalate to a person (**unchanged**) |

### 3. A single search may no longer speak for the whole store

The clause *"this shop doesn't appear to carry it"* is removed from the zero-results message. What replaces it is a claim about **the search**, which is what the evidence actually supports. The store's own category list still follows it where `CATEGORY_READ` is declared, so the shopper is still told what the store *does* sell.

## What this reverses, explicitly

`no_match.py` states that the node **may not** *"describe what was found"*, reasoning that an agent breaking bad news will offer the nearest thing and imply it fits — *"the most common failure mode of every recommender ever shipped"*.

**That reasoning is upheld and its scope is narrowed.** The failure it names is *implying fit*. Naming a price the shopper themselves set a bound on does the opposite: *"none under 40.00 USD, the closest is 44.00"* states that the product **does not** fit, in the shopper's own units, and is the sentence that lets them decide to stretch. The prohibition remains absolute on describing a near-miss as suitable, on explaining *why* the store does not stock something, and on any product claim beyond identity and price.

Three properties keep it safe, and all three are structural:

* **No model writes it.** The message stays a fixed template; the count and the price are copied from tool output, so the only two variable values are numbers the catalogue returned.
* **`promises` stays empty.** The fabrication check is unchanged — no product id enters the reply, so nothing here can be cited or recommended.
* **The near-miss is never named.** The count and the cheapest price are stated; the product is not identified, so there is nothing for a shopper to add to a basket by mistake.

## Consequences

**Good.** The false claim about a merchant's whole catalogue stops shipping. A bad query degrades to *"I couldn't find that"* instead of *"we don't sell that"*. The constraint case gains the most commercially useful sentence SELL can produce — and it is produced without a model, so it cannot drift.

**Costs, stated plainly.**

* **The honest miss is quieter.** *"This shop doesn't appear to carry it"* was a real feature — most recommenders would rather suggest something wrong. The replacement is weaker on purpose, because it is what the evidence supports. Where the store publishes categories, the shopper still learns what it *does* sell.
* **Stripping is a heuristic, and it is a small one.** It handles the phrasings above and will miss others. It reduces the blast radius of a bad query; it does not make queries good. **[A16](../../open-questions.md) is untouched** — SELL still searches the merchant's engine rather than our index, so recommendation quality is still bounded by their search, and this ADR does not change that. A16 is the real ceiling and remains open.
* **It cannot rescue a genuinely bad need statement.** *"something for a rainy walk"* searched as `rainy walk` returns zero for reasons no stripping addresses.

**Not decided here.** Whether to retry a zero-result search with a broader query, and whether to search our own index when the merchant's returns nothing, are both A16 and both still open — a retry loop and a second search path are each their own decision with their own failure mode.

## Alternatives rejected

**Tighten `plan.md`.** The prompt already says it. Rule 3.

**Escalate whenever a search returns zero.** Would make every genuine *"we don't sell fishing rods"* interrupt a human, floods the queue the console exists to keep small, and destroys the honest miss entirely to fix a wording problem.

**Filter price inside the adapter.** The generic interface is the merchant's contract ([ADR-0009](0009-generic-commerce-interface.md)); rewriting a caller's query there would be a silent behaviour every future adapter inherits without asking for it.
