# FiveNeurals — Business Blueprint v2

> **Status:** Draft for review · Supersedes [`docs/archive/FiveNeurals_AI_Agents_Blueprint_v1.md`](../archive/FiveNeurals_AI_Agents_Blueprint_v1.md)
> **Last updated:** 2026-07-25

---

## 0. What changed from v1, and why

v1 was a strong vision document. It is kept verbatim in `docs/archive/`. This version keeps the vision and fixes six things that would have caused real damage if carried into the product:

| # | Problem in v1 | Change in v2 |
|:--|:--|:--|
| 1 | ~35 capabilities presented as a product. Each row of those tables (dynamic pricing, multi-touch attribution, KYC biometrics, PCI-DSS compliance, supply-chain prediction) is a company on its own. | Every agent is re-cut into **MVP → v1 → Vision** tiers. Only the MVP tier is committed. |
| 2 | Unsupportable claims: "2% → 5-8% conversion", "catches 95% of fraud", "keeps you compliant with GDPR automatically — no more legal risk". | Replaced with metrics we can actually measure and defend. The GDPR sentence in particular was a legal liability, not a feature. |
| 3 | NEURA-GUARD sold on fraud detection — a market won by cross-merchant network data we will never possess. | GUARD re-scoped to what single-merchant AI genuinely does better than incumbents. |
| 4 | No ICP. The document never says who buys this. | §3 names the buyer, the budget, the current alternative, and the wedge. |
| 5 | Half the capabilities need historical labelled data a new client does not have. | §6 defines the mandatory **cold-start ramp**. |
| 6 | Flat pricing with unbounded LLM usage — a single high-traffic store destroys the margin. | §8 moves to base + metered with hard quotas. |

Three genuinely new strategic angles are added in §4: **agent-readiness**, **AEO/GEO**, and **data sovereignty**.

---

## 1. The Vision (unchanged)

FiveNeurals delivers modular AI agents that a business integrates individually or as an ecosystem. Each agent is useful alone; combined, they share context and compound.

That vision is correct and worth pursuing. What follows is the honest path to it, rather than the pitch for it.

---

## 2. The Strategic Reality

### 2.1 Every square is occupied

| Agent | Incumbents | Our honest angle |
|:--|:--|:--|
| **NEURA-CARE** | Intercom Fin, Gorgias, Zendesk AI, Tidio, Chatdesk | Platform-agnostic (they are Shopify-first), self-hostable, works on custom/in-house stores nobody else supports |
| **NEURA-SELL** | Rebuy, Nosto, Klaviyo, Dynamic Yield | **Agent-readiness** (§4.1) — selling *to* AI shopping agents, which none of them do yet |
| **NEURA-MIND** | Triple Whale, Polar Analytics, Lifetimely | Natural-language analytics over a store that has no analytics vendor because it isn't on Shopify |
| **NEURA-GROW** | Jasper, HubSpot, Klaviyo, Surfer | **AEO/GEO** (§4.2) — being cited by ChatGPT/Perplexity, with measurement. Content generation itself is commoditized to zero. |
| **NEURA-GUARD** | Signifyd, Riskified, Sift, Forter | Not fraud networks. **AI-safety and AI-compliance for the store's own agents** (§5.5) |

> **The uncomfortable truth:** we cannot out-feature any of these. We win, if we win, on **reach** (platforms they ignore), **sovereignty** (deployments they cannot offer), and **timing** (agentic commerce, which is genuinely early).

### 2.2 The ecosystem moat is real, but it is a *later* moat

Cross-agent intelligence is a genuine differentiator — but 5 agents × 0 customers = 0. The ecosystem effect only becomes a moat *after* one agent has customers. **Sequencing is not optional.** Win one agent, on one platform-class, for one buyer, then compound.

---

## 3. Ideal Customer Profile

This was the largest gap in v1. A product without a named buyer cannot be scoped.

### 3.1 Primary ICP (proposed — **requires founder confirmation**, see §11)

> **Mid-market merchants on non-Shopify commerce platforms** — custom/in-house builds, Bagisto, WooCommerce, Magento, Odoo, or regional platforms.

