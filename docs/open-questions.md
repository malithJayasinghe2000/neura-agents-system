# Open Questions Register

Every unresolved question from across the documentation, consolidated. Scattered across eight documents they are easy to miss; a future session that misses them will **invent answers instead of asking**.

> **Rule: nothing on this list may be silently decided.** Resolving one means writing the answer into the owning document — and an ADR if it is expensive to reverse — then striking it from here with the date.

**Legend:** 🔴 blocks work · 🟠 needed soon · 🟡 decide when reached

---

## Business

| # | Question | Impact | Source |
|:--|:--|:--|:--|
| B1 🔴 | **Is the proposed ICP reachable?** §3.1 proposes non-Shopify mid-market merchants. Is that a market accessible via network, geography, or the Bagisto/WooCommerce communities? If not, the ICP changes and pricing changes with it. | Everything | [blueprint §11.1](business/blueprint-v2.md) |
| B2 🔴 | **Is there a real design partner?** A merchant willing to run shadow mode on live traffic. Without one, the deflection number is synthetic and unsellable. **Top project risk.** | Phase 2 gate | [blueprint §11.3](business/blueprint-v2.md) |
| B3 🟠 | **Geography** — Sri Lanka / South Asia, or Western English-speaking? Drives pricing tiers, language priorities, compliance surface. | Pricing, GTM | [blueprint §11.2](business/blueprint-v2.md) |
| B4 🟠 | **Time budget** — full-time, part-time, or evenings? Phase 1 scope should be cut further if the last. | Roadmap realism | [blueprint §11.6](business/blueprint-v2.md) |
| B5 🟡 | **Open-source the adapter layer and spec?** Would spread the standard while keeping the runtime commercial. Affects licensing from the first commit, so decide before code. | Licensing | [blueprint §11.5](business/blueprint-v2.md) |
| B6 🟡 | **Sinhala/Tamil** — genuine local differentiator, but local 8B models handle Sinhala poorly. Measure before promising. | Product claims | [blueprint §11.4](business/blueprint-v2.md) |
| B7 🟡 | **Unit economics** — cost per resolution, real deflection rate, escalation rate, support hours saved. **Do not publish prices until all four are known.** | Pricing | [blueprint §8.3](business/blueprint-v2.md) |

## Commerce integration

| # | Question | Impact | Source |
|:--|:--|:--|:--|
| C1 🟠 | **Order-lookup identity.** How does an anonymous shopper prove they own order 1001? Order number + email is the security floor but adds friction to every query; magic links are stronger and slower. | Security + UX | [commerce §8.1](architecture/commerce-integration.md), [security §12.1](architecture/security-model.md) |
| C2 🟡 | **Multi-currency / multi-channel.** MVP assumes one channel; the canonical model reserves the fields. | Domain model | [commerce §8.2](architecture/commerce-integration.md) |
| C3 🟡 | **Historical order depth.** Proposed default 24 months, tenant-configurable. | Sync cost | [commerce §8.3](architecture/commerce-integration.md) |
| C4 🟠 | **Spec versioning and deprecation policy** — needed before the first *external* adopter, not after. | Public contract | [commerce §8.4](architecture/commerce-integration.md) |

## LLM

| # | Question | Impact | Source |
|:--|:--|:--|:--|
| L1 🟡 | **Cloud provider choice** — deliberately deferred. Decided by eval results, latency and price at swap time. **Do not pre-decide this.** | Production | [llm §10.1](architecture/llm-abstraction.md) |
| L2 🟡 | **Reasoning models** — does `deepseek-r1:14b` help the guard/verify nodes enough to justify its latency? | Quality | [llm §10.2](architecture/llm-abstraction.md) |
| L3 🟡 | **Fine-tuning a router** — only once real conversation data exists, and only with opt-in. | Cost | [llm §10.3](architecture/llm-abstraction.md) |
| L4 🟡 | **Sovereign hardware floor** — minimum spec for acceptable quality. Blocks selling the tier. | Product tier | [llm §10.4](architecture/llm-abstraction.md) |

## Agent runtime

