# ADR-0028 — Only The Catalogue May Say What A Store Sells

**Status:** Accepted · **Date:** 2026-08-28 · **Builds on:** [ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md), [ADR-0011](0011-deterministic-guard-not-classifier.md) · **Closes:** [A18](../../open-questions.md) · **Touches:** A5, A16

## Context

Found by hand against the real test shop, and the two runs that found it are the whole argument:

| shopper asked | `route` decided |
|:--|:--|
| *"do you sell **jackets**?"* | `recommend`, 0.80 — searched ✅ |
| *"do you sell **fishing rods**?"* | **`out_of_scope`, confidence 1.00** ❌ |

The catalogue was never read in the second case. The shopper was told *"That question is outside what I can help with"* — about the most ordinary question a shopper can ask.

And the need statement the router wrote for that turn was:

> `'We do not sell fishing rods.'`

**That is not a classification. It is an answer.** The router decided what the merchant stocks and filed the question as handled.

### The router is shown nothing about the store

`prompts/route.md` describes four categories and the extractions. **It contains no reference to the merchant's catalogue, categories, or product range**, and `route` runs *before* `retrieve`, so no store data exists in the turn yet.

So *"we do not sell fishing rods"* is a guess about a shop the model has never seen. For a clothing store it is a good guess. **For a fishing tackle shop it declines the merchant's best-selling product**, at confidence 1.00, and `out_of_scope` is the only category that ends a turn with neither an answer nor a person — so the merchant never finds out.

This is the difference between a demo that works on one clothing shop and a product that works on any store, which is what [ADR-0009](0009-generic-commerce-interface.md) is for. The commerce interface is platform-agnostic and the router is not **catalogue**-agnostic.

### Why this outranks the fix that preceded it

[ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md), one day earlier, rewrote both of `no_match`'s messages so that a miss speaks about the search rather than about the whole store. **`route` intercepts the traffic that would reach them.** The honest-miss path that `sell.md` §2.3's argument rests on is close to unreachable for the commonest phrasing of a miss, so ADR-0027's value is gated by this and not the other way round.

## Decision

**A model may not decide what a merchant sells. Only the catalogue may.**

Concretely: when `route` classifies a message as `out_of_scope` **and** the message is a shopper asking whether the store has something, the classification is overridden to `recommend` and the turn goes and looks.

`asks_what_the_store_sells()` is a deterministic pattern over the **shape of the question** — `do you sell/stock/carry/have …`, `have you got any …`, `can I buy … `, `are there any …`. It is the same instinct as [ADR-0011](0011-deterministic-guard-not-classifier.md): a rule that matches or does not, with no score and nothing to tune.

**It deliberately does not look at the product.** A pattern that tried to recognise plausible merchandise would be the original mistake rewritten as a regular expression — and would fail on exactly the shops this exists to serve.

**The rewrite is discarded on this path.** On an overridden turn the need statement is the router's own answer (*"We do not sell fishing rods."*), which searches for nothing. The shopper's raw message is used instead.

**Nothing else is weakened.** `needs_person` is untouched. `out_of_scope` still ends turns for the weather, the news and questions to the assistant about itself. The `DECLINE_MIN_CONFIDENCE` bar from [A5](../../open-questions.md) is unchanged — this removes one class of message from the decline path entirely rather than lowering the bar for the rest.

**`no_match` still says no.** The answer to *"do you sell fishing rods?"* in a clothing shop is still no. The difference is that it is said **after asking**, by the node designed to say it, in the wording ADR-0027 established — and with the store's own category list attached.

## Consequences

**Good.** A merchant's product range stops being a thing a model guesses at. The failure mode that made this a clothing-shop demo is gone: a tackle shop, a pharmacy, a bookshop get their catalogue searched for their own products. `no_match` becomes reachable for the phrasing shoppers actually use, which is what makes ADR-0027 worth having. And one class of message can no longer hide in `decline` — the path `route.py` already names as *"the one path an attacker gains from, because a message that gets itself classified out-of-scope is answered with a polite nothing and no security event reaches the merchant"*.

**Costs, stated plainly.**

* **A question that is not about products can now reach the catalogue.** *"Do you sell my data?"* matches the pattern. If the router sends it to `out_of_scope` it will now be searched and answered *"I can't find anything matching that"* plus the store's categories — odd, and less good than a decline. It is a **policy** question, so `needs_person` is its correct route and the override never fires on that path; this is the cost when the router is already wrong. **Accepted**, because the failure it replaces is a false statement about a merchant's stock and this one is a clumsy answer to a misrouted question.
* **An attacker can guarantee a catalogue search** by prefixing any message with *"do you sell"*. The cost is one lookup — **202ms measured, no model call** — against the 42s the same turn already spends in `plan`. The guard runs first and is unchanged.
* **The search query on this path is the raw message**, and *"do you sell fishing rods?"* is not a good query for a keyword engine. Query quality is **[A16](../../open-questions.md)** and is untouched: SELL still searches the merchant's engine rather than our index, so this makes the turn honest without making it good.
* **The pattern will miss phrasings.** It is English, it is a fixed list, and it will not catch every way of asking. A miss leaves today's behaviour, so it fails to the status quo rather than to something worse.

**Not decided here.** Whether `route` should be *given* the store's category list. Rejected for now, and it is the tempting fix: it invites the model to make the same judgement with slightly better information, when the point is that this judgement is not the model's to make. Categories are also coarse — a tackle shop's "Rods" tells a router nothing about "9ft carbon fibre".

## Alternatives rejected

**Tighten `route.md`.** It already says *"Be especially careful with `out_of_scope`… If a message might relate to shopping at this store, it is not `out_of_scope`."* The model read that and declined at confidence 1.00 anyway. Rule 3, for the third time in two days — after `plan.md`'s ignored price instruction and `route.md`'s copied example.

**Escalate availability questions to a person.** Correct and unaffordable: every *"do you sell X?"* would interrupt a human, which is the queue the console exists to keep small.

**Remove `out_of_scope` from SELL entirely.** Throws away [A5](../../open-questions.md)'s resolved reasoning — declining cheaply is a real feature — to fix one class of message.
