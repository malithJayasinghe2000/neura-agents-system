# Commerce Integration Architecture

> **Status:** Draft for review · **Last updated:** 2026-07-25
> **This is the most important architecture document in the repository.**

Platform independence is the product ([blueprint-v2 §3.1](../business/blueprint-v2.md)). Every incumbent's strength is deep native Shopify integration; that is precisely why they cannot serve merchants on custom, Bagisto, Odoo or regional platforms. This document defines the layer that lets us serve all of them without the core knowing any of them exist.

---

## 1. The Core Idea

```
┌──────────────────────────────────────────────────────────┐
│  Agents · tools · RAG · API                              │
│  Speak ONLY the canonical domain model.                  │
│  Contain ZERO platform-specific code.                    │
└───────────────────────────┬──────────────────────────────┘
                            │  CommerceAdapter protocol
                            │  + Capability set
┌───────────────────────────┴──────────────────────────────┐
│  Adapters — the only place a platform name may appear    │
│                                                          │
│   GenericAdapter    ShopifyAdapter    FeedAdapter        │
│   (Tier 2, MVP)     (Tier 1, later)   (Tier 3, later)    │
└───────────────────────────┬──────────────────────────────┘
                            │
              any commerce platform, ever
```

Two mechanisms carry the whole design:

1. **A canonical domain model** — one vocabulary the platform reasons in.
2. **Capability negotiation** — adapters *declare* what their platform can do, and the agent's toolset is computed from that declaration. A store that cannot cancel orders simply never sees a `cancel_order` tool.

Capability negotiation is what makes this work in reality rather than on a whiteboard. Without it, "support any platform" collapses the moment one platform lacks a feature the agent assumes.

---

## 2. Canonical Domain Model

Lives in `packages/neura-domain`. **Pure Pydantic — no I/O, no database, no HTTP.** Purity is what lets every other layer be replaced.

### 2.1 Entities

| Entity | Purpose | MVP |
|:--|:--|:--:|
| `Product` | Sellable item, with variants | ✅ |
| `ProductVariant` | SKU-level price/stock/options | ✅ |
| `Category` | Taxonomy node, hierarchical | ✅ |
| `InventoryLevel` | Stock per variant per location | ✅ |
| `Customer` | Identity + contact | ✅ |
| `Order` | Placed order, status, totals | ✅ |
| `OrderLine` | Line item | ✅ |
| `Fulfillment` | Shipment, carrier, tracking | ✅ |
| `Policy` | Returns / shipping / warranty text | ✅ |
| `Cart` | Active basket | Phase 2 |
| `Return` | RMA | Phase 2 |
| `Money` | `amount` (Decimal) + `currency` | ✅ |
| `Address` | Postal address | ✅ |

### 2.2 Design rules

**Every entity carries provenance.**

```python
class CanonicalEntity(BaseModel):
    neura_id: str  # ours — stable, ULID
    tenant_id: str
    external_id: str  # the platform's ID, as a string, always
    platform: str  # "generic" | "shopify" | ...
    synced_at: datetime
    raw: dict | None = None  # original payload, for debugging + late-binding fields
```

The `raw` field is deliberate. No canonical model survives contact with every platform; keeping the source payload means an unmapped field is a lookup rather than a re-sync.

**Money is never a float.** `Decimal` + ISO-4217 currency. Floats in commerce produce wrong totals and are unfixable after the fact.

**External IDs are always strings.** Some platforms use integers, some UUIDs, some prefixed slugs. Normalising to `str` at the boundary removes a whole class of bug.

**Status is a canonical enum, never a passthrough.** Platforms disagree wildly on order status vocabulary. The adapter maps into `OrderStatus`, and an unmappable value maps to `UNKNOWN` and raises a warning — it never leaks a platform string into the agent's reasoning.

```python
class OrderStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    UNKNOWN = "unknown"
```

**Timestamps are UTC, timezone-aware, always.**