| # | Question | Impact | Source |
|:--|:--|:--|:--|
| A1 🟠 | **Streaming vs. `verify`.** `verify` runs after `compose`, so a streamed answer could need retracting mid-sentence. Stream after verify (slower first token), or stream with a fast pre-check? **Decide before the widget ships.** | UX | [runtime §9.1](architecture/agent-runtime.md) |
| A2 🟡 | **Multi-turn ownership persistence.** How long does verified order ownership last? Proposed: session lifetime, re-verified per new order reference. | Security | [runtime §9.2](architecture/agent-runtime.md) |
| A3 🟡 | **`act` tool-call cap of 4** — a guess, not a measurement. Tune from eval data. | Quality/cost | [runtime §9.3](architecture/agent-runtime.md) |
| A4 🟠 | **Shadow-mode review capacity.** Grading is human time. How much is realistically available, and what sampling rate does that imply? | Phase 1 design | [runtime §9.4](architecture/agent-runtime.md) |

## Security

| # | Question | Impact | Source |
|:--|:--|:--|:--|
| S1 🟠 | **Injection classifier threshold.** A local 3B guard will have false positives (blocking real customers) and false negatives. Needs a labelled adversarial set and a tuned threshold before go-live. | Security + UX | [security §12.2](architecture/security-model.md) |
| S2 🟠 | **KEK custody.** Env var is acceptable for a pilot; **cloud KMS is required before the first real merchant.** | Security | [security §12.3](architecture/security-model.md) |
| S3 🟡 | **Sovereign hardening** — which controls become the customer's, and what must the deployment guide mandate? | Product tier | [security §12.4](architecture/security-model.md) |

## Evaluation

| # | Question | Impact | Source |
|:--|:--|:--|:--|
| E1 🔴 | **Seeding golden datasets without a design partner.** Real tickets need a real merchant. Interim: synthesize from the Bagisto store, marked `synthetic: true` — **and never counted as validation.** | Eval validity | [eval §8.1](architecture/evaluation-strategy.md) |
| E2 🟠 | **Judge tier vs. real customer data.** Currently a Gemini free tier, which is correct while every case is invented. Free tiers may train on submitted content, so the judge **must move to a paid tier before real conversations enter the datasets**. Also: free-tier rate limits keep full runs nightly rather than per-commit. | Compliance + budget | [eval §3.1](architecture/evaluation-strategy.md) |
| E3 🟡 | **Threshold calibration** — the gates are informed guesses. Recalibrate after ~100 real conversations. | Quality gates | [eval §8.3](architecture/evaluation-strategy.md) |
| E4 🟡 | **Multilingual evaluation** — grading Sinhala needs a Sinhala-capable judge or a human. Blocks any multilingual claim. | Product claims | [eval §8.4](architecture/evaluation-strategy.md) |

## API

| # | Question | Impact | Source |
|:--|:--|:--|:--|
| P1 🟠 | **Chat rate-limit granularity.** Per-API-key is too coarse for a widget where every shopper shares one public key. Needs a per-session dimension. | Abuse | [api §12.1](architecture/api-design.md) |
| P2 🟡 | **Conversation ID ownership** — server-issued (unguessable) vs client-supplied (easier correlation). Leaning server-issued with an optional `external_ref`. | API contract | [api §12.2](architecture/api-design.md) |
| P3 🟡 | Bulk conversation export. Not MVP. | Feature | [api §12.3](architecture/api-design.md) |
| P4 🟡 | GraphQL. Not planned; revisit only if an integrator is genuinely blocked. | Feature | [api §12.4](architecture/api-design.md) |

## Project

| # | Question | Impact | Source |
|:--|:--|:--|:--|
| X1 🟠 | **Initialise git?** Not a repository yet. Should happen before the first line of code. | Everything | — |
| X2 🟠 | **Deployment target.** Railway was the earlier plan but has no GPU path. Production inference is a cloud API, so the API/worker host is a separate open choice. | Phase 1.17 | [roadmap](roadmap.md) |
| X3 🟡 | **Which agent is second?** SELL (agent-readiness) or MIND (analytics). **To be decided by what a design partner asks for, not by us.** | Phase 3 | [agents/](agents/README.md) |

---

## Resolved

*(Move entries here with the date and the ADR that settled them. Nothing yet.)*
