# NEURA-GROW — Design

**Status:** **Accepted**, 2026-10-20 (R42) · with
[ADR-0064](../architecture/adr/0064-grow-shows-what-shoppers-asked-that-the-shop-s-pages-do-not-say.md) ·
nothing built · the owner's decisions are R36 to R41 in
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
*(Claude)*. *Things people want that you do not sell* is a separate GROW idea (R36, idea 3).

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
- a product the shop does not sell: no gap;
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

- GROW's other v1 ideas (R36): AI visibility checks, things you do not sell, shoppers' own words,
  rising topics, page health, AI shopper ready, the weekly brief, price comparison. Each is its own
  design.
- The screen's exact look: a mockup comes next, for the owner's approval (the console work cycle).