### 2.3 Identity mapping

```sql
CREATE TABLE entity_map (
    tenant_id     TEXT NOT NULL,
    platform      TEXT NOT NULL,
    entity_type   TEXT NOT NULL,     -- 'product' | 'order' | ...
    external_id   TEXT NOT NULL,
    neura_id      TEXT NOT NULL,
    PRIMARY KEY (tenant_id, platform, entity_type, external_id)
);
CREATE INDEX ON entity_map (tenant_id, neura_id);
```

Bidirectional and tenant-scoped. Two tenants may legitimately have an order `1001` each; the composite key makes collision impossible.

---

## 3. The Adapter Contract

`packages/neura-commerce/protocol.py`. A `typing.Protocol`, not an ABC — adapters are structurally typed, so a third party can implement one without importing our base class.

```python
class CommerceAdapter(Protocol):
    platform: ClassVar[str]
    capabilities: ClassVar[frozenset[Capability]]

    # ---- read ------------------------------------------------------
    async def health(self) -> HealthStatus: ...
    async def get_product(self, external_id: str) -> Product | None: ...
    async def search_products(self, q: ProductQuery) -> Page[Product]: ...
    async def list_products(self, cursor: Cursor | None) -> Page[Product]: ...
    async def get_order(self, external_id: str) -> Order | None: ...
    async def list_orders(self, cursor: Cursor | None) -> Page[Order]: ...
    async def find_orders_for_customer(self, ref: CustomerRef) -> list[Order]: ...
    async def get_customer(self, external_id: str) -> Customer | None: ...
    async def get_inventory(self, variant_ids: list[str]) -> list[InventoryLevel]: ...
    async def get_policies(self) -> list[Policy]: ...

    # ---- write (Phase 2 — behind the approval queue) ---------------
    async def cancel_order(self, external_id: str, reason: str) -> Order: ...
    async def update_address(self, order_id: str, addr: Address) -> Order: ...
```

Only the read surface is required for MVP. Write methods are optional and gated by capability *and* by the approval queue ([agent-runtime.md](agent-runtime.md)).

### 3.1 Capabilities

```python
class Capability(StrEnum):
    PRODUCT_READ = "product.read"
    PRODUCT_SEARCH = "product.search"
    CATEGORY_READ = "category.read"
    INVENTORY_READ = "inventory.read"
    ORDER_READ = "order.read"
    ORDER_SEARCH = "order.search"
    ORDER_WRITE = "order.write"
    CUSTOMER_READ = "customer.read"
    POLICY_READ = "policy.read"
    CART_READ = "cart.read"
    CART_WRITE = "cart.write"
    REALTIME_EVENTS = "events.realtime"  # push webhooks
    INCREMENTAL_SYNC = "sync.incremental"  # supports updated_since
```

### 3.2 How capabilities reach the agent

This is the mechanism that makes graceful degradation automatic rather than a per-integration special case.

```python
@tool(
    name="get_order_status",
    requires=[Capability.ORDER_READ],
    side_effect=SideEffect.READ,
)
async def get_order_status(order_ref: str, ctx: ToolContext) -> OrderStatusResult: ...
```

At conversation start:

```
tenant → adapter → adapter.capabilities
                        │
                        ▼
       tools where tool.requires ⊆ capabilities
                        │
                        ▼
       filtered further by tenant policy + agent mode
                        │
                        ▼
       the tool schemas the LLM is actually shown
```

A model can only call a tool it has been shown. A store without `ORDER_WRITE` makes cancellation **structurally impossible**, not merely discouraged by a prompt. That property is worth more than any amount of prompt engineering.

When a capability is missing, the system prompt receives an explicit statement of the limitation ("you cannot cancel orders for this store; escalate instead") so the model escalates rather than apologising vaguely.

### 3.3 Errors

Adapters translate platform failures into one hierarchy, so retry and escalation logic is written once:

