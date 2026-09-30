# ADR-0051 — The Public Website Is Its Own App, And Says Only What The Code Does

**Status:** **Accepted** — owner decision, 2026-09-30 · **Date:** 2026-09-30 · **Related:** [ADR-0002](0002-modular-monolith.md), [ADR-0026](0026-the-merchant-console-and-the-first-human-in-the-system.md), [ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)

## Context

NEURA had no public web presence. A shop owner could not read what the assistants do, and a
developer could not read how to connect a shop without being sent our internal documents.

The owner approved two sets of mockups on 2026-09-30 (the Design canvas, rows 8 and 9): a
**product site** (one page per assistant) and a **docs site** (setup guides, for owners and for
developers). The owner's rules for both, set 2026-09-28/29:

- **made-up examples only**, never the test shop's data;
- **honest**: no results or percentages, no prices, no time estimates, and every claim true in the code;
- **features are not setup steps**: the product site says what it does, the docs say how to set it up;
- **no commerce platform names** ([Rule 1](../../../AGENTS.md));
- **colours and fonts are placeholders**: branding is not decided.

`fiveneurals.com` is the company's own website. It lives in another repository and is not NEURA's.

## Decision

> **The public website is one static Next.js app, `apps/neura-web`, in this repository and separate
> from the console. It serves NEURA's product pages and its docs, and it says only what
> [`docs/FEATURES.md`](../../FEATURES.md) says is built.**

### 1. Where

| What | Address | Code |
|:--|:--|:--|
| The company website | `fiveneurals.com` | the other repository — unchanged except one link to NEURA |
| NEURA's product pages | `neura.fiveneurals.com` | `apps/neura-web` |
| NEURA's docs | `neura.fiveneurals.com/docs` | `apps/neura-web` |

### 2. Why its own app, and not a part of the console

- **The console holds a session and every shop's data; the website holds neither.** Apart, a
  mistake on a public page cannot reach a shop's data, and neither can break the other.
- **Different visitors, different hosting.** Anyone may read the website. It is static files; the
  console needs a server and the API.
- **Same repository**, because `FEATURES.md` and the checks live here: a feature and its public
  description change in one commit, and the platform-name check already scans every app.
- **Same tools as the console** (Next.js, Tailwind, TypeScript, ESLint, Prettier), so there is one
  way of working, not two.

ADR-0002's *one deployable* is about the server. A folder of static files is not a second server.

### 3. What the website may not contain

- **No secret, no API call, no cookie, no sign-in.** It links to the console; it never talks to the API.
- **No script of ours watches a visitor**: no analytics and no tracking pixel. Adding one would be
  observation, and [ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md)'s
  whole position is that nothing of ours watches a person unless someone chose it.
- **No external request at all.** Fonts are self-hosted at build time, as in the console.
- **Nothing that is not in `FEATURES.md` as built.** A page may not describe a feature ahead of the code.

### 4. What is still not decided — placeholders on the pages, one file in the code

`apps/neura-web/src/lib/site.ts` holds every value that is not decided, each shown on the page as a
bracketed placeholder, and `make web-check` lists every placeholder still present:

- the **contact address** (`[CONTACT ADDRESS]`);
- the **API's public address** in the chat box line (`[NEURA ADDRESS]`);
- the **dashboard's address** behind *Sign in*;
- **hosting**, and **branding** (the colours and fonts are the console's, as placeholders).

Also undecided, and **written on the pages as what is true today** rather than as a plan: how a
developer gets the check tool (*"Ask FiveNeurals for it"*); how the shop token reaches the developer
(*"FiveNeurals gives you"*); who makes the chat box key (**FiveNeurals, today** — the owner's direction
that the owner makes it in the dashboard is not built and needs its own ADR).

## Consequences

- A second Next.js project in the repository, with its own `node_modules`. Both projects pin the
  same versions, so updating them is one change twice.
- The company website needs one link to `neura.fiveneurals.com`; that is work in another repository.
- **The website will go stale unless `FEATURES.md` is kept.** CLAUDE.md §6 makes updating it part of
  finishing a feature; generating pages from it is a later option, not part of this decision.

## Alternatives considered

- **Put the pages in the console.** Rejected — see §2: the public site would share a process with
  sessions and shop data.
- **Put NEURA's pages in the company website's repository.** Rejected: they would be written away
  from `FEATURES.md` and the checks, which is how a page comes to describe something that is not built.
- **A separate repository for the NEURA website.** Rejected for the same reason, with more setup.
- **A docs framework for the docs.** Not needed for four pages; revisit if the docs grow.
