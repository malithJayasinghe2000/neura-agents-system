# Testing Log — walking the whole system, end to end

> **Purpose.** One person, testing every part of NEURA by hand, in order, to build a working
> mental model of the system. Started 2026-08-27.
>
> **This is a log, not a spec.** Update it as you go.
>
> **If you are a fresh session picking this up:** read `CLAUDE.md` and `docs/PROJECT_STATE.md`
> first, then this file. Find the first ⬜ in the stage table and continue from there — small
> steps, one command at a time, in plain language. Log what each stage proved, and log anything it
> found. **The findings are the point.** Three real defects surfaced in one afternoon of Stages
> 1-6, none of which fourteen eval runs had ever seen.

---

## What the system is, in five lines

A **shopper** types a question into a chat widget on a shop's website.
An **AI agent** answers it, using only that shop's own data.
A second AI **checks the answer** before the shopper sees it.
The **shop owner** watches all of this in a separate web console, and grades it.
Nothing the AI does can **change** anything in the shop — it is read-only, on purpose.

### The two agents

| Agent | Answers questions like |
|:--|:--|
| **NEURA-CARE** | *"Where is my order?"* · *"What's your returns policy?"* · *"Is this waterproof?"* |
| **NEURA-SELL** | *"I need a waterproof jacket under £150"* · *"Which of these two is warmer?"* |

### The console is the owner's screen, not the shopper's

The shopper never sees it. Five screens:

| Screen | Plain meaning |
|:--|:--|
| Sign in | Owner logs in via an emailed link |
| **Conversations** | Every chat the AI had |
| **Review** | *"The AI wrote this. Right or wrong?"* 👍/👎 |
| Shop | *"Is my store still connected?"* |
| Usage | How many chats, what it cost |

**Review is the important one.** Every test case in this project is currently invented. Review is
the only route to real graded answers — which is the only route to knowing whether the AI is good.

### The one idea that explains the architecture

**The shop speaks our language; we do not speak the shop's.**

Most products write one adapter per platform (a Shopify one, a Woo one, a Magento one). This one
does not. Instead the shop exposes **nine read-only URLs** in a fixed shape, and we read those.
Bagisto does it through a small bridge package; the next shop will need the same.

`make conformance URL=... TOKEN=...` is the single command that says whether a shop has done it.

---

## Setup used for this log

```bash
export SHOP=http://bagisto.test/neura/v1
export TOKEN=$(grep '^NEURA_API_TOKEN=' ~/Developer/bagisto/.env | cut -d= -f2-)
```

Bagisto must be running (Herd). **Known trap:** `/health` returns 200 but products fail with 500 →
MySQL is on port 3307 while the shop is configured for 3308.

---

## Stages

| # | Stage | Proves | Models? | Status |
|:--|:--|:--|:--|:--|
| 1 | Machine works | database, types, 848 tests, Ollama reachable | local | ✅ 2026-08-27 |
| 2 | Shop conformant | the shop exposes the 9 endpoints correctly | none | ✅ 2026-08-27 |
| 3 | Sync | shop data copied into our Postgres | none | ✅ 2026-08-27 |
| 4 | Index | that data made searchable | local (embeddings) | ✅ 2026-08-27 |
| 5 | CARE end to end | a real support conversation | local (heat) | ⬜ |
| 6 | SELL end to end | a real recommendation | local (heat) | ◐ tooling built |
| 7 | Widget | what a shopper actually sees | local | ✅ 2026-08-27 |
| 8 | Console | what the owner sees, incl. grading a real turn | none | ⬜ |
| 9 | New e-commerce | a second shop passes conformance | none | ⬜ |

---

## Stage 1 — machine works ✅

```bash
make up          # Postgres + Redis
make migrate     # tables
make check       # lint, mypy, 7 import contracts, 848 unit tests, 12 widget tests
make llm-check   # Ollama reachable, all five roles
```

**Result:** all green. `make check` 848 passed. `llm-check` confirmed five roles —
`llama3.2:3b` (router), `qwen3:8b` (reasoner), `llama3.1:8b` (guard),
`nomic-embed-text` (embedder, 768 dims), fully local.

---

## Stage 2 — shop conformant ✅

```bash
curl -s $SHOP/health -H "Authorization: Bearer $TOKEN"
make conformance URL=$SHOP TOKEN=$TOKEN
```

**Result:** `20 passed · 0 failed · 0 warnings — Conformant. This store can be connected.`

The shop declares 10 capabilities: product read/search, category read, inventory read, order
read/search, customer read, policy read, `sync.incremental`, `events.realtime`.