```
AdapterError
├── AdapterUnavailable      → retry with backoff
├── AdapterTimeout          → retry, then degrade
├── AdapterAuthError        → do not retry; alert the merchant
├── AdapterRateLimited      → honour Retry-After
├── EntityNotFound          → normal outcome, not an error path
└── AdapterMappingError     → data we could not canonicalise; log + surface in health
```

---

## 4. The Three Integration Tiers

How a real store connects. Ordered by merchant effort, ascending.

| Tier | Name | Merchant effort | Who builds the code | Phase |
|:--|:--|:--|:--|:--|
| **1** | Native adapter | Paste API credentials | **We** write the adapter | Phase 2+ |
| **2** | Generic Commerce Interface | Implement ~9 endpoints | **They** write the endpoints | **MVP** |
| **3** | Feed / push | Upload or push files | Neither — config only | Phase 3 |

### 4.1 Tier 1 — Native adapter

For platforms with a large installed base and a good API: Shopify, WooCommerce, Magento, BigCommerce. We absorb the integration cost once and amortise it over every merchant on that platform. The merchant does nothing but authorise.

Not in the MVP, because writing three native adapters before the abstraction has been proven once is how abstractions end up wrong.

### 4.2 Tier 2 — The Generic Commerce Interface *(the MVP path)*

> **Built (milestone 1.6).** The specification is published at
> [docs/spec/generic-commerce-interface-v1.md](../spec/generic-commerce-interface-v1.md)
> with a generated [OpenAPI 3.1 document](../spec/openapi.json). `GenericAdapter`
> and the `neura-conformance` CLI live in `packages/neura-adapters/generic/`.
> Where this section and the spec differ, **the spec is current** — it is
> generated from the code.

**A published specification any store can implement.** This is the answer to *"and newly created systems too"* — a developer building a store today implements nine endpoints and is integrated, with no adapter written by us and no waiting for us.

**The contract:**

```
GET  /neura/v1/health
GET  /neura/v1/products?cursor=&updated_since=&limit=
GET  /neura/v1/products/{id}
GET  /neura/v1/categories
GET  /neura/v1/inventory?variant_ids=
GET  /neura/v1/orders?cursor=&updated_since=&limit=
GET  /neura/v1/orders/{id}
GET  /neura/v1/customers/{id}
GET  /neura/v1/policies
```

Plus outbound webhooks to us for real-time updates:

```
POST {neura_webhook_url}
X-Neura-Signature: sha256=<hmac>
X-Neura-Timestamp: <unix>
{ "event": "order.updated", "external_id": "1001", "occurred_at": "..." }
```

**Design rules that keep it implementable by one developer in a day:**

- **Read-only for MVP.** Nine GET endpoints. No writes, no auth flows, no state.
- **Bearer token auth**, issued by us per tenant. One header.
- **Cursor pagination**, opaque cursor. No offset — offsets break under concurrent writes.
- **`updated_since` is optional.** A store that cannot filter by timestamp simply omits `INCREMENTAL_SYNC` from its declared capabilities and we full-sync it. The contract degrades instead of failing.
- **The response *is* the canonical model**, serialized. No translation layer on our side — `GenericAdapter` validates and passes through. That makes the spec self-documenting: the OpenAPI schema is generated from the same Pydantic models the agent reasons over.
- **Capabilities are self-declared** by `/health`:

```json
{
  "status": "ok",
  "spec_version": "1.0",
  "platform": "acme-custom-store",
  "capabilities": ["product.read", "product.search", "order.read",
                   "customer.read", "policy.read", "sync.incremental"]
}
```

**The conformance CLI** — the part that makes this genuinely easy to adopt:

