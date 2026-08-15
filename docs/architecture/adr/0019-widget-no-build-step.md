# ADR-0019 — The Widget Is A Dependency-Free Custom Element, Served By The API

**Status:** Accepted · **Date:** 2026-08-15 · **Resolves:** open question P8 (1), (2), (3) · **Builds on:** [ADR-0014](0014-api-keys-and-the-rls-bootstrap.md), [ADR-0016](0016-stream-only-after-verify.md), [ADR-0017](0017-rate-limit-subjects.md)

## Context

The widget is one line of the roadmap — *"embeddable chat, client-side rendered, AI disclosure, origin-locked keys"* — and it is the first surface a real shopper would touch.

Its **constraints** were already decided and merely scattered, which is what P8 recorded: a public key is inert until origin-locked and may not assert a customer (ADR-0014 §3), rate limits add `client` and `conversation` subjects because one widget key identifies the shop and not the shopper (ADR-0017), `ai_disclosure` renders on **every** message rather than the first (EU AI Act Art. 50), the socket carries only post-`verify` text (ADR-0016), and [security-model.md §13](../security-model.md) requires CSP and per-tenant CORS origin allowlists.

What was undecided was everything about how it is **built and delivered**, and this repository has no JavaScript toolchain at all: no `package.json` anywhere, no bundler, no lockfile, no static-file mounting in the API. So 1.16 either introduces a toolchain or deliberately avoids one, and that is not a choice to make silently.

## Decision

### 1. One dependency-free custom element, no build step

`widget.js` is a single file defining `<neura-chat>` as a Custom Element with an open Shadow root. No framework, no npm, no lockfile, no bundler, no transpilation. It is served byte-for-byte as it is written.

**The decisive argument is not toolchain cost, it is Shadow DOM.** This code is injected into an arbitrary merchant's theme. Their CSS must not be able to break our layout and ours must not leak into their page, and a Custom Element gets that isolation from the platform rather than from a convention. A framework would have to reproduce it anyway.

The toolchain argument is real but secondary: a framework brings npm into a Python-only monorepo, and with it a lockfile, a build artefact that must be committed or produced at deploy, and a supply chain that CI's dependency scanning does not currently cover — all to render one panel, a message list, an input and a disclosure line.

**Tests run on `node --test`**, which ships inside Node 24 and needs no `package.json` and no install. The tested surface is deliberately narrow: which message a given turn result renders. That is exactly the logic [ADR-0020](0020-a-withheld-turn-says-so.md) turns into a safety property, so it is the part that must not be left to inspection.

**The accepted cost:** no JSX, no reactive bindings, and DOM built by hand. If the widget ever grows past a few hundred lines of view code this decision should be revisited — and revisited by writing a superseding ADR, not by adding a `package.json` next to it.

### 2. Served by the API from our own origin

`GET /v1/widget/widget.js` and `GET /v1/widget/snippet` — no CDN, no copy-paste of the source. The merchant embeds two lines:

```html
<script src="https://api.example.com/v1/widget/widget.js" async
        data-neura-key="fn_pk_live_…"></script>
```

[overview.md §4](../overview.md) has claimed the API does "widget hosting" since it was written and nothing implemented it; this is the line that makes the claim true.

**Not a copy-paste snippet**, which ships fastest and then freezes every bug in place across the whole install base — a fix would require every merchant to re-paste. It also forces `unsafe-inline` into the *merchant's* Content-Security-Policy, which is a security concession we would be asking a third party to make on our behalf.

**Not a CDN.** It adds a third party to the security story to solve a distribution problem nobody has, and the deployment target is still an open question (**X2**). This is reversible: a CDN in front of the same URL changes nothing about the widget.

The asset is served with `Cache-Control: public, max-age=300` — short, because the merchant cannot re-paste to pick up a fix — and with `X-Content-Type-Options: nosniff`. The demo page at `/v1/widget/demo` carries a strict `Content-Security-Policy` of its own; the widget itself adds no inline script and no inline event handler, so a merchant running a strict CSP needs only to allow our origin in `script-src` and `connect-src`.

### 3. CORS is decided by the presented key, not by a deployment-wide list

