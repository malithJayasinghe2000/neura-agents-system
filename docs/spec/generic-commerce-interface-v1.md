# Neura Generic Commerce Interface — v1.0

> **Status:** Implemented (milestone 1.6) · **Machine-readable:** [`openapi.json`](openapi.json)
> **Audience:** a developer who maintains a store and wants an AI support agent on it.

Nine read-only `GET` endpoints and one signed webhook. Implement them and your
store works with a Neura agent — whatever it runs on, including software written
for one merchant that nobody else will ever integrate with.

Check your work as you go:

```console
$ uv run neura-conformance --url https://yourshop.example.com/neura/v1 --token $TOKEN
```

It names what is wrong and how to fix it. Nothing else is required of you: no
SDK, no library from us, no call.

---

## 1. What this is, and what it deliberately is not

| | |
|:--|:--|
| **Read-only.** | No writes in v1. The agent cannot change anything in your store — that is a feature, not a limitation ([ADR-0010](../architecture/adr/0010-read-only-mvp-tools.md)). |
| **Stateless.** | No sessions, no OAuth dance. One bearer token in one header. |
| **Yours to implement.** | You expose the data; we never get database access, admin credentials, or a plugin running inside your store. |
| **Partial is fine.** | Implement what you have. `/health` declares your capabilities and the agent's tools are computed from that — a store without policy text simply never gets asked about returns. |

The response bodies **are** our internal model, serialized. There is no
translation layer on our side, which is why this document and our code cannot
drift apart: `openapi.json` is generated from the same types the agent reasons
over.

---

## 2. Authentication

Every endpoint except `/health` requires a bearer token we issue per store:

```http
GET /neura/v1/orders/1001
Authorization: Bearer <token>
```

**Requests without a valid token must return `401`.** These endpoints expose
customer names, emails and order history; an endpoint that answers anonymously
publishes them to anyone who learns the URL. The conformance tool tests this
first and treats a failure as blocking.

`/health` may be served unauthenticated so you can verify a deployment before a
credential exists.

---

## 3. The endpoints

Base path is yours to choose — `/neura/v1` is the convention. Give us the full
base URL and we append these paths.

| | Endpoint | Capability |
|:--|:--|:--|
| 1 | `GET /health` | — |
| 2 | `GET /products?cursor=&limit=&updated_since=&q=&category_ids=&in_stock_only=` | `product.read`, `product.search` |
| 3 | `GET /products/{id}` | `product.read` |
| 4 | `GET /categories` | `category.read` |
| 5 | `GET /inventory?variant_ids=a,b,c` | `inventory.read` |
| 6 | `GET /orders?cursor=&limit=&updated_since=&email=&phone=&customer_id=&order_number=` | `order.read`, `order.search` |
| 7 | `GET /orders/{id}` | `order.read` |
| 8 | `GET /customers/{id}` | `customer.read` |
| 9 | `GET /policies` | `policy.read` |

Full parameter and schema detail is in [`openapi.json`](openapi.json).

### 3.1 `/health` — the most consequential response you send

```json
{
  "status": "ok",
  "spec_version": "1.0",
  "platform": "acme-custom-store",
  "capabilities": ["product.read", "product.search", "order.read",
                   "customer.read", "policy.read", "sync.incremental"]
}
```

This single field decides which tools the agent is given. A tool it is not given
is a tool it cannot call — that is a security property, not a UI preference.

**Declare only what you have implemented.** Under-declaring costs a feature.
Over-declaring produces a tool that fails in front of a customer.

### 3.2 Collections

```json
{ "items": [ ... ], "next_cursor": "eyJhZnRlciI6IjQyIn0" }
```

- `next_cursor` is **opaque to us** — a page number, a keyset, an internal token,
  whatever you like. We hand it straight back as `?cursor=`. `null` means this
  was the last page.
- **Never use offsets.** A catalogue sync is a long crawl over data a merchant is
  editing; `LIMIT/OFFSET` skips and duplicates rows while it runs, and the
  result — a few products missing from search — is close to undiagnosable later.
- The cursor must **advance**. One that repeats makes sync loop forever.
- `/categories`, `/policies` and `/inventory` return a bare JSON array; they are
  small and do not paginate.

### 3.3 Single entities

Return `404` when an id does not exist. **Not** `200` with an empty body: those
are indistinguishable from a real record, and the agent will confidently discuss
an order that never existed.

Ids are **always strings** on the wire, even if they are integers in your
database.

---

## 4. Data rules

**Money is an object, never a float.**

```json
{ "amount": "49.00", "currency": "USD" }
```

`amount` is a decimal *string*. Floats produce wrong order totals that cannot be
reconciled afterwards.

**Timestamps are ISO-8601 with an offset**, e.g. `2026-07-26T10:00:00Z`.

**Statuses use our vocabulary, not yours.** Map your platform's terms:

| Field | Allowed values |
|:--|:--|
| `Order.status` | `pending` · `processing` · `shipped` · `delivered` · `cancelled` · `refunded` · `unknown` |
| `Order.payment_status` | `pending` · `authorized` · `paid` · `partially_refunded` · `refunded` · `failed` · `unknown` |
| `Order.fulfillment_status` | `unfulfilled` · `partial` · `fulfilled` · `returned` · `unknown` |
| `Product.status` | `active` · `draft` · `archived` · `unknown` |
| `Policy.kind` | `returns` · `shipping` · `warranty` · `privacy` · `terms` · `other` |

