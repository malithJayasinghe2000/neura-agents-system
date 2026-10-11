# The Merchant Console — Design

**Status:** Designed 2026-08-26. **All five v1 screens built 2026-08-27**, a sixth — **Sold out**, [ADR-0046](architecture/adr/0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md) stage 1 — a seventh — **Suggestions**, [ADR-0050](architecture/adr/0050-the-shop-owner-may-choose-a-products-suggestions.md) — and an eighth — the shop's **Home** — all **built 2026-09-27**, when the console also gained a side menu and plain words (§3.0) and Review was redesigned (§3.2); the single chat page (§3.3), Suggestions (§3.6), Sold out (§3.7), Usage and cost (§3.5) and Shop connection (§3.4, with a new **Help** page) were redesigned 2026-09-28 — `make console-check` — 91 checks in a real browser before Shop connection's (which adds 18; see PROJECT_STATE, B7, for the run still owed). · **Decision:** [ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) · **Unblocks:** A4, E1, S5, and eventually [ADR-0010](architecture/adr/0010-read-only-mvp-tools.md)

> **Read [ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) first.** It records *why* — including the three decisions a fresh session is most likely to reverse by accident: the browser never holds a tenant API key, login is built rather than bought, and `users` is deliberately not tenant-scoped.

---

## 1. What this is, in one paragraph

The screen a shop owner logs into. It shows them what their AI assistant said, lets them grade answers before those answers ever reach a customer, connects their shop, and reports what it cost. **It is the first thing in this project built for the person who pays**, and it is the keystone under four deferred features.

### 1.1 What it is not

~~It is **not** an admin panel for us~~ (superseded 2026-10-11 by [ADR-0061](architecture/adr/0061-fiveneurals-has-an-admin-dashboard-that-sees-shop-facts-never-shoppers.md): FiveNeurals gets `/admin`, which shows shop facts and never a shopper), it is **not** a replacement for the shop's own back office, and in v1 it does **not** approve anything — because nothing in the system can yet change a merchant's store ([ADR-0010](architecture/adr/0010-read-only-mvp-tools.md)).

---

## 2. Scope — v1 is five screens

Deliberately cut the way CARE's three intents were cut. The temptation is eleven screens; the discipline is five.

| # | Screen | Reads | Ships in v1 |
|:--|:--|:--|:--|
| 1 | **Sign in** | `users`, `login_tokens` | ✅ **built 2026-08-27** |
| 2 | **Conversations** | `conversations`, `conversation_messages` | ✅ **built 2026-08-27** |
| 3 | **Review** (shadow grading) | `shadow_turns`, `conversation_messages`, `document_chunks` | ✅ **built 2026-08-27 — the one that earns its keep** |
| 4 | **Shop** (on screen: *Shop connection*) | `tenant_stores`, `sync_checkpoints`, `neura_entities` | ✅ **built 2026-08-27 — read-only, see §3.4.** Redesigned 2026-09-28: a *Get set up* checklist (also `api_keys`, `tenants`, `observed_events`, `document_chunks`), and **Sync now** — the third console write, and it writes only our copy. With it, a **Help** page, *Connecting your shop* (ADR-0026 §7) |
| 5 | **Usage** (on screen: *Usage and cost*) | `tenant_usage`, `tenants` | ✅ **built 2026-08-27** — redesigned 2026-09-28 (§3.5): every part follows the period, by assistant included |
| — | **Home** — what needs the owner, and how the assistant is set up (§3.0) | nothing of its own — it reads the endpoints of Review, Usage, Shop, Sold out and Suggestions | ✅ **built 2026-09-27** — outside v1's five like the two below it. **Adds a screen and no data**: every figure on it is one another screen already shows, with its period and its server-written caveat |
| — | **Sold out** — views of products while they could not be bought ([ADR-0046](architecture/adr/0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md) stage 1, [ADR-0049](architecture/adr/0049-a-product-view-records-whether-it-could-be-bought.md)) | `observed_events`, `synced_entities`, `tenants` | ✅ **built 2026-09-27** — outside v1's five, and 0046 records breaking the discipline on purpose. Counts and sessions, never a session token; not gated by the SELL entitlement (neura-api may not learn an agent's name). **Redesigned 2026-09-28 (§3.7)**: opening it asks the shop, in one stock lookup for every product listed, whether each can be bought now — the second console call that reaches the shop, and Home never makes it |
| — | **Suggestions** — what a basket suggests with each product, and the owner's way to change it ([ADR-0050](architecture/adr/0050-the-shop-owner-may-choose-a-products-suggestions.md)) | `synced_entities`, `sell_pairings`, `sell_pairing_choices` | ✅ **built 2026-09-27** — the **second screen that writes** (after grading). Served by SELL's own routes under `/v1/sell/console/…`, so the SELL entitlement is checked inside the agent; a shop without SELL is told so. Reads the **synced** catalogue: a product the shop added since the last sync is not listed until a sync runs. **Redesigned 2026-09-28 (§3.6)**: opening a product previews what a basket shows — the only console call that reaches the shop, and never a model run |
| 6 | Security | `audit_log` | v1.1 — closes **S5** |
| 7 | Settings & keys | `api_keys` | v1.1 |
| 8 | Approvals | — | **blocked** by [ADR-0010](architecture/adr/0010-read-only-mvp-tools.md) |

**Build order is 1 → 3 → 2 → 4 → 5**, and Review is second on purpose. It is the only screen that produces something the project does not already have: **real graded turns**, which is the sole route out of **E1** (every golden case is synthetic today). A console that shipped analytics first would look finished and change nothing.

---

## 3. The screens

### 3.0 The frame, the Home screen and the words — 2026-09-27

**2026-09-30 — a shop sees only its own assistants' screens.** The owner found *Sold out* in the menu of a shop
with NEURA-CARE only (*"a gym app showing the pool to a member without the pool"*). `/me` now carries each
membership's `assistants` (its `enabled_agents`, sorted — passed through as data, so the API still names no agent),
and `lib/shop-assistants.ts` hides NEURA-SELL's screens from a shop without it: **Suggestions** and **Sold out** leave
the menu and Home; *Sold out* opened by its address says it *"comes with NEURA-SELL, which this shop doesn't have"*;
Shop connection drops the two optional Sold-out steps; Help drops its Sold-out lines. **Display only** — SELL's own
routes still check the entitlement; `/sold-out` itself is not gated by it (it lives in `neura-api`, which may not
name an agent). An unreadable `/me` shows the screens rather than hiding a feature silently. `make console-check`
now checks both kinds of shop (**114**).

**Asked for by the owner from screenshots, designed as a mockup on real data, approved, then built.** The owner's
brief: *a shop owner is not always technical.*

**The frame.** A side menu replaced the row of tabs: the shop's **name** (from `/me`, which now returns it — read in
each held shop's own tenant session, never another's) with *Switch shop*, the everyday screens (Home, Review with a
count of replies waiting, Conversations, Suggestions, Sold out), then *Setup* (Shop connection, Usage and cost), and
*Sign out*. On a phone it folds into one menu button. The shop id is shown once, small, on Shop connection — *"if
support asks"*.

**Home** is the landing screen of a shop. Mode first (*Practice mode is on* / *Your assistant is live*), then
**Needs you** — each item one counted fact said as a sentence with one action, shown only when true (replies waiting
in Review; conversations handed to a person in the last 7 days; no shop connected) — then **Last 7 days** (three
counts, the period's dates, and the server's `handed_to_a_person` caveat, chosen **by key**: usage caveats are
`{key, text}` since this day so a screen can show the one that belongs to its figures without matching words), then
**Your setup**. The Suggestions card counts only when SELL's page holds every product; otherwise it says no number.

**Home's switch, 2026-10-02** ([ADR-0054](architecture/adr/0054-the-shop-owner-switches-practice-mode-and-a-new-shop-starts-in-it.md); the owner's decisions, no mockup by the owner's choice). The mode section gains **Go live** in practice mode and **Back to practice mode** when live. *Go live* first asks, in the same section: *"Go live? From now on, shoppers see your assistant's replies as soon as it writes them, also in chats that are already open"*, then Review's counts as a sentence (*"You checked 6 replies in Review: 4 good, 1 not good, 1 harmful. 2 more are waiting in Review."*, or *"You haven't checked any replies in Review yet."*), with **Go live** and **Stay in practice mode**; no threshold. *Back to practice mode* is one press. Both write `PUT /v1/console/shops/{t}/mode` (`console_mode.py`): only the `mode` key of the shop's settings, an audit entry (`mode.live` / `mode.practice`, who, before and after), nothing for a repeat; then the page is read again. On a phone the buttons are full width. Help's step 5 now says *"A new shop starts in practice mode… then press Go live on Home when you are ready."* **What building decided:** the turn reads the mode when the reply is released (`turns.py`), because a chat's live connection kept the mode it read when it opened (G72); `make tenant-new` writes practice mode into a new shop, and `TenantConfig.mode`'s default stays `live`. `make console-check` adds seven checks (Go live offered; the question's numbers equal the database's; asking changes nothing; no sideways scroll on a phone; *Stay* changes nothing; Go live and back, each said on Home and true in the database), starting the shop in practice and putting its mode back after.

**The words** the owner approved, used everywhere a merchant reads them:

