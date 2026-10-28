# ADR-0068 · GROW Shows What Shoppers Asked For That The Shop Does Not Sell

**Status:** **Accepted** (the owner approved the ADR and canvas row 19, 2026-10-28, R63) · owner decisions 2026-10-28, R59 to R62 (and R36's idea 3, chosen as GROW's next feature)
([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, *GROW*) · **built 2026-10-28**, what the build decided is [ADR-0069](0069-shoppers-asked-for-what-the-build-decided.md) (the AI's words R64, the switch's words R65) ·
Everything marked *(Claude)* was Claude's proposal, accepted with R63 · **Date:** 2026-10-28 · **Builds on:**
[ADR-0064](0064-grow-shows-what-shoppers-asked-that-the-shop-s-pages-do-not-say.md) and its build,
[ADR-0066](0066-missing-from-your-pages-what-the-build-decided.md); [ADR-0065](0065-fiveneurals-may-switch-off-one-feature-for-one-shop.md)
(the switch)

> **In one sentence:** a second GROW page, *Shoppers asked for*, lists the things at least 2 shoppers asked for in
> the last 30 days that the shop does not sell (*"Do you have matcha?"*), so the owner can decide to start selling
> them; it is found by the same night check, with no extra AI call.

## Context

ADR-0064 left *a product the shop does not sell* out of *Missing from your pages* on purpose: no page can answer
it. It is still worth knowing: a shop whose shoppers keep asking for matcha may want to sell matcha. GROW's first
design named it as its own idea (R36, idea 3). Today SELL and CARE say *"we don't carry that"* and the demand is lost.

## Decision

### 1. What counts *(Claude, from R36)*

A shopper asked for **a kind of product the shop does not sell**, and the reply said so (*"I can't find anything
matching that"*, *"we don't carry it"*). Not counted: a product the shop sells but has sold out (that is *Sold out*,
ADR-0046), a question about a product it sells (that is *Missing from your pages*), anything not a product.

### 2. Its own page, *Shoppers asked for* (R59: B)

In the menu after *Missing from your pages*, only for a shop with NEURA-GROW. Each row: the thing (*Matcha*), what
a shopper asked (*"Do you have matcha?"*), *"Asked by 3 shoppers · last on Oct 18"*, **See the chats** and **Hide**.
Most asked first. A line on Home for the Owner (*"3 things shoppers asked for that you don't sell"*). The words and
the look are fixed by the mockup.

### 3. From 2 shoppers, in 30 days (R60: A)

Counted by different conversations, as ADR-0064 §3. Counts only, never who asked.

### 4. The Owner only (R61: A)

Like *Sold out*: what to sell is the owner's decision. A new permission, `shop:wanted:read`, held by the Owner
alone *(Claude: the name)*. Support and the Developer see no menu item and no Home line.

### 5. *Hide*, and it comes back if asked again (R62: A)

*Hide* records who pressed it and when; the thing leaves the page, and comes back only if shoppers ask for it
again after that day, exactly as *I added it* (ADR-0064 §4).

### 6. The same night check, no extra AI call *(Claude)*

The night check already reads every reply that could not answer, and already recognises *a product the shop does
not sell* (to leave it out). It now **names it instead**: the same one call returns either a page gap, or a
*wanted* thing (a 1 to 4 word label and the shopper's question), or nothing. **The instructions change, so the
owner approves the new words before the build**, and the eval gains *wanted* cases; injection resistance stays
1.00. The free word check (R47) also lets through *don't carry*, *don't sell*, *no products matching*.

**The same code checks** as a gap's label and question (ADR-0064 §7): plain words, no link, email, long number or
command word; the label is shown as plain text. Labels are reused as topics are, so *matcha* and *matcha powder*
count together when the model is shown *matcha* already found.

### 7. Data *(Claude)*

Two tables beside `page_gaps`, in the shared core (Sold out's pattern, ADR-0066 §2): `wanted_items` (one row per
reply, with its conversation; deleted with it, 90 days; removed with the shop) and `wanted_hides` (*Hide*, by
label, with who). A console route `GET /v1/console/shops/{id}/wanted` and `POST …/wanted/hidden`, and *See the
chats* as Conversations' `?wanted=`.

### 8. Paused with the night check (ADR-0065)

The switch `grow.gaps` already stops the night check, so it pauses both pages; *Shoppers asked for* says *Paused*
the same way. The manifest's `pauses` names both pages *(Claude)*.

## Tests

**Written first, failing on the old code:** a *wanted* answer is stored, a gap and a *wanted* never both from one
reply; the code checks refuse a bad label as for a gap; a thing shows from 2 conversations in 30 days; *Hide* takes
it off until asked again after that day; only the Owner may open the route (Support and the Developer 403); *See the
chats* lists exactly the chats counted; Home's line only for the Owner; the switch pauses it. **The Gemini eval**
`gaps.yaml` with *wanted* cases, injection resistance 1.00. **In headless Chrome:** the page, Home's line, *Hide*,
desktop and phone.

## Consequences

- **No extra AI cost:** the same call per reply, a slightly longer answer.
- **A third GROW screen**, and the console further over its documented screen limit (console.md §2).
- **Text derived from shoppers' words reaches the owner's page**, made safe by the same code checks and the
  2-shopper threshold (Rule 3).

## Not decided here

Suggesting a supplier or a price; telling a shopper when the shop starts selling it (NEURA never messages a
shopper); counting searches on the shop's own site (not sent to NEURA).
