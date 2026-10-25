# ADR-0065 · FiveNeurals May Switch Off One Feature For One Shop

**Status:** **Proposed** · owner decisions 2026-10-25, R49 to R52
([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, *R49's switch*) · not built,
mockup first · Everything marked *(Claude)* is Claude's proposal, for the owner's yes ·
**Date:** 2026-10-25 · **Amends:** [ADR-0061](0061-fiveneurals-has-an-admin-dashboard-that-sees-shop-facts-never-shoppers.md) §2
(the admin dashboard gains a fourth job) · **Related:**
[ADR-0015](0015-usage-rollups-and-budget-degradation.md), [ADR-0022](0022-scheduling-under-rls.md),
[ADR-0064](0064-grow-shows-what-shoppers-asked-that-the-shop-s-pages-do-not-say.md)

> **In one sentence:** in the admin dashboard, FiveNeurals can switch off one feature for one shop, and on
> again, at any time; the first and only feature with a switch is GROW's night AI check, and off means no
> chat is read and nothing is spent, then or later.

## Context

GROW's night check (ADR-0064 §6, built 2026-10-25 as piece 1c) calls a model in the background for every
shop with GROW. Its cost is bounded (a free word check first, R47; at most 300 replies a night; the shop's
daily hard budget, ADR-0015), but **not measured**: there are no real chats. The owner (R49): costs may rise
later, so FiveNeurals needs a way to stop it.

Today the only lever is the assistant itself: a shop's assistants are chosen **once, at approval** (ADR-0061
§7), and there is no way to change them afterwards except by hand in the database (AD10). And unticking GROW
would stop **every** GROW feature, which the owner called *"not good"*: a later GROW feature that costs
nothing would stop with it.

## Decision

### 1. One switch per feature, per shop (R49, the owner)

A **switch** is one feature of one assistant, for one shop: **on** or **off**. It is changeable at any time.
A feature with no switch, or a shop with no record for it, is **on**: a switch is a way to stop something,
never a second place where a feature must be turned on.

### 2. Only FiveNeurals switches, in the admin dashboard (R50, the owner: A)

Cost is FiveNeurals' risk, so the shop owner cannot switch a feature back on that FiveNeurals stopped. The
switch is on the admin dashboard's page for one shop (ADR-0061 §8, screen 2), for a shop that is **approved**
and has the assistant. No shop role sees the switch or can change it.

### 3. The first feature with a switch is GROW's night check (R51, the owner: A)

Only `grow.gaps`, *Missing from your pages*' night AI check. SELL's model pairing (ADR-0045) gets none now.

**An agent declares its switches in its manifest** *(Claude)*: a key and the words the admin reads, e.g.
`grow.gaps` = *"Missing from your pages: the night AI check"*. The API lists a shop's switches from the
manifests of the assistants it has, so `neura-api` never names an agent, and a later feature adds a switch
with one line in its manifest and one check in its own code.

### 4. Off means nothing is read, then or later (R52, the owner: A)

- **While off**, the night job still runs once a day, checks the switch first (before the budget, before any
  query of the chats) and **calls no model and reads no chat**. It books tomorrow, so switching on needs no
  booking *(Claude)*.
- **Switched on again, the check starts from that moment.** Chats from while it was off are never read: off
  was chosen to save that money. The scan starts from the later of its own last mark and the moment the switch
  went on *(Claude: exact, rather than a nightly mark that could leave up to a day of off-time to be read)*.
- **What was already found stays.** The shop's page keeps its rows, which still age out after 30 days
  (ADR-0064), and says the check is **paused**. The words are fixed by the mockup.

### 5. Stored as a shop fact, recorded with who changed it *(Claude)*

- A new table, **`tenant_switches`**: shop, feature key, on or off, when it changed, and the admin who changed
  it. Under the shop's own row-level security (ADR-0008), like every shop table. One row per shop and feature;
  no row means on.
- **The change is written in the shop's own session after the admin check**, exactly as Approve is (ADR-0061
  §6), and recorded in **the shop's record** (`config.change`, `switch.off` / `switch.on`, the admin as the
  actor).
- **ADR-0061 §1 holds:** a switch is a shop fact, not a shopper's. The admin's cross-shop function may return
  a shop's switches; it gains no grant on any table holding a chat, a shopper or a catalogue, and the grant test
  keeps checking that.
- A route: **`PUT /v1/admin/shops/{tenant_id}/switches/{key}`** with `{ "on": true | false }`. An unknown key,
  or a key of an assistant the shop does not have, is refused with a plain sentence and changes nothing. Setting
  a switch to the state it already has changes nothing and records nothing.

### 6. Not decided here

A switch the shop owner may use; switches for SELL or CARE; an email to the shop when a feature is switched
off; switching a whole assistant off after approval (AD10's first framing); a limit on spend per feature.

## Tests

**Written first, failing on the old code:** a shop with no switch record has the night check on; switched off,
the night job calls no model, reads no chat and books tomorrow; switched on again, it reads only replies after
that moment, never those from while it was off; the route refuses a non-admin (404) and an old admin sign-in
(401 `ADMIN_SIGN_IN_AGAIN`), an unknown key and a key of an assistant the shop lacks; a change is recorded with
the admin as the actor, and a no-op records nothing; the cross-shop role still reads no table outside ADR-0061
§1. **In headless Chrome:** the admin shop page with the switch, and GROW's page when paused, at desktop and
phone width. **No AI run:** a switch reaches no model. The night check's eval is unchanged.

## Consequences

- **FiveNeurals can stop a cost in two clicks**, for one shop, without stopping the rest of the assistant.
- **The admin dashboard gains a fourth job** (ADR-0061 §2), and AD10 is answered for features, not for whole
  assistants.
- **A shop's owner sees that the check is paused and cannot undo it.** Asking FiveNeurals is the way back.
- **A new table** and a migration (`make migrate`).