An unrecognised value is read as `unknown` rather than rejected — one odd status
must not make an order unreadable. But `unknown` is a poor answer to "where is my
order?", so the conformance tool reports it as a warning.

**Unknown fields are ignored.** Send extra fields if it is easier; we drop them
and keep the original payload for debugging. Equally, we may add optional fields
in a later minor version without breaking you.

**If you are writing PHP, cast empty maps to objects.** `json_encode([])`
produces `[]` — a JSON *array* — whether you meant a list or a map, so a
variant with no options serialises as `"options": []` instead of `"options":
{}`. We accept an empty list where a map belongs, because most commerce
platforms are written in PHP and refusing it would fail a majority of correct
implementations over a field nobody set. Sending `(object) []` is still better:
the error, when a *non*-empty list arrives, points at a field you never
consciously set.

**Do not send `neura_id`, `tenant_id`, `platform` or `synced_at`.** Those are
ours; anything you send in them is discarded.

---

## 5. `updated_since`, and why it is optional

If you can filter by modification time, accept `?updated_since=<ISO-8601>` on
`/products` and `/orders` and declare `sync.incremental`. We will then poll for
changes rather than re-crawling everything.

If you cannot, **omit the capability** and we full-sync you instead. That path
works fine.

The one thing that must not happen is declaring `sync.incremental` and ignoring
the parameter: we would then sync only what we already had and silently never
notice the rest. The conformance tool checks for exactly this.

---

## 6. Webhooks (optional — capability `events.realtime`)

Without them, order data is as fresh as the last poll. With them, a status change
reaches the agent immediately. Send a notification, not the data:

```http
POST {your_neura_webhook_url}
Content-Type: application/json
X-Neura-Timestamp: 1785412800
X-Neura-Signature: sha256=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08

{"event": "order.updated", "external_id": "1001", "occurred_at": "2026-07-26T10:00:00Z"}
```

Events: `product.created` · `product.updated` · `product.deleted` ·
`order.created` · `order.updated` · `customer.updated` · `policy.updated`.

**Signing.** HMAC-SHA256 over `<timestamp>.<raw body>`, hex digest, using the
shared secret. Sign the exact bytes you send — re-serialising parsed JSON changes
key order and the signature stops matching, with nothing in either log to explain
why.

The timestamp is part of the signed value and requests more than **five minutes**
old are rejected. Without both properties, one captured request can be replayed
against us indefinitely.

To check your sender, print a known-good request and compare byte for byte:

```console
$ uv run neura-conformance --webhook-example --secret $SECRET
```

Deliver at least once; we are idempotent. Duplicates are safe, silence is not.

---

## 7. Conformance

```console
$ uv run neura-conformance --url https://yourshop.example.com/neura/v1 --token $TOKEN

  ✔ health                       ok
  ✔ auth.required                ok
  ✘ products.search_empty        search_products() raised on an empty query
      → Return an empty page. A search matching nothing is the commonest case.
  ⚠ sync.updated_since           declares sync.incremental but ignores updated_since
      → Either honour the filter or drop the capability — we will full-sync instead.

  18 passed · 1 failed · 1 warning(s)
```

Exit codes: `0` conformant · `1` not conformant · `2` could not connect.
`--json` gives machine-readable output for CI.

Not sure whether the tool itself is working? `--self-test` runs it against a
built-in store that is correct, and then against one that is deliberately broken,
and tells you what it found.

---

## 8. Versioning

`spec_version` is required in `/health` from v1.0.

- **Minor versions are additive.** New optional fields, new capabilities. A v1.0
  store keeps working against a v1.1 client and vice versa — which is why neither
  side rejects unknown fields.
- **Major versions may break.** A client only talks to stores declaring its own
  major version.
- Write support, when it arrives, will be a new capability and new endpoints, not
  a change to any of these.

Deprecation policy is not yet written; it is needed before the first external
adopter, and is tracked in [open-questions.md](../open-questions.md).

---

## 9. A real platform, conformed

The first implementation of this spec is a bridge inside a Bagisto shop —
roughly 700 lines of PHP in a package that modifies no core file of the shop.
It passes conformance with no warnings.

Two things that implementation had to decide, which any implementer will also
face:

- **A status the platform cannot produce.** Bagisto records that an order was
  dispatched and never hears back from the carrier, so nothing it sends can
  honestly map to `delivered`. Its bridge maps a completed order to `shipped`
  and stops there. Reporting `delivered` on no evidence would have the agent
  tell a customer their parcel arrived when nobody knows that.
- **One flag where the spec has two states.** The platform has a single
  enabled/disabled switch; the spec distinguishes `draft` from `archived`. The
  bridge maps disabled to `draft` — the weaker claim, which is the right one to
  make when guessing.

Both are lossy, both are documented in that code, and neither required a change
to this spec. That is the abstraction working: a platform admits what it does
not know, rather than the vocabulary bending to fit it.

## 10. Reference implementation

`packages/neura-adapters/src/neura_adapters/generic/reference.py` is a complete,
conformant store in about 400 lines of Python. It is the shortest answer to "what
exactly should this return?", it is what `--self-test` runs against, and its
responses are generated from the same models as this spec.
