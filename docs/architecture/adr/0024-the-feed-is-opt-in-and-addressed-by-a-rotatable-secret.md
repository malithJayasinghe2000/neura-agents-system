# ADR-0024 — The Product Feed Is Opt-In, And Addressed By A Rotatable Secret

**Status:** Accepted · **Date:** 2026-08-26 · **Resolves:** open question **S7** · **Builds on:** [ADR-0014](0014-api-keys-and-the-rls-bootstrap.md), [ADR-0021](0021-synced-entities-are-documents.md), [ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md)

## Context

[ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) put a machine-readable product feed in SELL's scope and deliberately left one thing undecided, as **S7**: how it is exposed.

**The constraint that makes this awkward is not negotiable.** A feed exists to be read by external crawlers and answer engines. Those clients cannot present a bearer token — nobody will provision one, and a feed nothing can fetch is a feature with no consumer. So this endpoint sits **outside** the authentication model in [api-design.md §2](../api-design.md), which until now has been "every request carries a key, and the key names the tenant".

Three things are therefore not obviously fine, and each needs answering separately:

1. **Consent.** "Connect your store" does not obviously mean "publish a machine-readable copy of it". A merchant who did not ask for publication must not get it.
2. **Enumerability.** If the URL is derivable from a merchant's name or tenant id, then reading *one* store's feed teaches you how to read *every* store's.
3. **Irreversibility.** Once a crawler has fetched and cached a document, taking it down does not un-publish it. This is the property that makes the decision expensive to reverse, and therefore an ADR rather than a note.

The data itself is the merchant's own storefront — public by nature. That argues the stakes are low. It is also the argument that would let this be decided carelessly, so it is recorded and then set aside: **the sensitivity of the content is not the question. The question is whether publication was chosen, and whether choosing it once means choosing it forever.**

## Decision

### 1. Off by default. Publication is an act, not a side effect

A connected store publishes nothing. A feed exists only after the merchant switches it on, and switching it on shows them the document they are about to publish first.

This is the same instinct as `fn_pk_` keys refusing to work with an empty origin allowlist ([ADR-0019](0019-widget-no-build-step.md) §3): where a default would grant exposure the operator did not ask for, the default grants nothing.

### 2. The address is a secret, not a name

```
GET /v1/sell/feed/{feed_token}/products.jsonld
GET /v1/sell/feed/{feed_token}/products.json
```

`feed_token` is high-entropy and unguessable. It is **not** the tenant id, not a slug, and not derived from anything a merchant publishes elsewhere.

**Stored hashed, exactly as an API key is** ([ADR-0014](0014-api-keys-and-the-rls-bootstrap.md)) — SHA-256, with a displayable prefix so a merchant can tell two feeds apart, and `hmac.compare_digest` on lookup. The plaintext is shown once, at creation. **This means we cannot show a merchant their own feed URL twice**, and that is the correct trade: a URL we can reproduce on demand is a URL an attacker who reaches our database can reproduce too.

The lookup is the [ADR-0014](0014-api-keys-and-the-rls-bootstrap.md) bootstrap, unchanged in shape: the tenant is not known until the token is resolved, so the read happens on `Database.credential_session` and **everything after it is an ordinary scoped session**. No new exemption, no second mechanism — the one that already exists, reused, because the problem is the same problem.

### 3. A separate table, not a new kind of API key

`sell_feeds` is its own tenant table under forced RLS, rather than a `FEED` variant of `ApiKeyKind`.

Reusing `api_keys` was genuinely tempting — hashing, revocation, `last_used_at` and the prefix display are all already there. It is rejected because **a secret in a URL path is not a bearer token and must never be handled as one.** URLs are logged by proxies, kept in browser history, pasted into chat, and sent in `Referer` headers. A single table whose rows are sometimes bearer credentials and sometimes URL segments is a table where someone eventually treats one as the other. The hashing helper is shared; the table is not.

### 4. Rotation is the revocation story, and it is the reason a secret beats a slug

Rotating mints a new token and invalidates the old one. The previous URL immediately returns `404` — the same `404` an unknown token gets, because a distinct "this feed was rotated" reply tells a scanner it found a real tenant.

This is what a readable path cannot offer. If the address *is* the merchant's identity, there is nothing to rotate: the only remedy for a leaked URL is to stop publishing altogether.

**Rotation does not un-publish anything already cached.** It stops future fetches. Said plainly here because a merchant will read "rotate" as "undo", and it is not.

### 5. What the document may contain, and what it may never contain

