# API Design

> **Status:** Draft for review · **Last updated:** 2026-07-25

The API is the product's first impression and, for the [ICP](../business/blueprint-v2.md#3-ideal-customer-profile), the whole integration experience. `implementation_plan_1` got most of this right; it is carried forward here with the gaps filled.

**Target:** a developer goes from API key to first successful response in **under five minutes**, without talking to us.

---

## 1. Principles

1. **Versioned from day one** — `/v1/`. Never break an existing integration.
2. **Predictable** — one response envelope, one error shape, one pagination style, everywhere.
3. **Idempotent writes** — clients retry; agents retry more.
4. **Self-documenting** — OpenAPI 3.1 generated from the same Pydantic models the agent uses. The spec cannot drift from the code because it *is* the code.
5. **Boring** — no cleverness. Every surprise costs a support conversation.

---

## 2. Authentication

```http
Authorization: Bearer fn_sk_live_a1b2c3...
```

| Key | Use | Scope |
|:--|:--|:--|
| `fn_sk_…` | Server-to-server | Full, per assigned scopes |
| `fn_pk_…` | Browser widget | Chat only, origin-locked |

Stored hashed — verifiable, never retrievable. Scoped (`care:chat:write`, `care:conversations:read`, …), expirable, revocable, with `last_used_at`. `fn_pk_` keys are locked to allowlisted origins because they are, by definition, public.

---

## 3. Envelopes

**Success:**

```json
{
  "data": { "...": "..." },
  "meta": {
    "request_id": "req_01J8XYZ",
    "timestamp": "2026-07-25T12:00:00Z"
  }
}
```

**Error** — one shape for every failure:

```json
{
  "error": {
    "code": "ORDER_NOT_FOUND",
    "message": "No order matching that reference and email.",
    "type": "not_found",
    "details": { "field": "order_ref" },
    "request_id": "req_01J8XYZ",
    "docs_url": "https://docs.fiveneurals.com/errors/ORDER_NOT_FOUND"
  }
}
```

`code` is a stable machine-readable string — clients branch on it, so it is part of the contract and never changes. `message` is human-facing and may be reworded. `docs_url` is what turns a 400 into a self-service fix.

`request_id` is the OpenTelemetry trace ID. A customer quoting it lets us retrieve the exact agent run.

| Type | Status |
|:--|:--|
| `invalid_request` | 400 |
| `authentication_error` | 401 |
| `permission_error` | 403 |
| `not_found` | 404 |
| `conflict` | 409 |
| `rate_limit_error` | 429 |
| `api_error` | 500 |
| `service_unavailable` | 503 |

---

## 4. Idempotency

Every write endpoint accepts:

```http
Idempotency-Key: idk_01J8XYZ...
```

Key + endpoint + request-body hash are stored for 24h. A replay returns the original response with `Idempotency-Replayed: true`. The same key with a *different* body is a `409` — that is a client bug, and surfacing it beats silently doing the wrong thing.

This is not optional polish: retries are routine, and an AI agent calling this API will retry more aggressively than a human-written client.

---

## 5. Pagination

Cursor-based, always. Offsets skip and duplicate rows under concurrent writes.

```http
GET /v1/care/conversations?limit=50&cursor=eyJpZCI6...
```

```json
{
  "data": [ ... ],
  "meta": {
    "next_cursor": "eyJpZCI6...",
    "has_more": true
  }
}
```

Cursors are opaque, signed, and never parsed by clients.

---

## 6. Rate Limits

Returned on every response, so a client can back off before being blocked:

```http
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 583
X-RateLimit-Reset: 1774440000
Retry-After: 12          # on 429 only
```

---

## 7. Endpoints (MVP)

### Chat

```http
POST /v1/care/chat
Idempotency-Key: idk_...

{
  "conversation_id": "cnv_01J8...",     // omit to start a new one
  "message": "where is my order 1001?",
  "customer": { "email": "jane@example.com" },
  "channel": "web",
  "locale": "en"
}
```

```json
{
  "data": {
    "conversation_id": "cnv_01J8...",
    "message_id": "msg_01J8...",
    "reply": "Your order #1001 shipped on 22 July, tracking TRK123456.",
    "state": "resolved",
    "escalated": false,
    "confidence": 0.91,
    "citations": [ { "type": "order", "id": "1001" } ],
    "ai_disclosure": "You are chatting with an AI assistant."
  },
  "meta": { "request_id": "req_...", "timestamp": "..." }
}
```

