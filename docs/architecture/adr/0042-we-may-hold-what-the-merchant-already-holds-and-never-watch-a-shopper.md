# ADR-0042 — We May Hold What The Merchant Already Holds, And Still Never Watch A Shopper

**Status:** **Accepted** — owner decision, 2026-09-25 · **not built** · **Date:** 2026-09-25 · **Extends:** [ADR-0010](0010-read-only-mvp-tools.md) · **Supersedes:** nothing · **Related:** [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md), [ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md), [blueprint-v2 §148](../../business/blueprint-v2.md), [A21](../../open-questions.md)

> **This ADR authorises a posture, not a feature.** It says what kind of data this system may hold
> about a merchant's shoppers and under what conditions. **It builds nothing and permits nothing to
> be built on its own** — every feature that stores personal data still needs its own ADR, and the
> first of those is cart recovery, which is written separately and cites this one.
>
> **Nothing here has been implemented and no personal data is stored today.** The conditions in §3
> and §4 are requirements on a future change, not descriptions of an existing control.

## Context

**Today this system holds no identified shopper.** Not as an oversight — as a property. The widget
cannot assert who a shopper is ([A21](../../open-questions.md)), a `customer` field is refused on a
public key in the route, and the pairing surface reads product ids, answers, and **writes nothing**.
Conversation transcripts exist and may contain whatever a shopper typed, but nothing links a
transcript to a person, and PII in one is tokenised before it reaches a model.

That property is worth naming before it is traded, because three real things rest on it: the
**sovereign tier** is easy to argue when there is no shopper data to egress; a merchant's integration
needs no consent flow of ours; and *"we do not know who your customers are"* is a sentence that is
either true or it is not.

**What it costs.** Measured against the [v1 blueprint](../../archive/FiveNeurals_AI_Agents_Blueprint_v1.md)
on 2026-09-20, eight capabilities across SELL and CARE are absent, and a whole group of them fails for
one reason: **the data is not collected.** Cart recovery, churn and proactive outreach, revenue
forecasting — none is blocked by engineering. Each is blocked by this one unmade decision, and
re-arguing it inside four separate feature ADRs would produce four slightly different answers.

**The owner decided it on 2026-09-25**, in the conversation that produced this file: holding shopper
data is necessary for the product this is meant to become. This ADR fixes *which* data, on what terms,
and — the part that matters more — **which data is still excluded.**

## Decision

> **NEURA may store personal data that the merchant's own store already holds about a person the
> merchant already has a relationship with. NEURA may not create new knowledge about a shopper by
> watching one.**

That line is the whole ADR. The sections below are what it means in code.

### 1. The line is *held* versus *observed*, not *personal* versus *anonymous*

| | example | permitted |
|:--|:--|:--:|
| **Held by the merchant** | a customer's email, an order and its lines, a checkout the shopper began and left | ✅ |
| **Observed by us** | pages viewed, time on page, scroll, clicks, add-to-cart events, a session followed across a visit | ❌ |

**A merchant already has the first column** — in their admin, in their order table, in the email they
could send today without us. We become a second holder of it, which is a processor relationship and a
well-understood one.

**The second column does not exist anywhere until we create it.** Building it means a tracking script
on a shopper's browser, an identity mechanism [A21](../../open-questions.md) has no design for, and a
consent surface of our own. That is a different product with different promises, and **this ADR does
not authorise one inch of it.**

The practical consequence is worth stating plainly, because it is a limit and not a loophole:
**predictive lead scoring stays blocked by this ADR**, since scoring a visitor's intent needs the
second column. Cart recovery, churn and forecasting do not.

### 2. The merchant is the controller; we are the processor

The merchant decides why the data is held and who is contacted. We hold it and show it back to them.
**We send nothing to a shopper** — [ADR-0010](0010-read-only-mvp-tools.md) is untouched by this ADR,
and no feature built on it may message a person. A merchant-facing list that a merchant exports and
acts on in their own tool is the permitted shape.

This is a contract before it is code: **no tenant stores personal data under this ADR until a
data-processing agreement is in place with that tenant.** It is a row in the tenant record, not a
handshake.

### 3. Deletion ships with the storage, in the same change

**Not "later".** A store of people's emails with no deletion path is a liability that grows daily, and
the migration that creates the table must also create:

* a **bounded retention period**, expressed in config, with a default measured in days rather than
  never;
