# Glossary

Shared vocabulary. Words here mean exactly one thing across code, docs and conversation. Ambiguity in these terms produces bugs.

---

## Platform

| Term | Meaning |
|:--|:--|
| **Tenant** | One customer of ours — a merchant. The unit of isolation, configuration, billing and quota. Every business row carries a `tenant_id`. |
| **Store** | A tenant's commerce platform installation. A tenant has one store in MVP; the model allows more. |
| **Platform** | A commerce product: Shopify, WooCommerce, Bagisto, "custom". Never used to mean *our* platform — say "Neura" for that. |
| **Channel** | How a shopper reaches the agent: `web`, `email`, `whatsapp`. Not to be confused with Bagisto/Shopify "sales channels", which are a store concept. |
| **Customer** | The merchant's shopper. **Never** our customer — that is the tenant. |

## Commerce integration

| Term | Meaning |
|:--|:--|
| **Canonical model** | Our platform-neutral entities (`Product`, `Order`, `Customer`, …) in `neura-domain`. The only vocabulary agents reason in. |
| **Adapter** | Code translating one platform into the canonical model. The **only** place a platform name may appear. |
| **Capability** | A declared ability of an adapter (`order.read`, `cart.write`). Determines which tools exist for a tenant. |
| **Capability negotiation** | Computing the available tool set from the adapter's declared capabilities. Both an integration mechanism and a security control. |
| **Generic Commerce Interface** | Our published ~9-endpoint spec that any store implements. Integration Tier 2, and the MVP path. |
| **Tier 1 / 2 / 3** | Native adapter (we write it) / Generic Interface (they implement it) / feed-push (files). |
| **Conformance** | Whether a store correctly implements the Generic Interface. Verified by `neura-conformance`. |
| **Sync** | Copying store data into our canonical store. Backfill → incremental → event-driven → reconcile. |
| **Entity map** | `(tenant, platform, type, external_id) ↔ neura_id`. |

## Agents

| Term | Meaning |
|:--|:--|
| **Agent** | A named product capability — NEURA-CARE. Not "an LLM call" and not "a graph node". Lives in `agents/<name>/` as its own package. |
| **Manifest** | An agent's identity card (`manifest.py`): key, version, required capabilities, scopes, route prefix. How the system discovers it. |
| **Entitlement** | Which agents a tenant has bought (`tenants.enabled_agents`). Gates routes, scopes, tools, billing and UI. Distinct from *capability*, which is what the store platform can do. |
| **Delivery mode** | Shared cloud · dedicated instance · sovereign. One codebase, three ways to ship it. |
| **Graph** | The LangGraph state machine an agent executes. |
| **Node** | One step in a graph (`guard`, `route`, `retrieve`, `act`, `compose`, `verify`). |
| **Tool** | A function the agent may call, with declared capability requirements, scopes and side-effect class. |
| **Side-effect class** | `READ` / `WRITE` / `IRREVERSIBLE`. Determines the authorisation gate. |
| **Policy engine** | The code that authorises every tool call. **The security boundary.** Never a prompt. |
| **Conversation** | One continuous exchange with one customer. The unit of budget, metering and evaluation. |
| **Turn** | One customer message and the agent's reply. |
| **Escalation** | Handing a conversation to a human with full context. **A successful outcome, not a failure.** |
| **Resolution** | A conversation the agent closed without escalation. The billing unit. |
| **Deflection rate** | Resolutions ÷ total conversations. Escalated and abandoned conversations are *not* deflected. |
| **Shadow mode** | Agent runs on real traffic, sends nothing, logs what it would have said. |
| **Practice mode** | The **merchant-facing name for shadow mode** — the same thing, said the way a shop owner would. Used in the console and in its server-written caveats; the code, the ADRs and `TurnMode.SHADOW` keep *shadow*. Owner-approved 2026-09-27. |
| **Grounded** | Every factual claim in a reply is supported by retrieved context or tool output. |

## LLM

| Term | Meaning |
|:--|:--|
| **Role** | What a call needs: `ROUTER`, `REASONER`, `GUARD`, `EMBEDDER`, `SUMMARIZER`. Application code names roles, never models. |
| **Role map** | Config binding roles → `(provider, model, params)`. `ollama-dev`, `cloud-prod`, `sovereign`. |
| **Provider** | An inference backend reached over an OpenAI-compatible API. |
| **LLM capability** | What a provider supports: `NATIVE_TOOL_CALLING`, `JSON_SCHEMA_MODE`, … Declared, never assumed. |
| **Structured output** | A schema-validated model response. Three fallback tiers by provider capability. |
| **Repair loop** | Bounded retry (max 3) feeding a validation error back to the model. |
| **Embedding namespace** | `(tenant_id, embedding_model)`. Vectors from different models are **not** comparable. Every `VectorStore` method takes one; there is no un-namespaced read or write. |
| **Chunk** | A retrievable unit of text with its embedding and metadata. Identified by `(namespace, source_type, source_id, chunk_index)`. |
| **Rendering** | Turning a canonical entity into the text that gets embedded. Content-hashed, so editing a renderer re-embeds rather than leaving a half-stale index. |
| **Reindex** | Moving to a new embedding model. A migration, not a config edit — [llm-abstraction §5.2](architecture/llm-abstraction.md). Both namespaces coexist until the new one is promoted. |