Restated from [`sell.md §7.2`](../../agents/sell.md) because this is the decision they hang from — a public endpoint is the wrong place to discover that a rule lived only in a design document:

- **The timestamp is the sync's, never the request's.** A price with no date is an offer with no date, and a caching layer that stamps serve-time turns a stale price into a fresh-looking one.
- **`DRAFT` and `ARCHIVED` products are excluded**, matching the retrieval index.
- **Availability is asserted only where `INVENTORY_READ` is declared and the sync is fresh**; otherwise the field is omitted. An omitted field is honest, a guessed `InStock` is a claim.
- **Stock quantity is never published.** Commercially sensitive, stale on write, and needed by no consumer.
- **No customer data, ever** — asserted by the renderer rather than assumed from the fact that a catalogue has none today.
- **No `AggregateRating`.** We hold no review data, and synthesising one is fabrication of exactly the kind GUARD v1 exists to detect.

### 6. Rate-limited as an anonymous subject

There is no key, so there is no key to limit. The feed is limited by client address and by feed token, under the existing several-subjects-narrowest-binds rule ([ADR-0017](0017-rate-limit-subjects.md)). A crawler that ignores `Cache-Control` must not be able to make a merchant's catalogue expensive to serve.

### 7. The alternatives, and what each would have cost

| | what an attacker needs to read a store's catalogue |
|:--|:--|
| on by default, tenant id in path | the tenant id — which appears in dashboards, support tickets and every merchant-side integration |
| opt-in, merchant slug in path | the merchant's name. And there is no rotation: the URL *is* the identity, so a leak is permanent |
| **opt-in, hashed secret in path** | the secret itself, which exists in exactly two places — the merchant's own records, and wherever they submitted it |

The middle option is the one to argue against, because it looks safe: opt-in genuinely fixes consent. It does not fix enumerability, and it makes the remedy for a mistake "stop publishing" rather than "rotate".

**The accepted cost of the chosen option:** discovery is worse. A crawler will not find an unguessable URL on its own, so the merchant must submit it. That is a real loss for a feature whose purpose is being found, and it is accepted because the alternative trades a permanent, enumerable exposure for a marketing convenience.

### 8. How it is mounted, since the API must not learn the word "sell"

The chat routes are generic and mounted per agent from the manifest's `route_prefix` ([`routes/agent.py`](../../../apps/neura-api/src/neura_api/routes/agent.py)). A feed is not generic — no other agent has one — so it cannot go there.

An agent therefore contributes its own routes through a **fourth entry-point group**, `neura.agent_routes`, mounted under the same `route_prefix` as everything else:

```toml
[project.entry-points."neura.agent_routes"]
sell = "neura_agent_sell.routes:build_routes"
```

Same shape and same reason as the three that already exist ([AGENTS.md](../../../AGENTS.md), "Add an agent"): `neura-api` resolves a router by entry point rather than importing an agent by name, so **the deployable never learns which products it serves**. Without this, delivering the feed at all would mean writing `from neura_agent_sell import ...` inside the API — and "one codebase, five products" would stop being structural.

## Consequences

**Good.** A merchant can be published to the agent-commerce channel without any credential exchange, and cannot be published by accident. A leaked URL has a remedy that is not "delete the feature". The credential path is the one already proven by API keys, so there is no second bootstrap to get wrong. And the endpoint stays outside the key model without punching a hole in it: nothing about `credential_session` changes, and every read after the token resolves is an ordinary scoped session.

**Bad / accepted.** Discovery is worse, and the merchant carries the submission step. The feed URL cannot be shown twice, which will generate support conversations — the answer is rotation, and rotation invalidates the old URL, which is not what the merchant asking the question wants to hear. One more table, one more migration, one more thing to rotate.

**The limit that no part of this decision addresses.** Rotation stops future fetches and does nothing about what is already cached, indexed or republished elsewhere. **Publication is one-way.** Everything above is about making sure it is *chosen* — none of it makes it reversible, and a merchant told otherwise has been misled.

## What this does not decide

- **Nothing about the MCP server's auth**, which is an ordinary bearer key carrying `sell:mcp:connect` and raises none of the questions above.
- **No `robots.txt`, sitemap or discovery-submission helper.** The merchant submits the URL themselves for now; automating that is Phase 2 and closer to GROW's territory.
- **No per-format opt-in.** Switching the feed on publishes every implemented rendering of it. If a merchant ever wants JSON-LD but not canonical JSON, that is a new decision.
- **S8 stays open.** Whether a product whose description trips the outbound injection rules is ever *withheld* from this document is unresolved, and this ADR publishes flagged products while surfacing the flag.
