# ADR-0053 · A Developer's AI Tool May Ask NEURA How To Build A Bridge

**Status:** **Proposed** · the owner's answers in a design session, 2026-10-02 (four questions, in
[CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, E6 Q1 to Q4); waiting for the
owner's approval · **Date:** 2026-10-02 · **Related:**
[ADR-0009](0009-generic-commerce-interface.md) (the bridge's format),
[ADR-0017](0017-rate-limit-subjects.md) (the request limiter),
[ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md) (SELL's own MCP server, a different thing),
[ADR-0051](0051-the-public-website-is-its-own-app-and-says-only-what-the-code-does.md),
[ADR-0052](0052-the-shop-owner-connects-their-own-shop.md); the log's findings G1, G4, G7, G10, G14, G37, G66, G69
and recommendation E6

> **In one sentence:** NEURA runs a public MCP server that teaches a developer's AI coding tool what a
> bridge must answer, in which format, with a sample for every answer and every rule developers get
> wrong, so the AI can help write the bridge. It only teaches: it never calls a shop, needs no account and
> no token, and every word it returns is ours.

## Context

Connecting a new shop from zero (Ceylon Harvester, 2026-09-30) showed that a developer works the bridge's
format out by guessing:

| Found | What it cost |
|:--|:--|
| No address has a sample answer, on the guide page or in the OpenAPI file (G1; the guide now shows one) | The developer guesses what one product looks like |
| How to fit a shop's own data (sizes, statuses, drafts, no policy pages) is written nowhere (G4) | A wrong guess is a wrong answer to a shopper |
| Staff returned as customers (G7), drafts told to shoppers (G37), `"OK"` instead of `"ok"` (G14), a missing `status` that makes NEURA-SELL recommend nothing (G69) | Each one passes or half-passes the check |
| The OpenAPI file teaches webhooks to NEURA, which NEURA cannot receive (G66) | Work that goes nowhere |

The owner kept a long *fit your data* table off the guide page (G4): a person would have to read all of it.
Most developers now write code with an AI tool, and an AI tool reads a long list for free. The owner's
idea (E6): plug NEURA into that tool.

**Not the same thing as SELL's MCP server** ([ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md)).
That one lets shoppers' AI agents read one shop's catalogue, with the shop's key. This one teaches developers
the bridge's format, and knows no shop at all.

## Decision

### 1. It teaches, and only teaches (Q1)

The developer's AI tool asks; NEURA answers with the format and the rules. **It never calls a shop and never
runs the check.** The AI writes the bridge in the developer's own project; NEURA never sees the shop's code.
The developer guides the AI, reviews and tests; the shop owner still runs the check and connects
([ADR-0052](0052-the-shop-owner-connects-their-own-shop.md)), exactly as today.

Checking a bridge (the *inspector*) is **not decided here**: it needs its own answers (§8).

### 2. NEURA runs it, at one public address (Q2)

A remote MCP server inside NEURA's API, `POST /v1/developers/mcp`. The developer pastes that one address into
their AI tool. Every developer gets a rule change the moment it ships, and none of our code is published.
(Not chosen: a package the developer installs, which can teach an old format and would publish our code.)

**It is built on the official MCP library** (the MCP project's Python SDK, open source, MIT licence), not on
hand-made protocol code (the owner's yes, 2026-10-02, after asking what it costs: nothing in money; the cost is
updating it on purpose, like any library). The library follows each new revision of the MCP standard and does
the safety checks the standard requires of a server (among them the `Origin` check against DNS rebinding); we
write only what the teacher says. It runs **stateless, answering in plain JSON**: no session, nothing kept
between questions, so any copy of NEURA's API can answer any question. The library is added to `neura-api`
only, at a pinned version, and updated deliberately with the tests of §5. **Fallback:** if the library cannot
sit with the project's own pinned dependencies, the server uses SELL's hand-made JSON-RPC framing instead,
moved to a shared package below the apps so that NEURA's API does not import an agent's code (AGENTS.md
rule 2). SELL's own server is not changed by this ADR; moving it to the library is its own later step.

### 3. Public: no account, no token, a limit on how often (Q1, Q2)

It answers anyone, like the guide page does. **It holds nothing worth protecting**: no shop's data, no
merchant text, no secret. What anyone could abuse is our server's time, so:

- **A limit per client address**, on the request limiter that already exists
  ([ADR-0017](0017-rate-limit-subjects.md), Redis, fails open). The starting value is a guess, to be set from real
  use (CLAUDE.md §4).
- **Its arguments are names, not text**: an address (`/products/{id}`), a rule's topic. Anything else is a
  JSON-RPC *invalid params*. Nothing a caller sends is stored beyond the ordinary request log.

### 4. What it teaches: everything (Q3)

Four read-only tools:

| Tool | Answers |
|:--|:--|
| `list_addresses` | The nine addresses: what each answers, which group it is in (*start with these three*, *add these for better answers*, *only for order questions*), and the `/health` word each needs |
| `get_address` | One address: method and path, its parameters, the format of its answer, **a sample answer**, and the rules for that address |
| `get_rules` | The rules developers get wrong, among them: the token on every address except `/health`; everything is `GET`; cursors, not page numbers; a missing record is a `404`; the exact `"ok"` and `"1.0"`; customers only, never staff (G7); `"active"` for a product on sale, or NEURA-SELL never recommends it (G69); drafts stay hidden from shoppers (G37); one variant for a product without sizes; a price is text plus a three-letter currency; **do not build webhooks to NEURA yet** (G66); and how to fit a shop's own data (G4) |
| `get_openapi` | The whole OpenAPI file, for a code generator |

**Marked the MCP way.** Every tool carries the standard's labels: *read only*, *always the same answer for the
same question*, *changes nothing*, and *reaches nothing outside NEURA*. Every answer is **structured** (with
its format declared) and also given as plain text, for AI tools that read only text.

**Every answer names the format version it teaches**, today `"1.0"`, the bridge's `spec_version`. The tools take
an optional version; when a version 2.0 of the bridge's format exists, the teacher teaches both, and a
developer whose shop is on 1.0 is never taught 2.0 by surprise. This is what lets it grow with the format.

### 5. It is true because it is built from the code, and tested (Rule 4)

- **The formats come from `build_openapi()`** (`neura_adapters/generic/spec.py`), the same function that makes
  the OpenAPI file. They cannot disagree.
- **Every sample passes NEURA's own reader of bridge answers** (`generic/wire.py` `to_canonical`), with no field
  the format does not know. A test fails otherwise, the way step 1's sample was checked (A10).
- **Lists come from the code's own lists**: the capability words from `Capability`, the statuses from
  `ProductStatus` and `OrderStatus`. A new word in the code fails a test until the teacher says it too (the
  spirit of idea D4).
- **No commerce platform's name in anything it returns** (Rule 1), tested over every tool's output.
- **There is no model of ours in it**, so Rule 4's evals have nothing to measure. Open question
  [E8](../../open-questions.md) asks what replaces them for such a surface; here it is, stated rather than
  improvised: deterministic tests of the content (above) and of the protocol (`initialize`, `tools/list`,
  `tools/call`, the error codes), and of the limit.
- **Tried with real AI tools before it is announced**: the MCP project's own test tool (*MCP Inspector*, free),
  and one real AI coding tool. The second uses an AI model, so it runs only with the owner's yes, as every model
  run does. (Nothing shows that SELL's MCP server was ever tried this way; this one will be.)
- **Counted, never read**: how many times each tool is called, per format version. Never what was asked, never
  who asked. That count is how the *Review* below is answered.

**G66 in the same change:** the OpenAPI file's `entityChanged` says *"Not used yet: NEURA has no address that
receives these. Do not build them."* Otherwise `get_openapi` and `get_rules` would contradict each other. (The
owner had moved the guide's *The full specification* section to later; this is the file only.)

### 6. How developers find it (Q4)

- **The developer guide**, *Before you start*, beside the OpenAPI download: *"Using an AI coding tool? Add this
  address to it."*
- **The shop owner's Help** (*Copy these steps for your developer*). A dashboard change: **mockup on the design
  canvas first**, then the owner's approval (the console work cycle).

Both show NEURA's address, which is **not decided** (`site.ts` `NEURA_ADDRESS`); until it is, they show the
same placeholder the chat box line does.

### 7. Order of building

1. The official MCP library in `neura-api`, pinned; first prove it sits with the project's dependencies (or take
   §2's fallback).
2. The content: the rules module and the samples, beside `spec.py`, with the tests of §5. Test first.
3. The route, public, stateless, with the limit, the labels and the count.
4. G66's sentence in the OpenAPI file.
5. Tried with *MCP Inspector*; then, with the owner's yes, with one real AI coding tool.
6. The guide's sentence; FEATURES.md's line, in the same change (CLAUDE.md §6).
7. The Help mockup, the owner's approval, then Help.

## Consequences

- **A second public MCP surface, and the first with no key at all.** Safe only because it holds nothing; the day
  it learns anything about a shop (the inspector), this ADR stops covering it.
- **The rules now live in code, beside the format**, and the guide page repeats some of them by hand. The
  guide may drift from the teacher; the teacher may not drift from the format.
- **More to keep true**: every change to the bridge's format now also changes what the teacher says. The tests of
  §5 make a mismatch fail rather than ship.
- **It needs NEURA's public address** before it can be announced to anyone real.

- **Growth.** Nothing is kept between questions and the answers are prepared once at start-up, so any number of
  copies of NEURA's API can answer, sharing only the limiter's counters. If it ever outgrows the one deployable
  ([ADR-0002](0002-modular-monolith.md)), it can move out alone: it needs no database and no shop.
- **One more library to keep current** (the MCP SDK), updated on purpose, never by accident.

## Alternatives considered

- **Hand-made protocol code**, as SELL's server has. Kept only as §2's fallback: every revision of the MCP
  standard would have to be noticed and followed by hand, and SELL's server is still fixed to `2025-06-18`.
- **A package the developer installs** (Q2). Works offline, and could later check a bridge on the developer's
  own computer, but teaches whatever version was installed, and publishes our code: the open-source question in
  [blueprint-v2.md §11.5](../../business/blueprint-v2.md) is the owner's to answer first.
- **A long *fit your data* section on the guide page** (G4). Declined by the owner: a person reads every line.
- **Teacher and inspector at once** (Q1). The inspector needs to know who the developer is and would make NEURA
  call an address a stranger types (G47). Kept for later.

## Not decided here

- **The inspector**: checking a bridge. Its questions: who the developer is (a developer account, D3, or a key
  the shop owner makes), NEURA calling a typed address (G47's rules), or a package that checks on the
  developer's own computer (the open-source question).
- **The limit's value**, set from use.
- **The MCP revision policy** for both servers ([P9](../../open-questions.md)); the library narrows it for
  this one, it does not answer it.
- **Moving SELL's MCP server to the library.**
- **NEURA's public address.**

## Review

If the first developers who use it still ask FiveNeurals what it should have answered, it is teaching the wrong
things: fix the content before building the inspector.
