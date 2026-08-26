# The Merchant Console — Design

**Status:** Designed 2026-08-26. **Screen 1 (sign in) built 2026-08-27** — `make console-check`. Screens 2–5 not written. · **Decision:** [ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) · **Unblocks:** A4, E1, S5, and eventually [ADR-0010](architecture/adr/0010-read-only-mvp-tools.md)

> **Read [ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) first.** It records *why* — including the three decisions a fresh session is most likely to reverse by accident: the browser never holds a tenant API key, login is built rather than bought, and `users` is deliberately not tenant-scoped.

---

## 1. What this is, in one paragraph

The screen a shop owner logs into. It shows them what their AI assistant said, lets them grade answers before those answers ever reach a customer, connects their shop, and reports what it cost. **It is the first thing in this project built for the person who pays**, and it is the keystone under four deferred features.

### 1.1 What it is not

It is **not** an admin panel for us, it is **not** a replacement for the shop's own back office, and in v1 it does **not** approve anything — because nothing in the system can yet change a merchant's store ([ADR-0010](architecture/adr/0010-read-only-mvp-tools.md)).

---

## 2. Scope — v1 is five screens

Deliberately cut the way CARE's three intents were cut. The temptation is eleven screens; the discipline is five.

| # | Screen | Reads | Ships in v1 |
|:--|:--|:--|:--|
| 1 | **Sign in** | `users`, `login_tokens` | ✅ **built 2026-08-27** |
| 2 | **Conversations** | `conversations`, `conversation_messages` | ✅ |
| 3 | **Review** (shadow grading) | `shadow_turns` | ✅ **the one that earns its keep** |
| 4 | **Shops** | `tenant_stores`, `sync_checkpoints` | ✅ |
| 5 | **Usage** | `tenant_usage` | ✅ |
| 6 | Security | `audit_log` | v1.1 — closes **S5** |
| 7 | Settings & keys | `api_keys` | v1.1 |
| 8 | Approvals | — | **blocked** by [ADR-0010](architecture/adr/0010-read-only-mvp-tools.md) |

**Build order is 1 → 3 → 2 → 4 → 5**, and Review is second on purpose. It is the only screen that produces something the project does not already have: **real graded turns**, which is the sole route out of **E1** (every golden case is synthetic today). A console that shipped analytics first would look finished and change nothing.

---

## 3. The screens

### 3.1 Sign in

Enter an email → receive a one-time link → land in the console. If the email has no membership, **the screen says the same thing either way and the same email is sent or not sent silently** — a login form that says *"no account with that email"* is an account-enumeration oracle for anyone who wants to know which merchants use us.

### 3.2 Review — grading, and the reason to build this first

A queue of turns the agent drafted while in shadow mode: the shopper's question, the evidence the agent retrieved, the reply it *would* have sent, and whether `verify` passed it. The merchant marks it good or bad and may say why.

**Three rules, each of which is a lesson already paid for elsewhere in this project:**

