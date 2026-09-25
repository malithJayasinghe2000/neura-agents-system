# ADR-0044 — A Shopper May Be Observed, Only When The Shop Switches It On, And Only From The Shop's Own Server

**Status:** **Accepted** — owner decision, 2026-09-25 · **not built** · **Date:** 2026-09-25 · **Amends:** [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) §1 · **Related:** [ADR-0010](0010-read-only-mvp-tools.md), [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md), [ADR-0043](0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md), [A21](../../open-questions.md), [blueprint-v2 §148](../../business/blueprint-v2.md)

> **This reverses a sentence written the same day, and the reversal is deliberate rather than a
> correction.** [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md)
> drew the line at *held versus observed* and named **predictive lead scoring** as the capability that
> line blocks. The owner accepted that, then decided the capability is wanted. **0042 is amended, not
> superseded**: everything else in it stands, and the held/observed distinction still governs every
> feature that does not opt in through this ADR.
>
> **Nothing here is built.** The parameters in §6 are guesses and are labelled as such. No shopper has
> been observed, no event has been stored, and the switch in §3 does not exist.

## Context

Lead scoring is the one blueprint capability that **is** shopper watching. There is no version of
*"who is browsing and who is about to buy"* that does not record what a person did, and
[ADR-0042 §1](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) closed
exactly that. The [v1 blueprint](../../archive/FiveNeurals_AI_Agents_Blueprint_v1.md)'s own example
request is the proof — `{"session_data": {"pages_viewed": [...], "time_on_site": 340}}` is the
forbidden payload, written into the product description three months before the rule existed.

**What is being traded.** *"We never watch your shoppers"* is currently true, and it is the clearest
difference between this product and the tools it competes with, every one of which is a tracking
company that also sells an assistant. This ADR spends that sentence. The replacement is narrower and
still worth saying: **we watch only when the shop turns it on, only from the shop's own server, and
never by default.**

**And it goes one way.** Watching can start later; it cannot be un-done afterwards. That asymmetry is
the reason the conditions below are conditions rather than intentions.

## Decision

> **A shopper may be observed — page views, searches, cart actions — but only for a tenant whose shop
> has switched it on, only through events the shop's own server sends, and never through code of ours
> running in a shopper's browser.**

### 1. What changes in ADR-0042, and what does not

**Changed:** the *observed* column opens, for tenants that opt in.

**Unchanged:** everything else. A tenant that has not switched this on is governed by 0042 exactly as
written, and a feature that wants observed data must cite **this** ADR rather than assume the column is
now generally open.

### 2. The shop's server sends. We never touch the browser.

**No script of ours runs on a shopper's page for this purpose.** The bridge already listens to the
platform's own events, already queues work, and already posts to us —
`Listeners/EntityChanged.php` and `Jobs/DeliverWebhook.php` are that pattern, built and running. This
reuses it.

Three reasons, in order of weight:

1. **The shop's server already knows.** A page was requested; nothing has to be spied on to learn that.
2. **An ad blocker cannot silently break it**, so the data is not quietly biased towards people who do
   not block scripts.
3. **One generic event shape**, mapped by each platform's bridge — the same arrangement as the nine
   endpoints, so no platform name enters our code and [Rule 1](../../../AGENTS.md) is untouched.

### 3. The switch lives in the shop and governs SENDING, not saving

**`NEURA_OBSERVE_ENABLED=false` by default**, in the shop's own configuration, exactly like
`NEURA_PAIRS_AUTO_OPEN` ([ADR-0041](0041-a-suggestion-is-delivered-in-the-panel-we-own.md)).

| switch | what happens |
|:--|:--|
| **off** | the bridge sends nothing — **the data never exists** |
| **on** | the bridge sends; we store |

**Off must mean "never collected", not "collected and discarded".** Data that reached our server and
was then thrown away is still data that reached our server: it appears in logs, in memory, in a breach
window, and in any honest answer to *"what do you hold?"* **A filter at our end is not a switch.**

**A dashboard toggle is the better product and is deliberately NOT v1.** It is recorded here in full so
the next session does not re-derive it:

* **Why it is wanted.** A merchant should not need to edit a file and redeploy to change their mind,
  and the console is where every other tenant setting will eventually live.
* **Why it cannot simply be moved.** If the authority lives with us, the shop keeps sending and we
  decide — which is precisely the "collected and discarded" shape above.
* **What it would need.** The bridge must learn its own state *from us* and stop sending: a small
  config read at boot with a cached TTL, or the enabled flag returned on an existing call. **No such
  mechanism exists today in either repository** — that is the whole of the extra work, and it is small
  but it is on both sides.
* **When.** After the feature has proven itself on one real shop. Until then the `.env` switch costs
  nothing and has the stronger property.

### 4. What is stored, and what is not

**Stored:** an opaque session identifier the shop supplies, the event type, the product or category it
refers to, and a timestamp.

**Not stored:** name, email, IP address, user agent, or anything the shop did not send for this
purpose. **An anonymous session id is still personal data** — an online identifier under GDPR — and
calling it anonymous in a conversation must not turn into treating it as non-personal in a table.

**No link to a customer record.** This ADR does not join observed events to an identified person;
doing so is a further decision with [A21](../../open-questions.md) sitting in the middle of it.

### 5. Consent is the merchant's, and the agreement must say so

**Two permissions, two people, and they are not interchangeable:**

