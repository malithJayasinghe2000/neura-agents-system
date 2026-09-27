# The Merchant Console — Design

**Status:** Designed 2026-08-26. **All five v1 screens built 2026-08-27**, a sixth — **Sold out**, [ADR-0046](architecture/adr/0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md) stage 1 — a seventh — **Suggestions**, [ADR-0050](architecture/adr/0050-the-shop-owner-may-choose-a-products-suggestions.md) — and an eighth — the shop's **Home** — all **built 2026-09-27**, when the console also gained a side menu and plain words (§3.0) — `make console-check` — 59 checks in a real browser. · **Decision:** [ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) · **Unblocks:** A4, E1, S5, and eventually [ADR-0010](architecture/adr/0010-read-only-mvp-tools.md)

> **Read [ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) first.** It records *why* — including the three decisions a fresh session is most likely to reverse by accident: the browser never holds a tenant API key, login is built rather than bought, and `users` is deliberately not tenant-scoped.

---

## 1. What this is, in one paragraph

The screen a shop owner logs into. It shows them what their AI assistant said, lets them grade answers before those answers ever reach a customer, connects their shop, and reports what it cost. **It is the first thing in this project built for the person who pays**, and it is the keystone under four deferred features.

### 1.1 What it is not

It is **not** an admin panel for us, it is **not** a replacement for the shop's own back office, and in v1 it does **not** approve anything — because nothing in the system can yet change a merchant's store ([ADR-0010](architecture/adr/0010-read-only-mvp-tools.md)).

---

## 2. Scope — v1 is five screens

Deliberately cut the way CARE's three intents were cut. The temptation is eleven screens; the discipline is five.

| # | Screen | Reads | Ships in v1 |
|:--|:--|:--|:--|
| 1 | **Sign in** | `users`, `login_tokens` | ✅ **built 2026-08-27** |
| 2 | **Conversations** | `conversations`, `conversation_messages` | ✅ **built 2026-08-27** |
| 3 | **Review** (shadow grading) | `shadow_turns`, `conversation_messages`, `document_chunks` | ✅ **built 2026-08-27 — the one that earns its keep** |
| 4 | **Shop** | `tenant_stores`, `sync_checkpoints`, `neura_entities` | ✅ **built 2026-08-27 — read-only, see §3.4** |
| 5 | **Usage** (on screen: *Usage and cost*) | `tenant_usage`, `tenants` | ✅ **built 2026-08-27** |
| — | **Home** — what needs the owner, and how the assistant is set up (§3.0) | nothing of its own — it reads the endpoints of Review, Usage, Shop, Sold out and Suggestions | ✅ **built 2026-09-27** — outside v1's five like the two below it. **Adds a screen and no data**: every figure on it is one another screen already shows, with its period and its server-written caveat |
| — | **Sold out** — views of products while they could not be bought ([ADR-0046](architecture/adr/0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md) stage 1, [ADR-0049](architecture/adr/0049-a-product-view-records-whether-it-could-be-bought.md)) | `observed_events`, `synced_entities`, `tenants` | ✅ **built 2026-09-27** — outside v1's five, and 0046 records breaking the discipline on purpose. Counts and sessions, never a session token; not gated by the SELL entitlement (neura-api may not learn an agent's name) |
| — | **Suggestions** — what a basket suggests with each product, and the owner's way to change it ([ADR-0050](architecture/adr/0050-the-shop-owner-may-choose-a-products-suggestions.md)) | `synced_entities`, `sell_pairings`, `sell_pairing_choices` | ✅ **built 2026-09-27** — the **second screen that writes** (after grading). Served by SELL's own routes under `/v1/sell/console/…`, so the SELL entitlement is checked inside the agent; a shop without SELL is told so. Reads the **synced** catalogue: a product the shop added since the last sync is not listed until a sync runs |
| 6 | Security | `audit_log` | v1.1 — closes **S5** |
| 7 | Settings & keys | `api_keys` | v1.1 |
| 8 | Approvals | — | **blocked** by [ADR-0010](architecture/adr/0010-read-only-mvp-tools.md) |

**Build order is 1 → 3 → 2 → 4 → 5**, and Review is second on purpose. It is the only screen that produces something the project does not already have: **real graded turns**, which is the sole route out of **E1** (every golden case is synthetic today). A console that shipped analytics first would look finished and change nothing.

---

## 3. The screens

### 3.0 The frame, the Home screen and the words — 2026-09-27

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

**The words** the owner approved, used everywhere a merchant reads them:

| was | now |
|:--|:--|
| Withheld (shadow mode) · shadow mode | **Held for your review** · **practice mode** (glossary: same thing as shadow mode) |
| `care` / `sell` | **Customer care** / **Shopping help** (`lib/assistants.ts`; an unknown key shows as itself) |
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
parameter. The per-agent split is labelled *today* because that is the grain the
meter records; summing it across a 30-day selector would report something nobody
measured.

**The caveats come from the server**, not from the JavaScript bundle — ADR-0020's
rule for merchant-facing sentences — and each appears only when it is true, so
the list never becomes boilerplate a reader learns to skip.

---

## 4. Identity — the part that is genuinely new

### 4.1 Three tables

```
users                       (NOT tenant-scoped — see ADR-0026 §4)
  id, email (citext, unique), name, created_at, last_seen_at

memberships                 (tenant-scoped, forced RLS)
  id, tenant_id, user_id, role='owner', created_at, revoked_at

login_tokens                (NOT tenant-scoped)
  id, user_id, token_hash, expires_at, consumed_at, requested_ip
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

`make console-check` then re-asserts them **in real headless Chrome** — 59 checks since 2026-09-27 — because every
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
| **No connect form (v1)** | A merchant cannot connect their own shop; somebody with API access has to. Deliberate — see §3.4. It blocks self-serve onboarding and nothing else. |
| **Shadow mode must be on to have anything to review** | A merchant who goes live immediately sees an empty Review screen forever. **Done 2026-08-27** — the empty state says exactly that, and distinguishes it from a filter that matched nothing. |

---

## 8. What is deliberately not decided here

* **The email provider.** A real choice with cost, deliverability and sovereign-tier consequences — a self-hosted deployment needs an SMTP path, not an API key to a US service. Decide it with **K1** / [X2](open-questions.md), which is also where the deployment target and the cloud model get decided.
* **The permission model.** One role until a merchant asks for a second.
* **Branding, colour and type.** shadcn/ui defaults until there is something to be consistent *with*.
* **Whether the console is the sovereign tier's problem too.** A customer running everything themselves still needs this screen, and their deployment has no email provider and possibly no public DNS.
