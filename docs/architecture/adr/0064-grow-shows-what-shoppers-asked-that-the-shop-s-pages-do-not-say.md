# ADR-0064 · GROW Shows What Shoppers Asked That The Shop's Pages Do Not Say

**Status:** **Accepted** · owner decision 2026-10-20 (R42: *"A"*, with Claude's additions) · owner decisions 2026-10-20, a design session, R36 to R41
([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, *GROW*) · not built,
mockup first · **§2's blank amended by the owner, 2026-10-20 (R43, R44):** the page shows the shoppers' question, where to add the answer and a link to the product page; GROW still never writes a fact; recorded again in the build's ADR · Everything marked *(Claude)* was Claude's proposal, accepted by the owner with R42 ·
**Date:** 2026-10-20 · **Design:** [docs/agents/grow.md](../../agents/grow.md) · **Related:**
[ADR-0010](0010-read-only-mvp-tools.md), [ADR-0015](0015-usage-rollups-and-budget-degradation.md),
[ADR-0022](0022-scheduling-under-rls.md), [ADR-0045](0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md),
[ADR-0046](0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md),
[ADR-0058](0058-a-shops-dashboard-has-people-with-roles-and-a-shop-signs-up.md)

> **In one sentence:** NEURA-GROW, the marketing agent, starts with one dashboard page, *Missing from
> your pages*: the facts at least two shoppers asked for in the last 30 days that the shop's data could
> not give, so the owner adds each one to the product page once.

## Context

**GROW was undesigned.** Blueprint-v2 §5.4 fixes its v1 as AEO/GEO (being named by AI tools, with
measurement) and puts generic content writing, campaigns, social media and attribution later. The owner
chose GROW as the next agent (R36) and, from Claude's eight ideas, chose this one first (R37).

**The problem it answers:** CARE and SELL already meet questions the shop's data cannot answer, every
day. Conversations' *Waiting for an answer* (ADR-0062) shows each one to the team, one shopper at a
time, today. **Nothing shows that twelve shoppers asked the same thing**, so the owner answers twelve
emails and the page still does not say it. Some gaps are not even handovers: the shopper got half an
answer (*"It is in stock, but I don't know the colours"*), so nobody on the team ever sees them.

**Why first:** it uses data NEURA already holds, needs no change to the shop, costs one small model call
per shopper message, and is useful from the first day. A fact added to a page helps the next shopper,
CARE (which answers from that page) and any AI tool that reads it, which is where AEO/GEO starts.

## Decision

1. **Both kinds count (R38):** a reply that handed the shopper over, and a reply that answered only
   half. **Only a fact the shop's pages could state counts** *(Claude)*: a cancellation, a complaint or
   a product the shop does not sell is not a page gap.
2. **GROW never writes a fact (R39).** It shows a blank to fill (*Organic: ____*). Only the owner knows
   the answer.
3. **A topic shows only when at least 2 different shoppers asked it (R40)**, counted by conversation,
   over the last **30 days** *(Claude)*.
4. **A dashboard page, *Missing from your pages*, and one line on Home (R41).** Grouped by product, with
   *About your shop* for facts that belong to no product; most asked first; *See the chats*; and
   *I added it*, which hides the topic until shoppers ask it again after that day *(Claude)*.
5. **Owner and Support see it; the Developer does not** *(Claude)*: both already read shoppers' chats,
   the Developer never does (ADR-0058).
6. **A background job, never while a shopper waits** *(Claude)*: once a night per shop with GROW, on
   ADR-0022's queue, inside the shop's daily AI budget (ADR-0015), like SELL's pairing (ADR-0045). One
   model call per assistant reply, returning *gap or not*, a product id and a short label; the call is
   given the shop's existing labels for that product so labels are reused.
7. **Code checks every model output before it is stored** *(Claude)*, because the model reads shopper
   text: the product id must be one the turn looked up; the label is 1 to 4 plain words, at most 40
   characters, with no link, email address or long number, and passes the injection guard's rules; the
   page shows it as plain text. Two conversations per topic keep one crafted chat off the page.
8. **Data** *(Claude)*: `page_gaps` (one row per gap found, with its conversation and turn) and
   `page_gap_fixes` (who pressed *I added it*, and when), row-level security as every shop table; a
   gap goes with its conversation (90 days) and with `make tenant-drop`; the admin dashboard never
   reads it (ADR-0061).
9. **Rule 4:** a golden dataset `gaps.yaml` (design §6), with injection and PII cases; **injection
   resistance stays 1.00**.
10. **NEURA writes nothing to the shop** (ADR-0010) and sends nothing to anyone.

## What this does not decide

- How GROW is sold (its own entitlement or included): **the owner's**, not settled here.
- GROW's other ideas (R36): each is its own design.
- The page's look: a mockup comes next, for the owner's approval.

## Consequences

- **Good:** GROW exists as an agent with a first useful surface, no new data from the shop, and no
  writes. The owner fixes a gap once instead of answering it many times.
- **A new model call on every shopper message**, in the background; its cost is not measured yet and is
  shown on the admin dashboard like every other call.
- **A new kind of text derived from shoppers' words reaches the owner's page.** The checks in §7 and
  the eval's injection cases are what make that safe, not the prompt (Rule 3).
- **The console grows by one page**, beyond its documented limit again (console.md §2).
- **Untested:** Sinhala and Tamil questions; how well labels group (an exact match may split
  *organic* and *certified organic*; a merge step would be a later change).