| Attribute | Value |
|:--|:--|
| Revenue | US$0.5M – 10M/yr online |
| Order volume | 500 – 20,000 orders/month |
| Support load | 100 – 2,000 tickets/month, handled by 1–5 people or the owner |
| Current alternative | Nothing, a dumb FAQ bot, or a human answering WhatsApp at 11pm |
| Why incumbents miss them | Gorgias/Fin are Shopify-first; a custom or Bagisto store gets a "contact sales" page and a 6-week integration quote |
| Budget | US$100 – 600/month for something that measurably removes work |
| Buyer | Founder / head of ecommerce / ops lead — **not** a procurement committee |

**Why this ICP:** it is defined by the exact thing our architecture is built around — *platform independence*. Every competitor's strength (deep native Shopify integration) is the reason they cannot serve this segment. That is a real, structural wedge rather than a wishful one.

### 3.2 Secondary ICP — data-sovereign organisations

Regulated or privacy-sensitive organisations (finance, health, government, defence-adjacent) that **cannot** send customer PII to a third-party cloud LLM. Longer sales cycle, far higher contract value, near-zero competition. Enabled by the same self-hostable stack we develop on (§4.3).

### 3.3 Anti-ICP — say no to these

- **US Shopify merchants.** Gorgias/Fin are one click away, cheaper for us to lose than to win.
- **Enterprise (>$50M).** Procurement, SOC 2, DPAs, security questionnaires, 9-month cycles. We have none of that yet.
- **Sub-$100k/yr micro-merchants.** They cannot pay, and support volume is too low for the agent to demonstrate value.

---

## 4. The Three New Bets

These did not exist in v1 and are, in my assessment, more valuable than most of v1's 35 capabilities.

### 4.1 Agent-readiness — making a store sellable to AI agents

**The shift:** customers are beginning to buy *through* AI agents rather than through websites — OpenAI's Agentic Commerce Protocol / Instant Checkout, Google's AP2, Perplexity shopping, and whatever ships next. A store that is not machine-readable and machine-transactable is invisible to that channel.

**What we sell:** structured, agent-consumable product data; an MCP server exposing the catalogue; agent-facing checkout endpoints; and a feed that external shopping agents can actually parse.

**Why it is a good bet:**
- It is **cheap for us** — it is the same canonical domain model and tool layer the CARE agent already needs, re-exposed. Marginal cost, not new construction.
- Gorgias and Intercom are support companies; this is not on their roadmap.
- It is a *new channel* for the merchant, not a cost saving — which is a far easier sale.

**Risk to state plainly:** the standards are young and may consolidate or change. We build against our own canonical model and treat each protocol as an output format, so a protocol dying costs us an adapter, not the architecture.

### 4.2 AEO/GEO — optimising to be cited by AI, not ranked by Google

Being cited in ChatGPT, Perplexity, Claude and Google AI Overviews is becoming an organic acquisition channel. Meanwhile "AI writes your blog posts" — v1's NEURA-GROW pitch — has been commoditized to roughly zero by every writing tool on the market.

**What we sell:** `llms.txt` and structured-data generation, entity/topical coverage analysis, and — the part that actually matters — **measurement**: are we being cited, for which queries, against which competitors, and is it trending.

**Why:** measurement is the defensible half. Anyone can generate content; almost nobody can tell a merchant whether it worked in an AI answer engine.

### 4.3 Data sovereignty — turning a constraint into the moat

We develop on Ollama because we have no LLM budget. That constraint produces an asset: **a stack that provably runs entirely on the customer's own infrastructure.**

"Your customer data never leaves your servers" is something Intercom Fin, Gorgias and Zendesk AI **structurally cannot say**. For the §3.2 secondary ICP it is not a feature, it is the entire buying criterion.

This belongs on the front page — not, as v1 had it, as a Phase-5 "on-premise option for enterprise".

**Honest caveat:** self-hostable models in the 8–30B range are meaningfully weaker than frontier models at multi-step reasoning and at low-resource languages including Sinhala. We will publish measured quality numbers per deployment mode (see [evaluation-strategy.md](../architecture/evaluation-strategy.md)) rather than pretending the tiers are equivalent.

---

## 5. The Five Agents — re-tiered

Format for each: **MVP** = committed and scoped · **v1** = next, conditional on MVP traction · **Vision** = directionally true, not promised.

### 5.1 NEURA-CARE — Customer Experience *(the one we build first)*