* **Show the evidence, not just the reply.** A grader who cannot see what the agent was working from is grading fluency. This is `--out`/**E7** restated as a screen: a draft is only judgeable against what it was allowed to rely on.
* **A withheld turn must look withheld.** 1.16 found that a shopper shown an empty panel is a bug report within a day ([ADR-0020](architecture/adr/0020-a-withheld-turn-says-so.md)); the merchant-facing version of the same mistake is a grading queue that silently omits the turns the agent declined to answer. Those are the interesting ones.
* **Do not add sampling.** **A4** is unanswered, and a sampling rate chosen before anyone has graded for an hour is a rate invented to fit an imaginary constraint.

### 3.3 Conversations

Transcript list, filter by escalated / blocked / declined. Read-only.

**PII is shown to the merchant unredacted, and this is a decision rather than an oversight** — they are the data controller for their own customers, and a support conversation with the addresses starred out is useless for the purpose they need it for. The redaction that matters is on what reaches the *model* (`PiiVault`, per-turn, never persisted), and that is unchanged.

### 3.4 Shops

Connect a shop (URL + token), run the conformance suite against it, and watch the first sync. `neura-conformance` already exists and already produces the result this screen needs — **the screen is a view over it, not a second implementation.**

Credentials are written through the existing envelope encryption path. **The console never displays a stored credential**, not even masked to its owner: a field that can be revealed is a field that gets revealed in a screen-share.

### 3.5 Usage

Conversations, turns, escalations, blocked attacks, tokens, cost — from `tenant_usage`, which has been written since 1.14.

**Every number carries its own honesty.** A figure derived from synthetic data says so *on the screen*. A deflection rate from eleven conversations shows the eleven. `docs/` has been disciplined about this from the beginning ([CLAUDE.md §4](../CLAUDE.md)) and a dashboard is exactly where that discipline usually dies.

---

## 4. Identity — the part that is genuinely new

### 4.1 Three tables

```
users                       (NOT tenant-scoped — see ADR-0026 §4)
  id, email (citext, unique), name, created_at, last_seen_at

memberships                 (tenant-scoped, forced RLS)
  id, tenant_id, user_id, role='owner', created_at, revoked_at

login_tokens                (NOT tenant-scoped)
  id, user_id, token_hash, expires_at, consumed_at, requested_ip
```

`sessions` are signed cookies rather than a table, so a logout is a cookie clear and there is no session store to grow unbounded. **Revocation is checked against `memberships` on every request**, not baked into the cookie — otherwise removing someone's access does nothing until their cookie expires.

### 4.2 The request path

```
browser  --cookie-->  console (Next.js)  --session-->  API
                                                        ↓ resolve person
                                                        ↓ resolve membership
                                                        ↓ SET LOCAL app.tenant_id
                                                        ↓ RLS does the rest
```

The last two steps are the ones that already exist and are already trusted. **The console adds a doorman in front of a lock that is not being changed.**

### 4.3 Rules that are not negotiable

1. **No tenant API key ever reaches the browser.** ([ADR-0026](architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md) §3)
2. **The tenant comes from the membership, never from the request.** A `?tenant=` parameter the browser can edit is not authorisation, it is a suggestion. `AGENTS.md` rule 3.
3. **Login tokens are single-use, hashed at rest, and consumed in the same transaction that creates the session.**
4. **Sign-in reveals nothing about who has an account.**

---

## 5. Documentation, shipped as part of the product

| Kind | Lives | Written for |
|:--|:--|:--|
| **Merchant help** | `/help` inside the console app | the owner — and the prospect reading before they buy |
| **In-app guidance** | empty states, tooltips, first-run tour | the person who will never open the help site |
| **Developer docs** | wrapped around the generated OpenAPI at `/docs` | the merchant's developer building the connector |

**The most valuable documentation here is the empty state**, and it is the piece most often left until last. A merchant who has just signed up sees five empty screens; whether they ever come back is decided there, not in a help article. Every empty state answers *what is this, why is it empty, what do I do next.*

**One rule carried over from the widget** ([ADR-0020](architecture/adr/0020-a-withheld-turn-says-so.md)): merchant-facing sentences come from the server, not hard-coded into a JavaScript bundle. A sentence a merchant cannot change and nobody reviews is how a wrong promise ships.

---

## 6. What "done" means for a surface with no model

**This is [E8](open-questions.md), not a new question**, and the console must not become the reason Rule 4 is quietly skipped. Until E8 is answered, the console's own minimum bar is deterministic and testable:

1. A person reaches **only** the tenants they hold a live membership for.
2. A **revoked** membership reaches nothing, immediately — not at cookie expiry.
3. An **expired**, **consumed** or **forged** login token reaches nothing.
4. **No console response ever contains another tenant's row.** Asserted with two tenants populated, not one.
5. Sign-in **cannot be used to enumerate** which emails have accounts.
6. No credential and no API key appears in any response body, ever.

---

## 7. Known limits, stated before anyone hits them

| Limit | Consequence |
|:--|:--|
| **Nothing in this system can send an email** | Magic-link login cannot work until a provider is chosen. The console is undeployable without it, and the failure mode is new: the software is fine and the user still cannot get in. |
| **Node and npm enter a pure-Python repo** | Second toolchain in `make check`; two ways to have a stale dependency. |
| **One role, `owner`** | A merchant who wants to give a support agent read-only access cannot, until somebody asks and it is designed. |
| **No approval queue** | Every write feature stays blocked. This is by design and is the next thing the console unlocks. |
| **Shadow mode must be on to have anything to review** | A merchant who goes live immediately sees an empty Review screen forever. The empty state has to say so. |

---

## 8. What is deliberately not decided here

* **The email provider.** A real choice with cost, deliverability and sovereign-tier consequences — a self-hosted deployment needs an SMTP path, not an API key to a US service. Decide it with **K1** / [X2](open-questions.md), which is also where the deployment target and the cloud model get decided.
* **The permission model.** One role until a merchant asks for a second.
* **Branding, colour and type.** shadcn/ui defaults until there is something to be consistent *with*.
* **Whether the console is the sovereign tier's problem too.** A customer running everything themselves still needs this screen, and their deployment has no email provider and possibly no public DNS.
