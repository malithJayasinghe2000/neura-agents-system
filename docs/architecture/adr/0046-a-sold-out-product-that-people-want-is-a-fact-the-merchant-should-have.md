# ADR-0046 — A Sold-Out Product That People Want Is A Fact The Merchant Should Have

**Status:** **Accepted** — owner decision, 2026-09-25 · **stage 1 approved to build; stages 2 and 3 are not** · **not built** · **Date:** 2026-09-25 · **Extends:** [ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) with a sixth surface · **Requires:** [ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md) for stage 1, [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) for stage 2, [A21](../../open-questions.md) for stage 3 · **Related:** [ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md), [ADR-0033](0033-care-answers-what-the-store-has-sell-helps-the-shopper-choose.md), [ADR-0043](0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md)

> **Only stage 1 is approved to build.** Stages 2 and 3 are recorded in full so the next session does
> not re-derive them, and each names the thing it is waiting for. **Nothing here is built**, and the
> screen this describes does not exist.

## Context

**SELL loses a sale silently, several times a day, and nobody ever finds out.** A shopper asks for
something the store does not have or cannot ship, [ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md)'s
honest miss fires — *"this is one search, not a statement about what the store carries"* — and the
conversation ends. **That answer is correct and it is a dead end.** The merchant learns nothing: not
that the question was asked, not how often, not by whom.

The same thing happens without a conversation at all. A shopper opens a sold-out product page, sees it
is unavailable, and leaves. **The shop's own analytics may show the page view; nothing anywhere
connects it to "this is demand for stock I do not have".**

**This surface turns both into a fact the merchant can act on.**

### Why it is SELL's, and the rule that makes it arguable

[ADR-0033](0033-care-answers-what-the-store-has-sell-helps-the-shopper-choose.md) says **CARE answers
what the store *has*; SELL helps the shopper *choose*.** *"Is it in stock?"* reads like CARE, and the
objection is fair.

**It is SELL's because of where it fires**: on SELL's own failed recommendation, the
[ADR-0027](0027-a-constraint-miss-is-not-an-empty-store.md) path that already exists in SELL's graph.
SELL tried to help someone choose and could not. And the purpose is the same as
[ADR-0043](0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md)'s: **recovering
a sale, not answering a question** — which is the line that put the recovery list in SELL rather than
in MIND.

## Decision

> **A sixth SELL surface: one merchant-facing screen listing sold-out or unfindable products by how
> many people wanted them, with the contactable ones named underneath. We store the interest. We show
> it. We contact nobody.**

### 1. What the merchant sees

```
SOLD OUT — people want these

Cashmere Crew Jumper                47 interested
   40  viewed the page
    5  logged-in customers      → contactable
    2  asked in chat            → contactable

Rain Shell — blue                   12 interested
    9  viewed the page
    3  asked in chat            → contactable
```

**One number to decide restocking with, and the contactable people underneath it.** Those are two
different jobs — *what do I reorder* and *who do I tell* — and they belong on one screen because the
merchant answers them in the same minute.

### 2. Three inputs, three different permissions — and this is the whole structure of the ADR

| input | what it yields | data is | governed by | stage |
|:--|:--|:--|:--|:--:|
| **A shopper views a sold-out product page** | a count, no identity | **observed** | [ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md) — the shop's switch | **1** |
| **A shopper asks in chat and leaves an email** | what they wanted + an email | **volunteered** | [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md), which does **not** yet cover volunteered data | 2 |
| **A logged-in customer views it** | an identified customer | **held** by the merchant | needs [A21](../../open-questions.md)'s identity mechanism, which does not exist | 3 |

**They are not one feature with three sources. They are three features on one screen**, and the screen
is the only thing they share.

### 3. Stage 1 — counts, and it is worth shipping alone

**No identity, no email, no consent question, nothing to delete on request.** A count of views against
a product that cannot be bought.

> *"The sold-out Cashmere Jumper was viewed 47 times this week."*

That sentence is useful to a merchant on its own, and it is the cheapest thing in this ADR: it rides on
the event stream [ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)
already defines — the shop's server sends a product-view event — plus a filter for *was it buyable at
the time* and a screen. **No new collection mechanism, no new permission.**

**It inherits ADR-0044's switch**: a shop that has not turned observation on has no counts and no
screen, and that is a correct empty state rather than a fault.

### 4. Stage 2 — the chat ask, and the gap it exposes

