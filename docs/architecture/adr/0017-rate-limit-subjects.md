# ADR-0017 — A Rate Limit Is Applied to Several Subjects at Once, and the Narrowest One Wins

**Status:** Accepted · **Date:** 2026-08-03 · **Resolves:** open question P1

## Context

[api-design.md §12.1](../api-design.md) records the problem in one sentence: *per API key is too
coarse for a widget where every shopper shares one public key*. It is the whole of open question
**P1**.

The shape of the problem is specific to how the widget works. A `fn_pk_` key is served to every
browser that loads the merchant's storefront ([ADR-0014](0014-api-keys-and-the-rls-bootstrap.md)),
so "per key" and "per merchant" are the same limit, and it has to be set high enough for all of a
busy shop's shoppers at once. At that height it constrains no individual — one script can consume
the entire merchant's allowance and every real shopper is refused. Set it low enough to constrain
the script and the shop's ordinary Monday morning fails.

There is a second question hiding behind it, and getting them confused is the expensive mistake: a
rate limit and a **budget** are not the same control. [ADR-0015](0015-usage-rollups-and-budget-degradation.md)
decided that a budget *degrades* — a shopper who hits a merchant's daily ceiling gets a person, never
an error. That is right for spend measured over a day. It is wrong for a burst measured over a
minute: at 40 requests a second there is no useful work to degrade *to*, and a handover per request
would occupy a human being for every message of the flood.

## Decision

### 1. Every request is checked against several subjects, and all of them must pass

A subject is the thing being limited. The set depends on which kind of key is presented, because
the two kinds have genuinely different callers behind them.

| Key kind | Subjects checked | Why that subject exists |
|:--|:--|:--|
| `fn_sk_` (server) | `tenant`, `key` | The caller *is* the merchant. One server, one allowance. |
| `fn_pk_` (browser) | `tenant`, `key`, `client`, `conversation` | The key identifies the shop, not the shopper. Two narrower subjects do that. |

`tenant` is always checked and is the backstop: it is the number a merchant is told, it bounds
what one account can cost us however many keys they hold, and it is the only subject that survives
a caller rotating everything else.

`client` is derived from the network peer, and `conversation` from the server-issued
`conversation_id`. Neither is sufficient alone, which is why both are checked:

- A **conversation** limit constrains an honest shopper's client from retry-storming, and it is
  the only subject that maps to "one chat". It constrains an attacker not at all, because
  starting a new conversation is free.
- A **client** limit constrains the attacker. It is coarse behind NAT — a school or an office
  shares one address — which is why the conversation limit is not replaced by it, and why the
  client allowance is set to a household's worth of shoppers rather than one person's.

The response reports the **tightest** subject: `X-RateLimit-Remaining` is the minimum remaining
across every subject checked, and `X-RateLimit-Reset` is that subject's window end. A client
backing off on those headers backs off on the constraint that will actually stop it.

### 2. The client identifier is the socket peer unless a proxy count is configured

`X-Forwarded-For` is attacker-controlled. Trusting it makes the `client` subject free to rotate,
which turns the narrowest control into no control at all — and it does so silently, because the
limiter carries on reporting perfectly plausible numbers.

So: `NEURA_TRUSTED_PROXY_HOPS` defaults to **0**, meaning the header is ignored entirely and the
peer address is used. A deployment behind *n* known proxies sets *n*, and the value taken is the
*n*-th entry from the right — the last hop the deployment's own infrastructure appended. It is
deliberately a count of hops rather than a list of addresses, because a hop count is a fact about
the deployment's own topology, and an operator who does not know it should not be guessing at an
allowlist either.

**The address is never stored.** It is hashed, keyed with `NEURA_SECRET_KEY`, into a counter key
that expires with its window. An IP address is personal data; a keyed hash with a one-minute
lifetime is the least of it we can keep and still count.

### 3. The counters live in Redis, and a rate limit that cannot be checked fails **open**

Redis, not process memory. This is one deployable ([ADR-0002](0002-modular-monolith.md)) but it is
not one *process* — any real deployment runs several workers, and an in-process counter multiplies
every limit by the worker count while continuing to report the configured number. A control that
is wrong by an unknown factor is worse than one that is absent, because nobody investigates it.