## Security

| Term | Meaning |
|:--|:--|
| **Prompt injection** | Text crafted to override the agent's instructions. Assumed to succeed; defended structurally. |
| **Indirect injection** | Injection arriving through data — a product description, a review — rather than a chat message. |
| **Untrusted content** | Customer messages *and* merchant catalogue text. Delimited explicitly in context. |
| **Ownership verification** | Proving a session may see a given order. Enforced in code, held server-side, never inferred from conversation text. |
| **Redaction** | Reversibly tokenising PII before it reaches a model. Rehydrated on response. |
| **Envelope encryption** | KEK wraps a per-tenant DEK; the DEK encrypts credentials. Rotation without mass re-encryption. |
| **Audit log** | Append-only, hash-chained record of every LLM call, tool decision, escalation and approval. |
| **RLS** | PostgreSQL Row-Level Security. Primary tenant isolation control. |
| **Held vs observed** | *Held*: data the merchant already has — an email, an order ([ADR-0042](architecture/adr/0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md)). *Observed*: data that exists only because someone watched a shopper — a page view, a basket add ([ADR-0044](architecture/adr/0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)). The line, not *personal* vs *anonymous*: an anonymous session token is still personal data. |
| **Observed event** | One row in `observed_events`: a session token, `product.viewed` or `cart.added`, a product id, a time — and, on a view, whether the product was `in_stock` at that moment ([ADR-0049](architecture/adr/0049-a-product-view-records-whether-it-could-be-bought.md)). Sent by the **shop's server**, only when the shop switched it on. Never a search ([ADR-0048](architecture/adr/0048-observation-phase-1-what-the-build-decided.md)). |
| **Counted link** | A link `go.fiveneurals.com/<code>` (`/go/<code>` on the API) that adds 1 to its own count for the day and opens one product's page with campaign labels ([ADR-0074](architecture/adr/0074-grow-counts-the-clicks-on-the-links-an-owner-posts.md)). A plan's link belongs to one post and one place; an own link has a name. **Not an observed event**: no session, no person, nothing joined; keeping anything more about a tap would be observation and fall under ADR-0044. |
| **Click** (on the Links pages) | One tap on a counted link by a browser that is not a known robot. **Not a person and not a visitor**: one person tapping twice is two clicks. Never a sale. |
| **DPA** | Data-processing agreement between a merchant and us. Recorded as `tenants.dpa_signed_at`; without one, no key can send observed events and none are kept. |
| **Owner's choice** | A product's paired suggestions as the shop owner set them in the console ([ADR-0050](architecture/adr/0050-the-shop-owner-may-choose-a-products-suggestions.md)). Wins over the model and the word path; an empty choice means *show nothing*; no choice means *automatic*. |
| **Retention sweep** | The `retention.sweep` job that deletes what has expired, per tenant, daily while anything is held. Booked by every write that creates something to expire. |

## Evaluation

| Term | Meaning |
|:--|:--|
| **Golden dataset** | Versioned test cases with expected behaviour. Sourced from real conversations. |
| **Eval** | A run of the agent over a golden dataset, scored against metrics. |
| **LLM judge** | A strong model scoring subjective metrics such as groundedness. Always a strong model, never the local reasoner. |
| **Escalation precision** | Of escalations, the share that should have escalated. |
| **Escalation recall** | Of cases needing escalation, the share that did. Gated *higher* than precision — under-escalation harms customers. |
| **Injection resistance** | Share of adversarial cases invoking no unauthorised tool. **Must be 1.00.** |

## Product

| Term | Meaning |
|:--|:--|
| **Sovereign** | Deployment entirely on the customer's infrastructure. No data egress. A product tier, not a dev mode. |
| **Agent-readiness** | Making a store readable and transactable by *external* AI shopping agents. |
| **AEO / GEO** | Answer / Generative Engine Optimisation — being cited by ChatGPT, Perplexity, AI Overviews. Distinct from SEO. |
| **Cold start** | A new tenant has no historical data. Every predictive feature ramps heuristics → shadow → live. |
| **Design partner** | An early merchant who runs the product on real traffic and shapes it in exchange for favourable terms. |
