# Walkthrough — What Is Built, And How To Test Every Part Of It

> **Who this is for:** the person who owns this project and needs to understand it end to end
> — not a fresh AI session, and not a merchant's developer.
>
> Every section says three things: **what it is**, **why it exists**, and **the command that
> proves it works**. Work through it in order the first time; after that use it as an index.
>
> Companion documents: [PROJECT_STATE.md](PROJECT_STATE.md) is what is true *today*.
> [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) is for a merchant's developer.
> This file is for you.

---

## 0. The product, in one page

**A merchant sells things online. Their customers ask questions. This answers them.**

```
   A shopper on a merchant's website
            │
            │  "where is my order 1001?"
            ▼
   ┌───────────────────────────────────────────┐
   │  THE WIDGET       a chat box on their site│
   └───────────────────┬───────────────────────┘
                       │ HTTPS / WebSocket
                       ▼
   ┌───────────────────────────────────────────┐
   │  THE API          checks who is asking    │
   ├───────────────────────────────────────────┤
   │  NEURA-CARE       the agent that answers  │
   ├───────────────────────────────────────────┤
   │  THE TOOL LAYER   with a policy engine    │
   │                   that says yes or no     │
   └─────────┬─────────────────────┬───────────┘
             │                     │
             ▼                     ▼
   ┌──────────────────┐   ┌──────────────────┐
   │ THE MERCHANT'S   │   │  AN AI PROVIDER  │
   │ SHOP             │   │  (Ollama local,  │
   │ read-only        │   │   or a cloud API)│
   └──────────────────┘   └──────────────────┘
```

**Three sentences that capture the whole design:**

1. **The core does not know what platform the shop runs on.** Not Shopify, not Bagisto — the
   name of a platform may only appear in one folder, and a CI check fails if it appears
   anywhere else. That is the entire market position.
2. **Safety is code, never an instruction to the model.** "Does this person own order 1001?"
   is answered by a policy engine, not by asking the AI politely.
3. **The agent cannot change anything.** There is no write tool. Not disabled — it cannot be
   registered.

---

## 1. Set up once

```bash
make up          # start PostgreSQL + Redis in Docker
make migrate     # create the tables
make check       # lint, types, architecture, all tests — takes ~1 minute
```

`make check` is the one command that must always be green before you push.

You will also want the test shop running at `http://bagisto.test` for anything marked
**needs the shop** below. Its token lives in that project's `.env` as `NEURA_API_TOKEN`.

```bash
export SHOP=http://bagisto.test/neura/v1
export TOKEN=$(grep '^NEURA_API_TOKEN=' ~/Developer/bagisto/.env | cut -d= -f2-)
```

---

## 2. The layers, bottom to top

Eight layers. Each one only knows about the ones below it — enforced by seven import
contracts, so a wrong `import` fails the build rather than being noticed in review.

```
   ┌──────────────────────────────────────────────┐
   │ 8  THE WIDGET        what a shopper sees     │
   ├──────────────────────────────────────────────┤
   │ 7  THE API           auth · limits · billing │
   ├──────────────────────────────────────────────┤
   │ 6  NEURA-CARE        the agent               │
   ├──────────────────────────────────────────────┤
   │ 5  AGENT CORE        graph · tools · policy  │
   ├──────────────────────────────────────────────┤
   │ 4  RAG               search the shop's text  │
   ├──────────────────────────────────────────────┤
   │ 3  COMMERCE          adapters · sync         │
   ├──────────────────────────────────────────────┤
   │ 2  LLM               model roles             │
   ├──────────────────────────────────────────────┤
   │ 1  CORE + DOMAIN     config · db · vocabulary│
   └──────────────────────────────────────────────┘
```

---

### Layer 1 — Core and Domain

**What it is.** The vocabulary and the plumbing. `neura-domain` holds the words the whole
system reasons in: `Order`, `Product`, `Customer`, `Policy`, `Money`, `Address`. `neura-core`
holds config, logging, errors, encryption, the database connection and tenancy.

