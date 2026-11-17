# ADR-0078 · Ask The Owner First, Then Write The Plan

**Status:** **Accepted** · the owner's decisions 2026-11-17 (D21, G121, G130, G131) · everything marked *(Claude)* is
Claude's, decided while building · **no mockup** · **built 2026-11-17** (the owner: *"this is approved and no need mockup you can build
that"*) · **Date:** 2026-11-17 · **Changes, in part:**
[ADR-0072 §5](0072-grow-plans-a-campaign-for-each-date-the-shop-keeps.md) (*a plan 21 days before each kept date,
2 or 3 products chosen by Gemini*) and [ADR-0076 §3](0076-the-owner-may-choose-a-plans-products.md) · **Related:**
G121, G130, G131, D21 in [CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md)

> **In one sentence:** 4 weeks before each kept date the AI suggests what its plan is about (products that fit the
> date, or a greeting only), the owner chooses, and only then is the plan written.

## Context

Reading the plan writer's instructions (G121), the owner saw that a plan **must** promote 2 or 3 products even
when none fits the date, so a tea shop could get *"Celebrate Vesak with our tea"* (G131): *"we need to suggest
suitable things for that festival or for the special day."* A religious day such as Vesak should get a respectful
greeting, not a sales push. And the instructions never mentioned stock, so a post could say *"available now"* about
a product the owner chose while it was sold out, or *"only a few left"*, which is manufactured urgency (G130).

The owner's answer (D21): *"before the plan [is made, we] notify… create the plan under this product or under this
greeting… if approve that only create the campaign."*

## Decision

### 1. The AI suggests first, 28 days before (D21; the owner, *"4 weeks before"*)

Once a night, for every kept date **28 days away or closer** with nothing yet, GROW makes a **suggestion**, never
a plan:

| The date | The suggestion | A model call? |
|:--|:--|:--|
| **Vesak or Poson** (Poya days) | a greeting only | **no**: fixed in code *(Claude)* |
| the shop has no product in stock | a greeting only | no |
| any other date | 1 to 3 products that fit it, **or none** | one (two if refused) |
| the AI's answer refused twice | nothing suggested; the owner chooses | (two) |

**The AI may answer "none fits"** (G131): it is asked for products a shopper would buy for, or because of, the
date, and told a forced fit is worse than none. No product: the suggestion is *a greeting only*. **It answers ids
only**, from the list it was given, so nothing it writes reaches the owner's page *(Claude)*: the page's words
(*"No product of yours fits Vesak, so the AI suggests a greeting only."*) are code's.

*Why only Vesak and Poson in code (Claude):* the owner named them. Christmas, Deepavali, Ramadan and Eid, and
Avurudu are gift-giving festivals where shops do sell; for those the AI decides, and the owner can still choose a
greeting.

### 2. The owner chooses (D21)

On the plan's page, and on a Home line *"Vesak is in 28 days. Choose what its plan is about."*:

- **Use these products** (when the AI suggested some);
- **Choose other products** (the chooser of ADR-0076, 1 to 3, sold out or not);
- **A greeting only**;
- **Skip this date**: nothing is made; the page keeps the choice open until the date (*Choose again*).

**Only then is the plan written**, at once, on the job *Make it again* uses. Products chosen either way are the
owner's (`owner_products`), so *Make it again* keeps them (ADR-0076 §3).

### 3. No answer, no plan (D21)

If the owner never chooses, **nothing is written and nothing is spent**; the Home line stays until the date passes.
The first post is 14 days before the date, so 28 days gives the owner two weeks to choose.

### 4. A greeting plan *(Claude)*

A respectful greeting for the day: **a post** (for the day itself) and **a banner** (for the home page, the day
before and the day). No products, no offer, no email, no counted link (a link opens a product). Its own
instructions, `write_greeting.md`, and its own checks: every check of a campaign plan (ADR-0072 §6), **plus no
selling words** (*sale, buy, shop now, order now, discount, deal, promo*) and **no `[your offer]`**.

### 5. No stock words, in any plan (G130)

A new rule in both instructions, held in code: **never write about stock or how many are left** (*in stock, sold
out, available now, back in stock, restock, only a few left, selling fast, limited stock, while stocks last,
running out, almost gone, limited edition*). The page already says *Sold out now* from the catalogue.

### 6. G121 closed

The owner read the plan writer's instructions (2026-11-17) and kept them, with §5's rule added: the claim words stay
blocked even when true (the owner adds *organic* themselves when editing), and the tone and post days stay.

### 7. What stays

Plans made before this ADR stay as they are. *Make it again* and *Change products* on a ready plan work as before;
*Change products* on a greeting plan makes it a products plan. A legacy *Make it again* with no owner's products
still lets the AI choose from the products in stock.

## Consequences

- **The date's 21-day plan becomes a 28-day question.** A plan now needs the owner, so a shop whose owner never
  opens the console gets no plans. That is the point: no plan nobody chose.
- **Cost falls**: a suggestion is a short call with ids only, and Vesak and Poson need none; a plan is written only
  when wanted.
- **Two new prompts and evals** (Rule 4): `suggest_products.md` with `suggest.yaml`, and `write_greeting.md` with
  greeting cases in `calendar.yaml`. Injection resistance must stay 1.00.
- **Migration** `calendar_plans`: `suggestion`, `suggested_at`, `plan_kind`, `skipped_at`, `skipped_by`.
