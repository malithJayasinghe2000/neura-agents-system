# ADR-0063 · The Handover Answered By Email: What The Build Decided

**Status:** **Accepted** · built 2026-10-11 and 2026-10-12, in five pieces (`69c74cc`, `09e8a1a`, `19b50bf`,
`403b74f`, and the Gemini check below) · Everything here is Claude's, decided while building
[ADR-0062](0062-a-handed-over-shopper-may-leave-an-email-and-the-shop-answers-from-its-own.md) inside what the owner
decided (R25 to R32) and the approved mockup (canvas row 15); none of it changes a decision of the owner's ·
**Date:** 2026-10-12 · **Related:** the log's G101, G103, G104, G105, AD9; console.md §3.10 *As built*

> **In one sentence:** ADR-0062 is built as one table beside the conversations, one route the chat box calls, two
> routes the dashboard calls, and a box at the top of a waiting chat; this records the choices the ADR left to the
> build, and what was and was not tested.

## Decision

### 1. One table, one row per chat (`waiting_answers`)

- **`reach` is `email` or `customer`.** A check constraint keeps `email` empty for a signed-in customer: their
  address is the shop's, never copied here (ADR-0062 §2). Row-level security as every shop table; the conversation
  fan-out (`delete_older_than`) and the drop list (`make tenant-drop`, G76) know it.
- **Mark as answered keeps the row and clears the address**: who answered and when stay, so a chat reopened later
  says *Answered, [name] marked it, [when]*. That names a member of the shop's team, never a shopper, and goes with
  the conversation (90 days).
- **The 30 days apply to both kinds.** `retention.sweep` deletes any row still unanswered after
  `RETENTION_HANDOVER_EMAILS_DAYS`, so a signed-in customer's chat leaves the waiting list too rather than waiting
  for ever.
- **A later handover**: a signed-in customer's row reopens (they can still be reached); a typed address that was
  answered does not (it is deleted, and a chat asks once). *Asked once* is counted from `conversations.escalations`,
  which counts live handovers only, so practice mode never asks.

### 2. What the shopper reads, and how the chat box knows

- **The reply is two lines**: the first sentence, a line break, then the shop's contact line. The reply carries
  `ask_email: true`, and the chat box draws its email box between the two lines (the approved mockup). A client
  without the box still shows the whole text, and the transcript holds exactly what the shopper read.
- **The chat box's box is not a `<form>`**: the message box stays the panel's one form, so Enter in each box does
  that box's thing.
- **Shop connection's preview** now shows the first handover's words, the commonest case (G104).

### 3. The route the chat box calls: `POST /v1/conversations/{id}/email`

- **Mounted once and naming no agent**, like the dispatched chat: the key must hold `<agent>:chat:write` for the
  conversation's own agent, read as data, so no shop makes a new key.
- **The address is checked in code, not by the request model**, because FastAPI's own validation error repeats
  what was sent, and the address must never be in an error answer. Refusals: `INVALID_EMAIL` (400),
  `NOT_HANDED_OVER` (409, practice mode included), `ALREADY_WAITING` (409, the first address stands), and a
  `404` that is the same for another shop's chat and for none.
- **No audit entry when a shopper leaves an address**: the audit log records what the shop's people and the agent
  did; the row itself is the record. *Mark as answered* is audited (`escalation`, `handover.answered`, who, never
  the address).

### 4. The dashboard's routes

- `GET …/conversations?waiting=1`, and `waiting` on every row and transcript: how and since when, who answered.
  **Never the address**, so Conversations stays readable by whoever reads chats.
- `GET …/conversations/{id}/waiting` (`shop:handovers:write`): the address, or the customer's id when the shop
  cannot give it (no `customer.read`, no such customer, or no answer from the bridge), plus the email's subject
  and body, made by the server (`answer_email`) so the words live in one place.
- `POST …/conversations/{id}/answered` (`shop:handovers:write`), and `/home` gives `waiting` to a role that may
  answer and `null` to any other.

### 5. The screens (console.md §3.10 *As built*)

- **Amber counts have a dark number**: white on the mockup's amber is under 3:1 at 12px.
- **The menu reads its count again after *Mark as answered*** (a window event): `router.refresh()` alone left the
  old number until the next page, which `make console-check` caught.
- **Small words the mockup did not show**: an empty waiting list, the signed-in customer's shorter help line and
  question (nothing of theirs is stored to delete), and *as today* dropped from the *No thanks* note.

### 6. The website (G105)

The product page's sample chat showed a handover in words CARE has not said since ADR-0055. It now shows the words
a signed-in shopper reads.

## What was tested, and what was not

- **Tests written first, failing on the old code**, then: `make check` green after every piece (1700 unit, 628
  integration, eval-fast), `make test-widget` 69, `make widget-check` 14 of 14 (4 new), `make console-check`
  **219 of 219** (17 new), `make web-check` green. Desktop and 390px seen for the chat box and every new screen.
- **The Gemini check (G103) and CARE's injection suite (1.00)**: see *The AI run* below.
- **Not tested**: a real shopper (none has left an email); a real email arriving from a team member's app (the
  `mailto:` link was checked, not a mail client); the chat box against the real API in a browser (the browser
  check uses its stub; the API side has its own integration tests); a signed-in customer's address read from a real
  bridge in the browser (the integration test uses a stand-in shop; the console check's placeholder shop shows the
  fallback); the local models (the 2026-09-19 decision); Support's screens in the browser (the role is held by the
  integration tests and `make console-check`'s People section, not by the new handover section, which runs as the
  Owner).

## The AI run (G103)

**Why it was run:** the fixed handover words are stored in the conversation, and the router reads the history on the
next message; A20 showed the old words there could make CARE's router hand over every later message (G103).

**How:** `scripts/handover_history_check.py`, on Gemini (cloud-prod), against Ceylon Harvester's real bridge (read
only), the graph run in memory with the history the turn service would load: a handover's words (the first handover's
*ask*, or *your question is with our store*, each with the contact line), then an ordinary question; and once with no
history as the control. About 60 model calls in all.

| | the ask in the history | *with our store* in the history | no history (control) |
|:--|:--|:--|:--|
| **CARE**, *"Do you have green tea?"* | 3 of 3 answered | 3 of 3 answered | 1 of 1 |
| **SELL**, *"I'd like a tea for the morning"* | 6 of 8 answered | 3 of 3 answered | 1 of 1 |

**SELL's two misses were not the words:** one was Gemini timing out while the Mac slept (`sell_compose_failed: cloud
timed out`, 41 minutes into the turn, G101), after which SELL handed over as it should; the other's log was not kept,
from the same run that crawled through sleeps. **No miss was traced to the new words.** Small numbers, one shop, one
model; the local path is untested (the 2026-09-19 decision).

**CARE's injection suite, 2026-10-12, on Gemini, the Mac awake** (`caffeinate -i make eval-one D=injection
ROLE_MAP=cloud-prod`): **injection resistance 1.00, 7 of 7 cases passed**, in 30 seconds, with no sleep in the run.
The guard's rules blocked 3 turns before any model saw them; the other 4 took 7 Gemini calls (4 router, 2 reasoner,
1 groundedness check). Escalation precision and recall 1.00 (2 cases), groundedness 1.00 (1 case), no personal data
leaked (3 cases). The cases
are synthetic, as the harness itself warns, so this shows nothing got worse; it does not show the agent is safe
against a real attacker. No AI instruction changed in this build.

## Consequences

- ADR-0062 is built. FEATURES.md *Hand to a person* and *L2* say what it does and what it does not.
- **Before real shops use it, AD9** (a data agreement with every shop) **must be done**, as ADR-0062 records.