When Redis cannot be reached the request is **allowed**, an error is logged for every occurrence,
and `/v1/health/ready` reports Redis as down. This is the one place in this codebase where a check
fails open, so the reasoning is worth stating rather than assuming:

- **A rate limiter is not an access control.** Authentication, entitlements, the policy engine and
  the ownership gate are all in the request path and all unaffected by Redis. Nothing becomes
  *permitted* that was forbidden; only the pace is unmetered.
- **The cost ceiling survives it.** The daily budget ladder is a Postgres rollup
  ([ADR-0015](0015-usage-rollups-and-budget-degradation.md)) read on every turn. With Redis gone,
  a flood still walks the tenant into `ESCALATE_ONLY` and stops costing model calls. The expensive
  outcome is bounded by a different store.
- **The alternative is worse.** Failing closed turns a cache outage into a total outage for every
  merchant at once — a self-inflicted denial of service, in exchange for an abuse window that the
  budget already bounds.

### 4. Exceeding a rate limit is a 429; exceeding a budget is still not

The two controls keep their two different answers, and the reason is who pays.

A **429 with `Retry-After`** is returned for a rate limit. It is honest — the request was not
processed and the client should try later — and it is machine-readable, which is what a retrying
client needs. It reaches a *client*, and a client can wait.

A **budget** continues to degrade to escalate-only, unchanged. It reaches a *shopper*, who cannot
wait a day and did not set the ceiling.

Health endpoints are exempt from rate limiting altogether. An orchestrator's liveness probe being
throttled would take a healthy process out of rotation.

## Consequences

**Good**

- P1's actual complaint is answered: one script sharing the shop's public key is constrained by
  its client and conversation subjects long before it reaches the merchant's ceiling, and the
  shop's other shoppers are unaffected.
- The headers stay truthful under a multi-subject scheme, because they report the binding
  constraint rather than an arbitrary one.
- Adding a subject later — per-agent, per-scope, per-store — is a row in a table of limits, not a
  new mechanism.
- Redis finally does something. `/v1/health/ready` has reported `redis: not_implemented` since the
  probe was written; it now reports what it found.

**Bad / accepted**

- **Every limit in the table is a guess.** They are informed starting points and must not be
  quoted as measurements (CLAUDE.md §4). Nothing here has seen a real shopper. They are
  configuration for exactly that reason, and the trigger to recalibrate is the same as **E3**'s:
  roughly a hundred real conversations.
- **The window is fixed, not sliding.** Two full allowances can be spent across a window boundary.
  A sliding window costs a sorted set per subject per window and is the upgrade if the boundary
  burst ever matters; `X-RateLimit-Reset` at least makes the boundary predictable rather than
  mysterious.
- **Behind CGNAT, one `client` subject is many households.** The conversation subject is what
  keeps an individual shopper from being starved by a stranger's traffic, and the client allowance
  is sized for a shared address rather than a person. This is a real limitation of IP-derived
  identity and there is no better identifier available to an anonymous browser.
- **A shopper can still start a new conversation per message.** That evades the conversation
  subject and lands on the client subject, which is the design: the narrower control is for
  honest clients, the coarser one for dishonest ones.

## Alternatives considered

- **Per key only, tuned high.** The status quo P1 objects to. It is not a per-shopper control at
  all, and its failure mode is that the first abuser denies service to every real shopper on the
  shop.
- **A signed session token minted per widget load, limited per token.** Stronger than a
  conversation id and genuinely unforgeable — but a token minted on demand by an anonymous browser
  is as cheap to obtain as a conversation, so it constrains exactly the same honest clients while
  costing a new issuance endpoint and a second credential to explain.
- **CAPTCHA or proof-of-work before a conversation starts.** Effective, and it puts friction in
  front of every shopper of every merchant to defend against a rare event. Revisit if a real shop
  is actually attacked; not before.
- **In-process token buckets, reusing `neura_commerce.sync.throttle`.** That limiter is correct
  and is the right tool for its job — pacing *our* outbound calls to one merchant's shop from one
  process. It is the wrong tool for counting inbound requests across workers, for the reason in §3.
- **Fail closed when Redis is unavailable.** Rejected in §3.
