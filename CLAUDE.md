# CLAUDE.md — Read This First

**Entry point for any new session.** You are starting with no memory of previous conversations. Everything you need is in this repository. Nothing you need is in your head.

---

## 1. Read these, in this order

| # | File | Why |
|:--|:--|:--|
| 1 | [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md) | **Where the project actually is right now.** Always read this first — the other docs describe the target, not the position. |
| 2 | [`docs/glossary.md`](docs/glossary.md) | Terms have exactly one meaning here. Using them loosely produces bugs. |
| 3 | [`AGENTS.md`](AGENTS.md) | Four non-negotiable rules + conventions + recipes |
| 4 | [`docs/business/blueprint-v2.md`](docs/business/blueprint-v2.md) | What is being built, for whom, and what is deliberately excluded |
| 5 | [`docs/architecture/overview.md`](docs/architecture/overview.md) | System shape, then follow links as needed |
| 6 | [`docs/open-questions.md`](docs/open-questions.md) | Everything not yet decided — **do not decide these alone** |

---

## 2. The anti-invention rule

This project has a large documented vision and a deliberately small build scope. The failure mode for a fresh session is **filling the gap with plausible invention**.

> **If it is not written in `docs/`, it is not decided. Ask. Do not design it silently.**

Concretely:

| If asked to… | Correct response |
|:--|:--|
| Build NEURA-MIND / GROW / GUARD | **These are not designed.** See [`docs/agents/README.md`](docs/agents/README.md). Say so and propose a design session first. |
| Build NEURA-SELL | **Designed 2026-08-26** — [`docs/agents/sell.md`](docs/agents/sell.md), [ADR-0023](docs/architecture/adr/0023-sell-is-read-only-and-a-protocol-is-an-output-format.md). It may be built, but **only within the scope that design fixes**: read-only, two intents, five tools, and **six surfaces** — four built ([ADR-0040](docs/architecture/adr/0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md), accepted 2026-09-20, built 2026-09-21), and two accepted-and-unbuilt: the recovery list ([ADR-0043](docs/architecture/adr/0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md)) and the sold-out demand list ([ADR-0046](docs/architecture/adr/0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md)), both accepted 2026-09-25. |
| Build SELL's sixth surface — the sold-out demand list | **[ADR-0046](docs/architecture/adr/0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md), accepted 2026-09-25 — and only STAGE 1 is approved.** Stage 1 is view counts of sold-out products, **no identity**, riding on [ADR-0044](docs/architecture/adr/0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)'s events; it is the cheapest thing designed that day. **Stage 2** (a shopper types an email in chat) is blocked until ADR-0042 gains a **volunteered-data** category — it permits *held* and *observed*, and an address a shopper types is neither. **Stage 3** (logged-in customers) is blocked on [A21](docs/open-questions.md)'s identity token, which is an ADR **and** a security review. Do not build 2 or 3 as "while we're here". |
| Build SELL's fifth surface — the recovery list | **Accepted 2026-09-25 and deliberately not scheduled.** [ADR-0043](docs/architecture/adr/0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md) is the whole scope: **checkouts** (not carts) that have a contactable owner and never became an order, shown to the merchant, **exported by the merchant, sent by the merchant**. It is the first feature here that is worthless until it has run for weeks on real traffic, so the sequencing is *decided now, built when a merchant exists* — see the Consequences section. Do not start it because the ADR says Accepted; ask first. |
| Send anything to a shopper — email, SMS, push | **Still excluded**, and ADR-0043 does not touch it. We show a merchant a list; we never message a person. Reopening it is a superseding ADR. |
| Track a shopper — page views, searches, cart actions | **Allowed since [ADR-0044](docs/architecture/adr/0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md), accepted 2026-09-25 — and only on its conditions**, which are the whole decision: **off by default**, per shop; **the shop's server sends the events** and no script of ours runs in a shopper's browser; the switch governs *sending*, so off means the data never exists rather than arriving and being discarded; and scoring is a **points table, not a model**. Nothing is built. It amends [ADR-0042](docs/architecture/adr/0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) §1 — a tenant without the switch is still governed by 0042 unchanged. |
| Use a shopper's behaviour to price, rank or decide | **Still excluded, and ADR-0044 strengthens this rather than loosening it.** No individual pricing ([§148](docs/business/blueprint-v2.md)), no ranking products by behaviour ([ADR-0040 §3](docs/architecture/adr/0040-a-paired-suggestion-is-a-fourth-surface-and-has-no-model-in-it.md)), no automated decision with a legal effect. Observing is permitted; acting on it in those three ways is not. |
| Add a write/refund/cancel tool | Blocked by [ADR-0010](docs/architecture/adr/0010-read-only-mvp-tools.md). Requires the approval queue, which does not exist. |
| Pick a cloud LLM provider | Deliberately undecided ([ADR-0006](docs/architecture/adr/0006-llm-model-roles.md)). Decided by eval results at swap time, not in advance. |
| Add a native Shopify/Woo adapter | Phase 2 ([ADR-0009](docs/architecture/adr/0009-generic-commerce-interface.md)). Tier 2 comes first, on purpose. |
| Quote a conversion or deflection number | **No measured numbers exist yet.** See §4 below. |
| Change an ADR | ADRs are immutable. Write a superseding one. |

Contradicting a documented decision is fine — but do it explicitly, in an ADR, not by quietly writing different code.