| Tier | Scope |
|:--|:--|
| **MVP** | Three intents only — **order status**, **product Q&A**, **returns/shipping policy**. Read-only. Grounded in real store data. Escalates to a human with full context when unsure. Web chat + REST + WebSocket. Shadow mode. |
| **v1** | Multi-channel (email, WhatsApp), conversation memory across sessions, tenant-configurable tone/persona, self-updating knowledge base from resolved tickets, write actions behind an approval queue (address change, order cancel). |
| **Vision** | Voice, proactive churn outreach, sentiment-adaptive tone, 100+ languages. |

**Why these three intents:** across ecommerce support they consistently dominate ticket volume, they are all answerable from data we already sync, and none of them require a write action — so the MVP cannot damage a customer relationship or an order.

**The metric we sell on:** **deflection rate** — the share of conversations resolved without a human, measured honestly (a conversation that escalates or that the customer abandons is *not* deflected). Plus first-response time and human-graded answer quality.

**What we will not claim:** a conversion-rate lift. v1's "2% → 5-8%" is a 2.5–4× improvement; published results for AI customer experience cluster in the 5–20% *relative* range. We will report the pilot's real number, whatever it is.

### 5.2 NEURA-SELL — Revenue Intelligence

| Tier | Scope |
|:--|:--|
| **MVP** | *(not in scope)* |
| **v1** | **Agent-readiness (§4.1)** — MCP server, structured agent-consumable catalogue, agent-facing checkout. Plus rule-based cart recovery and grounded product recommendation. |
| **Vision** | Predictive lead scoring, revenue forecasting, autonomous negotiation. |