**This is the command to run against the new e-commerce in Stage 9.** If it passes, that shop is
connected. If it fails, it names the endpoint that is wrong.

---

## Stage 3 — sync ✅

```bash
make sync-check URL=$SHOP TOKEN=$TOKEN
```

**Result:** 29 products · 6 categories · 11 policies, into tenant `tn_smoke`.
Re-running changed nothing. Deliberately corrupting the local copy and re-syncing repaired it.

**Why a copy at all:** the agent never calls the shop live during a conversation. It reads our
copy. That is what keeps a slow shop from making the AI look slow.

### ⚠️ Open gap found here: nothing syncs on a timer

- The worker that runs sync jobs exists ✅
- The "which shops are due?" query exists ✅ ([ADR-0022](architecture/adr/0022-scheduling-under-rls.md))
- **Nothing fires it on a schedule** ❌ — a recurring schedule is a `cron`-shaped table and its
  own decision, recorded as not built in [PROJECT_STATE.md](PROJECT_STATE.md)

So today a price change in the shop leaves our copy stale until someone triggers a sync.
Softened by two things: incremental sync is cheap (it fetches only what changed), and the shop
declares `events.realtime`, so webhooks *can* push changes — built, optional, not wired here.

**This belongs on the roadmap before a real merchant.** A merchant will not accept "your prices
are right whenever somebody remembers to press a button".

---

## Stage 4 — index ✅

```bash
make rag-check URL=$SHOP TOKEN=$TOKEN KEEP=1
make rag-ask Q="do you sell my data?" SHOW=1
```

**Result:** 46 entities → **49 chunks**, all embedded with `nomic-embed-text` (768 dims), under
namespace `tn_ragsmoke/nomic-embed-text`. Re-running embedded **0** — it knows what it already has.
Retrieval: **5 of 7** probes hit the right source type; the two misses are the documented ones
(*"something to wear to the office"* and a pronoun with no referent — a pronoun cannot be embedded
into a match).

Querying under a *different* embedding model returns empty **and says why**, rather than silently
returning nothing — the namespace-mismatch trap from llm-abstraction.md §5.2.

**What indexing buys you:** *"keeping my feet warm"* can find *Merino Walking Socks*, even though
those words appear nowhere in the product. Search by meaning, not by keyword.

---

## What we store about a merchant, and what we never do

Asked during Stage 4, and worth having written down for the first merchant conversation.

| | Copied into our database? | Why |
|:--|:--|:--|
| Products, categories | ✅ yes | public — anyone browsing the shop sees them |
| Policies (returns, shipping, privacy) | ✅ yes | public — published on their site |
| **Orders** | ❌ **never** | read live per question, through the adapter |
| **Customer records** | ❌ **never** | read live, and only for a *verified* customer |

Written into `neura_commerce/sync/engine.py` as a design decision, for freshness — *"an order's
status changes fast, and 'your parcel is out for delivery' being an hour stale is a worse failure
than the answer taking 400ms"* — but the privacy consequence is real and worth stating: **we hold
no customer's personal data taken from the shop.**

The one personal thing that *is* stored is the **conversation**, because the console has to show
it. Personal details are replaced with tokens (`[EMAIL_1]`) **before** anything is written
(security-model.md §6.2), and transcripts are kept 90 days.

### Two things to fix before a real merchant

1. **The key that encrypts a merchant's store credentials lives in an environment variable**, not
   a key manager. `.env` says so itself: *"acceptable for a pilot; cloud KMS is required before
   real merchants"* (security-model.md §12.3).
2. **There is no data processing agreement.** The facts above are true and precise; nothing states
   them in a document a merchant's lawyer can read and sign.

The honest pitch: *"We copy your catalogue and your published policies. We never copy your orders
or your customers. Chat transcripts are kept 90 days with personal details stripped."*

---

## Stage 5 — CARE end to end ⬜

Next up. Turns the synced text into vectors so the agent can search it by meaning rather than
by keyword.

```bash
make rag-check URL=$SHOP TOKEN=$TOKEN KEEP=1
make rag-ask Q="do you sell my data?" SHOW=1
```

⚠️ Runs the local embedding model. Mild laptop heat.

---

Next up. A real support conversation, start to finish.

```bash
make care-ask Q="where is my order 1001?" URL=$SHOP TOKEN=$TOKEN CUSTOMER=385
make care-check URL=$SHOP TOKEN=$TOKEN
```

⚠️ Runs router + reasoner + guard locally. Real laptop heat, ~20-90s per question.

