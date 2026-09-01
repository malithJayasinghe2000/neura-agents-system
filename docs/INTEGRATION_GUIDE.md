# Integration Guide

**For the developer of an online shop that wants to connect it to NEURA.**

This is the plain-language version. The precise contract is
[the Generic Commerce Interface spec](spec/generic-commerce-interface-v1.md), and where the
two disagree, **the spec is right** — it is generated from the code.

---

## 1. What you are actually connecting

Two separate things, and it helps to keep them apart:

```
   ┌──────────────────┐                            ┌──────────────────┐
   │   YOUR SHOP      │  ①  we READ your shop      │      NEURA       │
   │                  │ ◄──────────────────────────┤                  │
   │  products        │     9 read-only endpoints  │   the AI agent   │
   │  orders          │     you build              │                  │
   │  policies        │                            │                  │
   │                  │                            │                  │
   │  your website ───┼──  ②  the chat widget  ────┤   widget.js      │
   └──────────────────┘     2 lines of HTML        └──────────────────┘
```

**① is a developer's job** — roughly one day. **② is copy-and-paste.**

You do ① first. The widget has nothing to say until the AI can read your shop.

---

## 2. Why it works this way

Most AI support products write custom code for Shopify, then WooCommerce, then Magento. If
your platform is not on their list, you wait — possibly forever.

**We do the opposite: we publish a specification, and your shop implements it.** So any shop
can connect, including one you built yourself last year, without us writing a line of code for
it and without you waiting for us.

The price of that is the one day of work in §3. The benefit is that you are never in a queue.

---

## 3. What you build: nine read-only endpoints

Mount them under any prefix you like. `/neura/v1` is the convention.

| Endpoint | Returns |
|:--|:--|
| `GET /health` | What your shop can do — see §4 |
| `GET /products?cursor=&updated_since=&limit=` | A page of products |
| `GET /products/{id}` | One product |
| `GET /categories` | Your category tree |
| `GET /inventory?variant_ids=` | Stock levels |
| `GET /orders?cursor=&updated_since=&limit=` | A page of orders |
| `GET /orders/{id}` | One order |
| `GET /customers/{id}` | One customer |
| `GET /policies` | Returns, shipping and warranty text |

Four things to notice, because each one removes work you might be expecting:

- **Everything is `GET`.** There is no endpoint that changes anything in your shop. The agent
  is read-only by design, not by configuration — it has no write tool to call
  ([ADR-0010](architecture/adr/0010-read-only-mvp-tools.md)).
- **Authentication is one header.** `Authorization: Bearer <token>`, with a token we issue you.
  No OAuth, no signing, no key exchange.
- **There is no format to learn.** The JSON you return *is* our internal model, published as
  [OpenAPI 3.1](spec/openapi.json). Point your code generator at it.
- **Pagination is by cursor, not page number.** Return an opaque `next_cursor`; we send it back
  unchanged. Page numbers silently skip records when a shop is being written to at the same
  time, which is exactly when a catalogue sync runs.

---

## 4. `/health` is the most important thing you write

It is not a ping. It is where your shop declares **what it can do**, and your answer decides
which tools the AI is given.

```json
{
  "status": "ok",
  "spec_version": "1.0",
  "platform": "acme-custom-store",
  "capabilities": ["product.read", "product.search", "order.read",
                   "customer.read", "policy.read", "sync.incremental"]
}
```

The full list you may declare:

| Capability | Means |
|:--|:--|
| `product.read` | Products can be listed and fetched |
| `product.search` | Products can be searched by text |
| `category.read` | Categories can be listed |
| `inventory.read` | Stock levels are available |
| `order.read` | Orders can be listed and fetched |
| `order.search` | Orders can be searched |
| `customer.read` | Customers can be fetched by id |
| `policy.read` | Policy text is available |
| `sync.incremental` | `updated_since` really filters — see §6 |
| `events.realtime` | You will send webhooks — see §7 |

**If you leave something out, nothing breaks.** Omit `product.search` and the agent is simply
never given a product-search tool; it will say it cannot search rather than failing. The system
shrinks to fit your shop, automatically.

> **Be honest here.** Declaring a capability you have not implemented produces a tool that
> fails at runtime, in front of a customer. Under-declaring costs you a feature; over-declaring
> costs you a broken conversation.

---

## 5. Check your work with one command

You do not have to guess whether you got it right, and you do not need to talk to us.

```console
$ neura-conformance --url https://yourshop.com/neura/v1 --token $TOKEN

Neura Commerce Interface — Conformance v1.0

  ✔ health                    declares 6 capabilities
  ✔ products.list             cursor pagination correct across 3 pages
  ✔ products.get              schema valid
  ✘ products.search           500 on empty query   → must return an empty page
  ✔ orders.list               cursor pagination correct
  ⚠ orders.updated_since      claims sync.incremental but ignores the parameter
  ✔ customers.get             schema valid
  ✔ policies                  3 policies found

  8 passed · 1 failed · 1 warning
  Not yet conformant.
```

Fix what it names, run it again. When it is clean, you are integrated.

A `⚠` is worth as much attention as a `✘`: it means you *claimed* something in `/health` that
your endpoints do not actually do, and that is the failure mode that shows up later as a
confusing bug rather than immediately as an error.

---

## 6. `updated_since` — optional, and say so either way

If your shop can filter by "changed since this timestamp", accept `updated_since` and declare
`sync.incremental`. We will then ask only for what changed, which is much cheaper for both of
us.

