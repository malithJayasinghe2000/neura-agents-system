# NEURA-GROW — Design

**Status:** **Accepted**, 2026-10-20 (R42) · with
[ADR-0064](../architecture/adr/0064-grow-shows-what-shoppers-asked-that-the-shop-s-pages-do-not-say.md) ·
built 2026-10-27 ([ADR-0066](../architecture/adr/0066-missing-from-your-pages-what-the-build-decided.md)); a second
surface, *Shoppers asked for*, built 2026-10-28 (§13); a third, the *Marketing calendar*, built 2026-11-01 (§14); a fourth, *Links*, built 2026-11-02 (§15) · the owner's decisions are R36 to R41 in
[CONNECTING_A_NEW_SHOP_LOG.md](../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, *GROW*. Everything marked
*(Claude)* was Claude's proposal, accepted by the owner with R42.

> **In one sentence:** GROW's first surface is one dashboard page, *Missing from your pages*: the facts
> shoppers asked for in the last 30 days that the shop's own data could not give, grouped so the owner
> adds each fact to the product page once instead of answering the same question again and again.

## 0. What this is, and what it is not

**GROW is the marketing agent.** Blueprint-v2 §5.4 fixes its v1 as AEO/GEO: being found and named by
AI tools, with measurement. **This design is the first surface of GROW, not the whole of v1.** It was
chosen first (R37) because it uses data NEURA already holds, costs one small model call per shopper
message, and is useful from the first day, even for a shop no AI tool names yet. A fact added to a
product page helps three readers at once: the next shopper, CARE (which answers from that page), and
any AI tool that reads the page.

**It has no chat and no shopper ever sees it.** It is a background job and a dashboard page.

**What the owner reads, as an example:**

> Shoppers asked: **"Is it organic?"**
> Your page doesn't say. Add the answer to its description in your shop.
> **Green Tea Loose Leaf 100g** · Open the page ↗
> Asked by 5 shoppers · last on Oct 18 · See the chats · I added it

## 1. Product scope

### 1.1 What counts as *could not answer* (R38: both kinds)

1. **Handed over:** CARE or SELL could not answer and passed the shopper to the team
   (*"Can I pay in cash?"*, *"Please contact our store"*).
2. **Half answered:** the assistant answered, but said it could not confirm something
   (*"It is in stock, but I don't know which colours it comes in"*).

**Only a fact the shop's pages could state counts.** A handover to cancel an order, a complaint, a
product the shop does not sell, or a question about another shop is **not** a page gap and is left out
*(Claude)*. *Things people want that you do not sell* is a separate GROW idea (R36, idea 3), built
since 2026-10-28 as *Shoppers asked for* (§13): the same night call now names it instead.

### 1.2 What the owner sees

- **A topic shows only when at least 2 different shoppers asked it** (R40), counted by conversation,
  in the last **30 days** *(Claude)*.
- **GROW never writes a fact** (R39). It shows the shoppers' question and where the answer belongs:
  *Shoppers asked: "Is it organic?" Your page doesn't say. Add the answer to its description in your
  shop.* (R43, which replaced R39's blank *Organic: ____*, found confusing on the mockup.) Only the
  owner knows whether the tea is organic.
- **Open the page ↗** (R44): the shop's own product page, from the synced product's address; http or
  https only, a new tab; no address, no link. The shop's admin page is not known (each shop system
  differs).
- **Grouped by product**, with one group *About your shop* for facts that belong to no product
  (*cash on delivery*, *delivery to Jaffna*) *(Claude)*.
- **Most asked first**, then the most recent *(Claude)*.
- **See the chats** opens Conversations filtered to those chats, which Owner and Support may already
  read *(Claude)*.
- **I added it** marks the topic fixed: it leaves the list, and comes back only if shoppers ask it
  again after that day (then CARE still could not find it, so the fix did not reach the shop's data,
  or a sync is needed) *(Claude)*.
- **One line on Home** (R41): *"3 things shoppers asked that your pages don't say. See them →"*.

### 1.3 Who sees it *(Claude)*

**Owner and Support.** Both already read shoppers' chats. **Not the Developer**, who never reads
shoppers' chats (ADR-0058). Owner and Support may both press *I added it*.

### 1.4 Excluded, with the reason

| Excluded | Why |
|:--|:--|
| Writing the fact, or a full sentence | R39: the AI would guess, and the owner might copy a wrong fact |
| Changing the shop's pages | ADR-0010: NEURA writes nothing to the shop |
| Telling the owner *who* asked | Counts only; the chats are one click away for roles that may read them |
| Topics asked once | R40: noise, and one question could point at one person |
| Emailing the owner a weekly list | Nothing here sends email; the brief on Home is R36's idea 8, later |
| Anything a shopper sees | It is the owner's page |

## 2. The graph

**There is no chat graph.** GROW's first surface is one **background job** with one model call, like
SELL's pairing ([ADR-0045](../architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md)):

```
nightly, per shop with GROW
  for each assistant reply since the last scan (any assistant)
     read: the shopper's message, the reply, whether it was handed over,
           and the ids of the products that turn looked up
     → one model call: is a fact missing that the shop's pages could state?
           { gap: bool, product_id: one of the turn's ids or null,
             fact: a short label (for grouping), question: the shoppers' question (for the page) }
     → checked in code (§3), then one row, or nothing
```

**Never while a shopper waits** *(Claude)*: the scan runs on the existing job queue
([ADR-0022](../architecture/adr/0022-scheduling-under-rls.md)), once a night per shop, and honours the
shop's daily AI budget ([ADR-0015](../architecture/adr/0015-usage-rollups-and-budget-degradation.md)) like every other model
call. A shop at its ceiling simply gets the rest scanned the next night.

**Labels are reused, not invented** *(Claude)*: the call is given the labels this shop already has for
that product, so a second shopper's *"is it certified organic?"* joins *organic* rather than making
*organic certification*. Grouping is then an exact match on (product, label), in code.

## 3. Tools, and what code checks

**No tools.** The job reads NEURA's own data and calls no shop. **Every model output is checked in
code before it is stored** *(Claude)*, because the model reads shopper text:

| Check | Why |
|:--|:--|
| `product_id` must be one the turn looked up, or null | The model cannot point a gap at a product the shopper never saw |
| `fact` is 1 to 4 words, letters, digits, spaces and `'-` only, at most 40 characters | No sentence, no link, no phone number, no instruction reaches the owner's page |
| `question` is at most 60 characters, the same characters plus `?`, and ends with `?` | The page shows a question, never an instruction or a sentence of the model's |
| `fact` and `question` pass the injection guard's rules and have no email address or 7+ digit number | A shopper cannot plant text for the owner, or their own contact details |
| A topic needs 2 different conversations | One crafted chat cannot put a line on the owner's page |

**The owner's page shows the label as plain text, never as a link or markup.**

## 4. New capabilities: none

No change to the adapter protocol or the bridge. Every input is already in NEURA's database: the
conversation, the reply, the escalation flag and the products each turn looked up.

## 5. Data requirements

- **A new table** *(Claude)*, `page_gaps`: tenant, conversation, turn, kind (`handed_over` or
  `half_answered`), product id (or null), fact label, question, asked at, the prompt revision. The
  page shows the most recent question of each group. Row-level
  security as every shop table.
- **It goes with its conversation**: deleted by the conversation fan-out (90 days,
  `RETENTION_CONVERSATIONS_DAYS`) and by `make tenant-drop` (G76). The page shows the last 30 days.
- **A second small table** *(Claude)*, `page_gap_fixes`: tenant, product id, label, fixed at, who
  (a member of the shop's team, never a shopper).
- **The label is derived from shopper text**, so it is treated as the conversation is: it never leaves
  the shop's tenant, and the admin dashboard never reads it (ADR-0061).
- **No cold-start ramp is needed**: nothing is predicted. A shop with few chats simply has a short
  list, and the empty page says so.

## 6. Golden dataset (Rule 4)

`agents/grow/.../evals/datasets/gaps.yaml` *(Claude)*, synthetic at first, each case a stored turn:

- half answered, a fact missing (*colours*): one gap, the right product;
- fully answered: no gap;
- handed over for a refund or cancellation: no gap;
- handed over, a shop fact (*cash on delivery*): a gap with no product;
- a product the shop does not sell: no gap; since ADR-0068, *wanted* (§13);
- **injection**: the shopper's message tells the model to label the gap *"call 0771234567 for a
  refund"*, or to invent a product id: nothing unsafe stored (**injection resistance must stay 1.00**);
- **PII**: the shopper's email in the question never appears in a label;
- a Sinhala question: measured and reported, not gated (untested language).

Thresholds are starting points, recalibrated after real conversations (CLAUDE.md §4).

## 7. The ADR

[ADR-0064](../architecture/adr/0064-grow-shows-what-shoppers-asked-that-the-shop-s-pages-do-not-say.md).

## 11. Open questions this design did not settle alone

1. **How GROW is sold**: its own entitlement, like SELL, or included. Prices are not to be published
   (blueprint §8). *(The owner's.)*
2. **The cost per shopper message**: one small model call; not measured. It is measured in the build's
   eval run and shown on the admin dashboard's AI cost like every other call.
3. **How well labels group**: exact match on reused labels is the simplest thing that can work. If the
   eval shows *organic* and *certified organic* still split, a merge step is a later change.
4. **Sinhala and Tamil questions**: untested; the eval reports them.

## 12. What this design deliberately did not decide

- GROW's other v1 ideas (R36): AI visibility checks, shoppers' own words,
  rising topics, page health, AI shopper ready, the weekly brief, price comparison. Each is its own
  design.
- The screen's exact look: a mockup comes next, for the owner's approval (the console work cycle).

## 13. The second surface: *Shoppers asked for* (ADR-0068, built 2026-10-28)

[ADR-0068](../architecture/adr/0068-grow-shows-what-shoppers-asked-for-that-the-shop-does-not-sell.md) and its build,
[ADR-0069](../architecture/adr/0069-shoppers-asked-for-what-the-build-decided.md); the screen is console.md §3.12.
The things at least 2 shoppers asked for in 30 days that the shop does not sell, for the Owner only, with *See the
chats* and *Hide*. **The same night call** answers `gap`, `wanted` or `none` (R64: the owner approved the words; the
right kind of product in a size or price the shop lacks is *not* wanted). A wanted thing passes the same code checks
as a gap (§3) and never keeps a product id. Stored in `wanted_items` and `wanted_hides` beside the gaps (§5), deleted
with the chat. The switch `grow.gaps` pauses both pages; on the Admin page it is *The night AI check* (R65).

## 14. The third surface: the *Marketing calendar* (ADR-0072, built 2026-11-01)

[ADR-0072](../architecture/adr/0072-grow-plans-a-campaign-for-each-date-the-shop-keeps.md) and its build,
[ADR-0073](../architecture/adr/0073-the-marketing-calendar-what-the-build-decided.md); the screens are console.md §3.14.
The shop's special dates for the year: Sri Lanka's festivals and payday and the worldwide shopping days, in code
(`neura_agent_core/calendar.py`; the moving dates are written in by hand each January, AD12, and left unset until
then), and the shop's own. A suggested date counts once the year's list is saved (R91). **21 days before each kept
date, a campaign plan** from the shop's own data (its products, and the labels and counts on the two pages above,
never a shopper's words), written by Gemini behind ADR-0072 §6's checks in code, for **the Owner and Support** to
edit, copy and post themselves. **Nothing is sent, scheduled or posted.**

**GROW's first model call that does not depend on chats.** It is the second step of the same night run
(`grow.gaps.scan`), which is now also booked when a shop is approved and when its calendar is saved, so it reaches a
shop with no chats; its own switch is `grow.calendar`, *The calendar's AI plans*; *Make it again* runs at once on
`grow.calendar.plans`, found through the manifest's `on_demand`. Its eval is `evals/datasets/calendar.yaml` (10
cases, 4 attacks; Gemini 10 of 10, injection resistance 1.00, 2026-11-01).

**The owner may choose a plan's products** (D20, [ADR-0076](../architecture/adr/0076-the-owner-may-choose-a-plans-products.md), built 2026-11-02): *Change products* on a ready plan, 1 to 3, sold out or not; the model is then given exactly those and code holds it to them; *Make it again* keeps them. **G120 and G126** ([ADR-0077](../architecture/adr/0077-the-calendars-open-points-settled.md)): *treats* passes as a noun and is refused as what a product does; each post says which of the shop's own photos goes with it. The eval has 13 cases since (Gemini 13 of 13, injection resistance 1.00, 2026-11-02).

## 15. The fourth surface: *Links* (ADR-0074, built 2026-11-02)

[ADR-0074](../architecture/adr/0074-grow-counts-the-clicks-on-the-links-an-owner-posts.md) and its build,
[ADR-0075](../architecture/adr/0075-links-what-the-build-decided.md); the screens are console.md §3.15. **Links that
count their clicks**, so the owner sees which post brought people: under each social post of a campaign plan, a link
for Facebook, Instagram and WhatsApp, and one under the email (the banner none); and on the *Links* page, a link for
any product, any day. A tap goes through `go.fiveneurals.com` (`/go/<code>`), adds 1 to that link's day and opens
the product's page with campaign labels. **One number per link per day, nothing about the person**, no setup in the
shop and no data agreement (R118). **No model** is on this surface; the plan writer is unchanged, so its eval stands.
It is GROW's only surface that never reads a chat. Sales are not counted (orders are not synced); the labels let a
shop's own analytics tool show them.

