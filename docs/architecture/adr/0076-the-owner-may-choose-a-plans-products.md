# ADR-0076 · The Owner May Choose A Plan's Products

**Status:** **Accepted** · the owner's decisions 2026-11-02, R124 to R127 (D20) · everything marked *(Claude)* is
Claude's, decided while building · **no mockup** (R127: *"a little improvement, build it directly"*) · **built
2026-11-02** · **Date:** 2026-11-02 · **Changes, in part:**
[ADR-0072 §5](0072-grow-plans-a-campaign-for-each-date-the-shop-keeps.md): *"2 or 3 products to promote, chosen by
Gemini"* · **Related:** [ADR-0050](0050-the-shop-owner-may-choose-a-products-suggestions.md) (the same principle:
the owner's choice wins over the model's), [ADR-0074](0074-grow-counts-the-clicks-on-the-links-an-owner-posts.md)
(a post's link opens one of the plan's products), G125

> **In one sentence:** on a ready plan the owner may add, replace or remove products, 1 to 3, any the shop sells,
> sold out or not, and the plan is written again around exactly those; a later *Make it again* keeps them.

## Context

While G125 was being explained, the owner saw that a plan's products are the AI's alone: *"need a way to pick
products for this plan… for Avurudu, select fire crackers"* (D20). The owner knows what sells for a date; the AI
knows only titles and categories. ADR-0072 left the owner one lever, *Make it again*, which asks for a fresh plan
and hopes for other products.

## Decision

### 1. Change products, after the plan is made (R124)

On a ready plan, beside *Products to show*: **Change products** opens *Products for this plan*: the plan's products,
each with **Remove**; **Add a product** (a list of the shop's products, with a search box once there are more than
20); **Write the plan again** and **Cancel**. Replace is remove and add. **The plan is written again at once**, as
*Make it again* is (one model call, two when the first answer is refused); while it is made, the page says so.

**When a draft was edited it asks first**: *"Your edits will be replaced. Write the plan again?"* *(Claude, as
*Make it again*, R102)*.

### 2. 1 to 3 products (R125), sold out or not (R126)

At least one, at most three: the posts stay short; a fourth product gets its own post with *Make a link*. **Any
product the shop sells** (published, with a page of its own), and **a sold-out one says *Sold out now*** in the list,
on the plan and on its card: a restock may come before the date, and the owner decides. **The AI's own picks stay in
stock only** (ADR-0072 §5).

### 3. Kept on the plan *(Claude)*

The owner's products are stored on the plan (`calendar_plans.owner_products`), so **a later *Make it again* keeps
them**, and the page says *"Chosen by you. Make it again keeps them."* A chosen product that has left the catalogue
by the time the plan is written is left out; if none is left, the AI chooses from the products in stock, as before.

### 4. The model is given exactly those, and code holds it to them *(Claude)*

The model is given the owner's products in place of the 100 in stock, and told to choose that many; **the check in
code refuses an answer that leaves one out or adds another** (the *product* refusal, retried once with its reason).
The prompt's words are unchanged; *"Choose 1 product."* is now singular. The facts it is given (*Act on this first*)
are the same as before.

### 5. Who, and when

The Owner and Support (`shop:calendar:write`, R86); never the Developer. **Refused while FiveNeurals has paused the
plans, and once the date has passed** (R103), as *Make it again*.

### 6. G125: why *Act on this first* is empty *(Claude, the owner's earlier yes to the sentence)*

A plan now stores how many facts it was given (`facts_given`). With none chosen: given none, the page still says
*"Your shoppers haven't asked about anything for this yet, so this plan is from your products alone."*; given some
(or a plan made before this was stored), *"Nothing your shoppers asked fits this date, so this plan is from your
products alone."*

## What was tested

`tests/unit/test_grow_campaign.py` (every chosen product and no other; one product, in the singular; `facts_given`);
`tests/integration/test_grow_plans_postgres.py` (the owner's products reach the model, a sold-out one too, the first
answer that swapped one refused, kept for *Make it again*; a chosen product gone from the catalogue left out);
`tests/integration/test_console_calendar.py` (the route's refusals: none, four, the same twice, one not in the shop,
paused, passed; the job booked at once; *Sold out now* in the chooser; the plan says what is sold out);
`make console-check` (the panel, adding a sold-out product, three at most, removing, and *Write the plan again*
refused while paused, nothing kept; the G125 sentence). **The Gemini eval (cloud-prod), `calendar.yaml`, now 12
cases** (two new: one chosen product, sold out, for Avurudu; three chosen, a mug among two teas, for Christmas):
**12 of 12, injection resistance 1.00**, 2026-11-02. Synthetic cases (CLAUDE.md §4).

**Not tested:** a real owner changing a real plan; the cost of plans written again often.

## Consequences

- The owner's choice now wins over the model's on the calendar, as it does for paired suggestions (ADR-0050).
- A plan can promote a product that is sold out on its day. The page says *Sold out now*; whether it is restocked is
  the owner's.
- Each change is a model call, as each *Make it again* is; FiveNeurals' switch (ADR-0065) still pauses both.