* a **deletion path** that runs — a job, not a documented intention;
* **removal on resolution**: when the reason for holding a record ends (the shopper completed the
  order), the record goes, rather than being filtered out of a view while remaining in the table.

**There is a warning in this repository's own history about exactly this.** `RETENTION_CONVERSATIONS_DAYS`,
`RETENTION_AUDIT_LOG_DAYS` and `RETENTION_TRACES_DAYS` have been in `.env` for weeks and **no code reads
any of them** — they were checked while writing this ADR. A retention setting nobody enforces is the
same failure shape as [ADR-0036](0036-a-run-that-measured-nothing-fails.md)'s run that measured nothing
and [the widget check that had been dead for four days](../../PROJECT_STATE.md): a control that reads
green because it never executed. **The first feature under this ADR must make those settings real or
state in its own ADR that it has not.**

### 4. Four things stay forbidden, and this ADR strengthens rather than weakens them

1. **Individual pricing.** [blueprint-v2 §148](../../business/blueprint-v2.md) removed
   willingness-to-pay pricing on EU Omnibus and GDPR Art. 22 grounds and confined any future pricing
   work to segment, inventory and time granularity. **Holding a customer's order history does not
   reopen that**, and an argument of the form *"we have the data now"* is precisely the argument §148
   rejects.
2. **Ranking what a shopper is shown, by behaviour.** [ADR-0040 §3](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)
   and [sell.md §304](../../agents/sell.md) stand unchanged. *"Customers also bought"* remains a claim
   this system may not make, and holding orders does not make it makeable — a pairing ranked by
   purchase history is a Stage 1 → 2 → 3 ramp with shadow grading in the middle, not a query.
3. **Any write to the merchant's store**, and any outbound message to a shopper.
   [ADR-0010](0010-read-only-mvp-tools.md) is untouched.
4. **Quiet accumulation.** No feature may begin holding personal data without an ADR naming the
   fields, the reason, the retention and the deletion path. **This ADR is the gate, not the key.**

### 5. Isolation and the sovereign tier are the same controls as everything else

Personal data is tenant data: Row-Level Security, the unprivileged app role, and the two-database-URL
arrangement that already exists. **No new isolation mechanism is invented for it**, because a second
mechanism is a second thing to get wrong.

On the **sovereign** tier the data never leaves the merchant's infrastructure, which is the tier's
existing promise applied to a new table rather than a new promise.

### 6. What the merchant is told

The merchant's own privacy policy must be able to name us as a processor, and the shoppers whose data
we hold have never heard of us. That is normal for a processor and it is not automatic: **the
onboarding path must hand the merchant the text they need**, and a feature that stores personal data
before that text exists is not finished.

## Consequences

**What this buys.** Three blueprint capabilities stop being blocked by an unmade decision — cart
recovery, churn and proactive outreach, revenue forecasting. Each still needs its own ADR and its own
build; none needs this argument again.

**What it costs.** *"We hold no shopper data"* stops being true the day the first such feature ships,
and it is currently a real advantage in a sovereign and EU-facing pitch. The honest replacement is
narrower and still worth saying: **we hold what the merchant already holds, we never watch a shopper,
and we never message one.**

**What gets harder.** Every future data question now has a document to be consistent with, which is
the point, and a tenant without a signed agreement becomes a tenant with a feature switched off —
which is a support path that does not exist yet.

**Reversibility.** Low. Data that has been collected has been collected, and a merchant who has come
to rely on an export will not welcome its removal. This is the least reversible decision in this
repository to date, which is the reason it is a posture ADR rather than a paragraph inside a feature.

## What this ADR does NOT decide

* **It does not authorise cart recovery**, or any other feature. That is a separate ADR which cites
  this one, and it is where the fields, the retention period and the screen are decided.
* **It does not authorise observing shoppers** — no tracking script, no behavioural events, no session
  following. A future ADR may propose it; this one deliberately does not, and
  [A21](../../open-questions.md) is still undesigned.
* **It does not decide the agreement's wording**, which is legal drafting and not an architecture
  decision.
* **It does not set a retention period.** §3 requires one and requires it to be enforced; the number
  belongs to the first feature that stores anything, where it can be argued against a real purpose.
* **It does not turn on `ORDER` or `CUSTOMER` sync.** Those entity types exist in the sync engine and
  have no rows; switching them on is a change under this ADR, not an exemption from it.