SELL's miss path gains one offer: *"want me to tell the shop you asked?"* The shopper types an email;
we store it with what they were looking for.

**ADR-0042 does not cover this, and the gap is real.** It permits data the merchant **holds** and
(via 0044) data we **observe**. An email a shopper types into our own chat box is **neither** — it is
*volunteered*, a third category that no ADR names.

**It is the easiest of the three to justify and it still must be written down.** A person typing an
address into a box that says *"tell me when it's back"* is the clearest consent that exists — more
explicit than a cookie banner, given for one stated purpose. **Adding that category is a one-line
amendment to ADR-0042 and it is a prerequisite for stage 2, not a footnote to it.**

Two conditions come with it: the email is stored **only** against that interest and used for nothing
else, and **we still send nothing** — the merchant contacts them, exactly as in
[ADR-0043](0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md).

**A known abuse, accepted with its mitigation:** someone can type another person's address. The
merchant's message must therefore say *"you asked us about X"* and carry an unsubscribe — a controller
obligation, named in the agreement rather than solved in our code.

### 5. Stage 3 — the logged-in customer, and why it is last

If a signed, short-lived token from the merchant's server told us *"this is customer 385"*, a
logged-in shopper viewing a sold-out product would be contactable without typing anything.

**That token does not exist, and it must not be invented here.** [A21](../../open-questions.md) is
explicit that the shape is *probably* a short-lived token the merchant's server mints — and that it is
**an ADR and a security review**, being *"the one place in this system where inventing something
plausible would be worst."* Get it wrong and a browser that can name its own customer reads anyone's
orders.

**So stage 3 is blocked on a security decision, not on this feature**, and it is recorded here only so
the screen is designed with a column it can later fill.

### 6. What this surface never does

* **It never contacts a shopper.** No email, no SMS, no push.
  [ADR-0010](0010-read-only-mvp-tools.md) untouched; no approval queue needed, because there is no
  action to approve.
* **It never writes to the shop.** It does not reorder stock, change a price or edit a product.
* **It never ranks products by behaviour for a shopper.**
  [ADR-0040 §3](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md) stands — these
  counts are shown to the merchant and never used to order what a shopper is offered.
* **It never tells a shopper how many other people want something.** *"12 people are looking at this"*
  is manufactured urgency, and it is the same class of claim as *"customers also bought"*.
* **It runs no model.** A count is a count.

### 7. The parameters, and they are guesses

| parameter | v1 | why it is a guess |
|:--|:--|:--|
| the window a count covers | **7 days** | plausible; no shop observed |
| how long an interest row is kept | **days, set at build** | [ADR-0042 §3](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) requires a bound and a job that runs |
| when a row disappears | **when the product is buyable again** | the reason to hold it has ended |

The `RETENTION_*` warning applies here as everywhere: three settings sit in `.env` and **no code reads
any of them.**

### 8. The falsification test

**If merchants look at the screen and restock nothing, delete it.** Not "add a forecast", not "add a
model". Same test as [ADR-0040 §6](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)
and [ADR-0043 §8](0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md).

## Consequences

**SELL gains a sixth surface and a second merchant-facing one.** Of six, four face a shopper or a
machine and two face the merchant — the agent is becoming a product with an admin side, and that is
worth noticing rather than drifting into.

**It is the seventh console screen**, against [console.md §2](../../console.md)'s *"the discipline is
five"*. Broken twice now, in one day, both times deliberately and both times recorded.

**Stage 1 is the cheapest feature designed this session** — an event filter and a screen, no identity,
no consent, no model, nothing to delete on request. **Stages 2 and 3 are each gated on something
outside this ADR**, and neither should be smuggled in as "while we're here".

**The value is unmeasured**, like everything else here: no merchant has seen this screen, and *"47
views"* is a number this ADR has never observed.

## What this ADR does NOT decide

* **It does not approve stages 2 or 3.** Stage 2 needs the volunteered-data amendment to ADR-0042;
  stage 3 needs [A21](../../open-questions.md) resolved by its own ADR and security review.
* **It does not amend ADR-0042.** §4 says what the amendment must contain; writing it is a separate
  decision.
* **It does not design the identity token.** Naming its shape here would be exactly the invention A21
  warns against.
* **It does not let the shopper be told anything about demand**, and it does not surface counts to the
  recommendation surfaces.
* **It does not set the window, the retention period or the screen's layout.**