`state` ∈ `resolved` · `awaiting_customer` · `escalated` · `blocked`.
`citations` make grounding visible to the integrator — and to us, when a merchant disputes an answer.
`ai_disclosure` is always present ([EU AI Act Art. 50](../business/blueprint-v2.md#9-legal-compliance--risk)); the widget renders it, and any custom client is contractually required to.

### Conversations

```http
GET    /v1/care/conversations?cursor=&state=
GET    /v1/care/conversations/{id}
POST   /v1/care/conversations/{id}/escalate
POST   /v1/care/conversations/{id}/feedback
```

`feedback` is how a merchant marks an answer wrong. It is the highest-value signal we receive — it becomes a golden case ([evaluation-strategy.md](evaluation-strategy.md)).

### Knowledge base

```http
POST   /v1/care/knowledge-base/documents
GET    /v1/care/knowledge-base/documents?cursor=
DELETE /v1/care/knowledge-base/documents/{id}
POST   /v1/care/knowledge-base/reindex
```

For content not in the commerce platform: FAQs, policy PDFs, shipping tables. Catalogue and policies arrive via sync, not upload.

### Store connection

```http
POST   /v1/stores                      // register a store + credentials
GET    /v1/stores/{id}                 // includes negotiated capabilities
POST   /v1/stores/{id}/sync            // trigger a sync
GET    /v1/stores/{id}/sync/status
GET    /v1/stores/{id}/health
```

`GET /v1/stores/{id}` returning the **negotiated capability list** is important for integrator sanity — it is where a developer sees, concretely, which agent abilities their platform does and does not support.

### Webhooks and health

```http
POST   /v1/webhooks                    // register endpoint + events
GET    /v1/webhooks
DELETE /v1/webhooks/{id}
POST   /v1/webhooks/{id}/test

GET    /v1/health                      // liveness
GET    /v1/health/ready                // dependency readiness
```

---

## 8. WebSocket

```
wss://api.fiveneurals.com/v1/care/stream?token=fn_pk_...
```

Client → server: `{ "type": "message", "conversation_id": "...", "content": "..." }`

Server → client: `token` (streaming delta) · `tool_call` (a UI affordance — "checking your order…") · `done` (final state, citations) · `error`.

Same auth, same tenancy, same policy engine as REST. One agent runtime behind both transports — the transport is never allowed to become a second code path.

> **Open item:** streaming interacts awkwardly with the `verify` node, which runs *after* composition. Tracked in [agent-runtime.md §9.1](agent-runtime.md).

---

## 9. Outbound Webhooks

Events we push to the merchant: `conversation.started` · `conversation.resolved` · `conversation.escalated` · `agent.action.pending_approval` · `store.sync.failed` · `budget.threshold.reached`.

```http
POST {merchant_url}
X-Neura-Signature: sha256=...
X-Neura-Timestamp: 1774440000
X-Neura-Event-Id: evt_01J8...
```

Signed HMAC over the raw body, 5-minute timestamp tolerance, at-least-once delivery (`event_id` for dedupe), exponential-backoff retry ×6, then a dead-letter queue visible to the merchant. Details in [security-model.md §8](security-model.md).

---

## 10. Developer Experience

The five-minute target is a design constraint, not an aspiration.

- **Interactive docs** at `/docs`, generated from the OpenAPI 3.1 spec.
- **`llms.txt`** — the API described for AI coding assistants, since that is increasingly how integrations get written.
- **Auto-generated SDKs** from the OpenAPI spec rather than hand-written ones, so they cannot drift. Phase 2.
- **A published Postman/Bruno collection.**
- **A sandbox tenant** with seeded data — a developer must be able to try the API before connecting a real store.
- **Copy-pasteable errors.** Every `docs_url` resolves to a page explaining the cause and the fix.

---

## 11. Versioning Policy

`/v1` is stable. **Additive changes only**: new optional fields, new endpoints, new enum values (clients must tolerate unknown values — stated in the docs).

Breaking changes require `/v2`, with `/v1` supported for **12 months minimum**, deprecation headers, and a written migration guide. A public changelog is maintained from the first external user.

---

## 12. Open Questions

1. **Chat rate limiting granularity.** Per API key is too coarse for a widget where every shopper shares one public key — needs a per-session dimension.
2. **Conversation ID ownership.** Client-supplied or server-issued? Server-issued is safer (unguessable); client-supplied is easier to correlate with the merchant's own systems. Leaning server-issued with an optional `external_ref`.
3. **Bulk endpoints.** Merchants will eventually want bulk conversation export. Not MVP.
4. **GraphQL.** Regularly requested, rarely needed. Not planned; revisit only if an integrator is genuinely blocked.
