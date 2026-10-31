# ADR-0071 · A Product People Look At And Leave Is A Fact The Merchant Should Have

**Status:** **Accepted** · the owner, 2026-11-01 (R74 to R79) · the design is Claude's · **mockup approved 2026-11-01** (R80; canvas row 20, boards
71 to 74; console.md §3.13) · **built 2026-11-01** (pieces 1 to 3) · **Date:** 2026-11-01 · **Extends:** [ADR-0046](0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md)'s
screen with a second tab · **Requires:** [ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)
(cited, as its §1 asks) and [ADR-0048](0048-observation-phase-1-what-the-build-decided.md)'s two events ·
**Related:** [ADR-0033](0033-care-answers-what-the-store-has-sell-helps-the-shopper-choose.md),
[ADR-0049](0049-a-product-view-records-whether-it-could-be-bought.md), console.md §3.7

> **In one sentence:** beside *Sold out*, a second tab lists the products that are **in stock**, that **10 or more
> visitors** opened in the last 7 days, and that **fewer than 1 in 10** of them added to the cart, so the owner
> knows which product pages to look at again. Counts only, no AI, nothing sent to a shopper, nothing written to
> the shop.

## Context

*Sold out* (ADR-0046 stage 1) turns a view of a product that could not be bought into a fact: *people wanted this
while you had none*. The same events say something else nobody shows the owner today: a product that **could** be
bought, that many people opened, and that almost nobody put in the cart. Something on that page stops them: the
price, the photos, the description, the sizes. The shop's own analytics may hold the numbers; nothing puts them
side by side for one product.

The owner chose this (R74) after GROW's *Is AI naming your shop?* was stopped (R73), asking whether SELL already
had it. It had half: *Sold out* counts views of sold-out products only.

### Why it is SELL's

GROW helps people **find** the shop. SELL helps a shopper who is already looking **choose** (ADR-0033). A product
opened 40 times and added once has been found; the loss happens on its page, which is SELL's ground, and the
purpose is ADR-0046's: **recovering a sale, not answering a question**.

## Decision

### 1. What is listed (R75, R79)

A product is on the list when, in the last **7 days** (the retention window, so there is nothing older):

- **10 or more visitors** opened its page **while it was in stock**. A visitor is a browsing session the shop
  sends (ADR-0044 §4), never a person we can name. A view is counted only with `in_stock = true`
  (ADR-0049); a view with no stock value is not evidence either way, as on *Sold out*.
- **Fewer than 1 in 10 of those visitors** added it to the cart (`cart.added`, ADR-0048). Only visitors who opened
  the page count as *added*, so the number can never be larger than the visitors, and an add from a category
  page without opening the product does not count: the question is what the product's page does.

Ordered by the share that added it, lowest first, then by visitors, most first. At most 100 products, as *Sold
out*. **Both numbers (10 and 1 in 10) are starting guesses**, measured against nothing, to recalibrate once a real
shop has traffic (CLAUDE.md §4).

### 2. What a row says (R77)

Facts only: the product's **name, photo and price** (from the synced catalogue, as *Sold out* reads titles), **"40
visitors, 1 added to cart"**, and **Open the page**, a link to the product's page in the shop when the catalogue
has its address. Above the list, one fixed hint: *"Check the price, photos and description."*

**No AI.** A guess at the reason (*"too expensive"*) costs a model call per product and can be wrong; an owner who
lowers a price because of a wrong guess loses money for nothing.

### 3. Where it sits, and who sees it (R74, R76)

A second tab on the *Sold out* page: **Sold out** | **Rarely added to cart**. The same permission,
`shop:sold_out:read`: **the Owner only**. Changing a price, a photo or a description is the owner's decision, as
restocking is. It is shown, like *Sold out*, only to a shop with NEURA-SELL (display only, as console.md §2's
2026-09-30 note describes).

### 4. Home (R78)

One line on the Owner's Home, **"[n] products are viewed a lot but rarely added to cart"**, opening the tab, shown
only when [n] is at least 1. Home's number is the tab's number.

### 5. When nothing shows

