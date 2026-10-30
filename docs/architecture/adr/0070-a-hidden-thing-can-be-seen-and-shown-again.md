# ADR-0070 · A Hidden Thing Can Be Seen, And Shown Again

**Status:** **Accepted** · the owner, 2026-10-30 (R66: build D13 now, no mockup) · the design is Claude's · **built 2026-10-30** · **Date:**
2026-10-30 · **Amends:** [ADR-0068](0068-grow-shows-what-shoppers-asked-for-that-the-shop-does-not-sell.md) §5 ·
**Related:** [ADR-0069](0069-shoppers-asked-for-what-the-build-decided.md), console.md §3.12, D13

> **In one sentence:** on *Shoppers asked for*, the things the owner hid are listed under the page in a closed
> *Hidden* section, each with **Show again**, and the grey *Hidden.* row has **Show again** too, so a *Hide* pressed
> by mistake is undone in one click.

## Context

ADR-0068 §5 gave *Hide* no list and no undo: a hidden thing came back only when 2 more shoppers asked for it. The
owner's first real test (2026-10-30, D13) found the gap at once: there is no way to see what was hidden, or to take
back a *Hide* pressed by mistake. The owner also asked about a *Noted* mark; Claude's view, which the owner did not
contest: *Hide* already means *I have seen it*, so a second button would do the same thing.

## Decision

### 1. What the *Hidden* section lists

The things that **would be on the page if they were not hidden**: a hidden label that 2 or more shoppers asked for in
the last 30 days, counting every ask (before and after *Hide*), and that is not on the page already (one that came
back by itself is shown once, on the page). So **Show again always brings the thing back**, and a hidden thing whose
asks age past 30 days leaves the section too: there is nothing left to show. Each row: the thing, *A shopper asked:
"[question]"*, *"Asked by [n] shoppers · hidden on [date]"*, and **Show again**.

### 2. *Show again* forgets the *Hide*

It deletes the shop's `wanted_hides` row for that label, so every ask counts again, on the page, on Home and in *See
the chats*. `DELETE /v1/console/shops/{id}/wanted/hidden/{label}`, behind `shop:wanted:read` like *Hide* (the Owner
only, R61); a label that is not hidden is **404**. Who pressed *Show again* is logged, not stored: the row it would
be stored on is the one deleted, and *Hide* records who pressed it next time.

### 3. Where it sits

Under the list (or under the empty box), a closed section **Hidden ([n])**, shown only when [n] is at least 1. The
page's route returns `hidden` beside `items`, so one call fills both. *Paused* changes nothing here. The grey
*Hidden.* row gains **Show again**, which puts the row back as it was.

### 4. Only this page

*Missing from your pages* has no *Hide*: its button is *I added it*, which says the page was fixed, and a list of
fixed questions is a different idea. It stays open in D13.

## Consequences

- One more click target per hidden thing; nothing new is stored, and no table changes.
- A hidden thing's own row on the page still waits for 2 shoppers after *Hide* (ADR-0068 §5 is unchanged); only the
  undo is new.

## As built (2026-10-30)

`WantedRepository.hidden` and `show_again` (`neura_agent_core/wanted.py`; no table changes), the route's `hidden`
and `DELETE …/wanted/hidden/{label}` (`console_wanted.py`), `components/wanted/hidden-things.tsx` and *Show again* on
the grey row (`wanted-row.tsx`). **Tested:** 2 data tests and 3 route tests (the hidden list is what would be on the
page; Show again brings every ask back on the page, Home and *See the chats*; a label with a space; Support and the
Developer refused; not hidden is 404), all shown failing on the old code first; `make console-check` 277 passed,
0 failed (4 new: the grey row's Show again, *Hidden (1)* closed, opened on desktop and phone, Show again from it).
**Not tested:** two people pressing Hide and Show again on the same thing at once (the last one wins).

## Alternatives considered

- **A *Noted* mark beside *Hide*.** Two buttons that both mean *seen*; refused (above).
- **Hidden things shown greyed inside the main list.** Mixes what needs a decision with what does not; refused.
- **Every label ever hidden, even with no asks left.** *Show again* would then do nothing visible; refused.
