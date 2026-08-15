# Documentation

Everything needed to understand what this project is, why it is built this way, and how to work on it.

**Reading order for someone new:** [Project State](PROJECT_STATE.md) → [Glossary](glossary.md) → [Business Blueprint v2](business/blueprint-v2.md) → [Architecture Overview](architecture/overview.md) → [Roadmap](roadmap.md).

---

## Start here — current state

| Document | Answers |
|:--|:--|
| [PROJECT_STATE.md](PROJECT_STATE.md) | **Where the project is right now** — what exists, what is decided, what changed. Read before anything else; the rest of `docs/` describes the target, not the position. |
| [open-questions.md](open-questions.md) | Everything not yet decided, consolidated. Nothing here may be silently decided. |
| [agents/](agents/README.md) | Which agents are designed (one) and which are not (four). |
| [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) | **Written for someone outside this repository** — a merchant's developer connecting their shop. Plain language; the [spec](spec/generic-commerce-interface-v1.md) is the precise contract. |

---

## Business

| Document | Answers |
|:--|:--|
| [blueprint-v2.md](business/blueprint-v2.md) | Who buys this, what the five agents actually are once scoped honestly, what was cut from v1 and why, pricing, legal exposure |

## Architecture

| Document | Answers |
|:--|:--|
| [overview.md](architecture/overview.md) | System shape, containers, package map, request lifecycle, how the design is verified |
| [commerce-integration.md](architecture/commerce-integration.md) | How we integrate with any platform — canonical model, adapters, capability negotiation, three tiers, sync engine |
| [tenancy-and-packaging.md](architecture/tenancy-and-packaging.md) | Where agent code lives, and how one customer buys CARE alone from a single deployment |
| [llm-abstraction.md](architecture/llm-abstraction.md) | Model roles, provider capabilities, structured output, the local→cloud swap and its traps |
| [agent-runtime.md](architecture/agent-runtime.md) | Graph, tools, policy engine, memory, escalation, shadow mode |
| [security-model.md](architecture/security-model.md) | Threat model, prompt injection, ownership verification, tenant isolation, PII, secrets |
| [evaluation-strategy.md](architecture/evaluation-strategy.md) | Golden datasets, metrics and gates, adversarial evaluation, model-swap reports |
| [api-design.md](architecture/api-design.md) | Versioning, envelopes, errors, idempotency, endpoints, webhooks, DX |
| [adr/](architecture/adr/) | Ten decisions, each with the consequences we accepted |

## Planning

| Document | Answers |
|:--|:--|
| [roadmap.md](roadmap.md) | Phased plan, honest estimates, exit criteria, risks, what we are deliberately not doing |
| [glossary.md](glossary.md) | Shared vocabulary |

## Archive

| Document | Note |
|:--|:--|
| [FiveNeurals_AI_Agents_Blueprint_v1.md](archive/FiveNeurals_AI_Agents_Blueprint_v1.md) | The original vision document. Superseded, kept verbatim. |
| [implementation_plan_1.md](archive/implementation_plan_1.md) | The first implementation plan. Much of it survives; the deviations are recorded as ADRs. |

---

## The four things worth knowing

If you read nothing else:

1. **The integration layer is the product.** Not the agent. A canonical domain model plus a published spec that any store can implement is what lets us serve merchants the Shopify-first incumbents cannot. — [commerce-integration.md](architecture/commerce-integration.md)
2. **Model choice is configuration.** Code names roles, never models. Local models in development and for sovereign deployments; cloud in production; every swap gated on a measured eval comparison. — [llm-abstraction.md](architecture/llm-abstraction.md)
3. **The model is never a security control.** Assume prompt injection succeeds and design so it achieves nothing. The best defence against tool abuse is not registering the tool. — [security-model.md](architecture/security-model.md)
4. **Scope is the main risk.** The original blueprint described ~35 products. This one describes three intents, read-only, on one agent. — [blueprint-v2.md](business/blueprint-v2.md)