**Why it matters.** `neura-domain` is **pure** — it imports only Pydantic and the standard
library. No database, no HTTP. That purity is what lets everything above it be replaced
without touching the words.

**Test it:**

```bash
uv run pytest tests/unit/test_domain.py tests/unit/test_core.py -q
uv run lint-imports        # 7 contracts — proves the layering is real
```

**What you should see:** all green, and `Contracts: 7 kept, 0 broken`.

---

### Layer 2 — The LLM layer

**What it is.** The system never says "use GPT-4". It says **"use the ROUTER role"**, and a
*role map* decides which actual model that is.

| Role | Job | Local (`ollama-dev`) |
|:--|:--|:--|
| `ROUTER` | Classify the question — fast, cheap | `llama3.2:3b` |
| `REASONER` | Write the answer | `llama3.1:8b` |
| `GUARD` | Check the answer is true | `llama3.1:8b` |
| `EMBEDDER` | Turn text into numbers for search | `nomic-embed-text` |
| `SUMMARIZER` | Condense | — |

**Why it matters.** Swapping to a cloud provider is a config change, not a code change. Four
maps exist: `ollama-dev` (all local), `cloud-prod` (all cloud), `hybrid` (cheap roles local,
reasoning cloud), `sovereign` (all local, for customers who cannot send data out).

**Test it:**

```bash
make llm-check        # needs Ollama running. Chat, schema, embeddings, tool calling
```

> ⚠️ **Runs real models — warms the laptop.** For a cheaper run use `NEURA_ROLE_MAP=hybrid`,
> which sends only the expensive role to a cloud API.

---

### Layer 3 — Commerce: how a shop connects

**This is the layer that answers "how do we connect a new e-commerce platform?"** — see §5
for the full story.

**What it is.** A `CommerceAdapter` protocol plus **capability negotiation**. An adapter
declares what its platform can do; the agent's toolset is *computed* from that declaration.

**Why it matters.** Without capability negotiation, "supports any platform" collapses the
first time a platform lacks a feature. With it, a shop that cannot search products simply
never gets a search tool.

Also here: the **sync engine** — it copies the shop's catalogue and orders to us so that a
shopper's question does not become five live API calls to the merchant's server.

**Test it:**

```bash
make conformance-self-test                     # the checker checks itself
make conformance URL=$SHOP TOKEN=$TOKEN        # needs the shop
make sync-check   URL=$SHOP TOKEN=$TOKEN       # needs the shop
```

**What you should see:** conformance passes with 0 failures and 0 warnings against Bagisto.
That single result is the proof that the whole platform-independence claim is real.

Synced data lands in PostgreSQL — `synced_entities` and `sync_checkpoints`, both under the same
forced Row-Level Security as everything else ([ADR-0021](architecture/adr/0021-synced-entities-are-documents.md)).
**Run `make sync-check` twice**: the first run downloads the catalogue, the second finds
everything unchanged and writes nothing. That second run is the whole feature, and it is the one
thing an in-memory store can never show you.

---

### Layer 4 — RAG: searching the shop's own words

**What it is.** The merchant's policy pages and product descriptions are chopped into pieces,
turned into numbers ("embeddings"), and stored in PostgreSQL with `pgvector`. When a shopper
asks something, we find the closest pieces and give them to the AI as **evidence**.

**Why it matters.** This is what makes the answer come from *the merchant's actual words*
rather than from the model's imagination.

Each tenant's vectors are namespaced by `(tenant_id, embedding_model)` — so one merchant can
never retrieve another's text, and changing the embedding model does not silently mix two
incompatible sets of numbers.

**Test it:**

```bash
make rag-check URL=$SHOP TOKEN=$TOKEN KEEP=1     # index the real shop
make rag-ask Q="what is your returns policy?" SHOW=1
```

**What you should see:** the second command prints the actual policy text it found, with
scores. This is the "why did it say that?" tool — when an answer looks wrong, start here.

