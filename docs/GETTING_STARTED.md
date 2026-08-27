# Getting Started

A complete walkthrough: set the project up, run it, and see for yourself what works. Written to be followed line by line — no prior knowledge of the codebase assumed.

**Time:** about 15 minutes, most of it waiting for downloads.

---

## Before you start — do you need a shop?

**No.** Not yet.

Everything built so far runs with **Ollama only**. There is no connection to any commerce platform, because that layer has not been built yet.

| Milestone | Needs a shop? |
|:--|:--|
| 1.1 Workspace · 1.2 Core + domain | ❌ no |
| 1.3 LLM layer · 1.4 Eval harness | ❌ no |
| **1.5–1.8 Commerce layer + sync** | ✅ **yes — first time it's needed** |
| 1.9 RAG | ✅ yes — `make rag-check` needs a real catalogue to index |
| 1.10+ agent, API | ✅ yes |

[§7](#7-what-you-will-need-later) lists exactly what data that shop will need, so you can prepare it in advance if you want to.

---

## 1. What you need installed

| | Why | Check it |
|:--|:--|:--|
| **Ollama** | Runs the AI models on your machine, free | `ollama --version` |
| **Docker Desktop** | Runs the database | `docker info` |
| **uv** | Installs Python packages | `uv --version` |
| **git** | Version control | `git --version` |
| **Node.js 20+** | Runs the merchant console only — nothing else here needs it | `node --version` |

All four are already installed on this machine. On a fresh machine:

```bash
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ollama — download from https://ollama.com/download
# Docker Desktop — download from https://docker.com
```

> **Note:** `uv` installs to `~/.local/bin`. If `uv --version` says "command not found", either restart your terminal or run `source $HOME/.local/bin/env`.

### The AI models

Four are needed. They total about 14 GB and are already on this machine:

```bash
ollama pull llama3.2:3b        # 2.0 GB — fast, for classification
ollama pull llama3.1:8b        # 4.9 GB — checks answers are true, and writes handovers
ollama pull qwen3.5:9b         # 6.6 GB — the main thinker
ollama pull nomic-embed-text   # 274 MB — turns text into numbers for search

ollama list                    # confirm all four appear
```

**Why three?** Different jobs need different sizes. Classifying "is this about an order?" doesn't need a large model, and a small one answers in a fraction of the time. Only the hard reasoning uses the big model. This is what the code calls **roles** — see [§5](#5-the-one-idea-worth-understanding).

---

## 2. Set the project up

```bash
cd ~/Developer/neura-agents

uv sync                        # installs everything, ~1 minute the first time
cp .env.example .env           # your local settings
```

`.env` works as-is for development. Nothing to edit yet.

> `.env` is where secrets go, and it can never be committed to git — that's already configured. If you later add an API key, it goes there.

---

## 3. Start the database

```bash
make up          # start Postgres + Redis
make migrate     # create the tables
```

`make up` waits until both containers are genuinely healthy, then prints `✔ datastores ready`.

```bash
docker compose ps      # both should say "healthy"
```

> **Note:** Postgres runs on port **5433**, not the usual 5432 — something else on this machine was already using 5432. If 5433 is also taken: `POSTGRES_PORT=5434 make up`.

### Why there are two database usernames

Your `.env` has both:

```
DATABASE_URL=postgresql+asyncpg://neura_app:neura_app@localhost:5433/neura
DATABASE_MIGRATION_URL=postgresql+asyncpg://neura:neura@localhost:5433/neura
```

This is not clutter. Each merchant's data is kept separate by a PostgreSQL feature called Row-Level Security — the database itself refuses to return another merchant's rows, so a mistake in our code returns *nothing* rather than someone else's data.

**That feature does not apply to database owners.** Connect as `neura` and every merchant's data becomes visible to every query, with no error and no warning. So the application connects as `neura_app`, which has no such exemption, and only migrations use the owner. The app refuses to report itself healthy if it ever finds itself connected as a privileged role.

---

## 4. Check that everything works

Four commands, in order. Each one checks something different.

### 4.1 The AI models — `make llm-check`

**The most interesting one.** It talks to your real models and proves the AI layer works:

```bash
make llm-check
```

```
  role          model               capabilities
  router        llama3.2:3b         json.object, json.schema, streaming, tools.native
  reasoner      qwen3.5:9b          json.object, json.schema, streaming, tools.native
  guard         llama3.1:8b         json.object, json.schema, streaming, tools.native
  embedder      nomic-embed-text    json.object, json.schema, streaming
  summarizer    llama3.1:8b         json.object, json.schema, streaming, tools.native

  fully local: yes  ·  embedding namespace: nomic-embed-text

  ✔ chat                 'Ready' · 2326ms · 38 tokens
  ✔ structured output    intent=order_status order_ref=Order 1001 · 1 attempt(s)
  ✔ embeddings           768 dimensions · similarity 0.651
  ✔ tool calling         called get_order_status({'order_ref': '1001'})

All checks passed. The LLM layer is working.
```

**What each line means:**

| Check | What it proves |
|:--|:--|
| **chat** | The model responds at all |
| **structured output** | It can return strict, machine-readable data — not just prose. It read *"where is my order 1001??"* and correctly extracted `intent=order_status`. `1 attempt(s)` means it got the format right first time. |
| **embeddings** | Text becomes numbers, and similar phrases score as similar. *"cast iron skillet"* vs *"frying pan"* scored 0.651 — related but not identical, which is right. This is what makes search work. |
| **tool calling** | The model can decide to *use a tool*. It read a question and asked to call `get_order_status` with `order_ref: 1001`. This is the difference between a chatbot and an agent. |

**`fully local: yes`** means not one byte left your machine. That's the data-sovereignty product tier — not a dev-only mode.

### 4.2 The scoring system — `make eval-fast`

```bash
make eval-fast
```

```
╭────────────────────────────────────────────────────────╮
│ Judged metrics were skipped (--no-judge).              │
╰────────────────────────────────────────────────────────╯
╭────────────────────────────────────────────────────────╮
│ Every case in this run is synthetic.                   │
│ This run proves the harness works, not that the agent  │
│ does.                                                  │
╰────────────────────────────────────────────────────────╯

  cases       19  (0 passed, 19 failed)

  ✘ order_status_001  execution: No agent is wired up yet — milestone 1.11
```

**19 failures is the correct result.** There is no agent yet, so nothing can pass. The important thing is that it says so honestly rather than reporting a fake score.

### 4.3 The web service — `make api`

```bash
make api
```

Then in a second terminal:

```bash
curl http://localhost:8000/v1/health
curl http://localhost:8000/v1/agents
```

```json
{"status":"ok","service":"neura-api","environment":"development"}

{"data":{"installed":[{"key":"care","name":"NEURA-CARE",
  "route_prefix":"/v1/care",
  "requires_capabilities":["order.read","policy.read","product.search"]}]}}
```

That second response is **agent discovery** working: NEURA-CARE registered itself and declared what a shop must support for it to function. Nothing lists it anywhere — it announces itself.

Interactive API docs: **http://localhost:8000/docs**

Stop with `Ctrl+C`.

### 4.4 Everything at once — `make check`

```bash
make check
```

This is what runs before every commit:

```
All checks passed!                          ← code style
36 source files, no issues                  ← type checking
Contracts: 5 kept, 0 broken                 ← architecture rules
✔ platform independence                     ← no shop names in the core
92 passed                                   ← tests
```

**The two middle lines matter most.** They mechanically enforce the promises the architecture makes. If someone imports a shop-specific library into the core, the build fails. Documented rules rot; enforced rules don't.

---

## 4b. Seeing the merchant console

Everything above is the *shopper's* side and the API. The **merchant console** is the screen a shop
owner logs into ([ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md),
[console.md](console.md)). **All five v1 screens are built**: sign in, Conversations, Review,
Shop and Usage.

It is two processes, and both must be running. `make console` prints the two commands if you
would rather not scroll.

### Terminal 1 — the API

```bash
make up          # database, if it is not already running
make api         # http://localhost:8000
```

> **If port 8000 is taken** by something else on your machine, run the API somewhere else and tell
> the console where it went:
>
> ```bash
> NEURA_API_PORT=8010 uv run neura-api
> ```
>
> then set `API_BASE_URL=http://localhost:8010` in `apps/neura-console/.env.local`. Getting this
> wrong is quiet rather than loud — the console talks to whatever is on that port, even if it is a
> different application entirely.

### Terminal 2 — the console

```bash
cd apps/neura-console
npm install      # first time only
npm run dev      # http://localhost:3000
```

### Then give yourself an account

There is **no sign-up page**, deliberately: an open form on the sign-in screen would let anyone
create an account for any address. Accounts are made from the command line.

```bash
make tenant-new NAME="My Test Shop" AGENTS=care     # prints tn_...
make user-new EMAIL=you@example.com NAME="You" TENANT=tn_...
```

Now open <http://localhost:3000>, type that address, and click the link in your inbox.

**No email arriving?** Two possibilities, and it is worth knowing which:

```bash
make user-link EMAIL=you@example.com    # prints a working link, bypassing mail
```

If that link signs you in, the login flow is fine and the problem is **delivery** — check
`SMTP_*` in `.env`, and check your spam folder. If it does not, the problem is the flow.
The sign-in screen deliberately cannot tell you which, because it must answer identically for an
address that has an account and one that does not (otherwise it becomes a way to discover which
merchants use us). **The API's log is where a delivery failure shows up**, as
`sign_in_mail_not_delivered`.

### Proving it works without watching

```bash
make console-check EMAIL=you@example.com
```

Drives **real headless Chrome** through a real emailed link and then through all five screens:
**33 assertions**, no models, no cost.

It checks things a request library cannot, because they are properties of a *rendered page*: that
the session cookie is invisible to JavaScript, that no API key or stored credential ever reaches
the browser, that the Review queue shows the evidence rather than only the reply, that a turn the
agent declined explains itself instead of rendering an empty card, that a `[EMAIL_1]` token is
explained rather than left looking like lost data, and that no unmeasured figure is printed as
money. A grade given by clicking a real button is still there after a reload.

It seeds its own conversations, shadow turns, store and usage row — **a check with nothing to look
at proves nothing** — and removes exactly those rows afterwards, by id.

### Connecting a shop is not done in the console

Screen 4 shows the connection, the catalogue and the last sync, and **has no connect form** —
that is a decision, not an unfinished screen ([console.md §3.4](console.md)). Use the API or
the CLI:

```bash
make sync-check URL=https://your-shop/neura/v1 TOKEN=...   # connects and syncs
```

### Useful

```bash
make user-show EMAIL=you@example.com                    # account + which shops
make user-revoke EMAIL=you@example.com TENANT=tn_...    # withdraw access
```

Revocation takes effect on that person's **next request** — the session cookie is never recalled,
because it grants no authority by itself.

---

## 5. The one idea worth understanding

Everything else follows from this: **the code never names a model.** It names a *job*.

```python
client.chat(ModelRole.ROUTER, request)      # yes — "use the fast one"
client.chat("llama3.2:3b", request)         # never
```

Five jobs exist:

| Job | What it does | Currently |
|:--|:--|:--|
| `ROUTER` | Works out what the customer is asking | `llama3.2:3b` |
| `REASONER` | Writes the answer, decides which tools to use | `qwen3.5:9b` |
| `GUARD` | Checks the answer is supported by the evidence | `llama3.1:8b` — **not** the 3B, and `make verify-probe` is why ([ADR-0018](architecture/adr/0018-guard-model-must-refuse.md)) |
| `EMBEDDER` | Turns text into searchable numbers | `nomic-embed-text` |
| `SUMMARIZER` | Writes handover notes for humans | `llama3.1:8b` |

A **role map** decides which model does which job. Four exist:

```bash
make llm-check                                          # ollama-dev  (default)
uv run python scripts/llm_smoke_test.py --role-map hybrid
```

| Role map | What it does |
|:--|:--|
| `ollama-dev` | Everything local. Free. **What you're using.** |
| `cloud-prod` | Everything on a paid cloud AI. Best quality. |
| `hybrid` | Fast jobs stay local, only hard reasoning goes to the cloud. Usually the best cost/quality point. |
| `sovereign` | Everything on the customer's own hardware. A product we sell. |

**Switching is one line in `.env`** — `NEURA_ROLE_MAP=hybrid`. No code changes. That's the whole point of the design, and it's already working.

---

## 6. Command reference

```bash
make help              # list every command

# running
make up                # start database + redis
make migrate           # create/update the tables
make down              # stop them
make api               # run the web service
make dev               # both at once

# checking
make llm-check         # ← test the AI against real models
make eval-fast         # scoring system, no API calls
make eval              # scoring with an AI grader
make check             # everything CI runs

# checking against a real shop (needs URL= and TOKEN=)
make conformance URL=… TOKEN=…   # does the shop implement our spec?
make sync-check   URL=… TOKEN=…   # can we copy its catalogue?
make job-check    URL=… TOKEN=…   # can a worker sync a tenant nobody told it about?
make rag-check    URL=… TOKEN=…   # can we search that catalogue by meaning?
make care-check   URL=… TOKEN=…   # can the agent hold a conversation about it?
make api-check    URL=… TOKEN=…   # can a shopper reach it over HTTP and a socket?

# individual checks
make lint              # code style
make typecheck         # type errors
make arch              # architecture rules
make test              # unit tests

# the merchant console (see section 4b)
make api                                       # terminal 1
cd apps/neura-console && npm run dev           # terminal 2
make user-new EMAIL=you@example.com TENANT=tn_...   # no sign-up page, on purpose
make user-link EMAIL=you@example.com           # a working link, when mail is not arriving
make console-check EMAIL=you@example.com       # real Chrome, 7 assertions, free

# tenants — how a merchant comes into being. Every command runs under the same
# row-level security a request does, and since milestone 1.14 the key it issues
# is one a real HTTP request can authenticate with.
make tenant-new  NAME="Acme Store" AGENTS=care
make key-new     TENANT=tn_… SCOPES=care:chat:write   # shown ONCE, then only its hash is kept
make tenant-show TENANT=tn_…
make tenant-usage TENANT=tn_…                         # what they actually spent today
```

### Optional: a better grader for `make eval`

`make eval` uses an AI to grade the agent's answers. By default it falls back to a local model and **labels every score untrustworthy** — because a weak model grading a weak model produces numbers that look real and aren't.

To fix that, get a free Gemini key at **https://aistudio.google.com/apikey** and uncomment **exactly these three lines** in `.env` — nothing else is needed. Any OpenAI-compatible endpoint works; this is just the one with a free tier.

```bash
EVAL_JUDGE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
EVAL_JUDGE_API_KEY=your-key-here
EVAL_JUDGE_MODEL=gemini-3.6-flash
```

**Pin the model. Never use a `-latest` alias** — it changes under you, and this month's scores stop being comparable with last month's with nothing in any report to say why. Model names also get retired for new API projects without notice: this file said `gemini-2.5-flash` until milestone 1.13, and it now 404s.

**A free tier will not get you through a whole run.** Measured: 20 requests a day, exhausted partway through the suite. Unjudged cases are *skipped* rather than counted against the agent, so the report stays honest and tells you how many it missed — but you will not get a complete groundedness number without paying. That is open question E2.

Then check it actually works:

```bash
make judge-check
```

```
  model   gemini-3.6-flash
  trust   trusted

  ✔ accepts a grounded reply    score=1.0
  ✔ rejects a hallucination     score=0.0
        caught: 'Your order arrived yesterday'
        caught: 'your neighbour signed for it'

  Judge is working.
```

It deliberately tests **both directions**. A judge that approves everything looks identical to a working one — right up until it silently passes a hallucination.

> ⚠ Free tiers may use what you send them to improve their products. That's fine now — every test case is invented. It stops being fine once real customer conversations are in the test data. Move to a paid tier before that day.

### The `CLOUD_*` variables are a different thing

Easy to confuse, so to be clear:

| Setting | What it's for | Needed now? |
|:--|:--|:--|
| `EVAL_JUDGE_*` | The AI that **grades** answers during testing | Optional, recommended |
| `CLOUD_LLM_*` and `CLOUD_MODEL_*` | The AI that **runs the agent** in production | No — only for `hybrid` or `cloud-prod` |

If you switch `NEURA_ROLE_MAP` to `hybrid` without setting the `CLOUD_*` variables, you'll see this — which is correct behaviour, not a bug:

```
  reasoner    not configured    CLOUD_LLM_BASE_URL, CLOUD_MODEL_REASONER

  2 role(s) not configured: reasoner, summarizer
  Set the variables above in .env, or use --role-map ollama-dev to stay fully local.
```

Your same Gemini key works for those too, if you want to try `hybrid` later.

---

## 7. What you will need later

At **milestone 1.7** the system first connects to a real shop. You don't need this yet, but here's what to prepare.

### Any shop works

Bagisto, WooCommerce, Shopify, or something custom — it genuinely doesn't matter. The shop implements **nine simple web addresses** and it's connected. That's the whole design.

Your Bagisto install at `~/Developer/bagisto` is fine as the test shop. I'll write a small add-on for it when we get there.

### Data the shop needs

Not much, but it must be *realistic*. A shop with three fake products can't demonstrate anything.

| | How much | Why |
|:--|:--|:--|
| **Products** | 20–50 | Needs real names, descriptions, prices, stock levels. Descriptions matter most — that's what search reads. |
| **Categories** | 5–10 | Structure for browsing |
| **Customers** | 5–10 | Each needs a **working email** — that's how we verify who owns an order |
| **Orders** | 20–30 | The important part. Spread across statuses: some pending, some shipped **with tracking numbers**, some delivered, some cancelled, some refunded. |
| **Policy pages** | 3 | Returns, shipping, warranty. Real text, not lorem ipsum — the agent quotes these. |

**The single most valuable thing:** orders in *varied* states with real tracking numbers. Most support questions are "where is my order", and the agent can only be tested against orders that are genuinely in different stages.

Bagisto ships a sample-data generator that produces most of this.

### Also needed on the shop

- **Redis for its background queue.** Bagisto's `.env` currently says `QUEUE_CONNECTION=sync`, which means sending us an update would freeze a customer's checkout. Changing it to `redis` fixes that.
- **An API key** we generate, so the shop can prove it's really your shop.

---

## 8. If something breaks

| Problem | Fix |
|:--|:--|
| `uv: command not found` | `source $HOME/.local/bin/env`, or restart the terminal |
| `make llm-check` → "Could not reach ollama" | Ollama isn't running. Start the app, or run `ollama serve` |
| `make llm-check` → "Model not found" | `ollama pull llama3.2:3b` (and the other three) |
| `make up` → "port already in use" | Something else uses that port. `POSTGRES_PORT=5434 make up` |
| `make up` → "Cannot connect to Docker daemon" | Docker Desktop isn't running. Open it and wait for the whale icon |
| `make llm-check` very slow | Normal on first run — the model loads into memory. Later runs are faster. |
| `relation "document_chunks" does not exist` | You skipped `make migrate` |
| "the database role is a superuser, so Row-Level Security does not apply" | `DATABASE_URL` is pointing at `neura` instead of `neura_app`. See §3 — this refusal is deliberate and must not be worked around |
| Search finds nothing that should match | The catalogue was indexed with a different embedding model than the one now configured. The error message names both |
| Tests fail after you edit something | Read the failure message; the tests are written to say what broke and why |

Still stuck? `docker compose logs` and `make check` usually say what's wrong.

---

## 9. Where things live

```
neura-agents/
├── docs/              ← all documentation, start at docs/README.md
├── packages/          ← shared building blocks
│   ├── neura-core/       settings, logging, security basics
│   ├── neura-domain/     what "an Order" and "a Product" mean
│   ├── neura-llm/        talking to AI models          ← built
│   ├── neura-commerce/   talking to shops + sync       ← built
│   ├── neura-agent-core/ search over a catalogue       ← rag built; engine not yet
│   └── neura-adapters/   shop connectors               ← built
├── agents/care/       ← NEURA-CARE                     ← manifest only
├── apps/neura-api/    ← the web service
├── evals/             ← the scoring system
├── infra/migrations/  ← database schema, applied by `make migrate`
└── scripts/           ← check tools
```

**Two files to read first:**
- [`docs/PROJECT_STATE.md`](PROJECT_STATE.md) — exactly what's built and what isn't, updated every session
- [`docs/README.md`](README.md) — index of all documentation

---

## 10. Honest status

**Working now:** the foundation, the AI connection, the scoring system, the web service, the architecture guardrails — and, since milestone 1.9, **the ability to read a real shop's catalogue and search it by meaning**. `make rag-check` copies a live shop's products and policies, turns them into vectors with a local model, and answers questions like "how much does delivery cost?" with the right policy page.

**Not built yet:** the agent itself. Nothing holds a conversation. Retrieval can find the returns policy; nothing yet decides *when* to look it up, what to say, or when to hand over to a human.

That's milestones 1.10 through 1.12 — the agent engine, then NEURA-CARE, then the safety layer.

Everything you can run today is the machinery that makes the agent possible, plus the measuring tools to tell whether it's any good once it exists. That order is deliberate: measurement first, so we never have to guess.
