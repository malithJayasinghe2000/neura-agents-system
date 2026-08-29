# ADR-0030 — A Product Card Is Data The Widget Draws

**Status:** Accepted · **Date:** 2026-08-30 · **Builds on:** [ADR-0019](0019-widget-is-one-file.md), [ADR-0016](0016-nothing-reaches-the-shopper-before-verify.md), [ADR-0020](0020-a-withheld-turn-is-not-silence.md), [ADR-0029](0029-the-index-may-name-a-candidate-never-describe-one.md)

## Context

SELL recommends products in prose:

> *"The Waxed Cotton Field Jacket (1311) is 165.00 USD and in stock…"*

No picture, no price badge, nothing to click. A shopping assistant that cannot show the jacket is doing half the job, and the shopper has to go and find it themselves — which is the moment the conversation ends.

The widget renders **text only**, deliberately. Its own comment says why:

> *`textContent`, never `innerHTML`. Everything rendered here came off the network — a shopper's own words echoed back, a merchant's policy text, a model's reply — and none of it is markup we authored.*

That rule is correct and is not being relaxed. A merchant's product description is arbitrary text they typed; rendering it as HTML in their own storefront makes every description an injection point, and the description is exactly the field [S6](../../open-questions.md) records as already carrying hostile text in the wild.

## Decision

**The model names the products. The server states the facts. The widget draws the card.**

Three layers, and no layer may do another's job:

| Layer | Supplies | Never supplies |
|:--|:--|:--|
| the agent | **which** product ids | prices, images, links, markup |
| the server | title, price, stock, url, image — **from the merchant's live data** | markup |
| the widget | **all** the HTML | any value of its own |

### Where the facts come from

Not from the reply text, and not re-parsed out of a rendered tool result. The catalogue tools already fetch real `Product` objects; they now also stash them in a **per-turn cache on `Runtime`**, beside the PII vault and for the same reason — it is per-turn, it is never checkpointed, and an HTTP-shaped object has no business in a database row.

`respond` then builds a card for each id the draft actually cites, from that cache.

### Which products may appear

**Exactly the ones already allowed to be named.** `respond` runs the fabrication check on every SELL turn: an id that is not in `promises` escalates the turn. Cards are built *after* that check and from the same set, so **a card cannot show a product the shortlist rejected** — the out-of-stock recommendation and the price-ceiling violation are both already impossible, and cards inherit that rather than needing their own version of it.

A card is also only built for a product the reply *mentions*. A shortlist of four that the composer wrote about twice produces two cards, not four.

### On the wire

The socket already speaks typed frames — `accepted`, `token`, `done`, `error`. One more:

```json
{ "type": "products", "items": [ {"id": "1311", "title": "…", "price": "165.00",
  "currency": "USD", "in_stock": true, "url": "https://…", "image": "https://…"} ] }
```

The REST reply carries the same list, so a shopper behind a proxy that blocks websockets sees the same cards. **Fields only. No markup crosses the wire in either direction.**

### The three values that come from a URL, and what happens to them

`url` and `image` are the only fields that are not inert text, and they are the whole security surface:

* **`https` only.** A `javascript:` or `data:` URL never reaches an attribute. Anything else is dropped and the card renders without it — a card with no image is fine; a card with an executable image source is not.
* **Links open with `rel="noopener noreferrer"` and `target="_blank"`**, so a merchant's own product page cannot reach back into the tab.
* **A missing or rejected image is not an error.** The test shop publishes `image_urls: []` for every product; a design that needs an image is a design that breaks on the first real merchant.

**Not decided here: an image-host allow-list.** `https` from anywhere is what ships. Restricting images to hosts the merchant declares is stricter and is a conformance change — it means a merchant whose CDN differs from their storefront silently loses images, which is a support call, not a security win, until someone has asked merchants where their images live. Recorded as an open question rather than guessed at.

## Consequences

**Good.** The shopper can see the product and get to it in one click, which is the difference between a recommendation and a conversation about a recommendation. The safety argument does not get weaker: cards are drawn from the same `promises` set the fabrication check already enforces, and every value is inert text placed by the widget.

**Costs.**

* **A card is a stronger claim than a sentence.** *"Around £165"* is vague; **£165.00 · In stock** is a number a shopper acts on and will hold the merchant to. The facts come from a live adapter read, so they are as fresh as the turn — but the consequence of a stale one is now larger, and that is the reason this ADR does not allow a card to be built from the synced copy.
* **A wider client contract.** `products` is a new frame and a new response field. A client that ignores it still works — text is unchanged, so an old widget degrades to today's behaviour rather than breaking.
* **CARE is untouched, deliberately.** It also mentions products and has **no `promises` list**, so the guarantee cards rest on does not exist there. Giving CARE cards means first deciding what constrains them, which is a different decision.

## Alternatives rejected

**Let the model emit markdown or HTML.** The direct route and the one that ends in an incident: it makes every product description a script tag away from running on the merchant's storefront, and moves the escaping problem into a model's output where nothing can check it.

**Parse the cards back out of the rendered tool text.** No new plumbing, and it cannot work: `candidate()` renders title, price, availability and description — **it renders no image and no URL**, because it exists to justify a recommendation to a model, not to draw one for a person. Re-deriving structure from text we flattened on purpose is a fragile answer to a problem caused by throwing the structure away.

**Fetch the products again in `respond`.** Correct, and wasteful: up to four extra HTTP calls per turn to re-read what the same turn already fetched. The per-turn cache costs nothing and cannot go stale, because it dies with the turn.