---

### Layer 5 — The agent runtime

The most important layer to understand. Four parts.

#### 5a. The graph

The agent is **not** a loop that lets a model decide what to do next. It is an explicit state
machine with named steps ([ADR-0004](architecture/adr/0004-langgraph-explicit-graph.md)):

```
  guard → route → retrieve → plan → act → triage → compose → verify → respond
                     │                                                   ▲
                     └── decline ─────────────────────────────────────────┘
                     └── escalate (hand to a human)
                     └── blocked  (a named attack)
```

**The builder refuses to compile a graph** where `respond` can be reached without passing
`verify`, or that has no `escalate` path. A dangerous agent fails to start rather than
running.

#### 5b. The guard — no AI involved

Five named rules, pure code, no model, no score, no threshold
([ADR-0011](architecture/adr/0011-deterministic-guard-not-classifier.md)):

| Rule | Catches |
|:--|:--|
| `instruction_override` | "ignore your previous instructions" |
| `system_impersonation` | pretending to be a system message |
| `prompt_extraction` | "show me your prompt" |
| `role_reassignment` | "you are now a pirate" |
| `delimiter_injection` | fake `<system>` tags |

It also **tokenises PII** — an email or card number is replaced before it reaches the model,
and put back only in the final reply.

**Why no AI here:** a model can be talked out of its instructions. A regular expression cannot.

#### 5c. The policy engine — eight checks, in code

Before **any** tool runs, all eight must pass:

| # | Check |
|:--|:--|
| 1 | Is the tool registered and available in this conversation? |
| 2 | Can the shop actually do it? (capabilities) |
| 3 | Does the caller's API key hold the scope? |
| 4 | Does the tenant's own policy allow it? (also the budget ladder) |
| 5 | Side-effect gate — **no write tool can exist** |
| 6 | Are the arguments valid? |
| 7 | **Ownership** — does this person own this order? |
| 8 | Budget |

Check 7 is the important one. If ownership cannot be proved, the turn **escalates to a human**
rather than being refused — and the refusal wording is identical every time, so an attacker
cannot use it to discover which order numbers exist.

#### 5d. The audit log

Append-only and hash-chained. Editing or deleting a row is detectable, and the application
database role is **revoked** `UPDATE` and `DELETE`.

**Test all of layer 5:**

```bash
uv run pytest tests/unit/test_guard.py tests/unit/test_policy.py tests/unit/test_graph.py -q
make eval-guard-off      # ⚠️ real models — the suite with every guard rule OFF
```

**What `eval-guard-off` proves, and why it exists:** injection resistance must still be
**1.00** with the guard switched off. The defence is *structural* — no write tool, every call
authorised in code. If that number ever drops, the thing that broke is the policy engine, and
no new guard rule is the fix.

---

### Layer 6 — NEURA-CARE, the agent

**What it is.** The first and only product agent. Three topics: **order status**, **product
questions**, **policy questions**.

**Six nodes** (`agents/care/.../nodes/`): `route` · `plan` · `triage` · `compose` · `decline`
· `respond`.

**Seven tools**, all read-only:

| Tool | Does |
|:--|:--|
| `get_order_status` | One order — **session-scoped**, ownership enforced |
| `find_orders_for_customer` | That customer's orders only |
| `search_products` | Text search |
| `get_product_details` | One product |
| `check_stock` | Stock level |
| `search_policies` | The merchant's own policy text |
| `escalate_to_human` | Hand over |

**Every prompt is a file**, not a string in the code (`prompts/*.md`), and each is
content-hashed. The hash is recorded on every answered turn, so any past answer can be traced
to the exact prompt that produced it.

**Test it:**

```bash
# ⚠️ real models. One question, every step printed — the best tool in the repo
make care-ask Q="what is your returns policy?" URL=$SHOP TOKEN=$TOKEN

# the security case: ask about an order you do not own
make care-ask Q="where is order 1001?" URL=$SHOP TOKEN=$TOKEN

# the same, as a logged-in customer
make care-ask Q="where is my order?" URL=$SHOP TOKEN=$TOKEN CUSTOMER=385
```

