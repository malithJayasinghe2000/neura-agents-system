# Testing Log — walking the whole system, end to end

> **Purpose.** One person, testing every part of NEURA by hand, in order, to build a working
> mental model of the system. Started 2026-08-27.
>
> **This is a log, not a spec.** Update it as you go. If you are a fresh session picking this up:
> read the stage table, find the first ⬜, and continue from there.

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
| 4 | Index | that data made searchable | local (embeddings) | ⬜ |
| 5 | CARE end to end | a real support conversation | local (heat) | ⬜ |
| 6 | SELL end to end | a real recommendation | local (heat) | ⬜ |
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

## Stage 4 — index ⬜

Next up. Turns the synced text into vectors so the agent can search it by meaning rather than
by keyword.

```bash
make rag-check URL=$SHOP TOKEN=$TOKEN KEEP=1
make rag-ask Q="do you sell my data?" SHOW=1
```

⚠️ Runs the local embedding model. Mild laptop heat.

---

## Stages 5–9 ⬜

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
