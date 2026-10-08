# ADR-0043 — A Recovery List Is A Fifth Surface, And The Merchant Sends The Email

**Status:** **Accepted** — owner decision, 2026-09-25 · **not built** · **Date:** 2026-09-25 · **Extends:** [ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md), [ADR-0009](0009-generic-commerce-interface.md) · **Requires:** [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) · **Reopens:** the cart-recovery exclusion in [CLAUDE.md](../../../CLAUDE.md) · **Related:** [ADR-0010](0010-read-only-mvp-tools.md), [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md), [console.md §2](../../console.md)

> **Nothing here is built.** This records a design the owner and one session reached in conversation on
> 2026-09-25, argued before code exists rather than after.
> **[ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) was
> accepted the same day**, which is what makes this buildable at all — every row it stores is personal
> data. **Accepted does not mean scheduled:** see Consequences — decided now, built when there is
> traffic.
>
> **It reopens a decision [CLAUDE.md](../../../CLAUDE.md) records as closed** — *"checkout and cart
> recovery are excluded and are not re-openable"* — and says so in its title line rather than in a
> footnote. §1 is the argument for why the reopening is narrower than the exclusion assumed.

## Context

The [v1 blueprint](../../archive/FiveNeurals_AI_Agents_Blueprint_v1.md) lists **Abandoned Cart
Recovery** under SELL. It has been excluded since [ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md),
and the exclusion was right for the version that was being excluded: an agent that watches a shopper
abandon a basket, waits, and sends them a message. That needs identity ([A21](../../open-questions.md)),
behavioural events, a scheduler over a shopper's session, an outbound channel, and a write — **five
things this system does not have and four it does not want.**

**A different version needs none of them**, and the conversation of 2026-09-25 found it by removing
things rather than adding them:

| | the excluded version | this ADR |
|:--|:--|:--|
| Who is watched | the shopper, continuously | **nobody** |
| Who is identified | us, via a tracking mechanism | **the merchant already knows them** |
| Who decides the moment | our scheduler | **the merchant** |
| Who sends | us | **the merchant, in their own tool** |
| What we write to the shop | a message, a coupon | **nothing** |

What is left is **a list on a screen**. That is a surface, not an agent, and it is the second time
SELL has gained one this way — [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)
took the reachable half of cross-sell by asking which parts needed identity and dropping the rest.

## Decision

> **A merchant-facing recovery list is a fifth SELL surface: the checkouts that have a contactable
> owner and never became an order, shown to the merchant, exported by the merchant, acted on by the
> merchant. We store the rows. We send nothing, to anyone, ever.**

### 1. It is a checkout, not a cart — and that choice solves the identity problem instead of fighting it

**An abandoned cart usually belongs to nobody.** Verified against the test shop's own schema:
`cart.customer_id`, `cart.customer_email` and `cart.is_guest` are all nullable, and Bagisto sets
`is_guest = 1` for anyone who has not signed in. **Sign-in happens at checkout, and an abandoned cart
is by definition one that never reached checkout** — so the shopper we would most want to contact is
precisely the one who left no way to contact them.

Filtering the list to rows that have an email is the same insight, and naming the stage is the cleaner
form of it. **The definition is written generically, and that is a Rule 1 requirement rather than
style:**

> **a cart with a contactable owner that has not become an order**

That sentence is true of a Shopify abandoned *checkout* (a first-class object with an email on it), of
a Woo cart with an email captured at checkout, and of a Bagisto cart where `customer_email` has filled.
**No platform's vocabulary enters our code.** On the test shop the distinction is one non-null field,
not a second table — so choosing the checkout stage costs nothing to implement and removes a filter
whose yield nobody has measured.

### 2. The shop declares `cart.read`, and a shop that does not simply has no such screen

`Capability.CART_READ` has existed in `neura_domain.enums` since the capability set was written and
**nothing has ever used it.** This is what it was reserved for.

**The Generic Commerce Interface gains an optional endpoint, not a mandatory tenth one.** Capability
negotiation already computes a tenant's tools from what its adapter declares, and the same mechanism
governs this screen: declared → the feature exists; not declared → it does not, with no error and no
empty screen implying a fault. **A merchant who wants an assistant and not a recovery list implements
nothing new**, which is the property that keeps integration cost honest.

This extends [ADR-0009](0009-generic-commerce-interface.md)'s spec. The endpoint's shape is not fixed
here beyond the requirement that it return carts with their contact field and their line products, and
that it is readable in pages.

### 3. What is stored, and it is the latest state only

Per [ADR-0042 §3](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md),
storage and deletion ship in the same change. For each row: the store's own identifier for the
checkout, the contact field, the product ids and quantities, the value, and the timestamps the shop
reports.

**Not a history.** A v1 row is a snapshot of where the checkout stands now — **what is still unbought**
— and is replaced when the shop reports a change. The owner raised the more interesting case on
2026-09-25: a shopper who buys two of three items has *rejected* the third, and knowing which one is
worth more than knowing the cart existed. **That is true and it is deliberately not in v1**, because
recording what was removed means keeping the cart over time, which is a larger data footprint and a
different privacy argument than this ADR makes. It is a second ADR, and it should be written when
somebody has looked at a real list.