## Stage 6 — SELL end to end ⬜ (tooling built 2026-08-27)

`make sell-ask` did not exist. Written this session, because **until it did, SELL had never once
been pointed at a real catalogue** — the 0.43 escalation precision, the four A14 failures, the
whole of `evals/` all ran against `store.json`, four invented products. A recommender graded only
on fixtures is graded on somebody's imagination.

```bash
make sell-ask Q="I need something warm for winter" URL=$SHOP TOKEN=$TOKEN
```

It prints the two places SELL *chooses*, which is what makes it different from `care-ask`:
`plan` picks the search **and its query string**, and `shortlist` decides in code what may be
recommended at all. It also prints `promises` on every run — the list `respond` will refuse to
let the draft stray outside of.

### ⚠️ Finding 1: product search goes to the SHOP, not to our index

`search_products` calls the merchant's own `/products?q=` endpoint. Our semantic index is used by
`retrieve` for policy and context — **not for finding products**. Measured against the test shop:

| query | results |
|:--|:--|
| `jacket` | 4 |
| `waterproof` | 2 |
| **`warm jacket`** | **0** |

The shop stocks a *Waxed Cotton Field Jacket*, a *Quilted Liner Vest* and a *Lightweight Rain
Shell*. Adding one adjective returns nothing.

**So SELL's recommendation quality is capped by the merchant's search engine**, not only by their
product data. `sell.md` §5.2 says quality is bounded above by the merchant's catalogue; this is
stronger and was not written down. It never showed up in the evals because the fixture store's
search is ours.

