# ADR-0060 · Sign Up: What The Build Decided

**Status:** **Accepted** · owner decisions 2026-10-11 (R14, R15, R16, R17) · **built 2026-10-11** (piece 3 of
ADR-0058's build) · **Date:** 2026-10-11 · **Implements:**
[ADR-0058](0058-a-shops-dashboard-has-people-with-roles-and-a-shop-signs-up.md) §7 · **Related:**
[ADR-0059](0059-people-and-roles-what-the-build-decided.md), [ADR-0022](0022-scheduling-under-rls.md) (the
cross-tenant function pattern), [CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md) *Decisions*
*Roles (R14)* to *Roles (R17)*, G97, G99, AD1

> **In one sentence:** a new shop owner fills in *Create an account*, clicks the emailed link, and becomes the
> Owner of a shop that waits and opens nothing until FiveNeurals approves it by command, with the assistants
> FiveNeurals chooses; building it met four questions ADR-0058 §7 did not answer, which the owner decided, and
> this records them with the smaller defaults the build chose.

## Context

ADR-0058 §7 and its approved mockups (console.md §3.8, boards 42 to 45) fix the screens and the rule (*a waiting
shop can do nothing but wait*). Four things were open:

| # | Question | Decided |
|:--|:--|:--|
| R14 | Which assistants an approved shop gets | The owner, 2026-10-11: **A**, FiveNeurals names them at approval, CARE when none named |
| R15 | Someone who already has an account signs up again | The owner: **A**, the link adds a second waiting shop to their account, as Owner, and signs them in |
| R16 | Whether a refused shop's owner is told | The owner: **A**, a short email |
| R17 | The three emails' words and five small choices | The owner: **A**, approved as proposed |

## Decision

### 1. The request, and the link (R15)

- `POST /v1/console/auth/sign-up` takes an email, the shop's name (up to 100 characters, spaces tidied) and its
  website (with or without `https://`; kept as `scheme://host[:port][/path]`, the host lower-cased, the query and
  fragment dropped; only `http` and `https`, at least two host parts, no user name or password). A wrong value is
  refused in plain words before anything else: *"Enter your shop's website, like yourshop.com."*, *"Enter your
  shop's name, up to 100 characters."*
- **Nothing is made** but a row in `sign_up_requests` (no `tenant_id`, like `login_tokens`): the link's hash only,
  15 minutes, **one request per email** (a second replaces the first, so the first link stops). Expired rows are
  deleted by the next sign-up.
- **Every email gets a link and the same words** (*"A link is on its way. It works once and expires in 15
  minutes."*), so the form says nothing about who has an account (console.md §4.3 rule 4). An existing account
  needs the link too: it is how they add a second shop (R15).
- **The confirm email never repeats what was typed** (R17): anyone can type any text for any address, and an email
  that carried the shop's name would let anyone make NEURA mail any text to a stranger.
- **Sign-up and sign-in links count together** against G97's limit (5 an hour per email, 20 per network address):
  the limit is on what one inbox receives. Only the refusal's words differ: *"Too many sign-up links were asked
  for. Please wait a while, then try again."*

### 2. The link makes everything, at once

`POST /v1/console/auth/confirm-sign-up`, in the new shop's own tenant session, one transaction: deletes the request
(so the link works once, also when two clicks race), makes the account when the email has none, makes the shop
(`TenantStatus.WAITING`, no assistant, practice mode, `tenants.website`), makes its Owner membership, writes an
audit entry (`people.change`, `signed_up`, no email in it), and signs them in. **It signs in an existing account
too**: the link works 15 minutes and once, as a sign-in link does, so it opens nothing a sign-in link would not
(contrast R13, where a 7-day invite link must not). A used, replaced or old link says *"Sign-up links expire after
15 minutes and work once. If you already confirmed, sign in. If not, create your account again."* with **Sign in**
and **Create an account**.

### 3. A waiting shop opens nothing

- `acting_for` refuses **every shop route** of a waiting shop with **403 `SHOP_WAITING`**, whatever the role; a
  stranger still gets **404** first. Read on every request, so approval opens the shop on the Owner's next click.
- `/me` gives each membership its `status` and the person's own `email`; a waiting shop has **no permissions**.
- `ApiKeyRepository.issue` refuses a waiting shop, so `make key-new` cannot make one; any key would also fail,
  because a waiting shop is not servable.
- The dashboard's shop frame shows **the waiting screen** instead of the menu (board 44), and *Your shops* lists it
  as *Waiting for approval*. **The waiting screen shows *Your shops* when the person has another shop** (R17 a; the
  board has only *Sign out*, drawn for a first shop).

### 4. FiveNeurals approves or refuses, by command (AD1)

- `make tenant-waiting` lists waiting shops with name, website, Owner and date. A tenant session sees one shop, so
  the list comes from **`neura_waiting_tenants()`**, a `SECURITY DEFINER` function owned by the `NOLOGIN` role
  `neura_registrar`, which may read three columns of `tenants` (id, status, created) and only rows that wait, and
  returns ids only; each shop is then read in its own session. The ADR-0022 pattern, not a bypass.
- `make tenant-approve TENANT=… [AGENTS=care,sell]` (R14): only a waiting shop; the assistants must be installed
  ones (a typo is refused, nothing changed); **CARE when none is named**; the shop keeps practice mode and the
  daily spending limit; an audit entry (`config.change`, `shop.approved`); the approval email to every Owner.
- `make tenant-refuse TENANT=…` (R16): only a waiting shop; an audit entry (`shop.refused`), then **removed as
  `make tenant-drop` removes a shop**, then the refusal email, so the email states what is already true. **The
  person keeps their account** (R17 e): they may be in another shop. The shop's audit entries stay, as for every
  removed shop (S10).
- Each command says which emails were sent and which were not (*email is off* when `SMTP_HOST` is empty).

### 5. The emails (R17, the owner: A)

| Email | Subject | Body |
|:--|:--|:--|
| Confirm | *Confirm your FiveNeurals sign-up* | *Someone asked to sign up a shop for FiveNeurals with this email address. If it was you, use the link below to confirm it. [link] It works once and expires in 15 minutes. If it was not you, you can ignore this email. Nothing has been made.* |
| Approved | *[shop] is ready on FiveNeurals* | *FiveNeurals has approved [shop]. Sign in to start: [dashboard]. Your assistant starts in practice mode, so shoppers see none of its replies until you press Go live. The guide for shop owners shows the next steps: [guide]* |
| Refused | *Your FiveNeurals sign-up for [shop]* | *Thank you for signing up [shop] for FiveNeurals. We looked at it, and we can't start an assistant for this shop, so we have removed it. Nothing was charged.* |

## Consequences

- **A shop can come into being without FiveNeurals typing a command**, and still nothing runs, and nothing costs
  anything, until a person at FiveNeurals has looked at it.
- **One more cross-tenant function** (`neura_waiting_tenants`) and one more `NOLOGIN` role. It answers ids of
  waiting shops only; the admin dashboard (R8) will need its own answer for *every* shop (AD2).
- **Every console request reads the shop's status** (one small query), so approval needs no new sign-in.
- **The sign-in page now links to sign up**, and the owner guide's first step and the public site's *Get started*
  change with it (piece 4).
- **Email matters more again**: the confirm link is the only way in, so the online email service (K1) must be
  chosen before NEURA goes online.

## Not decided here

Everything ADR-0058 lists as not decided, and: a reason in the refusal email; removing the account of a refused
person who is in no other shop; a rate limit on approvals (they are a command); signing up without approval
(with billing).
