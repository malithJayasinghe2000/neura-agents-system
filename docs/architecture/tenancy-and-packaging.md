# Tenancy & Packaging — How Agents Are Delivered Individually

> **Status:** Draft for review · **Last updated:** 2026-07-25

The product sells **modular agents**: a customer buys NEURA-CARE alone, or CARE + SELL, or all five ([blueprint-v2 §8](../business/blueprint-v2.md#8-pricing)). The system is a **single deployable** ([ADR-0002](adr/0002-modular-monolith.md)).

Those two facts are not in tension, and this document explains why — because assuming they are is the most likely way for someone to wrongly conclude that we need microservices.

---

## 1. Two dials that are not connected

```
   HOW WE DEPLOY               ≠          WHAT A CUSTOMER GETS
   (our operations concern)               (a per-tenant setting)
```

Modularity of the **product** comes from the entitlement layer, not from the deployment topology. A microservices split would need this exact same entitlement layer anyway — so splitting the deployment buys product modularity *not at all*.

**One system. Per-tenant entitlements. Three delivery modes.**

---

## 2. Repository layout

Three top-level categories, each with one meaning:

```
neura-agents/
│
├── packages/        LIBRARIES — shared machinery, no product identity
│   ├── neura-core/
│   ├── neura-domain/
│   ├── neura-llm/
│   ├── neura-commerce/
│   ├── neura-agent-core/       the engine every agent runs on
│   └── neura-adapters/
│
├── agents/          PRODUCTS — one folder per sellable agent
│   ├── care/                   ✅ Phase 1
│   ├── sell/                   ⬜ not designed
│   ├── mind/                   ⬜ not designed
│   ├── grow/                   ⬜ not designed
│   └── guard/                  ⬜ not designed  (see docs/agents/README.md)
│
├── apps/            DEPLOYABLES — what actually runs
│   └── neura-api/
│
└── evals/           the eval runner (datasets live with each agent)
```

`agents/` is deliberately a top-level category rather than buried under `packages/`. Opening the repository should make the product shape obvious: *five agents, one built.*

### 2.1 Inside an agent

Every agent has the same five parts. Uniformity is the point — agent #3 should be navigable by anyone who has read agent #1.

```
agents/care/
├── pyproject.toml                  own dependencies + own version
└── src/neura_agent_care/
    ├── manifest.py             ①  identity card
    ├── graph.py                ②  the flow
    ├── nodes/                  ③  steps unique to this agent
    ├── tools/                  ④  what it can do
    ├── prompts/                ⑤  what it says — files, never inline
    └── evals/datasets/             its golden test cases
```

Golden datasets live **with the agent**, not in a central pile. The root `evals/` directory holds the runner and shared metric code; `make eval` discovers datasets from installed agents.

### 2.2 The manifest

The agent's declaration of itself. This one file is what makes everything downstream work.

```python
MANIFEST = AgentManifest(
    key="care",
    name="NEURA-CARE",
    version="0.1.0",
    requires_capabilities=[ORDER_READ, PRODUCT_SEARCH, POLICY_READ],
    optional_capabilities=[INVENTORY_READ],
    scopes=["care:chat:write", "care:conversations:read"],
    route_prefix="/v1/care",
)
```

`requires_capabilities` also gives a useful pre-flight check: a store whose adapter cannot satisfy them is told **at connection time** that this agent will not work for it — rather than the merchant discovering it through a failing conversation.

### 2.3 Shared vs. agent-owned

This split is what stops the same code being written five times.

| `packages/neura-agent-core` — built once | `agents/<name>/` — per agent |
|:--|:--|
| Graph engine + checkpointing | Its specific graph |
| `guard` node (injection + PII) | Its specialised nodes |
| `retrieve` node (RAG) | Its tools |
| `verify` node (groundedness) | Its prompts |
| `escalate` node | Its golden datasets |
| Tool registry + policy engine | Its manifest |
| Memory tiers, budgets, audit log | |

Building agent #2 means writing five things, not a system.

### 2.4 Two rules

**Agents never import each other.**

```
✅  agents/sell/  →  packages/neura-agent-core/
❌  agents/sell/  →  agents/care/            CI-enforced
```

Cross-agent communication goes through the event bus (Phase 3), never a direct import. This is the difference between five products sharing a codebase and one tangle that cannot be sold in pieces.

**`neura-agent-core` never learns an agent's name.** The engine must not know CARE exists — same rule, and same reason, as `neura-commerce` never knowing Shopify exists.

### 2.5 Discovery

Agents register through Python entry points — the standard plugin mechanism:

```toml
# agents/care/pyproject.toml
[project.entry-points."neura.agents"]
care = "neura_agent_care:MANIFEST"
```

At startup `neura-api` scans installed agents, reads their manifests, and mounts their routes. **There is no central list to edit**, so adding an agent never touches a shared registry file.

---

## 3. Entitlements — how one customer gets only CARE

Each tenant record carries the agents they have bought:

```
Acme Store        enabled_agents: ["care"]                   Starter
Bright Fashion    enabled_agents: ["care", "sell"]           Growth
MegaShop          enabled_agents: ["care", "sell", "mind"]   Scale
```

That field drives everything:

| Layer | For a CARE-only tenant |
|:--|:--|
| **Routes** | `/v1/care/*` serves. `/v1/sell/*` → `403 AGENT_NOT_ENABLED` |
| **API key scopes** | Key carries `care:*` only. No `sell:` scope exists on it. |
| **Tool registry** | Only CARE's tools load for their conversations |
| **Widget** | `FiveNeurals.init({ agents: ['care'] })` renders CARE only |
| **Events** | SELL's events have no subscriber for this tenant |
| **Metering** | Usage rows tagged per agent; billed for CARE only |
| **Dashboard** | Shows CARE. SELL is absent, not shown locked. |

From the tenant's side **SELL does not exist**. They cannot call it, see it, or be billed for it. Its code sits dormant in the process — no CPU, negligible memory.

### 3.1 The filter stack

Entitlement is one filter among three. All of them run before the model sees anything:

```
   All tools registered in the system
              ↓
   ①  Which agents did this tenant buy?        →  care
              ↓
   ②  What can their store platform do?        →  no ORDER_WRITE
              ↓
   ③  What scopes does their API key hold?     →  read-only
              ↓
   The tool schemas the LLM is actually shown
```

Filters ② and ③ are described in [commerce-integration §3.2](commerce-integration.md) and [security-model §9](security-model.md). ① is the entitlement layer. The result is computed per conversation, never hand-configured per customer.

### 3.2 Upgrading

```sql
UPDATE tenants SET enabled_agents = '["care","sell"]' WHERE id = 'tn_acme';
```

No deploy, no install, no migration, no downtime. The customer refreshes and SELL is there.

Under a microservices split the same upgrade would mean deploying a service, wiring routing, provisioning credentials — **and still needing this table.**

---

## 4. Three delivery modes, one codebase

| Mode | For | Mechanism |
|:--|:--|:--|
| **Shared cloud** | Most tenants | One deployment, entitlement flags, RLS isolation ([ADR-0008](adr/0008-multi-tenancy-rls.md)) |
| **Dedicated instance** | Customers wanting infrastructure isolation | Same image, own instance + own database |
| **Sovereign / on-prem** | Regulated industries ([blueprint §4.3](../business/blueprint-v2.md#43-data-sovereignty--turning-a-constraint-into-the-moat)) | Same image on the customer's hardware, local Ollama, no data egress |

Never a second codebase. The differences are configuration and, for sovereign, **which agent packages are installed at all** — a customer buying only CARE gets a build where `agents/sell` is not present rather than merely disabled.

---

## 5. The honest trade-off

On the shared cloud, a CARE-only tenant's requests run in a process that also carries other agents' code. If a future agent proves resource-hungry in a way that starves CARE, they should be split.

That is precisely the trigger [ADR-0002](adr/0002-modular-monolith.md) names for revisiting the monolith. Because `agents/*` are already separate packages that cannot import each other, extracting one is **a change to entrypoints and configuration, not a rewrite**.

---

## 6. Open Questions

1. **Entitlement granularity.** Per agent, or finer — per intent within an agent? Shadow mode is already per-tenant *and* per-intent ([agent-runtime §6](agent-runtime.md)), which hints that finer granularity may be wanted for billing too.
2. **Trial handling.** Is a trial an entitlement with an expiry, or a separate plan field? Affects the tenant schema and should be settled before billing exists.
3. **Sovereign licensing.** How is "you bought CARE only" enforced when the customer controls the machine? Probably a signed licence checked at startup — but it is a soft control, and that should be acknowledged rather than pretended otherwise.