| was | now |
|:--|:--|
| Withheld (shadow mode) · shadow mode | **Held for your review** · **practice mode** (glossary: same thing as shadow mode) |
| `care` / `sell` | **NEURA-CARE** / **NEURA-SELL** since 2026-09-28 — the owner's decision: the name on what a merchant pays for is the name on every screen. What each does (*Customer care* / *Shopping help*, the words approved the day before) stays beside it where there is room — the Usage table, a phone card (`assistantPurpose`). One file, `lib/assistants.ts`; an unknown key shows as itself |
| 1 turn | **1 question** |
| `web` | not shown while it is the only channel |
| Shop · Usage | **Shop connection** · **Usage and cost** |
| `9/24/2026, 9:09:29 PM` (server's zone) | **Today, 9:09 PM** / **Sep 24, 9:09 PM** in the owner's own zone (`<When>`) |

**Colour and type did not change**, on purpose — §8 still leaves branding undecided.

### 3.1 Sign in

Enter an email → receive a one-time link → land in the console. If the email has no membership, **the screen says the same thing either way and the same email is sent or not sent silently** — a login form that says *"no account with that email"* is an account-enumeration oracle for anyone who wants to know which merchants use us.

### 3.2 Review — grading, and the reason to build this first

A queue of turns the agent drafted while in shadow mode: the shopper's question, the evidence the agent retrieved, the reply it *would* have sent, and whether `verify` passed it. The merchant marks it good or bad and may say why.

**Three rules, each of which is a lesson already paid for elsewhere in this project:**

* **Show the evidence, not just the reply.** A grader who cannot see what the agent was working from is grading fluency. This is `--out`/**E7** restated as a screen: a draft is only judgeable against what it was allowed to rely on.
* **A withheld turn must look withheld.** 1.16 found that a shopper shown an empty panel is a bug report within a day ([ADR-0020](architecture/adr/0020-a-withheld-turn-says-so.md)); the merchant-facing version of the same mistake is a grading queue that silently omits the turns the agent declined to answer. Those are the interesting ones.
* **Do not add sampling.** **A4** is unanswered, and a sampling rate chosen before anyone has graded for an hour is a rate invented to fit an imaginary constraint.

#### Redesigned 2026-09-27 — an inbox and a table, from the owner's approved mockup

The owner found the card-per-turn page messy: every card fully expanded, our words (`get_order_status`,
`order_status`, *"took 14874 ms"*, a prompt hash) at the same weight as the reply, and graded turns mixed
into the queue. Now two tabs, because grading and looking back are different jobs:

| tab | layout | what it does |
|:--|:--|:--|
| **To review** (default) | **inbox** — waiting replies on the left, grouped **by day** in the reader's own zone and **by chat** within a day (*"2 replies in one chat"*); one reply open on the right | question · *Earlier in this chat* · **What it looked at** (the documents' own words, the lookups by name) · the reply · *Fact check* · three buttons · *Details* (time, model calls, cost, type, prompt) folded away. **Good** saves and opens the next reply; **Not good** / **Harmful** save at once, then ask *what was wrong?* On a phone: the list, then one reply at a time with the buttons fixed at the bottom |
| **Already graded** | **table** — question · assistant · grade · note · asked · graded by · graded | opens a reply again to change its grade |

**Filters on both**, all in the URL: outcome (*All · Answered · Handed to a person · Blocked as an attack*) or
grade (*All · Good · Not good · Harmful*), each with its count given the other filters; **Asked** (*Any time ·
Today · Last 7 days · Last 30 days · Choose dates*) — the day the **shopper asked**, on both tabs, because it
means one thing everywhere and it is the shopper's day the owner cares about (*day graded* waits for more than one
grader, i.e. roles); and **Assistant**. A filtered view says *"Showing 2 of 6 waiting · asked Sep 21 – Sep 27"*
and *Show all*.

**Kept, and how:** the evidence is in the open reply beside the buttons — you cannot grade a reply you have not
opened, so it is never behind a click at the moment of grading; declined and escalated turns are listed and
explain themselves; every turn is reachable (the list pages, every filter clears); counts only — **the agreement
percentage is no longer shown** (the API still returns it), because *"9 good, 1 not good, 0 harmful"* is the same
fact with its denominator; *"No shopper saw any of these replies"* is said once, at the top.

**Two decisions made while building it:**

* **"Couldn't help" is not a separate filter.** The mockup had it; the system records a polite *"that's outside
  what I can help with"* as an ordinary **answered** turn (`state=resolved`), exactly as Conversations shows it,
  and telling it apart would need `neura-api` to know each assistant's own intent labels, which it may not. The
  outcome filter is the conversation vocabulary instead.
* **"Today" is the reader's today.** The browser writes its IANA zone into a `tz` cookie (a preference, not a
  credential — `TimeZoneCookie`); the page groups by day in that zone and sends `since`/`until` as calendar days
  **plus `tz`**, and the API turns them into instants with `zoneinfo` and refuses an unknown zone or a reversed
  window with a 400.

**API, 2026-09-27:** `GET /review` takes `state`, `verdict`, `agent`, `since`, `until`, `tz`;
`GET /review/counts` returns `{total, by_state, by_verdict}` for the same filters; `GET /review/{id}` opens one
turn by link (404 for another shop's). One filter definition (`shadow._matching`) serves the page and its counts.

#### Built 2026-08-27, and the four things building it settled

**1. "The evidence" was not in the row, and the missing piece was the question.**
`shadow_turns` records the draft, the citations and what `verify` thought — and
*not the shopper's message*, which lives in `conversation_messages` because it
genuinely was said. **The row looks complete without it**, which is what makes
this the easy mistake: a queue that forgot the join renders a confident paragraph
with nothing to judge it against. `neura_agent_core.review` does the join, and
resolves cited documents to the merchant's own text out of `document_chunks`.

**2. A citation names a source, not the passage.** `type:id`, with the chunk
index stripped before it ever reaches the row — so the screen can show the
*document* an answer came from and cannot show the paragraph the retriever
returned. It says so on the card. Widening citations back to chunk precision
would change what every integrator is promised (api-design.md §7), and showing a
document while implying it was the passage is the invented-evidence version of
the same shortcut.

**3. A tool citation can only ever be a name**, and that is a decision made
earlier and kept here: the record a tool returned is the shopper's own data and
belongs in the audit log under its retention policy, not in a queue read for six
weeks. So the card names the lookup and states plainly that the result is not
here — because an empty panel is [ADR-0020](architecture/adr/0020-a-withheld-turn-says-so.md)'s
silence wearing a merchant's clothes.

**4. Zero is not a measurement, and this screen is where that bites.**
`PriceTable.cost` returns `0` for a **local** model and `0` for a cloud model
whose price is not configured — two entirely different facts that no layer below
the screen can tell apart. So the API returns the figure with a flag saying it is
unattributed, and the screen writes *"not priced"* rather than **$0.00**. This is
§5 and [CLAUDE.md §4](../CLAUDE.md) meeting an actual widget, and it is the exact
place a dashboard usually starts lying.

**Grading now records a person.** `shadow_turns.reviewed_by` was a free string
because there was no user table; the console writes the **authenticated** user
id and refuses a `reviewed_by` in the request body, so one reviewer cannot sign
another's opinion. It is the first grade in this system that can answer *"who
approved this?"* with something nobody could type in.

### 3.3 Conversations

Transcript list, filter by escalated / blocked / declined. Read-only.

**Since 2026-09-27** each row leads with the shopper's **first question** (one line, as stored — tokens included and explained under the list), the list is searchable by **what shoppers wrote** (`?q=`, never the assistant's words; `%` and `_` are searched for, not interpreted) and narrowed by **assistant** (`?agent=` — a key the API matches as data and cannot refuse, so an unknown one matches nothing), and it says *"Showing 26–50 of 55"* with *Newer* and *Older*. Paging is still a keyset cursor (api-design.md §5): the position is **counted** for the words and never used to fetch, and the *Newer* cursor is computed by the server.

**PII is shown to the merchant unredacted, and this is a decision rather than an oversight** — they are the data controller for their own customers, and a support conversation with the addresses starred out is useless for the purpose they need it for. The redaction that matters is on what reaches the *model* (`PiiVault`, per-turn, never persisted), and that is unchanged.

> **Found while building Review, 2026-08-27: the paragraph above is not currently
> deliverable, and the reason is storage rather than policy.** `append_turn` writes
> the shopper's message **as the guard left it** — tokenised — because a transcript
> kept under a merchant's retention policy must not become a long-term store of card
> numbers (security-model.md §6.2). The rehydrated text existed only in the reply the
> shopper saw and was never persisted anywhere. So Review shows `[EMAIL_1]` and
> explains what it is, and **Conversations will show the same thing.** Whoever builds
> screen 2 must decide which of the two rules gives way, in an ADR, rather than
> discovering it at the top of the file: either the merchant gets tokens and this
> paragraph is rewritten, or the transcript starts holding real addresses and
> security-model.md §6.2 is reopened. Nothing has been changed here on either side.

#### One chat, redesigned 2026-09-28 — the held reply is in the chat, from the owner's approved mockup

The owner opened *"Where is my order 86?"* and saw the question, one sentence (*"The draft is in Review"*) and an
empty page: most chats are held in practice mode, and a held reply lived only in Review. Now the page reads as a
chat, and it answers the question the owner asked while designing it — **Conversations is for reading the whole
story, Review is the to-do list for grading** (one row there is a chat; here, one reply):

| what | how |
|:--|:--|
| **Title** | the shopper's **first question** — the words the owner clicked in the list |
| **One sentence at the top** | what the shopper saw and how many held replies wait — *"Practice mode. The shopper saw none of the replies below. 2 are waiting for your grade."* / *"Sent. The shopper saw every reply below."* — counted from the replies on the page (`whatTheShopperSaw`) |
| **A held reply** | under the question it answers, dashed edge, **Held — not sent**, the assistant's name and *would have answered*; then **Grade this reply** (`/review?turn=<id>`), or *"You graded this Good — I'd send this"* with **Open in Review**. **One per reply**: a chat with two questions has two buttons. A held turn with no draft says why, in Review's words (`no_draft_reason`, now shared) |
| **A sent reply** | plain edge, **Sent**, and *What it looked at* in Review's words (`consulted()`, now shared) — *"It looked up products and read 6 items from your shop:"* — **by name** from the synced catalogue (three shown, *Show 3 more*), never `product:1311` |
| **Removed** | the question type (`order_status`, `recommend`) — our word; the owner agreed to drop it |

**Grading stays in Review**, where the evidence sits beside the buttons (§3.2). The chat page shows no evidence,
fact check or cost for a held reply — only the draft and a way there.

**API, 2026-09-28.** `GET /conversations/{id}` gains **`held`**: each `shadow_turns` row of that conversation, oldest
first — `id`, `message_id` (the shopper message it answers), `agent`, `state`, `draft`, `no_draft_reason`,
`verdict`, `reviewed_by`, `reviewed_at`. **A separate field, never merged into `messages`** — a draft is what the
agent *would* have said, and merging it would make it history (shadow.py). Each citation gains **`name`**: the
title from `synced_entities` for the same `(type, id)` pair (a product's or policy's `title`, a category's
`name`), `null` for a lookup and for anything the synced catalogue lacks — read like Sold out reads titles, never
from the shop. Asserted with two populated tenants: another shop's draft filed under **this** shop's conversation
id, and another shop's catalogue title for the same id, never appear.

**Known limits.** `shadow_turns` has no index on `conversation_id`, so the read scans one tenant's held turns —
fine at pilot size, and an index is a migration. And a name comes from the **synced catalogue** while Review's
evidence comes from the **search index**, which can disagree: on the test shop category 32 is *"Shirts &
Knitwear"* in the catalogue and *"men clothes"* in the index, so one citation can be worded differently on the two
screens until the index is rebuilt.

#### Built 2026-08-27, and it shipped against the tokens

**The screen shows what is stored and explains it.** `[EMAIL_1]` rendered bare
reads to a merchant as data the product lost, so the note appears in the same
place the token does: *"a personal detail the guard replaced before the model saw
it… the real value was never stored here."* That is what is **true today**; it is
not the resolution of the paragraph above, and the integration suite pins it, so
the day somebody changes the storage a test goes red and the change gets an ADR
rather than happening quietly.

**The five states stay five, and the filter defaults to hiding none of them.** A
list that opened on *Answered* would report a healthier product than the merchant
has — the interesting rows here are the refusals. `blocked` and `escalated` are
labelled as different things because [ADR-0012](architecture/adr/0012-blocking-is-about-cost.md)
says they cost different things, and `blocked` is deliberately **not** painted as
an error: a recognised attack ended cheaply is the defence working, and colouring
it red teaches a merchant to read their best outcome as a problem.

**An unknown `?state=` is a 400, not a shrug.** A silently dropped filter returns
everything while looking filtered, which is how a merchant concludes they have no
escalations.

**Building it found a live defect in the transcript itself** — see
[PROJECT_STATE](PROJECT_STATE.md). `append_turn` had been silently discarding
`intent`, `state` and `prompt_revision` from every agent message ever written.

### 3.4 Shops

Connect a shop (URL + token), run the conformance suite against it, and watch the first sync. `neura-conformance` already exists and already produces the result this screen needs — **the screen is a view over it, not a second implementation.**

Credentials are written through the existing envelope encryption path. **The console never displays a stored credential**, not even masked to its owner: a field that can be revealed is a field that gets revealed in a screen-share.

#### Built 2026-08-27, **read-only** — and that is a decision

The screen shows the connection, what is in the catalogue, when each kind last
synced, and an **opt-in** live reachability check. **The connect form is not
built**, and the reason is the shape of the console's authority rather than the
size of the form:

> The console's entire write surface is one grading verdict. A browser form that
> submits a store credential would be the highest-value target in the
> application, added on the screen a merchant opens least often, before anybody
> has connected a shop through anything but the CLI.

That is the same reasoning [ADR-0026 §6](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md)
used to defer the approval queue. Connecting stays on `POST /v1/stores` and
`make tenant-new`; whoever adds the form does it deliberately. **The empty state
says so in the merchant's words**, because "you cannot do this here" is only
useful if it also says where it *can* be done.

**Never showing a credential is structural, not careful.** The read goes through
`StoreConnectionRepository.list_for`, which selects four columns and *cannot*
return `credentials` or `wrapped_dek` because it never asks for them. The
integration suite writes a recognisable placeholder into both columns and asserts
it never appears — an assertion about a string that is really in the row, not a
hopeful check against a column that happened to be empty.

**The live probe is a click, not a page load.** Everything on first render comes
from the database; *"is it reachable right now?"* makes an outbound request to
the merchant's own server and therefore happens only when asked. A page that
probed on every glance would be a monitoring agent nobody asked for. The probe
returns **200 describing a failure** rather than 503: from the console's point of
view "your shop did not answer" is the result, and a 503 would be
indistinguishable from our own outage in the exact moment somebody is trying to
tell the two apart.

**The opaque sync cursor is never rendered.** Whether a crawl is part-way through
is the fact a merchant needs; the value is a string they can only paste somewhere
it will go stale (api-design.md §5).

#### Redesigned 2026-09-28 — approved and BUILT (canvas seventh row, boards 21–23)

The owner found the screen thin and asked what connecting a new shop takes. It was **nine steps, two
people, all in a terminal** (docs/CONNECTING_THE_SHOP.md), and nothing in the console guided any of it. Approved
from the mockup and built the same day: **stage 1** below. **Stage 2 is not decided** — the widget install code with a key made in the
console, a connect form (still deliberately not built, as above), creating a shop and inviting its owner, and
recording the data agreement from the console (the admin side, group C — an ADR).

**Shop connection** (board 21, phone board 23):

| part | what it shows | from |
|:--|:--|:--|
| **Get set up** — a checklist, each step ✔ / not yet, and who does it | *Your shop is connected* (host, "set up by FiveNeurals") · *Your shop answers* — **still a button** (*Check now* / *Check again*): the shop is asked only when pressed, as today · *Your catalogue is copied* (products, last read) · *The chat box is on your shop* — **"used today from bagisto.test"**, from the public key's `last_used_at` and its allowed origin (**owner-approved**; never the key, its prefix, its hash or its scopes) · then **Optional — needed for Sold out**: *Data agreement on record* (since when) · *Your shop is sending product views* (the Sold out `receiving` fact) | `tenant_stores`, the health probe, `sync_checkpoints`, `api_keys`, `tenants.dpa_signed_at`, `observed_events` |
| **Our copy of your catalogue** | products · categories · policy pages (**Variants is dropped** — sizes and colours live inside a product, so it always read 0); *"Last read from your shop yesterday, 2:51 PM. New products and stock changes show up after the next sync — nothing syncs by itself yet."*; **Sync now** (*"Reads your shop again. Nothing in your shop changes."*) and, after it, *"Asked your shop for a fresh copy. The counts and the time above update when it finishes."*; per kind *"38 read"*, and `last_run_count = 0` said as *"no changes since the time before"* (it read as a contradiction beside *11 policy pages*); **"Search by meaning covers 29 of 38 products — the 9 newest are not in it yet"** (**owner-approved**; display only — rebuilding the index runs a model and is not offered) | the synced catalogue, `document_chunks` (distinct `source_id` per `source_type`) |
| **What your shop lets the assistant do** | after *Check now*: the declared capabilities **in plain words** (read and search products, categories, check stock, look up orders, a customer's details, policy pages, copy only what changed, send change messages — *"NEURA does not listen to these yet"*); before it, *"Press Check now above to ask your shop."*; always **"Read only. Your assistant cannot change anything in your shop."** | the health probe |
| **Connection details** — for your developer or support | address, *Standard NEURA bridge* (was `generic`), status, Shop ID | `tenant_stores` |

**Sync now — owner-approved 2026-09-28.** A new console action, the third that writes (after grading and the
owner's suggestions), and it writes **only our copy**: it queues the sync job that already exists
(`neura_api.jobs.enqueue_sync`, which returns the running job rather than queueing a second — pressing it four
times is one sync). Nothing is written to the shop.

**Help — "Connecting your shop"** (board 22), a new console page under *Setup* in the side menu. **Already
decided in [ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) §7** (merchant
help lives inside the console), never built until now: who does what (*You* · *Your developer* · *FiveNeurals, for
now*); five steps (six when built; the owner removed *Optional: Sold out* on 2026-09-30 — it is a
NEURA-SELL feature, not a connection step), each with who and **"How you'll know"** — the same ticks as the checklist; **For your developer**:
the one-line chat box snippet (`<script src=".../v1/widget/widget.js" async data-neura-key="fn_pk_…">` —
platform-agnostic, the same `SNIPPET` the API serves; no platform's own settings or commands, Rule 1) and the two
keys explained (the shop token is secret and stays on the shop's server; the chat box key is public and locked to
the shop's address), with *Copy these steps for your developer*; and **If something doesn't work** — five common
problems in plain words. **No time estimates and no numbers**: nothing has been measured.

**Rewritten with it:** `docs/CONNECTING_THE_SHOP.md` (2026-09-19) predated the console — no owner account or
sign-in link, no data agreement, no product views, no suggestions key scope, and `NEURA_WIDGET_HOST=…:8000`, where
another project listens on this machine. It now follows the Help page's five steps (product views an unnumbered optional section after them), each with the checklist tick
that shows it is done.

**What building it decided — each a correction of the mockup, none a new feature:**

| # | the mockup said | built as | why |
|:--|:--|:--|:--|
| 1 | *Sync now* (mode unstated) | a **full** read (`incremental=False`) | the screen promises *"stock changes show up after the next sync"*, and a shop's *changed since* filter follows a product's own edits — the reference bridge filters on the product rows, so a sale that lowers stock is invisible to an incremental read |
| 2 | *"Products — 38 read"* | *"Products — 1 new or changed"*; 0 is still *"no changes since the time before"* | `last_run_count` is what the sync **wrote** (created + updated), not what it read. The first live *Sync now* read all 38 products and recorded **1**. The old screen's *"118 read"* had the same error |
| 3 | *"the 9 newest are not in it yet"* | *"the other 9 are not in it yet"* | nothing checks that the missing ones are the newest. Counted from the catalogue's side (a synced product with at least one chunk), across embedding models, so an index entry for a product the shop no longer has does not count |
| 4 | *Check now* as a link (`?check=`) | a button whose answer lives in the page, not the address | *Sync now* re-reads the page when its sync finishes; an address carrying the check would have asked the shop again on that re-read. **A page load still never asks the shop** |
| 5 | *"used today from bagisto.test"* | the most recently used **live** public key (not revoked, not expired) — its `last_used_at` and allowed addresses, **two columns selected by name** | a shop can hold several public keys; a revoked key used later must not tick the box. The key, prefix, hash and scopes cannot be returned because they are never read |
| 6 | Help step 2: *"This moves into the console later"* | dropped | the connect form is stage 2 and **not decided**; a help page must not promise it |
| 7 | Help step 5: *"no shopper sees it yet"* | *"While practice mode is on, … no shopper sees them"* | **a new tenant starts live** (`TenantConfig.mode` defaults to `live`) |
| 8 | one shop connection | the connection steps and the two cards repeat per connection, named by address when there is more than one | `make console-check` adds a second connection to a real shop |

**Sync now, as built:** the button queues the job and the page then re-reads **our own** `/store` every few
seconds (never the shop) until the job is no longer queued or running, then refreshes: *"Finished. The counts and
the time above are the fresh copy."* — or, if the product sync's time did not move, *"The sync stopped before it
finished…"*. It stops watching after a few minutes and says the sync has not finished yet. Seen live on the test
shop: pressed, *"Asked your shop for a fresh copy…"*, the time changed by itself, *"Finished."*

**Help's chat box line** is fetched from `GET /v1/widget/snippet` — exactly the API's `SNIPPET` — so its address is
the API's `PUBLIC_BASE_URL`. **Since 2026-10-03 (G24)**: left empty in development it is this machine at
`NEURA_API_PORT` (it was a fixed `http://localhost:8000`, the wrong port here); staging and production refuse to
start without it, and production only with a public `https://` address.

**Help's *For your developer*, 2026-10-02** (canvas row 11, boards 36-37, approved by the owner; ADR-0053 §6 step 7,
G71). The box now reads in building order: *"The bridge answers nine read-only addresses… The guide for developers
explains each one"* and **Open the guide for developers** (`DEVELOPER_GUIDE_URL`, the address Shop connection
already copies, ADR-0051's, online once the website is deployed; it opens in a new tab); then **Does your developer
use an AI coding tool?**, the developer MCP's address and one sentence (*their tool learns from NEURA how to build
the bridge; it never sees your shop and needs no token*); then the chat box line; then the two keys. *Copy these
steps for your developer* ends with the guide's address and *"Using an AI coding tool? Add this address to it as an
MCP server: …"*. On a phone the copy button is full width. No long dash in the box or in what it copies; the page's
first paragraph and one *If something doesn't work* row keep theirs for now (G71 c, with G71 a, *Sync now*: the rest
of Help, later). **Words only: no setting, no switch; Shop connection is unchanged** (the owner's choice: its guide
link already leads to the address). **What building decided:** the address is the API's, never built by the
console: `GET /v1/widget/snippet` gains `developer_mcp_url`, made from the same public address as the chat box line
(`PUBLIC_BASE_URL`, or `base=`) and the MCP server's own mount, so Help shows NEURA's real address where the
public guide shows a placeholder (ADR-0053 §6 expected a placeholder in both; the dashboard has the address, the
website does not). When the API can't be reached the AI tool block is left out and the copy has no such line.
`make console-check` adds six checks: the guide link; the address equals the chat box line's address plus
`/v1/developers/mcp`; **that address answers `tools/list`**; no long dash in the box; the copied text carries both
addresses; no long dash in it (all six failed on the old page, then passed).

**Shop connection's *Your shop's contact details*, 2026-10-02** ([ADR-0055](architecture/adr/0055-a-handover-tells-the-shopper-how-to-contact-the-shop.md), G44; the owner's decisions, no mockup by the owner's choice). After *Get set up*, shown connected or not: *"When your assistant can't help a shopper, it tells them to contact your store with these. Both are optional."* An **Email** and a **Phone** field and **Save** (full width on a phone); under them, *What a shopper reads when your assistant can't help* and the **server's** sentence, returned with the details, so the screen never shows a copy (*"I can't help with this here. Please contact our store: hello@yourshop.example, +94 11 234 5678."*; with nothing set, the sentence stops after *store*). `GET`/`PUT /v1/console/shops/{t}/contact` (`console_contact.py`): the email must look like one; the phone is digits, spaces, `+ - ( )`, 6 to 15 digits; an empty field clears it; a refused field comes back as one sentence naming it (*"Email: this doesn't look like an email address…"*), the form's own browser check is off (`noValidate`) so only ours speaks; only the two keys of the shop's settings are written; an audit entry names which fields changed, never their values. **Where the sentence is used:** every handover the turn service releases, both assistants, both transports (`turns.py`, `neura_core.tenancy.handover_message`); the engine's fallback and CARE's `escalation_message.md` say the no-details form. `make console-check` adds five checks (the section is there; a wrong email is refused in plain words and nothing saved; saved details are in the settings; the screen shows the shopper's sentence with them; no sideways scroll on a phone), and puts the test shop's details back. Its older *no credential form exists on the shop screen* check now allows this one form and still fails any other field, or any password, token, secret or key field.

**Shop connection's *Order questions from signed-in shoppers*, 2026-10-09** ([ADR-0057](architecture/adr/0057-a-signed-in-shopper-may-ask-about-their-orders-in-the-chat-box.md) §3; no mockup, the owner's choice: *"that is simple one. do that with better with user friendly"*). Shown after the contact details, for a **connected** shop with **NEURA-CARE** whose last check lists `order.read` (a shop whose check is unknown shows it, as `hasSell` does). *"Your assistant can answer "Where is my order?" for shoppers who are signed in to your shop, and only about their own orders. For this, your developer needs a secret from you."* With none: *"Not set up yet. Until it is, every shopper who asks about an order is asked to sign in, or to contact you."* and **Make the secret**. The secret (`fn_cs_…`) is shown **once**, with **Copy**, and *"Send it to your developer through a password manager or a one-time link, never in a plain email. They keep it in your shop's settings, never in a web page, and follow Order questions in the developer guide."* (a link to `#orders`). After: *"Made [date]. Only your shop and NEURA know it…"* and **Make a new secret**, which asks first: *"The old secret stops working at once. Signed-in shoppers can't get answers about their orders until your developer puts the new one in, so tell them straight away."* (true here, unlike the shop token's G49: NEURA checks this secret). `GET`/`POST /v1/console/shops/{t}/customer-secret` (`console_customer_secret.py`): the read gives only `made_at`; each make writes an audit entry (`customer_secret.made` / `.replaced`), never the secret. `make console-check` adds seven checks, pressing the buttons only on a shop with no secret yet, and deleting the one it made.

**API, 2026-09-28.** `GET /console/shops/{t}/store` gains, per connection, `index` (`products`, `searchable`),
`sync_asked` (`status`, `queued_at` of a sync still queued or running — nothing else of the job) and `notes`
(`{key, text}`: `no_schedule` always, `index` when there are products), and at the top a `setup` block —
`chat_box` (`last_used_at`, `origins`, or `null`), `agreement_since`, `receiving` (any product view in 7 days,
`ObservedEventRepository.any_views_since`, as Sold out asks it) and `window_days`. `variant` is no longer counted.
New `POST /console/shops/{t}/store/{store}/sync` → **202**, `enqueue_sync(…, incremental=False)`; a store that is
not this shop's is a 404 and queues nothing. Tests: `test_console_shop_and_usage.py` +12 (every setup fact; no part
of a chat box key — token, prefix, scopes — in the body; a revoked key used later is not the one reported; an
empty shop says no to each; the index counts a product in two chunks once and ignores an indexed product the
catalogue lacks; Sync now queues one full read, twice is one, shows on the screen, 404 for an unknown or another
shop's store, 401 with no session); `test_console_screens.py` +6 (the sentences, singular and plural; variants not
counted).

#### Connect your shop, from the dashboard: approved and BUILT 2026-10-01 (ADR-0052, canvas row 10, boards 31-35)

**The owner connects their own shop.** Decided by the owner on 2026-10-01 (ideas D2 and D5 in
[CONNECTING_A_NEW_SHOP_LOG.md](CONNECTING_A_NEW_SHOP_LOG.md)), recorded in
[ADR-0052](architecture/adr/0052-the-shop-owner-connects-their-own-shop.md), which amends the two decisions above:
the connect form is now built, and a token is shown **once**, by the response that made it.

| part | what it does |
|:--|:--|
| **Connect your shop** (not connected) | Replaces *"No shop connected yet"*. Three steps, each saying who: **1 You** make the shop token (NEURA makes it, shown once with Copy and how to send it safely; after a reload only *when* it was made); **2 Your developer** builds the bridge (*Copy the guide link*); **3 You** type the bridge's address, press **Check**, then **Connect and copy my catalogue** |
| **The check** | The full check (`neura_commerce.check_adapter`, the terminal tool's own), queued as a `shop.check` job and watched every 3 s, like Sync now. One cause said first (G48): *Your shop refused the token* / *We couldn't reach this address* / *There is no bridge at this address*. *Copy the full check for your developer* gives the technical list, without the private file path (G17). A clean check lists **only what it tested and passed** (G51, 2026-10-03: a shop without orders is never told *Orders can be looked up*) and says *"The check proves the format, not the facts."* **Its warnings reach the owner** (G75, 2026-10-02): *N things to look at*, in the owner's words for four of them (products with no usable status, G69; orders' status words; empty policy pages; a search that finds products for nonsense), any other counted as *a technical detail for your developer*; a warning is counted, not passed (*18 of 20*) |
| **Connect** | Only after a clean check of the same address, made after the token. Saves the connection, discards the waiting token, queues the full copy, and keeps that clean check as the connection's first |
| **Your shop passes the check** (connected) | Replaces *Your shop answers*. **Check again** runs the full check; the page opens on the last one, read from our table, so a page load still never asks the shop. A clean check with warnings shows the same *things to look at* box and *Copy the full check for your developer* (G75) |
| **Your shop token** (connected) | *Set {when}*, never the token. **Make a new token** asks first and says what really happens (G49): NEURA stops using the old token at once, **your shop still accepts it until your developer puts the new one in**. The new token is shown once |

**What building it decided, each a correction of the mockup, none a new feature:**

| # | the mockup said | built as | why |
|:--|:--|:--|:--|
| 1 | *"ecommerce.test · connected by you on Sep 30"* | the address only | who connected is not stored on the connection; the audit log has it |
| 2 | the connect card replaces the page | the connect card, then *Get set up* below it; *Help* linked once, from the card | the chat box and Sold out steps still belong on the checklist |
| 3 | after *Check*, step 1 folds to *"Made today"* | the token stays on screen for the rest of that visit | a reload is what hides it; copying it twice in one visit is no leak |
| 4 | (not drawn) | after Connect, the page opens on the clean check, not *"Not checked yet"* | found in the browser test; the check is carried over to the connection |
| 5 | *"the old one stops working at once"* | *"your shop still accepts the old one until your developer puts the new one in"* | G49, fixed in the ADR before the build |

**API, 2026-10-01** (`routes/console_connect.py`): `POST /console/shops/{t}/token` (returned once; 409 when
connected), `POST /checks` (`{address}` or `{store_id}`; 202; one live check per shop; 409 without a token),
`GET /checks/{id}`, `POST /connect` (409 `CHECK_FIRST` without a clean check of that address after the token),
`POST /store/{s}/token` (returned once). `GET /store` gains `connect` (when a token was made, the last check) and,
per connection, `last_check` and `token_set_at`. Tables `shop_tokens` (sealed like `tenant_stores.credentials`) and
`shop_checks` (findings, never a token). Each token made, replaced and each connect writes an audit event, with no
token. **Addresses** (`addresses.py`, G47): in production `https://` and public internet addresses only, checked
before every call, for `POST /v1/stores` too; outside production a test shop on this machine is allowed. **DNS
rebinding, ADR-0052 §3's known limit, closed 2026-10-03** (G47, G78): in production every call to a shop and every
webhook connects through `outbound_transport`, which checks the address as it connects (security-model.md §8).

**Checked:** `make check` (1400 unit, 453 integration: `test_shop_connect.py` 27, `test_console_connect.py` 8);
`make console-check` 109 of 109; a live run against the API (24 of 24) and a real-Chrome run of the whole flow (25 of
25), both on throwaway test accounts with a fake bridge (the reference store), never on a real test shop.

### 3.5 Usage

Conversations, turns, escalations, blocked attacks, tokens, cost — from `tenant_usage`, which has been written since 1.14.

**Every number carries its own honesty.** A figure derived from synthetic data says so *on the screen*. A deflection rate from eleven conversations shows the eleven. `docs/` has been disciplined about this from the beginning ([CLAUDE.md §4](../CLAUDE.md)) and a dashboard is exactly where that discipline usually dies.

#### Built 2026-08-27, and it is entirely subtractive

**There is no rate on this screen, of any kind.** Not deflection, not resolution,
no trend, no target. Escalations over conversations is arithmetic the data
supports; *deflection* is a business claim it does not — it counts a shopper who
gave up, or who accepted a wrong answer, as deflected, and [CLAUDE.md §4](../CLAUDE.md)
lists deflection rate under **unknown**. So the screen shows *"1 of 2
conversations were handed to a person"*, which a merchant can check, and the same
sentence refuses the word: *"that is a count, not a deflection rate."* Both halves
matter — state the count alone and the reader does the division themselves.
An integration test walks every field name in the payload and fails on anything
ending in `_rate`.

**Zero is never printed as money.** `PriceTable.cost` returns `0` for a local
model *and* for a hosted model whose price is not configured, and nothing below
the screen can tell them apart. The screen writes **"not priced"** and explains
both possibilities. `make console-check` fails if a `$0` ever renders.

**Shadow mode is stated before any figure.** The usage row cannot say the work
was withheld; `TenantConfig.mode` can. Without it, a merchant reads "41
conversations, 2 escalated" as a working assistant when no shopper was shown a
single reply — **the most misleading page this console could produce, built
entirely from true numbers.**

**Every total names its period**, and an unknown `?period=` is a 400 rather than
a silent correction: a quietly adjusted window is a wrong number, not a wrong
parameter. ~~The per-agent split is labelled *today* because that is the grain the
meter records; summing it across a 30-day selector would report something nobody
measured.~~ **Corrected 2026-09-28:** the meter's grain is one row per
`(tenant, day, agent)` (ADR-0015), so a period's per-agent figure is the same kind of
sum as the period's total, and the agents' rows add up to it. The split now follows
the period chosen — see below.

**The caveats come from the server**, not from the JavaScript bundle — ADR-0020's
rule for merchant-facing sentences — and each appears only when it is true, so
the list never becomes boilerplate a reader learns to skip.

#### Redesigned 2026-09-28, from the owner's approved mockup

The owner's screen read *TURNS 82*, *TOKENS 291,499*, `2026-08-30 to 2026-09-28`,
*not priced* three times, practice mode twice, a per-assistant split for **today**
under a **30-day** selector — and *Shopping help: 0 conversations, 3,326 tokens*,
which looks broken and is the AI computing pairings in the background (ADR-0045).

| what | how |
|:--|:--|
| **Period** | chips *Today · Last 7 days · Last 30 days · Everything*; the heading says it in words — *Last 30 days · Aug 30 – Sep 28*, *Everything recorded · since Sep 1* (`period.first_recorded`). The meter's days are UTC calendar days, formatted as days (`dayWords`), never converted through a time zone |
| **Practice mode** | once, before any figure (the server's `practice_mode` caveat is not repeated under it) |
| **Conversations** | four counts — conversations, **questions** shoppers asked (was *turns*), handed to a person, blocked as attacks — with *See them →* on conversations and on handed to a person (`?state=escalated`); the server's *"36 of 53 … a count, not a deflection rate"* under them |
| **AI use** | AI calls, tokens (*"the unit AI providers charge by"*), and cost: an amount when measured, else **Not priced** said once, the server's reason under it — never a zero figure. **When an agent called a model on a day it served no turn** (`background_ai`), one sentence: *"Some AI work happens without a conversation, like working out product suggestions."* A day that mixed both cannot be split by the rollup, so the sentence errs towards silence |
| **By assistant** | a table (a card per assistant on a phone) **for the period chosen**, each named as the merchant buys it — **NEURA-CARE** / **NEURA-SELL**, with *Customer care* / *Shopping help* under it — and *"The rows add up to the totals."* |

Still true: no rate, no trend, no chart, and `$0` never renders (`make console-check`).

**API, 2026-09-28.** `GET /usage` replaces `today_by_agent` with **`by_agent`** for the
period (`UsageMeter.by_agent_since`), adds `period.first_recorded`
(`UsageMeter.first_recorded`) and the `background_ai` caveat
(`UsageMeter.worked_without_a_conversation`). `neura-api` still names no agent: the
sentence names a feature, and the screen maps keys to names.

---

### 3.6 Suggestions — redesigned 2026-09-28, from the owner's approved design

**The screen could change what it could not show.** Every product whose suggestions come from its own words read
*"Automatic"* over an empty row, because a word-path answer is worked out live on a shopper's basket and never
stored. On the test shop that was **37 of 38 products** — so the owner, asked what the screen was for, answered
correctly (*see each product's suggestions, change them if you want*) and could only do the second half.

| what | how |
|:--|:--|
| **Layout** | products on the left, one open on the right, like Review; on a phone the list, then one product with *All products* to go back. **Pages of 25** like Conversations — *"Showing 26–38 of 38"*, *Previous / Next* (products have no date order, so not *Newer / Older*) — rather than a list in its own scroll box; the open product **stays on screen** while the page scrolls |
| **Filters with counts** | *All · Your choice · Chosen by AI · Automatic* — counted given the search and category, never given the mode filter, so each chip says what choosing it would show. A **Category** menu (the shop's own categories with counts, and **No category** — the products that can never get an automatic suggestion), from the synced catalogue: no call to the shop |
| **Each row** | title, category names and price from the synced catalogue; *No category* is said, because it is the reason nothing can be picked automatically |
| **Open a product → the preview** | *"What a shopper's basket shows with it now"*: the heading and cards a basket gets, then **where they came from** — *Your choice* / *Picked by the AI — it looked for …* / *Picked automatically from this product's own words* |
| **When nothing shows** | **why**, in words the owner can act on: no category in the shop, nothing matched, the owner chose nothing, the owner's choices are sold out, the shop did not find the product |
| **When the AI tried and lost** | *"The AI also tried: it looked for laundry detergent, garment bag and phone case, matched nothing in your shop, so word matching is used"* — so *the AI found nothing* and *the AI never ran* read apart |
| **Change these** | the same ADR-0050 editor, in the panel, starting from what shoppers see now (or the owner's own list); the product picker now shows prices. With the list empty the sentence says what to do (*No products picked yet. Use Find below to add some.*) and **the button says what it does — *Show nothing with this product*** rather than *Save*, because an empty choice turns automatic suggestions off for that product (owner-approved after the first version confused the owner) |

**Two rules the owner approved with it:**

* **The shop is asked only when the owner opens a product** (and on *Ask your shop again*). Everything else on the
  screen is the synced catalogue. A shop that does not answer is **said** (*"Your shop did not answer just now"*),
  never shown as *nothing to suggest* — `suggest()` forgives a failed lookup as a missing product, so the preview
  asks for the product itself first.
* **A preview never runs the model and never saves anything.** It calls the basket's own `suggest()` with the
  basket's own cache and choices, through the same seams (`routes._pairing_cache`, `routes._owner_choices`), so it
  cannot drift from what a shopper sees — but the cache is wrapped read-only (`_ReadOnlyPairings`): a basket's miss
  queues a model computation ([ADR-0045](architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md) §2), and an owner clicking through products is not a shopper's first use.
  `make console-check` asserts the job queue does not grow when a never-paired product is opened.

**API, 2026-09-28.** `GET /v1/sell/console/shops/{t}/suggestions` gains `mode` (`owner` · `automatic` · `pending`,
400 on anything else), `category` (an id, or `none`; an unknown id matches nothing rather than being refused),
`meta.counts` and `meta.counted_all` (it reads up to 2,000 products to count and filter by mode, and says when it
stopped short), `meta.categories` (`named` with counts, and `none`), paging as Conversations pages
(`total`, `offset`, `has_previous`, `previous_cursor`; pages of 25), and each row's `categories` and `price`. New
`GET …/suggestions/{product}/preview` → `product` (the list's row), `reachable`, `origin` (`owner` · `model` ·
`words`), `reason`, `heading`, `suggestions` (the basket's cards), `ai` (`kinds`, `found` — only for the product's
current text). `Pairing` gained `origin` and `reason` for it; **the storefront route still sends only `heading`,
`paired_with` and `suggestions`**, and a test pins that a shopper's page learns nothing new.

**Found while designing it, on the test shop — not fixed here:** the AI has run for 4 of 38 products (it runs only
when a basket first shows a product) and found something once (*Leather Loafer → Merino Walking Socks*, after the
owner added the loafer to a cart on 2026-09-28). Two causes, both setup rather than code: `.env` has
`NEURA_ROLE_MAP=ollama-dev`, so the worker uses the small local `qwen3:8b` (it asked for *phone case* and *towel*
for clothes), where ADR-0045's measured run used `gemini-3.8-flash`; and the **search index lacks the 9 newest
products** (belt, socks, tights, tie, shoe cream, shoe trees, waterproofing spray, wool wash, clothes brush), so
the AI's search by meaning cannot find the very complements the shop stocks.

### 3.7 Sold out — redesigned 2026-09-28, from the owner's approved design

**The owner could not tell how it worked, and could not act on it.** Empty, it said *"No sold-out product was
viewed"* and that a switch *"cannot be seen from here"* — without saying where the switch is. With data, it said
*VIEWS 2 · SESSIONS 1* in capitals beside an internal id (`#1320`), and a caveat handed the most useful fact back to
the owner: *"some may be back in stock now"*. And the synced copy of the catalogue could not answer that either: on
the test shop it still said the sold-out jumper was **in stock**, because nothing had synced since its stock went to
0 — the same undecided recurring sync as §3.6.

| what | how |
|:--|:--|
| **One name** | *Sold out*, in the menu and as the title (was *Wanted while sold out*), with its job under it: *"Products shoppers wanted while you had none, so you know what to restock."* |
| **Each product is a sentence** | *"Opened **3 times**, in 1 visit · last opened 28 Sep"*, then category and price from the synced catalogue; the id is gone (a product the catalogue lacks is still shown, by id, and says so). The API still says `sessions`; the screen says *visits* |
| **Now** — *Still sold out* / *Back in stock* / *Couldn't check* | Asked of the shop **when the owner opens the screen** (and on *Check again*): **one stock lookup for every product listed**, never one per product (`GET /inventory?variant_ids=…`, which takes many). The rule is the shop's own for a view (ADR-0049): in stock when **any** variant has stock. *Back in stock* adds *"These visits happened while it could not."* A shop that does not answer, or does not share stock, is said under the list (*"…so we can't say what is in stock today. The counts are still right."*), and a product the shop said nothing about reads *Couldn't check* — **never** *Still sold out* |
| **Is it working?** | ✔/✗ *Data agreement on record* (since when), ✔/✗ *Your shop is sending product views* — whether **any** product view arrived in the window, sold out or not: a yes or no, never a count. It is what tells *switched off* from *nothing sold out was opened*. The switch itself is in the shop and cannot be seen; the screen says so and says *usually*, not *the switch is off* |
| **How this works** | three numbered steps (a sequence), and *"Nothing here reaches your shoppers, and we never contact them."* Step 3's *"We keep it for N days"* is the retention setting the sweep enforces (`kept_days`), not a number typed into the page |
| **Three empty screens** | no agreement (*Nothing is collected*), no views arriving (*Nothing to show yet* — *usually this means product views are switched off in your shop's settings; whoever set up your shop can switch them on*), views arriving but nothing sold out opened (*No sold-out product was opened … Nothing to restock*) |
| **Fine print** | one line, from the server: a visit is not a person, crawlers are counted, *"We never know who the shopper was."* The *"may be back in stock"* caveat is gone — the screen now says, per product |

**The rule the owner approved with it: the shop is asked only when this screen opens.** Home reads the same route
without `?stock=now` and never reaches the shop; an empty list asks nothing. It is the second console call that
reaches the shop, after the Suggestions preview (§3.6). It opens a connection like the Shop screen's probe
(§3.4) — the store directory reuses a shop's declared capabilities for a minute, so a first opening may also make
the shop's `/health` call.

**The checklist is built entirely on our side.** The agreement is our row; *views arriving* is our table. Nothing
changed in the shop's bridge — a merchant turns views on once, in their shop's settings (ADR-0044), and this screen
only reads what arrives.

**API, 2026-09-28.** `GET /v1/console/shops/{t}/sold-out` gains `agreement_since`, `receiving`, `kept_days`, each
product's `categories`, `price` and `in_stock_now` (`true` / `false` / `null`), and `stock` (`asked_at`, `answered`,
`reason`: `unreachable` · `not_supported`) — `null` unless `?stock=now`, the only value it takes (400 otherwise).
`ObservedEventRepository.any_views_since` answers *receiving* with an `EXISTS`, never a count.

### 3.8 People and roles, and Create an account: from the owner's approved design, 2026-10-10 (People and roles built 2026-10-10; Create an account built 2026-10-11)

[ADR-0058](architecture/adr/0058-a-shops-dashboard-has-people-with-roles-and-a-shop-signs-up.md), accepted 2026-10-10; mockups approved the same day (canvas rows 12 and 13, boards 38 to 45, version 31). **Build from this section and the ADR; do not redesign.**

**Roles (checked in code, per shop, on every request; the dashboard only hides what the API refuses):**

| Role | Menu | Can | Cannot |
|:--|:--|:--|:--|
| **Owner** | everything, plus **People** under Setup | everything | |
| **Support** | Home, Review, Conversations, Help | read chats (CARE and SELL), grade replies | Suggestions, Sold out, Shop connection, Usage, People, *Go live* |
| **Developer** | Home, Shop connection, Help | **all of Shop connection, the same page as the Owner's** (setup list, Check, Connect, Sync now, the shop token, the sign-in secret, the contact details: R10, the owner's B) | shoppers' chats, Review, Suggestions, Sold out, Usage, People, *Go live* |

- **The shop switcher** says the role: *"You're the Owner · Switch shop"* (Support, Developer likewise).
- **A page the role cannot open** (a link, a typed address): *"You can't open this page"*, *"Your role in [shop] is [role], which doesn't include [what]. If you need it, ask the shop's owner."*, and a link to a page the role can open. The API answers 403 for a member without the permission; **404 for a stranger**, as today.
- **Home** shows *Go live* / back to practice to the Owner only.
- **Shop connection's secrets** say who made them: *"Made Oct 10 by Nimal Perera (Developer)."*

**The permissions, as built (piece 1, 2026-10-10).** The map is `neura_core/identity/roles.py`; each route states its
permission on the route (`Depends(Permitted(...))` in `neura_api/dependencies.py`), checked before the request's body
is read. A stranger gets **404** *No such shop.*; a member without the permission **403** `ROLE_NOT_ALLOWED`, with
`details.role` and `details.permission`. The Owner holds every permission, also one an agent brings later; a role or a
permission the code does not know opens nothing; the database refuses any role but these three
(`ck_memberships_role`). **The names differ from the ADR's draft** (it said *fixed in the build*): a screen the
console serves names no agent (G88).

| Permission | Opens | Owner | Support | Developer |
|:--|:--|:--|:--|:--|
| `shop:home:read` | Home's own facts: the mode, and the handed-over count for a role that reads chats (R12) | ✅ | ✅ | ✅ |
| `shop:conversations:read` | Conversations (CARE's and SELL's chats) | ✅ | ✅ | ❌ |
| `shop:review:write` | Review: read and grade | ✅ | ✅ | ❌ |
| `sell:suggestions:write` | Suggestions (SELL's own permission, on SELL's routes) | ✅ | ❌ | ❌ |
| `shop:sold_out:read` | Sold out | ✅ | ❌ | ❌ |
| `shop:connection:write` | Shop connection: read, Check, Sync now, the shop token, the sign-in secret | ✅ | ❌ | ✅ |
| `shop:connect:write` | Shop connection: Connect | ✅ | ❌ | ✅ |
| `shop:contact:write` | Shop connection: the contact details | ✅ | ❌ | ✅ |
| `shop:mode:write` | *Go live* and back to practice | ✅ | ❌ | ❌ |
| `usage:cost:read` | Usage and cost | ✅ | ❌ | ❌ |
| `people:members:write` | People (its routes come in piece 2) | ✅ | ❌ | ❌ |

Every dashboard route and its permission is also written, from this table, in `tests/console_permissions.py`; a
route missing from it, or declaring another permission, fails `tests/unit/test_console_roles.py`, and
`tests/integration/test_console_roles.py` calls every route as each role and as a stranger.

**As built in piece 2 (2026-10-10; what the build decided is [ADR-0059](architecture/adr/0059-people-and-roles-what-the-build-decided.md)):**

- **The menu per role** comes from `/me`, which gives each membership its `permissions` (the API's own map; the
  dashboard keeps no copy, `lib/roles.ts`). A screen the role may not open is not listed; opened by a link it shows
  *You can't open this page* (`components/not-allowed.tsx`) with *Go to* the first screen the role can open.
  [what] is the screen's name, and *shoppers' chats* for Conversations (board 40).
- **Home for Support and the Developer (R12, the owner: A):** Support sees the mode as a sentence with no button,
  replies waiting for review and chats handed to a person; the Developer the same mode sentence, *your shop isn't
  connected yet* when true, and the Catalogue card. No 7-day numbers, money or *Go live* (`GET /home`).
- **An invite link signs in only a new account (R13, the owner: A).** Someone who already uses NEURA is added and
  signs in as usual, so a forwarded invite cannot open their other shops. The invite page: *"You've joined"*,
  *"You've joined [shop]. Sign in to open it."*, **Sign in**; a link that no longer works: *"That link didn't work"*,
  *"That invite link has already been used, or it no longer works. If you already joined, sign in. If not, ask the
  shop's owner to send it again."*, with **Sign in** (G96: a link works once, so this is usually someone who joined)
- **The Developer's card** says, as R10's B allowed: *"Shop connection and Help: connects your shop, makes its
  secrets and edits its contact details. Never sees shoppers' chats."*
- **When the email could not be sent:** *"The invite for [email] is ready, but the email could not be sent. Try Send
  again in a moment."* Locally, `make invite-link EMAIL=… TENANT=…` prints a new link.
- **Checked:** `make console-check` signs in as the Owner, invites two people in the database (no email is sent),
  opens their links in two more browsers, and checks each role's menu, Home and refusals on desktop and phone, then
  changes a role and removes both on the People screen.

**People** (board 38; Owner only): heading *People*, *"Who can open [shop]'s dashboard, and what each person can do."*, button **Invite a person**. A list: Person (name and email), Role (a choice: Owner, Support, Developer), Status, actions.
- The Owner's own row: *"[name] (you)"*, role as text; when they are the only Owner: *"The only Owner, so this can't be removed"*, no Remove.
- A member: the role choice, *"Joined [date]"*, **Remove**, which asks first: *"Remove [name]?"* *"[name] can't open this shop's dashboard from the next click. Everything done before stays in the record. You can invite them again later."* **Remove** / **Keep**.
- An invite: the email, *"Invite sent [date]"*, *"Waiting · the link works until [date]"*, **Send again**, **Cancel**.
- **What each role can do**, three cards: **Owner** *"Everything, including inviting and removing people. A shop always keeps at least one Owner."* **Support** *"Reads chats and grades replies in Review. Can't open settings, keys, Usage, Suggestions or Sold out."* **Developer** *"Shop connection and Help: connects your shop and makes its secrets. Never sees shoppers' chats."* (Since R10's B the Developer also edits the contact details; the card's words may say so at the build, plainly.)
- Under it: *"Every invite, role change and removal is kept in your shop's record, with who did it."*

**Invite a person** (board 39): a box *Invite a person*: *"Their email address"*; *"Their role"* as three choices, each with its card's words; Owner's: *"Everything you can do, including removing you. Choose it only for a partner."*; *"We email them a link. It works once, for 7 days. They see only what their role allows, and you can change it or remove them at any time."*; **Send invite** / **Cancel**. After: *"Invite sent to [email] as [role]. The link works for 7 days."*, and the invite in the list.

**Phone** (board 41): each person is a card; **Invite a person** full width at the top; buttons 44px.

**Sign in** (board 42): today's card, and under it *"New to NEURA? Create an account"*.

**Create an account** (board 43): the sign-in card's look. *Create an account*, *"Tell us about your shop. We'll email you a link to confirm. No password to remember."*; fields *"Your email address"*, *"Your shop's name"*, *"Your shop's website"*; **Create my account**; *"FiveNeurals looks at every new shop before its assistant starts."*; under the card *"Already have an account? Sign in"*. After: *Check your email*, *"A link is on its way to [email]. It works once and expires in 15 minutes."*, **Use a different address**. **The same words whether or not the email already has an account.**

**Waiting for approval** (board 44; the only screen of a waiting shop): *"[shop] is waiting for approval"*, *"Thanks for signing up. FiveNeurals looks at every new shop before its assistant starts. We'll email [email] when it's ready."*, *"Until then nothing runs and nothing costs anything."*, a link *"While you wait: the guide for shop owners"*, **Sign out**. No time is promised.

**FiveNeurals approves** with a command for now (`make tenant-approve`, and a refusal), the admin dashboard later (the log's *Admin needs*, AD1 to AD6).

**As built in piece 3 (2026-10-11; what the build decided is [ADR-0060](architecture/adr/0060-sign-up-what-the-build-decided.md), R14 to R17):**

- **Create an account** is `/sign-up`, open to anyone, signed in or not (an existing account may add a second
  shop, R15). The website may be typed with or without `https://`; a wrong one: *"Enter your shop's website, like
  yourshop.com."* *Check your email* says the same words for every email, because every email gets a link.
- **The link** (`/auth/sign-up?token=…`) makes the account when the email has none, the shop waiting for approval
  and its Owner, signs them in and opens the shop, which shows the waiting screen. A used or old link: *"That link
  didn't work"*, *"Sign-up links expire after 15 minutes and work once. If you already confirmed, sign in. If not,
  create your account again."*, **Sign in** and **Create an account**.
- **The waiting screen** replaces the menu and every screen of a waiting shop (`components/waiting-for-approval.tsx`,
  from the shop's frame); a typed address to another screen shows it too. It also shows **Your shops** when the
  person has another shop (R17 a). *Your shops* lists a waiting shop as *Waiting for approval*.
- **The API is the lock:** every shop route answers a waiting shop **403 `SHOP_WAITING`** (a stranger still 404);
  `/me` gives each membership its `status` and no permissions for a waiting shop; no key can be issued for it.
- **FiveNeurals:** `make tenant-waiting`, `make tenant-approve TENANT=… [AGENTS=care,sell]` (CARE when none named,
  R14; the approval email), `make tenant-refuse TENANT=…` (removed, then the refusal email; the person keeps their
  account). The three emails' words are in ADR-0060 §5.
- **Checked:** `make console-check` signs up a new owner in its own browser (the request made in the database, so
  no email is sent), reads Create an account and the waiting screen on desktop and phone, approves the shop in the
  database, and Home must then open; `tests/integration/test_console_sign_up.py` holds the API, the commands and
  the emails.

### 3.9 FiveNeurals admin: from the owner's approved design, 2026-10-11 (built 2026-10-11)

[ADR-0061](architecture/adr/0061-fiveneurals-has-an-admin-dashboard-that-sees-shop-facts-never-shoppers.md), accepted 2026-10-11 (R19 to R23); mockups approved the same day (canvas row 14, boards 46 to 49, version 34; the side menu is R24). **Build from this section and the ADR; do not redesign.** Only for people on FiveNeurals' admin list (`make admin-add`); anyone else gets *No such page*. **Shop facts only, never a shopper's chat or details.**

**The frame** (all three screens): a **side menu** like a shop's: *FiveNeurals* with a black **Admin** badge; a card *FiveNeurals admin*, *"You're an admin · Your shops"* (a link to Your shops) where a shop's menu has its switcher; **Shops** (with the number of shops waiting, when there are any) and **AI use and cost**; **Sign out** at the bottom. On a phone the menu folds into a menu button, as a shop's does; the bar says *FiveNeurals admin* and shows the badge. **Your shops** gets an **Admin** link for an admin only.

**Shops** (board 46; `/admin`): heading *Shops*, *"Every shop on NEURA, and its state. Facts about shops only: no shopper's chat or details are shown here."*
- *Waiting for approval · [n]*: one amber card per waiting shop: its name, *"[website] · signed up [date, time] by [owner email]"*, **Look and decide**. The section is left out when nothing waits.
- *All shops · [n]*: a table, waiting shops first, then newest first: **Shop** (a waiting shop's name links to its page, with its website under it), **State** (*Waiting for approval* amber, *Practice* grey, *Live* green), **Assistants** (*CARE, SELL*; *None yet* while waiting), **Shop connected** (*Yes* / *Not yet*), **Chats, 7 days**, **AI cost, 7 days** (*Not priced* when there was AI use and no price; *No AI use* when none), **Since** (the date).
- Under it: *"Chats and AI cost are for the last 7 days. **Not priced**: the AI model in use has no price set, so NEURA records no cost. The full numbers are on AI use and cost."*

**A waiting shop** (board 47; `/admin/shops/[id]`): *← Shops*; the name, the *Waiting for approval* badge; facts: **Website** (a link, *opens in a new tab*), **Owner**, **Signed up**, **Shop id**; *"Look at the website before you decide: is it a real shop that sells things?"*
- **Approve**: *"Choose its assistants. CARE is the usual start."* Two choices: **NEURA-CARE** (ticked) *"Answers shoppers' questions: orders, delivery, returns, the shop's policies."*; **NEURA-SELL** *"Helps shoppers choose, and suggests what goes together. Uses some AI in the background for each product."*; *"It starts in practice mode, with the daily spending limit every shop has. We email [owner]."*; **Approve** (black) and **Refuse** (red outline).
- **Refuse** asks: *"Refuse [shop]?"* *"It is removed, and [owner] gets an email. This can't be undone."* **Refuse** (red) / **Keep waiting**.
- After approving: *"[shop] is approved"*, *"With [assistants], in practice mode. We emailed [owner]. It is in the shop list now, as Practice."* After refusing: *"[shop] is refused and removed"*, *"We emailed [owner]. [They keep] their account, in case [they are] in another shop."* Each with *Back to Shops*.

**AI use and cost** (board 48; `/admin/usage`): heading, *"Across every shop. The same counts each shop sees on its own Usage screen."*, the period **Today / 7 days / 30 days**; six tiles: **chats**, **questions**, **handed to a person**, **AI calls**, **tokens**, **cost** (*Not priced*, dashed, when nothing was priced); **By shop** (only shops with use; *"[n] shops had no AI use in these [period]."*) and **By assistant** (*NEURA-CARE*, *NEURA-SELL*), each with Chats, Questions, Handed to a person, AI calls, Tokens, Cost; *"The rows add up to the totals above."*; the box *"**Why "Not priced".** The AI model in use has no price set in NEURA, so no cost is recorded, and a free local model records none either. NEURA never shows that as $0.00. The real amount is on the AI provider's own bill."*

**On a phone** (board 49): each shop is a card (name, state badge, one line of facts); the waiting shop first with a full-width button; buttons 44px.

**As built (2026-10-11):**

- **Routes** (`neura_api/routes/admin.py`): `GET /v1/admin/shops`, `GET /v1/admin/shops/{id}`, `POST …/approve`
  (`{"agents": [...]}`, at least one: the API names no agent, so CARE being ticked is the dashboard's default),
  `POST …/refuse`, `GET /v1/admin/usage?period=today|7d|30d`. Each states `AdminOnly` on the route (a test fails for
  one that forgets): signed out 401; not a live admin **404 *No such page.***; an admin signed in more than 12 hours
  ago **401 `ADMIN_SIGN_IN_AGAIN`**. `/me` gives `is_admin` for the *Admin* link.
- **The database keeps §1 true:** `neura_admin_shops()` and `neura_admin_usage()` (migration `9b4e7a2c5d18`), owned
  by the `NOLOGIN` role `neura_admin_reader`, which holds column grants on shop facts only and answers only a
  transaction naming a live admin (`app.user_id`). A test reads the role's grants and fails if it can read anything
  else.
- **Refuse removes the shop with `remove_tenant`** (`neura_core/tenancy/removal.py`): every base table with a
  `tenant_id`, read from the database, the tables that point at others first, the audit log kept (S10). `make
  tenant-refuse` uses it too.
- **Admins:** `platform_admins` (no tenant; never deleted, `removed_at`), changed only by `make admin-add`,
  `make admin-remove`, `make admin-list`.
- **Screens:** `/admin` (Shops), `/admin/shops/[id]` (a waiting shop: Approve, Refuse; any other shop: its facts
  and *"This shop is not waiting for approval, so there is nothing to decide here."*), `/admin/usage`. Someone not
  on the list sees *No such page*, *"There's nothing at this address."*, *Your shops*; an admin signed in over 12
  hours ago sees *Sign in again*, *"Admin pages need a sign-in from the last 12 hours. Your shops are not
  affected."*, **Sign in again**. When an email could not be sent, the result says *"The email to [owner] could not
  be sent."* rather than *"We emailed"*. The result stays until the admin leaves; **Back to Shops** re-reads the
  list and the menu's count (G100).
- **Checked:** `tests/unit/test_admin.py`, `tests/integration/test_admin.py`; `make console-check` has an admin
  section (its own browser; waiting shops made with no owner, so no email can be sent; desktop and phone; the
  12-hour rule with a cookie made 13 hours old).

### 3.10 The handover answered by email: from the owner's approved design, 2026-10-11 (not built)

[ADR-0062](architecture/adr/0062-a-handed-over-shopper-may-leave-an-email-and-the-shop-answers-from-its-own.md), accepted 2026-10-11 (R25 to R32); mockups approved the same day (canvas row 15, boards 50 to 56, version 36). **Build from this section and the ADR; do not redesign.** For **Owner and Support** (`shop:handovers:write`); the Developer sees none of it. **NEURA sends no email**: *Answer by email* opens the team member's own email app. No new screen: Conversations, Home and the menu gain parts.

**The chat box, not signed in** (board 50): under the handover reply *"I can't answer this here. Leave your email so our store can answer you."*, a small box: *Your email*, a field, **Send** and **No thanks**; under the box the contact line *"Or contact our store: [email], [phone]."* (left out with no details set). **Send** with a good address: the box goes and a new reply says *"Thanks. Your question is with our store, and they can answer you at [email]."*. A bad address: the field turns red and *"Please check your email address."* under it. **No thanks**: the box goes; the contact line stays. Shown only when the reply carries `ask_email: true` (a real handover, once per chat, never in practice mode).

**The chat box, signed in** (board 51): never asked; the reply says *"I can't answer this here. Your question is with our store, and they can answer you by email."* and the contact line.

**Conversations** (board 52): a new choice **Waiting for an answer** right after *All*, with an amber count; selected, an amber line *"**[n] shoppers are waiting for an answer.** Your assistant handed them over, and each left a way to reach them. Open one to answer by email."*; each row has the amber **Waiting for an answer** badge and *left an email* or *signed in to your shop* in its line. Under the list: *"A chat where the shopper pressed No thanks is not here: nobody can answer it. It stays under Handed to a person, as today."* **The menu** shows the same amber count beside *Conversations* while any shopper waits; on a phone, an amber dot on the menu button.

**A waiting chat** (boards 53 and 56): the amber **Waiting for an answer** badge in the header, then an amber box at the top: **This shopper is waiting for an answer**, *"They left their email after your assistant handed them over, [date] at [time]."*; the address in monospace and **Copy** (*Copied* after); **Answer by email** (black, opens `mailto:` with the address, the subject *"Your question to [shop]"* and the body *"Hello,⏎⏎You asked us in the chat on our website:⏎\"[the first question]\"⏎⏎⏎⏎[shop]"*; never the AI's unsent draft) and **Mark as answered**; under them *"Answer by email opens your email app with their address and question filled in. Send it from your shop's email. When you have answered, press Mark as answered: their email is deleted then, or after 30 days if nobody answers."* **Mark as answered** asks: *"Mark as answered?"* *"We delete the shopper's email, and this chat leaves Waiting for an answer. This can't be undone."* **Mark as answered** / **Cancel**. After: a green box *"Answered"*, *"[name] marked it, just now. The shopper's email is deleted."*, the badge goes back to *Handed to a person*, the menu count drops. In the chat, where the email was left, a centred line *"The shopper left their email for an answer · [time]"* (the address itself is never in the chat). On a phone the three buttons are full width, 44px.

**A signed-in shopper's chat** (board 54): *"They were signed in to your shop when your assistant handed them over, [date] at [time]."*; the address with *"from your shop's customer record"*, read from the shop when the chat opens, never stored. When the shop cannot give it: *"Your shop didn't give us this customer's email. Find customer [id] in your shop's admin, and write to them from there."* (no Copy, no Answer by email; Mark as answered stays).

**Home** (board 55): first in *Needs you*, for Owner and Support: **[n]** *"shoppers are waiting for an answer"* / *"shopper is waiting for an answer"*, *"Your assistant handed them over, and each left a way to reach them. Answer them by email."*, **Answer them** (black), opening the waiting list. Left out when nobody waits.

## 4. Identity — the part that is genuinely new

### 4.1 The tables

```
users                       (NOT tenant-scoped — see ADR-0026 §4)
  id, email (citext, unique), name, created_at, last_seen_at

memberships                 (tenant-scoped, forced RLS)
  id, tenant_id, user_id, role='owner' (or 'support', 'developer': ADR-0058), created_at, revoked_at

login_tokens                (NOT tenant-scoped)
  id, user_id, token_hash, expires_at, consumed_at, requested_ip

sign_up_requests            (NOT tenant-scoped: there is no shop yet; ADR-0058 §7)
  id, email (one per email), shop_name, website, token_hash, expires_at, requested_ip
```

`sessions` are signed cookies rather than a table, so a logout is a cookie clear and there is no session store to grow unbounded. **Revocation is checked against `memberships` on every request**, not baked into the cookie — otherwise removing someone's access does nothing until their cookie expires.

### 4.2 The request path

```
browser  --cookie-->  console (Next.js)  --session-->  API
                                                        ↓ resolve person
                                                        ↓ resolve membership
                                                        ↓ SET LOCAL app.tenant_id
                                                        ↓ RLS does the rest
```

The last two steps are the ones that already exist and are already trusted. **The console adds a doorman in front of a lock that is not being changed.**

### 4.3 Rules that are not negotiable

1. **No tenant API key ever reaches the browser.** ([ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) §3)
2. **The tenant comes from the membership, never from the request.** A `?tenant=` parameter the browser can edit is not authorisation, it is a suggestion. `AGENTS.md` rule 3.
3. **Login tokens are single-use, hashed at rest, and consumed in the same transaction that creates the session.**
4. **Sign-in reveals nothing about who has an account.**
5. **Asking for a sign-in link is limited**, per network address and per email, over an hour (G97, 2026-10-10;
   `RATE_LIMIT_SIGN_IN_*`, guesses until real use). **Sign-up links count in the same limit** (ADR-0060). Checked before anything is looked up, so the limit, too, says
   nothing about who has an account; neither the address nor the email is stored, only keyed hashes that expire.

---

## 5. Documentation, shipped as part of the product

| Kind | Lives | Written for |
|:--|:--|:--|
| **Merchant help** | `/help` inside the console app | the owner — and the prospect reading before they buy |
| **In-app guidance** | empty states, tooltips, first-run tour | the person who will never open the help site |
| **Developer docs** | wrapped around the generated OpenAPI at `/docs` | the merchant's developer building the connector |

**The most valuable documentation here is the empty state**, and it is the piece most often left until last. A merchant who has just signed up sees five empty screens; whether they ever come back is decided there, not in a help article. Every empty state answers *what is this, why is it empty, what do I do next.*

**One rule carried over from the widget** ([ADR-0020](architecture/adr/0020-a-withheld-turn-says-so.md)): merchant-facing sentences come from the server, not hard-coded into a JavaScript bundle. A sentence a merchant cannot change and nobody reviews is how a wrong promise ships.

---

## 6. What "done" means for a surface with no model

**This is [E8](open-questions.md), not a new question**, and the console must not become the reason Rule 4 is quietly skipped. Until E8 is answered, the console's own minimum bar is deterministic and testable:

1. A person reaches **only** the tenants they hold a live membership for.
2. A **revoked** membership reaches nothing, immediately — not at cookie expiry.
3. An **expired**, **consumed** or **forged** login token reaches nothing.
4. **No console response ever contains another tenant's row.** Asserted with two tenants populated, not one.
5. Sign-in **cannot be used to enumerate** which emails have accounts.
6. No credential and no API key appears in any response body, ever.

**All six are asserted, on every screen, and the repetition is the point.** The bar is *per
screen*, not per project: a membership check that holds on one route and was forgotten on
another is exactly the shape of bug §6 exists to catch, and "the other file tests it" has never
once been true of the route somebody added last. So clauses 1, 2, 4 and 6 are re-asserted in
`test_console_review.py`, `test_console_conversations.py` and `test_console_shop_and_usage.py`
— each against real PostgreSQL with **two populated tenants** — and `test_console_auth.py` owns
3 and 5.

`make console-check` then re-asserts them **in real headless Chrome** — 91 checks since 2026-09-28 — because every
rule this console has is a claim about what a *rendered page* contains. A server that offered
safe material and a screen that displayed it are not the same thing, and only one of them is the
product: a page can fetch a payload with no credential in it and still print `$0.00` under the
word "cost".

**Twice now, a browser check passed against nothing and had to be made real.** The first Shop
check asserted "no credential reached the screen" against a shop with no store connected, and
the first Usage check asked for a period label on a screen showing its empty state. Both now
seed real rows first and remove exactly those rows afterwards. *A check that can pass with
nothing to look at is not a check* — the same lesson as **E6**, in a third place.

---

## 7. Known limits, stated before anyone hits them

| Limit | Consequence |
|:--|:--|
| **Nothing in this system can send an email** | Magic-link login cannot work until a provider is chosen. The console is undeployable without it, and the failure mode is new: the software is fine and the user still cannot get in. |
| **Node and npm enter a pure-Python repo** | Second toolchain in `make check`; two ways to have a stale dependency. |
| **One role, `owner`** | A merchant who wants to give a support agent read-only access cannot, until somebody asks and it is designed. |
| **No approval queue** | Every write feature stays blocked. This is by design and is the next thing the console unlocks. |
| ~~**No connect form (v1)**~~ | **Lifted 2026-10-01** ([ADR-0052](architecture/adr/0052-the-shop-owner-connects-their-own-shop.md)): the owner connects their own shop on Shop connection. A new shop's **account** is still made by FiveNeurals. |
| **Shadow mode must be on to have anything to review** | A merchant who goes live immediately sees an empty Review screen forever. **Done 2026-08-27** — the empty state says exactly that, and distinguishes it from a filter that matched nothing. |

---

## 8. What is deliberately not decided here

* **The email provider.** A real choice with cost, deliverability and sovereign-tier consequences — a self-hosted deployment needs an SMTP path, not an API key to a US service. Decide it with **K1** / [X2](open-questions.md), which is also where the deployment target and the cloud model get decided.
* **The permission model.** One role until a merchant asks for a second.
* **Branding, colour and type.** shadcn/ui defaults until there is something to be consistent *with*.
* **Whether the console is the sovereign tier's problem too.** A customer running everything themselves still needs this screen, and their deployment has no email provider and possibly no public DNS.
