# ADR-0058 · A Shop's Dashboard Has People With Roles, And A Shop Signs Up

**Status:** **Proposed** · owner decisions 2026-10-09 and 2026-10-10, a design session, R1 to R11
([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, *Roles*). Everything marked
*(Claude)* is Claude's proposal, for the owner to accept or change · **Date:** 2026-10-10 · **Supersedes:**
[ADR-0026](0026-the-merchant-console-and-the-first-human-in-the-system.md) §5 (*one role in v1: owner*), and nothing
else of it · **Resolves:** [K2](../../open-questions.md) once built · **Related:**
[ADR-0014](0014-api-keys-and-the-rls-bootstrap.md) (key scopes, the naming copied here),
[ADR-0052](0052-the-shop-owner-connects-their-own-shop.md) (the shop token),
[ADR-0057](0057-a-signed-in-shopper-may-ask-about-their-orders-in-the-chat-box.md) (the sign-in secret), the log's
D3 (a developer account), D9 (the owner makes the chat box key), G9, G44, and its new *Admin needs* list (AD1 to AD6)

> **In one sentence:** a shop's dashboard gets people besides its owner, each with a **role** that is a bundle of
> **permissions** checked in code on every request; three roles now (**Owner**, **Support**, **Developer**), each
> future agent bringing its own permissions and, if it needs one, its own role; the owner adds a person with an
> emailed invite; and a new shop owner **signs up** and waits for FiveNeurals to approve the shop.

## Context

ADR-0026 §5 gave the dashboard one role, `owner`, and named its own trigger for more: *a merchant asking to give
someone access, likely the first one with a support team.* The owner chose on 2026-10-09 to finish the shop side of
the dashboard **before** looking for a shop owner, so the trigger is met by design rather than by a merchant's
request, for three reasons found in the work itself:

- **Every shop has a developer, and today a developer would need the owner's account** (G9), which shows every
  shopper's chat. Since ADR-0057, chats hold order details and home addresses.
- **CARE's next feature** (the shop's team gets handed-over chats, G44, L2) is a help-desk job, not the owner's alone.
- **Three more agents are planned** (MIND, GROW, GUARD). The structure must take their screens without being rebuilt.

**What exists and stays:** the sign-in cookie names the person and nothing else, and every request re-derives
person → membership → shop (`acting_for`, `memberships_for`), so a removed membership stops working on the person's
next request; `memberships.role` already exists (default `owner`) and `revoked_at` keeps who used to have access
(ADR-0026 §4); sign-in links are single-use, 15 minutes, hashed at rest.

## Decision

### 1. A role is a bundle of permissions (R2)

A **permission** opens one thing; a **role** is a named set of them (explained to the owner as a hotel's key cards:
a permission is a door, a role is a card type). Permissions are named the way key scopes already are
(`care:chat:write`): `<area>:<thing>:<read|write>`, where the area is an agent (`care`, `sell`) or a shop-wide area
(`shop`, `people`, `usage`).

- **The map from role to permissions is code** (`neura_core.identity`), never data a browser sends and never a
  prompt (Rule 3).
- **Each console route declares the permission it needs**, checked in `acting_for` after the membership. A person
  with no membership in the shop still gets **404** (ADR-0026: it reveals nothing about which shops exist); a member
  without the permission gets **403** *(Claude: they already know the shop exists, and a plain refusal is easier to
  understand)*.
- **The dashboard hides what a role cannot open**, but the API is the lock: a hidden button is a convenience, the
  403 is the rule.
- **Each new agent brings its own permissions in its own ADR, and may bring its own role** (the owner, R2: a
  **Marketing** role arrives with GROW, whose screens are not designed). The Owner gets every new permission
  automatically (R4).

### 2. Three roles now (R3)

| Role | For | May | May not |
|:--|:--|:--|:--|
| **Owner** | The shop owner | **Everything**, including people | |
| **Support** | The help desk | Read chats (CARE and SELL), grade replies in Review; reply to shoppers once the handover feature is built (§8) | Keys and secrets, Shop connection, *Go live*, people, Usage |
| **Developer** | Whoever builds the bridge and the chat box line | Shop connection (including the shop token and the sign-in secret, §6), Help | **Read shoppers' chats**, Review, *Go live*, people, Usage |

The first permissions, from today's screens *(Claude; the exact names are fixed in the build)*:

| Screen or action | Permission | Owner | Support | Developer |
|:--|:--|:--|:--|:--|
| Home | (every member) | ✅ | ✅ | ✅ |
| Help | (every member) | ✅ | ✅ | ✅ |
| Conversations | `care:conversations:read`, `sell:conversations:read` | ✅ | ✅ | ❌ |
| Review: read and grade | `care:review:write`, `sell:review:write` | ✅ | ✅ | ❌ |
| Suggestions (choose) | `sell:suggestions:write` | ✅ | ❌ | ❌ |
| Sold out | `sell:sold_out:read` | ✅ | ❌ | ❌ |
| Shop connection: read, Check, tokens and secrets | `shop:connection:write` | ✅ | ❌ | ✅ |
| Shop connection: Connect, contact details | `shop:connect:write`, `shop:contact:write` | ✅ | ❌ | settled at the mockup (R10) |
| *Go live* and back to practice | `shop:mode:write` | ✅ | ❌ | ❌ |
| Usage and cost | `usage:read` | ✅ | ❌ | ❌ |
| People: invite, change a role, remove | `people:write` | ✅ | ❌ | ❌ |

