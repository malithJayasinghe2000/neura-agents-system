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
| 7 | Widget | what a shopper actually sees | local | ⬜ |
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

## Stage 7 — the widget ⬜

What a shopper actually sees. Needs the API running.

```bash
make widget-check                                    # headless Chrome, no models, free
make widget-demo SHOP=$SHOP TOKEN=$TOKEN             # prints a URL to open by hand
```

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