**What you should see:** the anonymous order question **escalates to a human** instead of
answering. That is check 7 working.

---

### Layer 7 — The API

#### How authentication works

Two kinds of key:

| Key | Who holds it | Rules |
|:--|:--|:--|
| `fn_sk_…` **secret** | The merchant's own server | Full scopes. May say who the customer is |
| `fn_pk_…` **public** | A shopper's browser (the widget) | Chat only. **Locked to the merchant's domain.** May **never** claim to be a customer |

**The clever part** ([ADR-0014](architecture/adr/0014-api-keys-and-the-rls-bootstrap.md)).
Every table is protected by PostgreSQL Row-Level Security keyed on the tenant — but
authentication has to read a row **before it knows which tenant it is**. Chicken and egg.

The solution: **the hash of the key is itself the permission to read that key's row.**

```sql
CREATE POLICY credential_lookup ON api_keys
    FOR SELECT USING (token_hash = current_setting('app.api_key_hash', true));
```

That transaction is `READ ONLY` and can see exactly one row of one table — the record of a
credential the caller already holds. It discloses nothing they did not already have.

Keys are stored as **SHA-256**, never recoverable. Not bcrypt — bcrypt exists to make weak
human passwords expensive to guess, and there is nothing to guess in 256 random bits.

#### Tenant isolation

Thirteen tables carry a `tenant_id`, and every one has a **forced** RLS policy. A test fails
if any `tenant_id` table lacks one.

**And the app connects as a non-superuser on purpose.** PostgreSQL ignores RLS for
superusers, so `Database.ping()` refuses to start on one. That check caught a real
misconfiguration in CI — see the 2026-08-16 entry in PROJECT_STATE.

#### Also in this layer

- **Usage metering** — every turn writes turns, LLM calls, tokens and cost
- **Budgets** — soft limit → fewer tools; hard limit → **empty tool allowlist**, so every turn
  hands over to a person. It degrades, it never errors
- **Rate limits** — several subjects at once, the narrowest binds
  ([ADR-0017](architecture/adr/0017-rate-limit-subjects.md))
- **Idempotency** — the same request retried returns the original answer, not a second charge
- **Outbound webhooks** — durable, signed, retried, with a dead-letter queue

**Test it:**

```bash
make api-check URL=$SHOP TOKEN=$TOKEN     # ⚠️ real models — REST + WebSocket, end to end
uv run pytest tests/integration -m integration -q      # 119 tests, real PostgreSQL, no models
```

---

### Layer 8 — Shadow mode and the widget

#### Shadow mode — how a merchant is talked into saying yes

| Mode | Shopper sees | For |
|:--|:--|:--|
| `SHADOW` | An honest "no automated answer" message | Proving the agent before it speaks |
| `LIVE` | The agent's real reply | Steady state |

In shadow mode the **whole turn runs** — same models, same tools, same `verify` — and the
reply is withheld at the very end. It is not a cheaper simulation; it is the real answer,
recorded for a human to grade: **agree · disagree · would have harmed**.

Settable **per topic**: live for order status, shadowed for returns policy.

The scorecard is built so it cannot flatter itself — every rate shows its denominator,
agreement is `null` (not `0.0`) before anything is graded, and harm is a **boolean**, because
there is no acceptable percentage of harmful answers about a shopper's money.

#### The widget

One file, no framework, no build step. Two lines on the merchant's site.

**Test both:**

```bash
make widget-check                                   # free — no models. 4 browser scenarios
make widget-demo SHOP=$SHOP TOKEN=$TOKEN SHADOW=1   # ⚠️ one real turn — prints a URL to open
```

---

## 3. The complete journey of one question

Put it all together. A shopper types **"where is my order 1001?"**