```console
$ uv run neura-conformance --url https://store.example.com/neura/v1 --token $TOKEN

Neura Commerce Interface — Conformance v1.0

  ✔ health                    declares 6 capabilities
  ✔ products.list             cursor pagination correct across 3 pages
  ✔ products.get              schema valid
  ✘ products.search           500 on empty query   → must return an empty page
  ✔ orders.list               cursor pagination correct
  ✔ orders.get                schema valid
  ⚠ orders.updated_since      claims sync.incremental but ignores the parameter
  ✔ customers.get             schema valid
  ✔ policies                  3 policies found
  ✔ webhook signature         HMAC verified

  8 passed · 1 failed · 1 warning
  Not yet conformant. See https://docs.fiveneurals.com/spec/errors#search-empty-query
```

A developer runs this, fixes what it says, and is integrated. No support ticket, no call with us. That is the difference between a spec and an adoptable spec.

> **Strategic note:** publishing this spec openly (see [blueprint-v2 §11.5](../business/blueprint-v2.md)) would let the *standard* spread while the agent runtime stays commercial.

### 4.3 Tier 3 — Feed / push

For legacy systems with no API surface at all: the store pushes JSON/CSV product and order feeds to a signed upload endpoint, or we pull from a URL on a schedule. Capabilities are limited (no real-time, no live order lookup — orders are as fresh as the last feed) and the agent's tool set contracts accordingly, automatically, via §3.2.

---

## 5. Bagisto — the reference implementation

Bagisto at `/Users/malithjayasinghe/Developer/bagisto` is a **test harness, not a target platform**. Its role is to prove the abstraction is real.

**We deliberately do *not* write a `BagistoAdapter`.** Instead we write a thin Laravel package inside Bagisto that makes Bagisto **conform to Tier 2**. The platform then reaches it through the same `GenericAdapter` any custom store uses.

This is the right call for three reasons: it dogfoods our own spec, so spec defects surface immediately; it proves a real third-party platform can be onboarded without core changes; and it keeps the core free of Bagisto-shaped assumptions.

**Findings from surveying the Bagisto 2.4 codebase**, which the bridge must work around:

| Finding | Consequence |
|:--|:--|
| No REST API for orders or customers. The `bagisto/rest-api` package is not installed. | The bridge must expose them itself, via `Webkul\Sales\Repositories\OrderRepository` and `CustomerRepository` |
| The storefront `/api/*` routes use the `web` middleware — session + CSRF, not tokens | Unusable for server-to-server. The bridge adds its own token-guarded routes |
| No GraphQL | Not an option |
| Sanctum is installed, both models use `HasApiTokens`, but **no route uses `auth:sanctum`** and `config/sanctum.php` has `'guard' => []` | Bearer auth is straightforward to add; the plumbing is already there |
| ~250 string-dispatched events, including `checkout.order.save.after`, `sales.order.update-status.after`, `checkout.cart.add.after`, `customer.registration.after`, `catalog.product.update.after` | This is the real-time trigger surface → outbound webhooks. `Event::listen('name', ...)` in the bridge's `EventServiceProvider` |
| No outbound webhook system exists | The bridge builds it: listener → queued job → signed POST |
| **`QUEUE_CONNECTION=sync`** | Must move to Redis first, or every webhook send blocks the shopper's checkout request |
| `product_flat` — denormalized per locale + channel | Ideal read source for catalogue sync; avoids the EAV join maze |
| Documented extension mechanism is event listeners + a new package under `packages/Webkul/*`, with dual registration in `bootstrap/providers.php` and `config/concord.php` | The bridge is a clean package; **zero core files modified** |
| 22 locales including `sin` (Sinhala); `ta` (Tamil) absent | Relevant to [blueprint-v2 §11.4](../business/blueprint-v2.md) |
| Ships `laravel/ai` v0.2.2 with an `ollama` provider already wired, and `agent_conversations` tables migrated | Interesting, but **not used** — inference stays in our Python runtime, not in the store |

**Bridge deliverable:** `packages/Webkul/NeuraBridge/` inside the Bagisto install — token-guarded Tier-2 endpoints, event listeners → signed webhooks, an admin config page for the API key, and the widget snippet. It lives in the Bagisto repo, not this one.