The tab says why, in words the owner can act on, as *Sold out* does:

- **No views arrive** (the shop has not switched sending on, or has no data agreement): the same words and the same
  step as *Sold out*'s.
- **Views arrive, nothing qualifies**: *"No product had 10 or more visitors with fewer than 1 in 10 adding it to the
  cart in the last 7 days."*

### 6. What this never does

The whole of ADR-0046 §6, unchanged: it never contacts a shopper, never writes to the shop, never runs a model,
never tells a shopper how many people looked at something, and **the order is for the owner's reading only, never
used to rank anything a shopper sees** (ADR-0044 §8.2, ADR-0040 §3).

**It is not ADR-0044's phase 2.** Phase 2 scores a **visitor** with a points table; this counts per **product**,
across visitors, as *Sold out* does. No visitor is scored, listed or followed.

**It says *rarely added to cart*, never *not bought*.** We receive views and cart adds; orders are not synced
(`ORDER` sync is off), so whether anyone bought is not something we know.

### 7. The falsification test

**If owners look at the tab and change no product page, delete it.** Not "add an AI reason". The same test as
ADR-0046 §8.

## Consequences

- No new table and no new event: a query over `observed_events`, a tab and a Home line.
- **Empty until a shop switches on sending views**, and no real shop does yet. The test shop proves the pipe
  (events in, the counts right, the screen renders), not that the list helps anyone sell.
- The 7-day window is short for a small shop: 10 visitors a week to one product is a lot of traffic for a shop
  with few visitors. Widening it needs a longer retention, which ADR-0048 set at 7 days on purpose; not done here.

## What this ADR does NOT decide

- **It does not sync orders.** *Bought* would need `ORDER` sync, which is its own decision.
- **It does not ask the shop for stock now.** *Sold out*'s *Check again* asks because a sold-out product may be back;
  a product listed here was in stock when viewed, and whether it still is changes nothing the owner should do.
- **It does not change the retention or the window.**
- **It does not give the tab to Support or the Developer.**

## As built (2026-11-01)

The count is `ObservedEventRepository.rarely_added` and `count_rarely_added` (`neura_core/observation/repository.py`,
`RARELY_MIN_VISITORS` 10, `RARELY_ONE_IN` 10; no table changes); the route is `GET …/sold-out/rarely-added`
(`console_sold_out.py`); Home's payload gains `rarely_added`; the screens are the second tab on
`app/console/[tenantId]/sold-out/page.tsx` (`?tab=rarely`) and Home's line. **Tested:** 7 Postgres tests of the
count's edges (exactly 1 in 10 stays off, 9 visitors stay off, one session opening it 15 times is one visitor, an add
from a session that never opened the page does not count, sold-out, unknown and old views do not count, another
shop's views never count); 6 route tests (the rows and the rule, no session token, the Owner only, both empty causes,
Home's number); `make console-check` 287 passed, 0 failed (10 new: the tabs, the row, *Open the page*, what is left
off, the rule and the caveat, no token, Home's line, a phone). **Found while building: G117**, search-engine crawlers
count as visitors and can put a product on the list with no shopper. **Fixed the same day (the owner: A):** the
reference bridge sends nothing for a known robot or a request with no user agent, judged on the shop's own server
(the user agent is still never sent); the spec and the developer guide ask the same of every shop; the sentence
under both tabs says known robots are left out and an unknown one may still count. Tested against 20 real robot
and 9 real browser user agents (0 wrong); **not run live**, because sending is switched off on the test shop. **Renamed the same day (G118, R81):** the menu item and the page say **Product views**, since
the page holds two tabs; the tabs and the address are unchanged. **Not tested:** any
real shop's traffic (no real shop sends views); a shop's photo drawn from another address.

## Alternatives considered

- **Every viewed product, most viewed first** (R75 B). A product seen twice and not added looks like a problem when
  it is not; refused.
- **No limit on *rarely*** (R79 B). Home could not say *rarely*; refused.
- **An AI reason per product** (R77 B). Costs a call and can be wrong; refused.
- **A GROW page.** GROW is about being found; refused (R74).