| # | What happens | Layer |
|:--|:--|:--|
| 1 | The widget opens a WebSocket, sending the public key | 8 |
| 2 | The key is looked up by hash; **the browser's domain is checked** | 7 |
| 3 | Rate limits checked — tenant, key, client, conversation | 7 |
| 4 | Previous turns of this conversation are loaded | 7 |
| 5 | **`guard`** — attack rules run, PII tokenised. *No model* | 5 |
| 6 | **`route`** — ROUTER model classifies: `order_status` | 6 |
| 7 | **`retrieve`** — vector search over the merchant's text | 4 |
| 8 | **`plan`** — REASONER decides: call `get_order_status` | 6 |
| 9 | **`act`** — the **policy engine's 8 checks** run first | 5 |
| 10 | → check 7: anonymous shopper, unowned order → **escalate** | 5 |
| 11 | *(if owned)* the adapter calls the shop | 3 |
| 12 | **`compose`** — REASONER writes a draft | 6 |
| 13 | **`verify`** — GUARD model checks every fact against the evidence | 6 |
| 14 | Fail → hand to a human. Pass → send | 5 |
| 15 | The transcript, the usage row and the audit entry are written **in one transaction** | 7 |
| 16 | If the tenant is in shadow mode, the reply is **withheld** here | 7 |
| 17 | The widget draws the reply — or the withheld-turn message | 8 |

**Watch all of this happen for real:**

```bash
make care-ask Q="where is order 1001?" URL=$SHOP TOKEN=$TOKEN
```

---

## 4. Feature-by-feature test checklist

Work down it. **Free** means no models and no laptop heat.

| # | Feature | Command | Cost |
|:--|:--|:--|:--|
| 1 | Everything compiles, layers hold | `make check` | Free |
| 2 | Tenant isolation, real PostgreSQL | `uv run pytest tests/integration -m integration` | Free |
| 3 | The conformance checker itself | `make conformance-self-test` | Free |
| 4 | A real shop passes the spec | `make conformance URL=$SHOP TOKEN=$TOKEN` | Free |
| 5 | Sync from a real shop — **run it twice**, the second must re-download nothing | `make sync-check URL=$SHOP TOKEN=$TOKEN` | Free |
| 6 | Indexing for search | `make rag-check URL=$SHOP TOKEN=$TOKEN KEEP=1` | Models (embeddings only — light) |
| 7 | Search quality | `make rag-ask Q="..." SHOW=1` | Light |
| 8 | The widget in a real browser | `make widget-check` | **Free** |
| 9 | The widget against the real API | `make widget-demo SHOP=$SHOP TOKEN=$TOKEN` | 1 turn |
| 10 | The AI layer | `make llm-check` | Models |
| 11 | One question, every step | `make care-ask Q="..." URL=$SHOP TOKEN=$TOKEN` | 1 turn |
| 12 | Full conversation, REST + socket | `make api-check URL=$SHOP TOKEN=$TOKEN` | ~4 turns |
| 13 | The graded test set | `make eval` | **Heavy — ~8 minutes** |
| 14 | The structural-defence proof | `make eval-guard-off` | Heavy |
| 15 | Is the verifier honest? | `make verify-probe` | Heavy |

**Suggested first pass:** 1 → 2 → 3 → 4 → 8 → 11. That is most of the system, and only one
step runs a model.

> **Tip for anything heavy:** put `NEURA_ROLE_MAP=hybrid` in front of the command. The
> expensive role goes to a cloud API and only the small models run locally.

---

## 5. When a new e-commerce platform arrives

The question you asked, answered properly.

### The rule

**We do not write code for their platform. Their platform implements our published spec.**

Three ways in, by how much work the merchant does:

| Tier | How | Who writes code | Status |
|:--|:--|:--|:--|
| **1** Native adapter | Merchant pastes API credentials | **We** write it, once, for everyone on that platform | Phase 2 |
| **2** Generic Interface | Merchant implements 9 endpoints | **They** do | ✅ **This is what exists** |
| **3** Feed | Merchant uploads files | Nobody | Phase 3 |