---

## 6. The Sync Engine

`packages/neura-commerce/sync/`. Runs in `neura-worker`.

### 6.1 Why we sync at all rather than always calling live

| Concern | Live call | Local sync |
|:--|:--|:--|
| Latency in a chat turn | 200–2000ms per lookup | ~5ms |
| Store under load | We add load to their production | Read once, serve many |
| Semantic search over the catalogue | Impossible | Required for RAG |
| Store offline | Agent is dead | Agent degrades gracefully |

**The rule: catalogue and policy are synced; order and customer lookups are live-through-cache.** Product data changes slowly and needs embedding. Order status changes fast and must never be stale when a shopper asks where their parcel is — a wrong answer there is worse than a slow one.

### 6.2 Pipeline

```
    ┌──────────────┐
    │  Backfill    │  full paginated crawl · resumable via cursor
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │ Incremental  │  updated_since polling (if INCREMENTAL_SYNC)
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │  Event-driven│  webhook → targeted refresh of one entity
    └──────┬───────┘
           ▼
    ┌──────────────┐
    │ Reconcile    │  nightly count + checksum vs source; repair drift
    └──────────────┘
```

**Properties, each for a specific failure we expect:**

- **Idempotent** — every write is an upsert on `(tenant_id, platform, entity_type, external_id)`. Webhooks *will* be delivered twice.
- **Resumable** — cursor checkpointed per tenant per entity type. A worker restart mid-backfill does not start over.
- **Rate-limited per tenant** — a token bucket honouring `Retry-After`. We must never take down a merchant's production store with our own sync.
- **Reconciling** — event-driven sync silently drifts (a dropped webhook is invisible). A nightly comparison is the only way to notice.
- **Observable** — per-tenant sync health surfaced to the merchant: last successful sync, entity counts, mapping errors.

### 6.3 Catalogue indexing for RAG

```
Product ──► render to text ──► chunk ──► embed ──► pgvector
                                                      │
                              namespace: (tenant_id, embedding_model)
```

The namespace is not optional. Different embedding models produce different vector dimensions and are **not comparable**; mixing them silently degrades retrieval rather than erroring. Since dev uses `nomic-embed-text` (768-dim) and production uses a cloud embedder (1536/3072-dim), this trap is on our direct path. Full detail and the reindex procedure are in [llm-abstraction.md](llm-abstraction.md).

---

## 7. Adding a New Platform

The measure of whether this architecture works.

**Tier 2 (a store implements the spec) — zero code from us:**
1. Merchant implements the nine endpoints.
2. Runs `neura-conformance` until green.
3. Registers the store in the dashboard; capabilities auto-negotiate.

**Tier 1 (we write a native adapter) — one file, no core changes:**
1. `packages/neura-adapters/<platform>/adapter.py` implementing `CommerceAdapter`.
2. Declare `capabilities`.
3. Map platform payloads → canonical models, including status enums.
4. Register in the adapter registry entry point.
5. Run the shared adapter conformance test suite — the same one every adapter must pass.

No change to `neura-domain`, `neura-agent-core`, any tool, or the API. If a new platform ever *does* require a core change, that is a defect in this design and should be treated as one.

---

## 8. Open Questions

1. **Order lookup identity.** A shopper in an anonymous chat asks about order 1001. Verifying they own it — order number + email, a magic link, or session identity — is a real security decision, not a detail. Tracked in [security-model.md](security-model.md).
2. **Multi-currency and multi-channel.** Bagisto and Shopify both support several channels/currencies per store. MVP assumes one channel; the canonical model reserves the fields.
3. **Historical order depth.** Backfilling five years of orders for a large store is expensive and mostly useless. Proposed default: 24 months, tenant-configurable.
4. **Spec versioning.** `spec_version` is in `/health` from v1.0. Deprecation policy for v1.1+ needs writing before anyone external adopts it.