**Recorded as [A16](open-questions.md).** The options each cost something: search our own semantic index instead
(better matching, but a stale index now decides what is recommended), send simpler queries
(loses the shopper's constraints), or fall back from the shop's search to ours when it returns
nothing (two behaviours, one of which is invisible).

### ✅ Fixed: a chunk address was readable as a product id

The first real question — *"show me a jacket"* — returned **"this shop doesn't appear to carry
it"**, from a shop with four jackets.

```
RETRIEVE  found  ['product:1311#0', ...]                    ← the search WORKED
PLAN      chose  get_product_details(product_ref='product:1311#0')
ACT       store said: no product with id 'product:1311#0'
SHORTLIST nothing survived
NO_MATCH  "this shop doesn't appear to carry it"
```

Product **1311 is the Waxed Cotton Field Jacket**. Semantic search found exactly the right
product; the id it was handed was a *chunk address*, not a product id.

**The prompt was obeyed, and that is the point.** `plan.md` says *"Do not guess ids. Every id you
pass must have appeared in a result you were shown."* The model followed it exactly. The id it was
shown was the wrong one, so the rule **produced** the error rather than preventing it — the shape
of every rule 3 argument in this project, arriving in a prompt instead of an authorisation check.

Fixed by naming the attributes: `ref="1311" chunk="0"` instead of `id="product:1311#0"`. Re-run
gives `get_product_details(product_ref="1311")` → *Waxed Cotton Field Jacket, 165.00 USD, in
stock*, shortlisted. Pinned by a test.

### ⚠️ Finding 3 — the worst one: `no_match` overclaims, and it is shipping

*"I need trousers under 40"* → the planner searched `"trousers under 40"` → the shop's literal
search returned zero → the shopper was told **"this shop doesn't appear to carry it"**, about a
shop holding five kinds of trousers.

`sell.md` §2.3 says that sentence is a claim about the **entire store** and is only safe when the
evidence covers the entire store. `shortlist` enforces it — and enforces the wrong half. It asks
*"did the store reply?"*, never *"did we ask it a question it could answer?"* **A search returning
zero rows counts as the store having answered.**

So the guarantee holds against an outage, and not against a bad query — which is the far commoner
case. **Recorded as [A15](open-questions.md), 🔴.** Not fixed: widening the precondition trades the
honest-miss message, which is a real feature, against a false claim about a merchant's whole
catalogue. The false claim is worse and it is what currently ships.

### ⚠️ Finding 2: each script indexes under its own tenant

`make rag-check` indexed under `tn_ragsmoke`; `sell-ask` runs under `tn_sell_ask` and found
nothing. Not a bug — tenant isolation working — but it means `retrieve` is empty unless you index
that tenant too:

```bash
make rag-check URL=$SHOP TOKEN=$TOKEN KEEP=1 TENANT=tn_sell_ask
```

---

## Stage 7 — the widget ✅

What a shopper actually sees. Needs the API running.

```bash
make api                                             # or: NEURA_API_PORT=8010 uv run neura-api
make widget-check                                    # headless Chrome, no models, free
make widget-check-live URL=... SHOP=$SHOP TOKEN=$TOKEN            # one real turn
make widget-check-live URL=... SHOP=$SHOP TOKEN=$TOKEN SHADOW=1   # the withheld version
make widget-demo URL=... SHOP=$SHOP TOKEN=$TOKEN     # prints a URL to open by hand
```

**Result:** all four green.

| run | what it proves | models |
|:--|:--|:--|
| `widget-check` | 4 scenarios against a **stub**: an answered turn draws the reply, a shadowed turn draws the server's words rather than silence, an empty turn is visibly an error, and a **refused socket falls back to REST and still answers** | none |
| `widget-check-live` | the real `widget.js`, the real key, the real origin lock, the real graph — *"can I return these after 20 days?"* → **"You can return most items within 30 days of delivery for a full refund"** | local |
| `…​ SHADOW=1` | what a shopper is shown when the reply is withheld: *"Thanks — your message has been received."* | local |
| `widget-demo` | a URL to open by hand. `/v1/widget/demo` is `include_in_schema=False` and **404s in production** — deliberate, and correct | none |

**The stub is the valuable one and it is free.** Three of its four scenarios are states that are
awkward to produce on demand — a withheld reply, an empty answer, a socket that will not open —
and the socket-to-REST fallback is the one nobody would notice was broken until a shopper behind
a corporate proxy could not get an answer.

### ✅ Re-verified after the fixes, same afternoon

Stage 7 was re-run from the top once the three defects above were fixed. All four commands green
again, and the two dead fields now carry values.

**A17 was confirmed exactly, by accident of model variance.** Two real local turns, same code:

| | turn that **escalated** | turn that **resolved** |
|:--|:--|:--|
| `latency_ms` | 23570 ✅ | 21613 ✅ (`curl` measured 21.8s) |
| `prompt_revision` | *empty* ❌ | `662df2be…` ✅ |

So the fix works wherever the value exists, and the value does not exist on a turn that gives up
before `respond`. That is A17 stated as a measurement rather than as a reading of the code.

**The resolved turn's row, which is the whole system in one line:** `intent policy_qa`,
`tool_calls 1`, `llm_calls 5`, `grounded t`, `latency_ms 21613`, `cost_usd 0`, `mode shadow` —
and **`verdict` empty**. That blank is **E1**. Everything else in this project has been measured
against invented cases; that column is where a real human judgement would go, and Stage 8 is the
only thing that can fill it.

**Cleanup verified both directions.** One shopper question wrote **7 rows across 7 tables**
(`shadow_turns`, `conversations`, `conversation_messages`, `tenant_usage`, `api_keys`,
`tenant_stores`, `tenants`); `make tenant-drop` took all seven to **0**. Orphan count across the
database is **still exactly 3**, all created *before* the fix — four runs since have added none.

*(`conversation_messages` holds only the shopper's words on a shadow turn. The AI's draft goes to
the review queue instead of the transcript, deliberately — withheld from the shopper means
withheld from the shopper's history too.)*

### ⚠️ Trap: port 8000 was somebody else's app

`localhost:8000` answered `404`, not "connection refused" — an unrelated project was on it. Every
live command here defaults to `URL=http://localhost:8000`, so the check would have driven a real
browser at a stranger's API and reported a failure about *our* widget. Our API also does not serve
`/health`; it is **`/v1/health`** and `/v1/health/ready`. Run ours on another port:

```bash
NEURA_API_PORT=8010 uv run neura-api
curl -s localhost:8010/v1/health/ready     # postgres ok, redis ok
```

### ✅ Fixed: the review queue recorded no latency, ever

The shadow turn landed in the queue with `latency_ms = 0`, on a turn that had really run five
model calls locally. Not a rounding error — **the turn is never timed at all.** `_shadow_turn` in
`neura_api/turns.py` set every other field and skipped this one, so it fell to its dataclass
default. The field is read in two places (the console Review screen, and the scorecard's
`total_latency_ms`, whose own comment says *"the tail is what a shopper waits behind"*), so both
were rendering a zero nobody had measured.

The same shape as five failures already on this project's record: **a number nobody has read is
not a number that works.** Fixed by timing the graph — wall-clock around `runner.run` and its
adapter teardown, deliberately not a sum of model calls, because the tool round-trips and the
adapter's HTTP are exactly the part a per-call meter cannot see.

Verified on a real turn: `curl` measured **23.8s**, the row now records **`latency_ms 23570`**.

### ⚠️ Finding 4: the turns worth grading cannot say which prompt wrote them

`prompt_revision` was also never written — same omission, same function, and the answered-turn
transcript **twelve lines above it** was passing the value correctly. Forwarding it was one line.

**It is still empty, and that is the finding.** The re-run turn escalated, and
`usage["prompt_revision"] = REVISION` is set only in `respond` — the last node of the happy path.
So **every turn that escalates, declines or is blocked carries no revision**. The shadow queue
exists to grade failures; a failure whose prompt nobody can name is evidence about nothing. Worse,
it is the exact precondition for the mistake this project has now recorded twice — the 2026-07-30
prompt loosened to make a gate go green, and A14's near-miss of tightening one against a fault the
model no longer had. Recorded as **[A17](open-questions.md)**, not fixed: stamping the revision at
graph entry is almost certainly right, but it changes both agents and the eval harness, and that
is not a cleanup helper's decision.

### ⚠️ Finding 5: nothing in this project deletes a merchant

Chasing the missing latency turned up something bigger. Today's live turns had left **no
transcript at all** — which looked like the widget failing to persist, and was not. Persistence
works; **cleanup was eating it.** `deprovision()` in `scripts/widget_check.py` deleted 7 of the 19
tenant-scoped tables and left twelve standing.

Counted on the live database, rows belonging to tenants that no longer exist:

| table | orphaned rows |
|:--|--:|
| `document_chunks` | **147** |
| `synced_entities` | **46** |
| `audit_log` | 4 |
| `sync_checkpoints` | 3 |
| `shadow_turns` | 3 |

The shadow rows are drafts of replies whose conversation, message and tenant had all been deleted
around them. The first two are **the merchant's own catalogue, embedded and stored, outliving the
tenant that owned it.**

**And `deprovision` is the only code in the repository that deletes a tenant.** It is a test
harness helper. So the honest pitch written down in Stage 4 — *"we copy your catalogue and your
published policies"* — currently has no ending, because there is no route through the product for
a merchant who asks for it back.

**The fix was refused by the database, and the refusal is the best thing found today.** The first
version deleted all 19 tables; Postgres answered `permission denied for table audit_log`.
`neura_app` is granted only `INSERT` and `SELECT` there — **append-only is a privilege, not a
convention somebody remembered to honour**, so the guard events behind ADR-0012 and S5 survive the
code that erases everything else. A control that had never been exercised was exercised, and it
held.

That leaves a genuine conflict rather than a bug: a tamper-evident security log that must be kept,
against a deletion promise that must be kept. Recorded as **[S10](open-questions.md)**, alongside
S2 (the KEK in an env var) and the missing DPA — the same pre-merchant conversation.

The helper now covers 18 tables, documents why the nineteenth is absent, and was verified to leave
**zero residue**. The 203 pre-existing orphans were **left in place as the evidence**; clearing
them is a one-line drop per tenant when someone wants the database tidy.

## Stage 8 — the console ⬜

What the shop owner sees, and the only screen that produces something this project does not
have: **a real graded turn** (**E1**).

```bash
make console                                         # prints the two commands to run
make tenant-new NAME="My Shop" AGENTS=care
make user-new EMAIL=you@shop.com TENANT=tn_...
make user-link EMAIL=you@shop.com                    # a sign-in URL
make console-check EMAIL=you@shop.com                # 33 browser checks
```

## Stage 9 — the new e-commerce ⬜

The same command Stage 2 used. If it passes, that shop is connected; if it fails, it names the
endpoint that is wrong.

```bash
make conformance URL=https://newshop/neura/v1 TOKEN=xxx
```

⚠️ **Know this before starting:** the new shop must expose the **nine read-only endpoints** itself.
That is real work — `docs/INTEGRATION_GUIDE.md` is the spec — not a settings screen. Bagisto does
it through a bridge package.

Not started. See the stage table above.

---

## Running notes

**2026-08-27 — cost of a cloud eval run is now known.** `$0.011` per full SELL suite on
`gemini-3.6-flash`, ~100 seconds. The first real cost figure this project has ever had. Everything
in Stages 1–3 above is free — no models, or local ones.

**2026-08-27 — the local models are the weak link, and it is measured.** SELL's release gate sits
at escalation precision 0.43 on `ollama-dev` and 1.00/0.75/0.75 on a cloud model. Three of four
known failures do not reproduce on cloud at all. See **A14** in
[open-questions.md](open-questions.md). Expect local runs in Stages 5–6 to look worse than the
product actually is.