**Removed from v1 of this document:** dynamic pricing based on *"individual customer willingness-to-pay"*. Personalised pricing triggers disclosure obligations under the EU Omnibus Directive, sits adjacent to automated-decision rules under GDPR Art. 22, and carries severe reputational risk (Amazon's 2000 experiment is still cited 26 years later). Any future pricing work stays at **segment / inventory / time** granularity, never individual.

### 5.3 NEURA-MIND — Business Intelligence

| Tier | Scope |
|:--|:--|
| **MVP** | *(not in scope)* |
| **v1** | Natural-language questions over the synced canonical data ("how many orders are stuck in processing?"), scheduled digests, threshold-based anomaly alerts. |
| **Vision** | Causal analysis ("*why* did sales drop"), demand forecasting, supply-chain disruption prediction, competitive intelligence. |

**Note:** the v1 pitch — *"it predicted a 15% demand spike two weeks early"* — requires years of the client's history. See §6.

### 5.4 NEURA-GROW — Marketing & Growth

| Tier | Scope |
|:--|:--|
| **MVP** | *(not in scope)* |
| **v1** | **AEO/GEO (§4.2)** — citation measurement, `llms.txt`, structured data, coverage gap analysis. |
| **Vision** | Campaign autopilot across ad platforms, multi-touch attribution, autonomous social management. |

**Deprioritised:** generic content generation. It is commoditized and it is not a reason to buy.

### 5.5 NEURA-GUARD — Security & Trust *(substantially re-scoped)*

v1 positioned GUARD against Signifyd/Riskified/Sift. Those companies win on **cross-merchant network data** — they see a card fail at 400 stores; we see it at one. That is not a gap we can close with better models, and "catches 95% of fraud" is removed entirely.

What single-merchant AI *does* do better, and what GUARD becomes:

| Tier | Scope |
|:--|:--|
| **MVP** | Built into the platform, not sold separately: **prompt-injection defence**, tool-authorisation policy engine, PII redaction, immutable agent action audit log. |
| **v1** | Fake/incentivised review detection, DSAR automation, consent management, AI-transparency compliance artefacts (EU AI Act Art. 50), rule-based order risk flags routed to human review. |
| **Vision** | ML risk scoring on the merchant's own accumulated history; integrations *with* fraud networks rather than competing against them. |

**This is a stronger position, not a weaker one.** Every business deploying AI agents now inherits a brand-new attack surface — prompt injection, tool abuse, data exfiltration through agent context — and almost nobody sells defence for it. That market is empty; the fraud market is full.

**Compliance language, corrected.** v1 said *"keeps you compliant with GDPR automatically — no more legal risk, no more manual audits."* That is a legal-advice claim and would be Exhibit A if a client were ever fined. The product **supports compliance workflows and produces audit evidence. It does not provide legal advice and does not guarantee compliance.** This wording appears in the ToS, the marketing site, and the product UI.

---

## 6. The Cold-Start Problem

Absent from v1, and it invalidates several of its headline capabilities on day one of any deployment.

Lead scoring, revenue forecasting, fraud ML, demand forecasting and churn prediction all require **labelled historical data the new client does not have**. A store that signs up on Monday has no training set.

**The mandatory ramp — every predictive capability ships through all three stages:**

| Stage | What runs | Duration | What we tell the client |
|:--|:--|:--|:--|
| **1. Heuristics** | Explicit, inspectable rules. No ML. | Day 1 | "Rules-based today. Here is exactly what they are." |
| **2. Shadow** | Model runs on live traffic, takes no action, logs what it *would* have done. Humans grade it. | 4–12 weeks | "It is learning your store. Here is its scorecard versus your team." |
| **3. Live** | Model acts, within budget and approval limits, monitored for drift. | After shadow clears threshold | "It is live, and here is the measured accuracy that earned it." |

Shadow mode is simultaneously the **best de-risking mechanism and the best sales instrument we have** — the client watches the agent be right for six weeks before it is allowed to touch anything. It is therefore built in Phase 1, not deferred.

---

## 7. Operating Principles

Non-negotiable product rules. They constrain every roadmap decision that follows.

1. **Human-in-the-loop for anything irreversible.** No refund, cancellation, price change, transaction block, or outbound campaign executes without an approval gate, an audit record, and a rollback path. v1's *"SELL blocks the transaction"* had none of these.
2. **Grounded or silent.** The agent answers from retrieved store data or it escalates. It does not improvise about orders, prices, stock, or policy. An escalation is a success; a confident wrong answer about someone's money is a failure.
3. **Authorisation lives in code, never in a prompt.** A customer can type anything into a chat box. What the agent is *permitted* to do is enforced by the policy engine, outside the model. See [security-model.md](../architecture/security-model.md).
4. **Disclose the AI.** Users are told they are talking to an AI, and how to reach a human. Required by EU AI Act Art. 50 and simply correct regardless.
5. **The customer's data is the customer's.** No training on client data without explicit opt-in. Deletion is honoured end-to-end, including vector stores.
6. **Measure before claiming.** No number goes on the website that the eval suite or a live pilot did not produce.

---

## 8. Pricing

### 8.1 Why v1's pricing was dangerous

Flat US$99–2,499/month with unbounded usage puts **all cost variance on us**. LLM inference cost scales with conversation volume; the price does not. One high-traffic store on the $99 tier can consume more inference than the tier's entire annual revenue. That is not a pricing bug, it is an unbounded liability.

### 8.2 v2 model — base + metered, with hard caps

| Plan | Base | Included resolutions/mo | Overage | Target |
|:--|:--|:--|:--|:--|
| **Pilot** | Free, 60 days | 500 | — hard stop | Design partners |
| **Starter** | $149/mo | 750 | $0.20 each | ICP low end |
| **Growth** | $449/mo | 3,000 | $0.15 each | ICP core |
| **Scale** | $1,200/mo | 10,000 | $0.10 each | ICP high end |
| **Sovereign** | From $2,500/mo + setup | Unlimited (their compute) | — | §3.2 secondary ICP |

**Mechanics that make this safe:**
- Bill on **resolutions**, not messages. A resolution is a conversation the agent closed without escalation — the unit the merchant actually values, and it aligns our incentive with theirs.
- **Hard per-tenant token and cost budgets** with circuit breakers. When a tenant hits its ceiling the agent degrades to escalate-only; it never silently burns margin.
- Cost per resolution is a tracked metric in the eval suite. **Gross margin per tier is monitored from day one**, not discovered later.
- **Sovereign** inverts the economics entirely — the customer supplies the compute, so we sell software and support at near-zero marginal cost. This is why §4.3 matters commercially, not just technically.

### 8.3 Unit economics to validate during the pilot

Blocking questions before public pricing: cost per resolution at each deployment tier; the real deflection rate; escalation rate; and how much support time a merchant actually saves. **We do not publish prices until the pilot has answered all four.**

---

## 9. Legal, Compliance & Risk

| Area | Position |
|:--|:--|
| **EU AI Act Art. 50** | Users must be informed they are interacting with AI. Implemented in the widget and in every channel's first message. |
| **Emotion inference** | v1's "Emotional Intelligence" is regulated in workplace/education contexts and carries transparency duties elsewhere. Deferred out of MVP; when built, it is disclosed and never used for automated adverse decisions. |
| **Automated decisions (GDPR Art. 22)** | No solely-automated decision with legal or similarly significant effect on a person. This is precisely why §7.1 exists. |
| **Personalised pricing** | Not built. See §5.2. |
| **Data processing** | We are a processor. Required: DPA, sub-processor list, retention schedule, deletion propagation into vector stores, and a documented cross-border transfer position. |
| **PII and LLMs** | Redacted before leaving our boundary. Under **Sovereign**, it never leaves the customer's boundary at all. |
| **Compliance claims** | "Supports compliance workflows; does not constitute legal advice." Never "guarantees compliance". |
| **Liability** | ToS must cap liability for agent output, and require the merchant to keep a human escalation path. |

---

## 10. Sequencing

The plan is deliberately narrow. Breadth is what kills solo-built platforms.

| Phase | Goal | Success gate |
|:--|:--|:--|
| **Phase 1** | NEURA-CARE MVP (3 intents) + the platform-agnostic integration layer, proven on a test store | Measured deflection rate on real traffic; a second platform integrates via the published spec without core code changes |
| **Phase 2** | First paying design partner; MCP server; agent-readiness v0 | One merchant paying, and renewing |
| **Phase 3** | Second agent (SELL or MIND, decided by what design partners actually ask for) | Cross-agent shared context demonstrably beats either agent alone |
| **Phase 4+** | Remaining agents, ecosystem effect, sovereign deployments | — |

See [roadmap.md](../roadmap.md) for effort estimates. Note that v1's "Weeks 1-4 / 5-8 / 9-16" schedule is optimistic by roughly 3× for a solo developer, and has been restated honestly.

---

## 11. Open Business Questions

These do not block Phase 1 engineering, but they must be answered before pricing is published or a go-to-market begins.

1. **ICP confirmation.** §3.1 proposes non-Shopify mid-market merchants. Is that the market you can actually reach — through network, geography, or the Bagisto/WooCommerce communities? If your real reach is elsewhere, the ICP changes and §8 changes with it.
2. **Geography.** Sri Lanka / South Asia first, or English-speaking Western markets? This drives pricing (a $449/mo tier is a different proposition in each), language priorities (Sinhala/Tamil), and compliance surface (EU AI Act applies to EU users regardless of where we sit).
3. **Design partner.** Is there a real merchant — not the Bagisto test install — willing to run shadow mode on live traffic? Without one, the deflection number is synthetic and unsellable.
4. **Sinhala/Tamil.** Genuine local differentiator, but self-hostable 8B models handle Sinhala poorly. Needs measurement before it becomes a promise. (Note: Bagisto ships `sin` translations; Tamil `ta` is absent from every package.)
5. **Open source.** Open-sourcing the adapter layer and the Generic Commerce Interface spec would drive adoption of the *standard* while keeping the agent runtime commercial. Strong strategic move, worth deciding early because it affects licensing from the first commit.
6. **Time budget.** Solo, part-time, or full-time? Phase 1 scope should be cut further if this is evenings-and-weekends.

---

## Appendix — Claims removed from v1

Recorded so they do not quietly return to a pitch deck.

| Removed claim | Reason |
|:--|:--|
| "pushing your conversion to 5-8%" (from 2%) | 2.5–4× lift is not credible; unsupportable |
| "NEURA-GUARD would have caught 95% of those" | No network data; unfalsifiable and unsupportable |
| "keeps you compliant with GDPR automatically — no more legal risk" | Legal-advice claim; direct liability |
| "individual customer willingness-to-pay" pricing | EU Omnibus disclosure duties + reputational risk |
| "By 2027, 80% of customer interactions will be handled by AI" | Uncited third-party projection stated as fact |
| "Real-time translation … for 100+ languages" | Not measured; low-resource languages fail badly |
| "AI-powered KYC with biometric matching" | Regulated activity requiring accreditation we do not have |
| "Automatically ensures GDPR, CCPA, PCI-DSS compliance" | PCI-DSS in particular is an audited certification, not a feature |
