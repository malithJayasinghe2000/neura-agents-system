# ADR-0079 · NEURA Runs On Azure, And Scales To Zero

**Status:** **Accepted** · the owner's decisions 2026-11-17, R129 to R132 · everything marked *(Claude)* is Claude's ·
**Date:** 2026-11-17 · **Resolves:** [X2](../../open-questions.md) (*the deployment target*) · **Roadmap:** 1.17 ·
**Related:** [ADR-0002](0002-modular-monolith.md) (one deployable), [ADR-0017](0017-rate-limit-subjects.md) (the limiter
fails open), [ADR-0051](0051-the-public-website-is-its-own-app-and-says-only-what-the-code-does.md) (the website is
static)

> **In one sentence:** the first online NEURA runs on the owner's Azure for Students credit, paying only for what is
> used: the website free, the API and the dashboard switched off while nobody uses them, and the smallest database.

## Context

The first step online is **marketing**: the website, sign-up and the dashboard, with **no shop connected**. So the
cheapest way that is still safe wins (R129). The owner has Azure for Students credit and has deployed there before.

## Decision

### 1. Where each part runs (R129)

| Part | Azure service | Address (R131, R132) |
|:--|:--|:--|
| The website (static, ADR-0051) | Static Web Apps, free plan | `neura.fiveneurals.com` |
| The API, with its job runner inside it (ADR-0002) | Container Apps, consumption, **min replicas 0** | `api.fiveneurals.com` |
| The dashboard (Next.js) | Container Apps, consumption, **min replicas 0** | `app.fiveneurals.com` |
| PostgreSQL with `vector` and `pgcrypto` | Flexible Server, Burstable B1ms | private to the apps |
| The night run's clock *(Claude)* | a Container Apps **job** on a schedule that calls the API once a night | none |

Region: **Central India**; Southeast Asia if B1ms is not offered there (R132). `fiveneurals.com` stays the company
website. `go.fiveneurals.com` stays for links (AD13).

### 2. Scale to zero, and what it costs us *(Claude)*

- **A slow first open.** After a quiet time the first request waits while a copy starts (tens of seconds).
- **The job runner sleeps with the API.** Jobs run only while a copy is up, so a nightly scheduled job wakes the API
  and keeps it up long enough for the due jobs. With no shop, there is almost nothing due.
- **One copy at most for now** (max replicas 1). The rate limiter's counters would otherwise be split between
  copies; with no Redis there is no limiter anyway (§3).

### 3. No Redis for now (R130)

The owner's choice: **no Redis until real shops join.** The limiter fails open by design (ADR-0017), so **every
rate limit is off**, including the sign-in email limit (5 per address per hour): the public sign-in page could be
used to send many sign-in emails to one address. The daily AI budget per shop is in PostgreSQL and stays on.
**Redis is a must before real shops join**, with G128 (`/go/` limit), AD9 (the data agreement) and AD13.

### 4. Staging first

`NEURA_ENV=staging`: test shops only, no real shopper. Production is a later step, after §3's musts.

### 5. What is not decided here

The AI provider stays undecided as a product decision (ADR-0006); this deploy uses the `cloud-prod` role map
(Gemini), as every test has. The database after its 12 free months is a cost to watch.

## Consequences

- **Cost:** the website is free; the API and the dashboard are inside Container Apps' monthly free grant at this size;
  the database is free for 12 months on the student offer, then paid monthly (it is not pay-per-use); Gemini is pay
  per use. Nothing here is measured yet.
- New files: two Dockerfiles, an Azure setup script and a runbook (`docs/DEPLOY.md`).
