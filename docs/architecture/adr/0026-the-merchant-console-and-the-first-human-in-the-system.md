# ADR-0026 — The Merchant Console, And The First Human In The System

**Status:** Accepted · **Date:** 2026-08-26 · **Builds on:** [ADR-0002](0002-modular-monolith.md), [ADR-0010](0010-read-only-mvp-tools.md), [ADR-0012](0012-blocking-is-about-cost.md), [ADR-0019](0019-widget-no-build-step.md) · **Design:** [`docs/console.md`](../../console.md) · **Open questions:** A4, E1, E8, S5, S2

## Context

Every feature this project has deferred is deferred behind the same missing thing, and it is not a feature. It is a **screen**.

- Writes are blocked by [ADR-0010](0010-read-only-mvp-tools.md) until an **approval queue** exists. An approval queue is a screen.
- Shadow-mode grading has been shipped since 1.15 and has **nowhere to grade in** (**A4**). Grading is a screen.
- The audit log has been written and hash-chained since 1.14, and **nobody reads it in aggregate** (**S5**). Reporting is a screen.
- Golden datasets are entirely synthetic, and the only route to real ones runs through graded real conversations (**E1**).

One build unblocks four recorded open questions. Nothing else in the backlog has that ratio, and the project owner's own reason is simpler and better: **a merchant cannot be sold something they cannot see.** There is exactly one piece of user interface in this repository — `widget/widget.js`, which is the *shopper's* chat box. The person who pays has never had a screen.

### The fact that shapes everything below

The schema has **fifteen tables and not one of them describes a person.** `api_keys`, `tenants`, `tenant_stores`, `tenant_usage`, `conversations`, `shadow_turns`, `audit_log`, `job_queue` — every one is machine-oriented or tenant-oriented. Authentication today is a bearer token presented by a *program*, resolved to a tenant, which sets the row-level security context for the request.

**A console needs to authenticate a human, and the system has no concept of one.** This ADR is therefore less about a dashboard than about introducing the first human identity into a system whose entire security model is built on tenant isolation.

### The second fact, found while designing this

**Nothing in this codebase can send an email.** No SMTP, no provider SDK, no queue for it. Magic-link login depends on delivering a link to an inbox, so the console cannot be deployed at all until an email path exists. Recorded here because it is easy to discover on the day it blocks, and because it is a genuinely new external dependency for a system that currently has none beyond the LLM provider and the merchant's own shop.

## Decision

### 1. The console is a Next.js application at `apps/neura-console`, using Tailwind and shadcn/ui

Same repository as the API, so the two version together and one contract cannot silently drift from its only consumer. It is **not** served by FastAPI: [ADR-0019](0019-widget-no-build-step.md) chose no-build-step for the widget, and that decision was right for a 400-line script a merchant pastes into their own page. It is the wrong decision for a seven-screen application with tables, filters, forms and charts, and pretending otherwise costs more than the toolchain does.

shadcn/ui rather than a component library, for one reason that matters more than looks: **the component code is copied into the repository rather than imported.** There is no vendor to be locked into, no upgrade that restyles the product, and accessibility ships in the defaults instead of becoming a to-do.

**The cost is stated rather than waved at:** this puts Node and npm into a repository that is currently pure Python, and `make check` grows a second toolchain.

### 2. Humans sign in with a magic link, built here, not bought

A one-time link to an email address. No password is ever stored, so none can be leaked, reset, reused across sites, or phished in the ordinary way.

**It is built rather than bought because of the sovereign tier.** [blueprint-v2 §5](../../business/blueprint-v2.md) sells a deployment a customer runs entirely on their own hardware. A hosted authentication vendor — Clerk, Auth0, Supabase Auth — is a per-user cost, a third party in the trust path, and above all a service that **cannot be run inside the customer's perimeter.** Buying login would quietly delete a product tier, and it would do so in a `package.json`.

### 3. The browser never holds a tenant API key. This is the security spine of the console

A session cookie identifies the *person*. The API resolves person → membership → tenant, and only then sets the row-level security context, exactly as it does for a machine key today.

The rejected alternative is the one that will be proposed by anyone in a hurry: mint a tenant API key at login and let the console call the existing API with it. **A secret key in a browser is a secret key in every extension, every crash report and every screenshot the merchant ever takes**, and it carries the tenant's full machine authority with no session lifetime and no revocation the merchant would ever think to use. `AGENTS.md` rule 3 applies unchanged — the mapping from session to tenant is code, and no part of it is a claim the browser makes about itself.

Sessions are cookie-based (`HttpOnly`, `Secure`, `SameSite=Lax`), not tokens in local storage, because a token in local storage is readable by any script that gets onto the page.

### 4. Three new tables, and one of them deliberately breaks the tenant rule