**Not a role now:** *Staff* for products and selling (Suggestions, Sold out). The owner asked about it; it is left
for a real shop to ask for, because a role is cheap to add and costly to remove (ADR-0026's own warning, R3).

### 3. The Owner (R4)

- The Owner holds every permission of Support and Developer, and more.
- **A shop always keeps at least one Owner:** the last Owner cannot be removed or given another role. Checked in
  code, in the same transaction as the change *(Claude)*, so two owners removing each other at once cannot leave
  none.
- **A shop may have more than one Owner** (for example two partners).

### 4. Adding a person (R5, R9)

- The Owner types an email and picks a role. NEURA emails an **invite link**. It works **once**, for **7 days**;
  only its hash is stored *(Claude: as sign-in links are)*. The owner may **cancel** it or **send it again** (a new
  link; the old one stops).
- Clicking it signs the person in (creating their account if the email has none) and adds them to **that shop
  only**, with that role. Later sign-ins are the ordinary email link; no passwords.
- The Owner may **change a role** or **remove** a person at any time. Removing sets `revoked_at`; it takes effect on
  that person's **next request**, because the cookie carries no access (ADR-0026 §3; checked in the code
  2026-10-10).
- **Every invite, cancel, acceptance, role change and removal is an audit entry with who did it** *(Claude)*.
- **The People screen is the Owner's alone** *(Claude)*: who works in a shop is the owner's business, and a list of
  colleagues' emails is personal data.
- An invite to an email that is already a member of the shop is refused with a plain sentence *(Claude)*.

### 5. Every role is per shop (R6)

A person (one email) may belong to several shops, with a different role in each. **An Owner can give access only to
their own shop**: the invite is created under the shop's own row-level security, so Shop A's owner can never open
Shop B for anyone. This is how `users` and `memberships` already work.

### 6. The Developer makes the shop's secrets (R10)

The Developer may make the **shop token** and the **customer sign-in secret**, and put them straight into the shop's
settings, so **a secret never travels by email or chat**. Each make is audited with who made it, and Shop connection
shows the owner *Made [date] by [name]* *(Claude)*. With D3, the Developer presses **Check**. **Go live** stays the
Owner's. When this is built, the developer guide's *Shop owner* lines for Check (step 3) become *You* (D3).

### 7. Signing up (R7)

- A new page beside *Sign in*: *"New to NEURA? Create an account"*: **email, shop name, shop website**. The email link
  signs them in as **Owner** of a new shop in a **waiting** state.
- **A waiting shop can do nothing but wait** *(Claude)*: no keys, no chat box, no AI, no connection; its owner sees
  one screen, *"Thanks. We'll look at your shop and email you when it's ready."* Nothing in it costs anything.
- **FiveNeurals approves or refuses it** (no billing yet, so every approved shop spends our AI budget). **A command
  for now** (`make tenant-approve`, AD1), the admin dashboard later (R8). On approval the shop works as today's
  shops do (practice mode, the daily spending limit); its owner gets an email *(Claude)*. A refused shop is removed.
- **Sign up says nothing about who already has an account** (console.md §4.3 rule 4, applied here too) and is
  rate-limited per address and per email, as sign-in is *(Claude)*.
- The public website gets *Get started* beside *Sign in*; the owner guide's first step changes from *ask
  FiveNeurals* to *create an account*.

### 8. Not in this ADR: Support replying to shoppers (R11)

Support works with today's screens (read chats, grade replies). **Replying to a shopper arrives with the handover
feature** (the shop's team gets handed-over chats, G44, L2), designed next in its own session and ADR, which adds its
own permission (for example `care:handover:write`) to Owner and Support.

### 9. Tests

**Written first, failing on the old code:** each role is refused (403) every route its permissions do not open, and
allowed every route they do; a non-member still gets 404; the last Owner cannot be removed or demoted, also when two
requests race; an invite works once, expires after 7 days, stops when cancelled or sent again, and adds the person to
that shop only; Shop A's owner cannot invite into Shop B; a removed person is refused on the next request; a waiting
shop has no keys, no chat and no connection, and its approval makes it an ordinary shop; sign up and invites reveal
nothing about existing accounts. **In headless Chrome:** each role sees only its screens, on desktop and phone.
**No AI run:** nothing here reaches a model.

## Consequences

- **A shop can be run by a team** without sharing the owner's sign-in, and a developer never sees a shopper.
- **The developer guide changes** (D3: *You* press Check; the developer makes the secrets), and so do the owner guide
  (sign up, inviting the developer) and FEATURES.md.
- **New screens:** People (list, invite, role, remove), Create an account, the waiting screen. **Mockups first**,
  then the owner's approval (the console work cycle).
- **Every console route gains a declared permission**; a route that forgets one must fail a test, not open by
  default *(Claude)*.
- **Email matters more:** sign-in, invites and approvals all arrive by email, so the online email service (K1) must
  be chosen before NEURA goes online.
- **FiveNeurals approves shops by command** until the admin dashboard exists (R8, the *Admin needs* list).

## Not decided here

- The FiveNeurals admin dashboard: its own session, right after the shop side (R8), from the *Admin needs* list.
- The handover feature and Support's replies (§8).
- A *Staff* or *Marketing* role (with a real shop's request, or with GROW).
- The owner choosing permissions with tick boxes (custom roles).
- A second sign-in step for Owners, and *Sign in with Google*: only if shops ask.
- Billing, and signing up without approval.
- The online email service (K1).
