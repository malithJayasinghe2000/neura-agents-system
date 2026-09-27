# ADR-0048 — Observation Phase 1: What The Build Decided, And Which Retention Settings Are Still Not Real

**Status:** **Accepted** — owner decisions, 2026-09-26 · **built and run against the real shop the same day** · **Date:** 2026-09-26 · **Implements:** [ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md) phase 1 · **Discharges, in part:** [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) §2 and §3 · **Related:** [ADR-0014](0014-api-keys-and-the-rls-bootstrap.md), [ADR-0022](0022-scheduling-under-rls.md), [ADR-0046](0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md)

> **ADR-0044 left four things to the build, and ADR-0042 §3 requires the first feature holding
> personal data to say, in its own ADR, which retention settings it has *not* made real.** This is
> that ADR. Nothing here reopens 0044: the switch is still the shop's, it still governs sending, and
> nothing is scored or shown.

## Context

Phase 1 is *"collect, prove the pipe, show nothing"* (0044 §9). Building it met four questions no
document answered. The owner decided all four on 2026-09-26:

| question | decided |
|:--|:--|
| How does the shop's server prove it is the shop? | **An API key**, not a signed message |
| ADR-0042 §2's *"a row in the tenant record"* — build it now? | **Yes, and enforce it** |
| Which of the three `RETENTION_*` settings become real? | **Conversations**, plus the new events setting. Audit log and traces are written down, not built |
| What is recorded? | **Product viewed** and **added to basket**. Nothing else |

## Decision

### 1. The shop sends with a secret key holding `observe:write`

The tenant comes from the key, through the authentication path every other request already uses
([ADR-0014](0014-api-keys-and-the-rls-bootstrap.md)). **Not an HMAC signature**, although the bridge's
change notifications use one: verifying a signature means finding a per-store secret *before* the
tenant is known, which is the row-level-security bootstrap ADR-0014 solved once for keys. Solving it a
second time is a second mechanism to get wrong.

**A browser key can never hold the scope.** Refused when the key is issued, and refused again by the
route if one somehow does — 0044 §2's *"no script of ours runs in a shopper's browser"*, as code.

### 2. The agreement is a column, and three things enforce it

`tenants.dpa_signed_at` — `NULL` for every existing tenant, because none has one. Three enforcers,
so no single forgotten check can store anything:

| where | what it does without an agreement |
|:--|:--|
| issuing a key | refuses `observe:write` — **the shop has no credential to send with** |
| the route | refuses with `DPA_REQUIRED` — an agreement can be withdrawn after a key was issued |
| the retention sweep | deletes **every** observed event of the tenant |

**Withdrawing deletes in the same transaction** (`make tenant-dpa WITHDRAW=1`). ADR-0042 §3's
*removal on resolution*: without an agreement there is no reason to hold any of it.

### 3. Two events, and what is not in them

`product.viewed` and `cart.added`. **Searches are excluded by 0044 §4 itself**: it stores a product or
category and nothing else, and a search points at neither — recording one usefully means keeping what
a shopper typed. Category and policy views were not chosen.

The body is exactly §4's fields plus the shop's own `event_id`, which makes a retried delivery one row
rather than two page views. **Any other field is refused with a 400 naming it, never dropped** —
dropped is *collected and discarded*, which §3 says is not a control. The session id must be an
opaque token; the bridge sends a keyed hash of its session id and never the cookie, because the raw
id is a live credential.

### 4. Retention: seven days for events, ninety for conversations, and a job that runs

**`RETENTION_OBSERVED_EVENTS_DAYS=7`.** The longest window anything designed reads is one week —
ADR-0046's sold-out count and 0044 §6's *"third visit in a week"*. A page view older than every use
for it is, in 0044 §7's words, pure liability. A timestamp outside the window is refused at the door,
so the shop's clock cannot decide how long a row lives.

**`RETENTION_CONVERSATIONS_DAYS=90`, enforced for the first time.** A conversation *untouched* that
long is deleted with its messages and its checkpointed working state, in one transaction —
security-model.md §6.2's fan-out. `shadow_turns` is left, as `ConversationRepository.by_ids` already
documented: the graded review queue outlives the transcript. `audit_log` is left — see §5.

**The schedule without a cron.** ADR-0022 has no recurring schedule and this adds none. The
`retention.sweep` job re-arms itself daily **while the tenant holds anything**, and every write that
creates something to expire — a new conversation, a stored event — books it in its own transaction.
So *nothing can be written that no sweep is booked to delete*. Rows written before 2026-09-26 had
nothing to book one; `make retention-sweep TENANT=…` runs a pass and books the next.

### 5. What is NOT made real — ADR-0042 §3's required statement

| setting | why it is not enforced | what it would take |
|:--|:--|:--|
| `RETENTION_AUDIT_LOG_DAYS` (730) | the audit log is append-only and hash-chained; the app role is **revoked** `DELETE` on it, and deleting old rows breaks verification of every later row | a privileged pruning path **and** a chain anchor so verification still holds — its own ADR |
| `RETENTION_TRACES_DAYS` (30) | **we hold no traces.** OTel exports to an outside collector and Langfuse is off | the trace backend's own retention setting — not code of ours |

**Neither is a `Settings` field**, on purpose: a field nothing acts on is a setting that appears to
work. `.env.example` says so beside each, and `tests/unit/test_observation.py` fails if a `RETENTION_*`
line appears that is neither enforced nor on this list.

### 6. Found by the live run: a full-page cache hides page views

The test shop serves product pages from a response cache. The first hook — a composer on the product
view — fired only on the first visit after the cache was cleared; **every later view was lost
silently, most of all on popular pages**, which are the ones that stay cached. That is the bias 0044
§2 refused a browser script over.

The bridge now tags the cached copy with the product id (a header the shopper never receives) and
counts a view each time that copy is served. **Any bridge, on any platform with a page cache, has the
same problem**; the spec says so.

## Consequences

**Proved on the real shop, 2026-09-26:** off sends nothing, even to the shop's own queue; no key
without an agreement; no browser key; on, six events arrive with exactly §4's columns; an expired row
is deleted by the API's own worker, which then re-books itself; withdrawal deletes everything at once
and later events are refused and dropped — never retried, never in `failed_jobs`.

**Accepted limits, none blocking phase 1:**

* **No rate limit on the route.** Rate limits sit on chat routes only. The key is secret and
  server-held; a busy real shop is where this is measured, not guessed.
* **A tenant with two stores cannot say which a product id belongs to.** Nothing reads the events
  yet; ADR-0046 stage 1 must decide it before it counts anything.
* **A session is short.** The bridge's token lives as long as the shop's session (hours), so 0044
  §6's *"third visit in a week"* cannot be computed from it. A longer-lived visitor id is more
  tracking, and is phase 2's decision — not a cookie added quietly.
* **Consent is the merchant's.** The bridge cannot know whether a shopper agreed; 0044 §5 puts that
  in the agreement, and the bridge README says so.

## What this ADR does NOT decide

* It does not score, rank or show anything. Phase 2 is the points table; displaying is ADR-0046.
* It does not decide the audit log's retention — §5 names what that ADR must solve.
* It does not open any other event type. A third is a decision, not an enum member.