| Table | Scope |
|:--|:--|
| `users` | **Not tenant-scoped** |
| `memberships` | Tenant-scoped, forced RLS |
| `login_tokens` | **Not tenant-scoped** |

`users` and `login_tokens` cannot be tenant-scoped, and the reason is not convenience: **at the moment someone clicks a login link, we do not yet know which tenant they belong to** — that is what the lookup is *for*. A person may also own two shops, and the same human owning two tenants must not become two accounts with two passwords to the same inbox.

So the rule this project has held since 1.10 — every table carries `tenant_id` under forced RLS — gains its first exception, and the exception is contained rather than waved through: `users` holds an email, a name and timestamps and **no business data whatsoever**; every row a person can reach through the console is reached *through* `memberships`, which is tenant-scoped and forced like everything else. Tenant isolation is unchanged. What changed is that the door now has a doorman as well as a lock.

`login_tokens` stores a **hash** of the token, never the token, following `api_keys.token_hash` exactly. Single use, short expiry, and consumed inside the transaction that creates the session so that a link forwarded to a group inbox cannot be redeemed twice.

### 5. One role in v1: owner

Everyone with a membership can do everything to that tenant. **No permission model is invented before a merchant has asked for one.** A four-role matrix designed against imagined staff is four times the authorisation surface and zero times the evidence, and roles are cheap to add later and expensive to remove once someone depends on them.

### 6. The approval queue is designed and **not built** in v1

It is the reason the console is the keystone, and building it now would be building a screen with nothing to approve: [ADR-0010](0010-read-only-mvp-tools.md) still blocks writes, and both agents are read-only by design ([ADR-0023](0023-sell-is-read-only-and-a-protocol-is-an-output-format.md)). Its slot is in [`console.md`](../../console.md) so the shape of the app anticipates it.

### 7. Documentation ships as part of the product, in three kinds

| Kind | Where | For |
|:--|:--|:--|
| Merchant help | inside the console app | the shop owner, and a prospect reading before they buy |
| In-app guidance | the screens themselves | the person who will never open the help site |
| Developer / API | wrapped around the generated OpenAPI at `/docs` | the merchant's developer |

The merchant help site lives inside the console app rather than as a separate deployment: one thing to deploy, one thing to keep current, and a help page can link straight into the screen it describes.

## Consequences

**The project gains a second language and a second toolchain.** Node, npm, a build step, and a JavaScript test runner in CI. This is normal and it is still a cost — `make check` gets slower and there are now two ways for a dependency to be out of date.

**Email becomes a hard dependency of logging in.** A provider must be chosen and it is not chosen here (see below). Until then the console cannot be used by anyone who is not already in the database, and a login-by-email flow has a failure mode nothing else in this system has: *the software is fine and the user still cannot get in.*

**Rule 4 has no obvious meaning here, and that is [E8](../../open-questions.md), not a new question.** *"Nothing merges without an eval"* assumes model behaviour that can regress, and the console contains no model of ours at all. E8 already asks what substitutes for a surface with no model — proposing a deterministic abuse and conformance suite — and the console falls under the same answer whenever E8 gets one. **The console must not be the reason Rule 4 is quietly skipped.** Its own minimum is stated in [`console.md`](../../console.md): a person reaches only the tenants they hold a membership for, a revoked membership reaches nothing, an expired or reused login token reaches nothing, and no console response contains another tenant's row.

**S2 gets sharper, not new.** KEK custody was already "env var acceptable for a pilot, cloud KMS before the first real merchant". The console is what brings the first real merchant, so S2's trigger and the console's launch are the same date.

**The console is where the product stops being invisible.** That is the point of building it, and it is also the risk: a screen makes claims. Every number it displays must carry the same honesty the documents do — a synthetic figure has to say it is synthetic, on the screen, where a merchant reads it.

## What was rejected

| Rejected | Why |
|:--|:--|
| Server-rendered from FastAPI, no build step | Right for a 400-line widget ([ADR-0019](0019-widget-no-build-step.md)), wrong for a seven-screen app. Fights you from screen three. |
| Hosted auth provider | Deletes the sovereign tier in a `package.json`. |
| Passwords | We would own hashing, resets, breach response and 2FA forever, for a product with a few hundred merchants. |
| Google/Microsoft sign-in only | Assumes every small shop has a corporate account. Poor assumption for the stated South Asian market ([blueprint-v2 §11](../../business/blueprint-v2.md)). |
| Tenant API key held in the browser | A secret in every extension, crash report and screenshot, with the tenant's full machine authority. |
| A role matrix in v1 | Four times the authorisation surface, zero evidence anybody wants it. |
| Separate repository | Two things to keep in sync; the API contract breaks silently when one moves. |