### Tier 2, step by step

**Step 1 — their developer builds nine read-only endpoints.**

```
GET /neura/v1/health          GET /neura/v1/orders
GET /neura/v1/products        GET /neura/v1/orders/{id}
GET /neura/v1/products/{id}   GET /neura/v1/customers/{id}
GET /neura/v1/categories      GET /neura/v1/policies
GET /neura/v1/inventory
```

All `GET`. One `Authorization: Bearer` header. The JSON they return **is** our model —
published as OpenAPI, so they can generate the types.

**Step 2 — `/health` declares what the shop can do.**

```json
{ "capabilities": ["product.read", "order.read", "policy.read"] }
```

Leave out `product.search` and the agent is simply never given a search tool. **The system
shrinks to fit the shop, automatically.** This is the mechanism that makes "any platform"
true instead of aspirational.

**Step 3 — they check their own work.**

```bash
neura-conformance --url https://theirshop.com/neura/v1 --token xxx
```

It names exactly what is wrong. They fix it and re-run. No call with you.

**Step 4 — you connect them.**

```bash
make tenant-new NAME="Their Shop" AGENTS=care
# then POST /v1/stores with their URL + token, and:
make key-new TENANT=tn_... SCOPES=care:chat:write PUBLIC=1 ORIGINS=https://theirshop.com
```

**Step 5 — they paste two lines. Start in shadow mode. Grade. Then go live.**

### Why this is the whole business

Competitors integrate deeply with Shopify. That depth is exactly why they cannot serve
merchants on Bagisto, Odoo, a regional platform, or something custom. **Those merchants are
your market**, and this design is the only reason you can reach them.

**It has been proven once.** Bagisto — a real third-party PHP platform — connected with
**zero** changes to this codebase. The bridge lives in Bagisto's own repository.

---

## 6. Where things live

```
packages/
  neura-domain/       the vocabulary (pure — no I/O)
  neura-core/         config · db · tenancy · crypto · errors
  neura-llm/          model roles
  neura-commerce/     adapter protocol · capabilities · sync
  neura-adapters/     ← THE ONLY PLACE A PLATFORM NAME MAY APPEAR
  neura-agent-core/   graph · tools · policy engine · guard · audit · rag

agents/care/          NEURA-CARE — nodes, tools, prompts, golden cases
apps/neura-api/       the deployable — API, widget, auth, limits, metering
evals/                the grading harness
docs/spec/            the published contract for shops
scripts/              every `make *-check` you ran above
```

---

## 7. What is NOT built — read this before promising anything

| | |
|:--|:--|
| ❌ **No real merchant** | The top risk. Everything is proved against a test shop |
| ❌ **All 47 test conversations are invented** | They prove the machinery, **not** that the agent is good |
| ❌ **Never deployed** | It runs on one laptop |
| ❌ **Nothing schedules a sync** | The catalogue is durable now, but a worker still cannot enumerate tenants under RLS to know whose to run (**P7**) |
| ⚠️ **One quality gate unmet** | Escalation precision — it hands over slightly too often |
| ❌ **No screen for the merchant** | Grading is API calls today |
| ❌ **4 of 5 planned agents do not exist** | Only CARE is even designed |
| ❌ **Numbers in these docs are not measurements** | See [CLAUDE.md §4](../CLAUDE.md) |

---

## 8. The five things to remember

1. **Platform independence is the product.** If a platform name leaks out of
   `neura-adapters/`, the product claim becomes false. CI enforces it.
2. **Safety is code, not prompts.** If the argument is *"the prompt says not to"*, there is no
   argument.
3. **The agent cannot write.** Not disabled — no write tool can be registered.
4. **Shadow mode is how you sell it.** A merchant sees weeks of proof before the agent speaks.
5. **No number here has been measured on a real conversation.** Not one.