---

## 3. The four rules (full version in `AGENTS.md`)

1. **No commerce-platform name outside `packages/neura-adapters/`** — `bagisto`, `shopify`, `woocommerce`, `magento`. CI-enforced. This is the entire market position; if it breaks, the product claim is false.
2. **Dependencies point downward only.** `neura-domain` imports only Pydantic + stdlib.
3. **Authorisation is code, never a prompt.** If your safety argument is "the prompt says not to", you have no safety argument.
4. **Nothing merges without an eval.** Injection resistance must stay at 1.00.

---

## 4. Numbers in these docs are NOT measurements

Nothing has been built or measured. Every figure below is illustrative or a target, and **must not be repeated as fact** — to the user, in marketing, or in code comments:

- All eval scores in [evaluation-strategy.md](docs/architecture/evaluation-strategy.md) §6 and [llm-abstraction.md](docs/architecture/llm-abstraction.md) §8.1 — **illustrative report shapes**, not results.
- All metric thresholds — informed starting points, to be recalibrated after ~100 real conversations.
- All prices in [blueprint-v2.md](docs/business/blueprint-v2.md) §8 — proposals. Explicitly **not to be published** until pilot unit economics exist.
- All effort estimates in [roadmap.md](docs/roadmap.md) — planning inputs. They will be wrong.
- Deflection rate, cost per resolution, model quality deltas — **unknown**. Saying otherwise invents evidence.

---

## 5. Project facts a fresh session usually gets wrong

- **Bagisto is a test harness, not a customer and not a target platform.** It lives at `/Users/malithjayasinghe/Developer/bagisto`. We do **not** write a `BagistoAdapter` — Bagisto conforms to *our* spec via a bridge package. The reasoning is in [commerce-integration.md §5](docs/architecture/commerce-integration.md).
- **Ollama is for development and for the sovereign product tier.** It is not a placeholder to be ripped out. Production uses a cloud API; both paths ship.
- **Python is pinned to 3.12**, though 3.14 is installed on this machine. Deliberate — library wheel availability.
- **The MVP agent is read-only.** It cannot change anything in a store. That is a feature — and **so is agent #2**: SELL's whole designed scope stays inside [ADR-0010](docs/architecture/adr/0010-read-only-mvp-tools.md).
- **SELL is one product with six surfaces, only one of them is an agent, and only four are built.** Recommendation has a graph; the MCP server, the product feed and the two unbuilt merchant-facing lists — recovery ([ADR-0043](docs/architecture/adr/0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md)) and sold-out demand ([ADR-0046](docs/architecture/adr/0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md)) — have no nodes, no prompts and no LLM call of ours in them, and the safety argument on those four is the policy engine and tenant isolation, never "a persuaded model achieves nothing". **The paired suggestion is no longer one of them**: [ADR-0045](docs/architecture/adr/0045-a-pairing-may-be-computed-by-a-model-but-never-while-a-shopper-waits.md), accepted 2026-09-25 and **unbuilt**, lets a model compute a pairing **once, in the background, never while a shopper waits** — so ADR-0040's title is no longer literally true, the model names *kinds* while only the store names products, and **[Rule 4](AGENTS.md) now reaches this surface**. **None of the six ranks by behaviour for a shopper**: "customers also bought" is not a feature we lack but a claim we cannot make, and a shopper is never told how many other people want something either — manufactured urgency is the same class of claim.
- **Two of SELL's six surfaces face the merchant, not a shopper, and that is deliberate.** Both were argued from [ADR-0033](docs/architecture/adr/0033-care-answers-what-the-store-has-sell-helps-the-shopper-choose.md)'s line — *CARE answers what the store has; SELL helps the shopper choose* — on the ground that **their purpose is recovering a sale, not answering a question**. ADR-0046 fires on SELL's own [ADR-0027](docs/architecture/adr/0027-a-constraint-miss-is-not-an-empty-store.md) dead end. **The agent now has an admin side**, and the console is over its documented five-screen limit ([console.md §2](docs/console.md)) by two.
- **We may hold what a merchant already holds, and we may watch a shopper only when their shop switches it on.** Two ADRs, both accepted 2026-09-25, both unbuilt: [ADR-0042](docs/architecture/adr/0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) permits an email, an order, a checkout someone began and left; [ADR-0044](docs/architecture/adr/0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md) amends it so page views and cart actions are permitted **for an opted-in shop only**, sent by **the shop's own server**. **Off is the default and off means the data never exists** — nothing of ours runs in a shopper's browser, and a filter at our end would not be a switch. The old sentence *"we never watch your shoppers"* **is no longer true and must not be repeated**; the accurate one is *"we watch only if your shop turns it on."*
- **Nothing about any of that is implemented.** No personal data is stored, no event has ever been collected, `ORDER` and `CUSTOMER` sync are off, the observe switch does not exist, and the three `RETENTION_*` settings in `.env` are **read by no code at all** — which both ADRs name as the control that must become real before anything is kept.
- **One deployable process**, not microservices ([ADR-0002](docs/architecture/adr/0002-modular-monolith.md)) — the earlier plan said otherwise and was changed.
- **There is no design partner and no real merchant yet.** The top project risk.

---

## 6. Before you finish a session

Update [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md): what changed, what is next, anything newly decided or newly blocked. That file is the handoff to the next session — including your own next session, which will remember none of this.