| who | what they permit |
|:--|:--|
| the **shop owner** | whether NEURA collects at all — §3's switch |
| the **shopper** | whether they may be observed |

**The owner's switch is not the shopper's consent.** The shop needs its own consent mechanism, and the
data-processing agreement [ADR-0042 §2](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md)
requires must state that obligation explicitly. **A merchant who switches this on without a consent
banner has created our problem as well as theirs**, which is why it belongs in a signed document and
not in a tooltip.

### 6. Scoring is a points table, and every number in it is a guess

**No model.** A trained scorer needs thousands of labelled sessions — sessions that ended in a purchase
and sessions that did not — and none exists. **Rules are also what the industry ships**, frequently
under the word "AI"; this file will not repeat that.

| signal | points |
|:--|:--|
| views a product | +5 |
| views the same product again | +15 |
| reads a returns or delivery policy | +15 |
| adds to cart | +20 |
| third visit in a week | +15 |

**Illustrative, not tuned.** They are a starting shape borrowed from common practice, they have been
measured against nothing, and they must never be quoted as calibrated. The same applies to any
threshold that decides when something happens.

**A points table is also the honest choice for a second reason: it is explainable.** A merchant can be
told exactly why a visitor scored 65, which a model cannot offer and which this repository's whole
posture on evidence demands.

### 7. Retention and deletion ship with the storage

Per [ADR-0042 §3](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md), in
the same change as the table: a bounded period in config, **a job that actually runs**, and removal
when the reason to hold ends. Observed events age out fast — a page view from six weeks ago scores
nothing and is pure liability.

**The standing warning applies here too:** `RETENTION_CONVERSATIONS_DAYS`, `RETENTION_AUDIT_LOG_DAYS`
and `RETENTION_TRACES_DAYS` sit in `.env` and **no code reads any of them.** A fourth unread setting
would be worse than the first three.

### 8. Four uses stay forbidden

1. **Individual pricing.** [§148](../../business/blueprint-v2.md) stands. A visitor's score may not
   change what anything costs — that is the Art. 22 / EU Omnibus ground the blueprint already settled,
   and *"we have the data now"* is the argument it rejects.
2. **Ranking products by behaviour.** [ADR-0040 §3](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)
   stands. A paired suggestion is still chosen by the merchant's own words, never by what anyone did.
3. **Any write to the merchant's store, and any message to a shopper.**
   [ADR-0010](0010-read-only-mvp-tools.md) stands.
4. **A decision with a legal or similarly significant effect**, made automatically from a score.
   Refusing service, refusing a payment method, or withholding an offer on that basis is out.

### 9. Three phases, and the first one is the whole commitment

| phase | what | when |
|:--|:--|:--|
| **1 — collect** | events in, stored, deleted on schedule. **Nothing scored, nothing shown to a shopper** | buildable now; provable by the owner browsing their own shop |
| **2 — score** | the points table, and a console screen showing it | after phase 1 holds |
| **3 — act** | context handed to the agent, or a live list for the merchant | **needs real shoppers** |

**Phase 1 can be verified honestly on the test shop and phase 3 cannot.** The owner browsing their own
storefront proves the pipe: events arrive, the score computes, the screen renders, deletion works.
**It cannot prove that a score of 65 means anyone is about to buy** — that needs many real people, some
of whom bought and some of whom did not, and the person acting out the sessions already knows the
answer.

### 10. The falsification test

**If no merchant ever switches it on, delete the feature** — the collector, the table and the screen.
Not "add a model", not "tune the points". The same test
[ADR-0040 §6](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md) and
[ADR-0043 §8](0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md) carry.

## Consequences

**The sentence changes.** *"We never watch your shoppers"* becomes *"we watch only if your shop turns
it on"*. Honest, and weaker. Anyone quoting the old sentence after this ships is quoting a claim the
product no longer supports.

**The sovereign tier still holds** — observed events stay on the merchant's infrastructure there, like
everything else — and it becomes the tier where this argument is easiest.

**New obligations arrive the first time a merchant switches it on**, not when the code merges:
deletion requests, retention enforcement, and a breach surface that did not previously exist.

**Work is roughly 80% ours.** The bridge side is one listener reusing `DeliverWebhook`; ours is an
endpoint, a table, a migration, retention, deletion, scoring, a console screen, tests and a browser
gate. **The 20% repeats once per platform**, which is the cost [ADR-0041](0041-a-suggestion-is-delivered-in-the-panel-we-own.md)
worked to avoid and which is accepted here deliberately.

**Reversibility: none, for data already collected.** The switch can be turned off and the table
dropped; the fact that people were observed cannot be undone.

## What this ADR does NOT decide

* **It does not open the observed column generally.** A tenant without the switch is governed by
  [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) unchanged,
  and a future feature wanting observed data cites this ADR explicitly or does without.
* **It does not put the switch in the console.** §3 records the design, the obstacle and the trigger
  for moving it; v1 is the shop's `.env`.
* **It does not join observed events to an identified customer.** That needs [A21](../../open-questions.md)
  and another ADR.
* **It does not authorise a model.** §6 is a points table; replacing it is a change with an eval
  attached, under [Rule 4](../../../AGENTS.md).
* **It does not authorise the agent to speak first.** Phase 3 hands *context* to an assistant a shopper
  has already opened. A proactive pop-up is still [ADR-0040](0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)'s
  excluded case.
* **It does not set the retention period or the scoring thresholds.** Both belong to the build, argued
  against a real purpose.