If it cannot, **just leave the capability out.** We will fetch everything on a schedule
instead. That is slower and completely fine. What is *not* fine is declaring it and ignoring
the parameter — we would then believe we had the latest data while quietly reading a stale
catalogue.

---

## 7. Webhooks (optional)

If you can tell us when something changes, declare `events.realtime` and `POST` to the URL we
give you:

```http
POST {neura_webhook_url}
X-Neura-Signature: sha256=<hmac of the raw body, with your shared secret>
X-Neura-Timestamp: <unix seconds>

{ "event": "order.updated", "external_id": "1001", "occurred_at": "..." }
```

**Send the identifier, not the data.** We fetch the entity ourselves. That way a replayed or
forged webhook cannot inject anything into a merchant's data — the worst it can do is make us
re-read a record we are allowed to read anyway.

Sign the **raw body bytes**, before any parsing. Re-serialising JSON changes whitespace and key
order, and the signature will not match.

---

## 8. Then: the widget

Once §5 is clean and the merchant's account is connected, the site gets two lines:

```html
<!-- NEURA chat -->
<script src="https://api.example.com/v1/widget/widget.js" async
        data-neura-key="fn_pk_live_..."></script>
```

That is the whole front-end integration. A chat bubble appears in the bottom-right corner.

**Things worth knowing:**

- **The key is public and that is fine.** It is locked to the merchant's own domain. Copied onto
  another site, it is refused before the agent runs
  ([ADR-0014](architecture/adr/0014-api-keys-and-the-rls-bootstrap.md)).
- **It cannot claim to be a customer.** A browser saying "I am customer 385" is refused. If you
  want the agent to know who is logged in, that must come from *your server* using a secret
  key, never from the page.
- **It brings no dependencies.** One file, no framework, no build step. It draws itself inside a
  Shadow root, so your CSS cannot break it and it cannot leak into your page
  ([ADR-0019](architecture/adr/0019-widget-no-build-step.md)).
- **It needs no `unsafe-inline` in your CSP.** Allow our origin in `script-src` and
  `connect-src` and you are done.

Optional attributes:

| Attribute | Default | What it does |
|:--|:--|:--|
| `data-neura-key` | *required* | The public key |
| `data-neura-api` | the origin serving the script | Point at a different API host |
| `data-neura-agent` | *(none — the server chooses)* | Pin the widget to **one** agent. Leave it out and every message is routed to whichever of the merchant's enabled agents declares that it answers that kind of question ([ADR-0031]) — which is what a shop running two agents wants, because a shopper does not know which of your services owns their question. Set it only to pin a page to one service. |
| `data-neura-title` | `Chat with us` | The panel heading |
| `data-neura-open` | `false` | Start with the panel open |

---

## 9. Going live is a process, not a switch

This is the part most worth understanding, because it is how the product is meant to be
adopted.

| Stage | What the shopper sees | What it is for |
|:--|:--|:--|
| **Shadow** | A polite "no automated answer is available" message | The agent answers every real question in the background, and nobody sends those answers. A human reads them and grades them: *agree · disagree · would have harmed*. |
| **Live** | The agent's actual reply | Only after the grades are good enough |

**The widget is on the site during the shadow stage.** That is why a shadowed turn still shows
the shopper an honest message rather than an empty box
([ADR-0020](architecture/adr/0020-a-withheld-turn-says-so.md)) — and why the wording is
configurable per merchant, and why it never promises that a person will follow up.

Shadow mode can also be set **per topic**: live for order status, shadowed for returns policy.
A merchant can hand over exactly as much rope as they are comfortable with.

---

## 10. What is not built yet

Stated plainly, so nobody plans around something that does not exist:

| | Status |
|:--|:--|
| "Just paste your Shopify API key" — no endpoints to write | **Phase 2.** Today every platform implements §3 |
| Upload a CSV instead of building endpoints | **Phase 3** |
| A web page for the merchant to grade shadow answers in | **Phase 2.** Today grading is API calls |
| Merchant self-service signup | Not built — account setup is an operator command |
| A sync you can ask for | ✅ `POST /v1/stores/{id}/sync` queues one and returns `202`; `GET /v1/stores/{id}/sync/{job_id}` reports on it |
| A sync that runs on a **timer** | ⚠️ **Not built.** A worker runs whatever is queued ([ADR-0022](architecture/adr/0022-scheduling-under-rls.md)); nothing yet enqueues one on a schedule, so a merchant or an operator has to ask |
| Anything that changes your shop | Deliberately never, in this phase ([ADR-0010](architecture/adr/0010-read-only-mvp-tools.md)) |

---

## 11. A real example

Bagisto — a third-party PHP platform nobody here works on — is connected exactly this way. The
bridge lives in **Bagisto's own repository**, not ours, and connecting it required **zero**
changes to our core.

That is the whole claim this architecture makes, and it has been demonstrated once. Your shop
is the second.

---

## 12. Where to go next

| You want | Read |
|:--|:--|
| The exact contract | [spec/generic-commerce-interface-v1.md](spec/generic-commerce-interface-v1.md) |
| Machine-readable schemas | [spec/openapi.json](spec/openapi.json) |
| Why it is built this way | [architecture/commerce-integration.md](architecture/commerce-integration.md) |
| What the agent actually does with the data | [architecture/agent-runtime.md](architecture/agent-runtime.md) |
| What is true today, honestly | [PROJECT_STATE.md](PROJECT_STATE.md) |