**Three deletion triggers, all required at build time:**

1. **Resolution** — an order appears for that contact after the checkout. The row goes, rather than
   being hidden from a view while remaining in the table.
2. **Retention** — a bounded period, enforced by a job that runs. `RETENTION_*` settings exist in
   `.env` and **no code reads them**; this feature makes one real or says in PROJECT_STATE that it did
   not.
3. **Request** — the merchant, or a person exercising a right through the merchant, can have a row
   removed.

**The resolution match is a heuristic and is labelled one.** Matching an order to a checkout by
contact and time is wrong if the shopper completes the purchase under a different email. The failure
is visible and cheap — the merchant sees a row for someone who has already bought — which is the
failure mode [ADR-0040 §4](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)
also chose: **visible and ignorable, never invisible and believed.**

**`ORDER` sync must be switched on.** The entity type exists in the sync engine and has no rows.
Nothing in this feature works without it, and turning it on is a change under ADR-0042 rather than an
exemption from it. **`CUSTOMER` sync is not required for v1** and stays off.

### 4. The merchant sends. We do not.

**No email, no SMS, no push, no message of any kind leaves this system towards a shopper.** The screen
shows the list and exports it; the merchant sends from the tool they already use.
[ADR-0010](0010-read-only-mvp-tools.md) is untouched — we write nothing to the shop — and no approval
queue is required, because there is no action to approve.

This is also what keeps the legal shape simple: the merchant is the controller and holds the marketing
consent, we are the processor, and the agreement [ADR-0042 §2](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md)
requires is in place before a single row is stored.

### 5. Nothing here ranks, scores or predicts

The list is **facts in an order the merchant chooses** — value, age, number of items. **No propensity
score, no "likely to convert", no model.** This is the third SELL surface with no model of ours in it,
and the safety argument is the same as the other two: the policy engine and tenant isolation, never
"a persuaded model achieves nothing".

If the list ever suggests a *product* to pair with an abandoned checkout, it uses
[`pairing/select.py`](../../../agents/sell/src/neura_agent_sell/pairing/select.py) **unchanged** —
it is pure, it ranks terms rather than products, and [ADR-0040 §3](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)'s
ban on claims about behaviour applies to an email exactly as it applies to a cart page.

### 6. The parameters, and they are guesses

| parameter | v1 value | why it is a guess |
|:--|:--|:--|
| when a checkout counts as abandoned | **1 hour** | borrowed from common industry practice (1h / 24h / 72h sequences), not measured here |
| how long a row is kept | **set at build time**, days not never | no purpose exists yet to argue a number against |
| how the list is ordered by default | **value, highest first** | plausible; untested |

**Borrowed is better than invented, and neither is measured.** These must not be repeated as tuned,
and the first real shop should be expected to move all three.

### 7. It is a sixth console screen, and [console.md §2](../../console.md) says five is the discipline

*"The temptation is eleven screens; the discipline is five."* That line was written to stop exactly
this, so breaking it is a decision and not an oversight. The argument for breaking it: the five
existing screens are all about **the agent's own behaviour** — evidence, grading, transcripts — and
none is about the merchant's commerce. This is the first screen of a second kind, and its browser
coverage joins `make console-check` rather than sitting outside it.

### 8. The falsification test

**If merchants do not export the list, delete the screen.** Not "improve the ranking", not "add a
model" — delete it. The same test [ADR-0040 §6](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)
carries, and it is the only honest way to find out whether a feature nobody has used is worth its
maintenance.

## Consequences

**The unknown that decides everything.** Nobody knows how many of a real shop's checkouts are abandoned
with a contact attached. **It could be a healthy list or three rows a week**, and it depends on the
merchant's own storefront — whether they capture an email early, whether their checkout asks for it
first. **This feature's value is set by somebody else's shop design, not by our code quality**, and a
merchant with no email capture should be told that rather than shown an empty screen.

**It cannot be validated here.** There is no merchant, no shopper and no traffic
([B2](../../open-questions.md)). Seeded carts prove the code works; they cannot prove a merchant acts
on the list or that a shopper returns. **Every SELL surface so far works on day one for any shop with
no history. This one does not** — it is the first feature in this product that is worthless until it
has been running for weeks.

**Therefore: decide now, build when there is traffic.** The reasoning is fresh today and will not be
in a month; the screen can wait for somebody to look at it.

**What it costs.** A sixth screen to maintain, an optional endpoint each merchant must implement to
benefit, and the first personal data this system has ever held.

## What this ADR does NOT decide

* **It does not authorise sending anything to a shopper** — no channel, no scheduler, no message.
  That remains excluded and would be a superseding ADR.
* **It does not authorise tracking.** No script, no events, no session following.
  [ADR-0042 §1](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md)'s
  observed column stays closed, and **predictive lead scoring stays blocked.**
* **It does not record what a shopper removed from a cart.** §3 — a second ADR, after a real list.
* **It does not fix the endpoint's payload**, the retention number, or the screen's layout.
* **It does not turn on `CUSTOMER` sync**, which v1 does not need.
* **It does not claim a recovery rate.** No figure in this file is a measurement, and none may be
  quoted to a merchant.