This is the part of §13 that was specified and not built. `settings.widget_origins` is a **process-wide** environment list, so onboarding a second merchant means an environment change and a restart, and any origin on that list passes CORS while holding any tenant's key.

The obvious fix — resolve the allowlist per tenant at preflight — **cannot be built as stated**, and the reason is worth recording because it will be met again. A CORS preflight is an `OPTIONS` request that carries no `Authorization` header, so there is no key to resolve a tenant from; and the union of every tenant's origins cannot be read out of PostgreSQL either, because `api_keys` is under forced Row-Level Security and no transaction can enumerate tenants (**P7**, ADR-0008). The two ways around that are a `BYPASSRLS` role — which P7 argues against — or an index kept outside PostgreSQL, which for webhooks costs a delayed schedule but here would cost a **total widget outage** whenever the index is lost.

So the decision is to put the check where the credential actually is:

- **A preflight is answered for any syntactically valid origin.** Approving a preflight authorises a browser to *send* a request; it authorises nothing to be read. The request it permits is still refused by the key's own origin lock (ADR-0014 §3) before a single model call.
- **An actual response carries `Access-Control-Allow-Origin` only when the presented key permitted that origin.** No authenticated caller, no header — so a rejected cross-origin request is unreadable in the browser, and a refusal is not an oracle for *"is this key valid somewhere else?"*.

This is per-tenant, needs no index that can be lost, and needs no redeploy to onboard a merchant. It is also honest about what CORS is doing here: with `allow_credentials=False` and a bearer token there are no ambient credentials to steal, so **CORS is defence in depth and the key's origin lock is the access control**. `settings.widget_origins` survives only for endpoints that have no key to consult.

### 4. WebSocket first, REST as the fallback

The widget opens `WS /v1/{agent}/stream` and falls back to `POST /v1/{agent}/chat` when the socket cannot be opened.

ADR-0016 already settled that no model-generated text reaches a shopper before `verify` passes, so the socket does **not** buy earlier text. What it buys is `step` and `tool_call` frames during the wait — and the wait is the point. The recorded p50 turn latency on `ollama-dev` is **41.8–50.9s** ([PROJECT_STATE](../../PROJECT_STATE.md), 2026-08-13). Forty seconds of motionless spinner is indistinguishable from a broken integration; forty seconds of *"checking your order"* is a system visibly working. Those frames name a node and say nothing about the answer, which is exactly why they are safe to send before `verify` has run.

The fallback is cheap because the `done` frame and the REST `data` object already carry the same fields, so one renderer serves both.

**The accepted cost, stated rather than discovered later:** `Idempotency-Key` is a REST header and the socket has no equivalent. A socket dropped mid-turn and retried by the shopper is a turn the merchant pays for twice. The REST fallback path does send the header. This is the smaller half of a trade whose larger half is a shopper leaving during a silent minute.

## Consequences

**Good**

- The monorepo stays Python-only. No `package.json`, no lockfile, no npm in CI, no build artefact to keep in sync with its source.
- A merchant's CSS and ours cannot collide, by construction rather than by naming convention.
- A fix reaches every merchant on the next cache expiry rather than on the next re-paste.
- Onboarding a merchant's origin is a key issue, not a deploy.
- The shopper sees progress during a turn that currently takes tens of seconds.

**Bad, or merely accepted**

- View code is hand-built DOM. This is fine at this size and would not be at ten times it.
- Two transports in the client, therefore two paths to keep behaving identically. The mitigation is that both render from one function, and a test asserts the REST payload and the `done` frame carry the same fields.
- No idempotency on the socket path.
- Answering every preflight looks permissive read in isolation. It is only defensible *because* the origin lock and the missing `Access-Control-Allow-Origin` sit behind it, and a future change that weakens either one silently re-weights this decision.

**Neutral**

- Agent behaviour provably cannot move: the widget is a client, and the eval harness imports no `neura_api`. Rule 4 is satisfied structurally, as it was in 1.14 and 1.15, rather than by spending model runs.

## What would change this

A second surface needing the same view logic (the merchant console, Phase 2) is the trigger to revisit §1 — at that point a shared component layer may earn a toolchain that one widget does not. A merchant blocked by our origin's latency or availability is the trigger to revisit §2, which is a deployment change and not a rewrite.
