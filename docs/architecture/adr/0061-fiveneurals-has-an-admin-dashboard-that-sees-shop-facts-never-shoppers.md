# ADR-0061 · FiveNeurals Has An Admin Dashboard That Sees Shop Facts, Never Shoppers

**Status:** **Accepted** · owner decisions 2026-10-11, a design session, R19 to R23
([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, *Admin*) · **not built**; the three
screens are drawn for the owner's approval first (the console work cycle) · Everything marked *(Claude)* was Claude's
proposal, accepted by the owner with R23 · **Date:** 2026-10-11 · **Supersedes:** [console.md](../../console.md) §1.1's
*"It is not an admin panel for us"*, and nothing else · **Related:**
[ADR-0058](0058-a-shops-dashboard-has-people-with-roles-and-a-shop-signs-up.md) (shop roles; the admin is not one),
[ADR-0060](0060-sign-up-what-the-build-decided.md) (sign up and approval by command),
[ADR-0022](0022-scheduling-under-rls.md) (the only way code may look across shops), [ADR-0026](0026-the-merchant-console-and-the-first-human-in-the-system.md) (the sign-in it reuses), the log's *Admin needs* (AD1 to AD6) and R8

> **In one sentence:** FiveNeurals staff get an area of the dashboard, `/admin`, where they see every shop's facts
> (its state, whether it is connected, its AI use and cost) and approve or refuse the shops that signed up, and
> **never** a shopper's chat or details: the database itself refuses to give an admin page anything else.

## Context

The owner decided on 2026-10-10 (R8) that the FiveNeurals admin dashboard is designed right after the shop side,
from the *Admin needs* list kept since then. With sign up built (ADR-0060), a new shop waits until someone at
FiveNeurals runs `make tenant-approve`; seeing every shop and the AI spend across them needs database queries.

An admin is **the first person in this system who reaches every shop**. Every other person reaches only the shops
they are a member of, and the cookie names a person, never a shop (ADR-0026). So the design question is less *what
the screens show* than *what an admin must never be able to see*, and how that is made true in code rather than in
the screens.

## Decision

### 1. An admin sees shop facts, never shoppers (R19, the owner: A)

| An admin sees | An admin never sees |
|:--|:--|
| Each shop's name, id, website, when it signed up or was made | A conversation, a message, a draft reply or a grade |
| Its state: waiting, practice, live (or suspended, leaving) | A shopper's name, email, address or order |
| Its assistants, and whether a shop is connected | The catalogue, the shop's keys, its secrets |
| Its Owners' emails (the shop's own contact, needed to approve it) | Product views or anything else observed about shoppers |
| Per day and assistant: chats, AI calls, tokens, cost, chats handed to a person | Anything inside a shop's own dashboard |

When FiveNeurals must see a chat to fix a problem, **the shop owner shows it**. There is no *sign in as this shop*
(R23).

### 2. The first version has three jobs (R20, the owner: A)

1. **Approve or refuse** a shop that signed up (AD1).
2. **See every shop** and its state (AD2).
3. **AI use and cost** across all shops (AD6).

The data agreement (AD3), a secret key (AD4) and removing a shop (AD5) **stay commands**: they are rare, and a
command is harder to press by mistake. They stay on the *Admin needs* list for a later version.

### 3. Where: `/admin` in the same dashboard (R21, the owner: A)

The admin area is part of the dashboard, at `/admin`, with **its own side menu** (settled at the mockup, the owner,
2026-10-11, R24: *the admin side will get a lot of things*, so a side menu from the start rather than a top bar
changed later): the black *Admin* badge by the name, a card *FiveNeurals admin*, *You're an admin · Your shops*
where a shop's menu has its switcher, then *Shops* and *AI use and cost*, and *Sign out*. An admin finds it from a link on *Your shops*; nobody else is shown the link. **The address is
not the lock**: the API checks every admin request (§4), and the dashboard only hides what the API refuses, as for
shop roles.

### 4. Who is an admin, and how they sign in (R22, the owner: A)

- **The admin list is a table** (`platform_admins`: a person, when added, when removed; no `tenant_id`, like
  `users`), changed **only by command**: `make admin-add EMAIL=…`, `make admin-remove EMAIL=…`, `make admin-list`.
  No route writes it, so no admin can make another admin from the dashboard *(Claude)*.
- **Sign-in is the email link everyone uses**, and **an admin request needs a sign-in from the last 12 hours**: the
  cookie already records when it was issued, so nothing about it changes. An older sign-in gets **401
  `ADMIN_SIGN_IN_AGAIN`** and the dashboard asks the admin to sign in again; their shop screens keep the usual 30
  days.
- **Someone not on the list gets 404 *No such page*** on every admin route, whatever they send: an admin route
  reveals nothing to a stranger, as a shop route reveals nothing about a shop *(Claude)*.
- The list is read on every request, so a removed admin stops on their next click.
- **A second step, a 6-digit code from an authenticator app, is a MUST before NEURA goes online** (R22): an admin
  reaches every shop's facts and approves shops, so a stolen admin inbox must not be enough. Not designed here.

### 5. Being an admin is not a shop role (R23 1, *Claude*)

The admin flag grants **nothing** on a shop's own routes: `acting_for` is unchanged, so an admin who is not a member
of a shop still gets 404 on its Conversations, Review, Shop connection and every other shop screen. The admin pages
are separate routes (`/v1/admin/…`), with their own check.

### 6. The database keeps §1 true, not only the code (R23 2, *Claude*)

A shop's own session sees one shop (ADR-0008), so reading across shops needs the one pattern this project allows,
from ADR-0022: **`SECURITY DEFINER` functions owned by a `NOLOGIN` role that holds column grants on exactly the facts
of §1**, and no grant at all on any table that holds a conversation, a message, a shopper or a catalogue.

- Two functions: one answers **every shop's facts**, one answers **AI use per shop, day and assistant** for a period.
  They return those columns and nothing else.
- **They answer only a transaction opened for a live admin**: each checks that the person the transaction names is
  on `platform_admins` and not removed, and returns nothing otherwise. A bug that called one from a shop route would
  get an empty answer, not every shop *(Claude)*.
- A test reads the role's grants from the database and fails if it can read any table outside §1.
- **Approve and refuse** write one shop, in that shop's own session, after the admin check, exactly as the commands
  do (ADR-0060 §4); refusing removes a waiting shop the way `make tenant-drop` does, without the API naming an
  agent (the build fixes how).

### 7. Approve and refuse (R23 3 and 4)

- **Approve** shows the shop's name, website, Owner and sign-up date, and asks which assistants: **CARE ticked,
  SELL optional** (R14). The shop keeps practice mode and the daily spending limit.
- **Refuse** asks first: *"Refuse [shop]? It is removed, and [email] gets an email. This can't be undone."*
- Both send **the same emails as the commands** (R17), and both are written in **the shop's record with the admin
  who did it** (`config.change`, `shop.approved` / `shop.refused`, the admin's user id as the actor).
- Approving or refusing a shop that is no longer waiting (another admin, or a command, was first) is refused with a
  plain sentence, and nothing changes *(Claude)*.

### 8. The three screens (R23 8), mockups first

1. **Shops**: every shop, waiting shops first, each with its state, assistants, connected or not, chats and AI cost
   for the last 7 days, and when it signed up. On a phone, one card per shop.
2. **A waiting shop**: its facts, **Approve** with the assistants, **Refuse** with its question.
3. **AI use and cost**: today, 7 days or 30 days; the total, per shop and per assistant, with the Usage screen's
   rules for money (a cost shown is a cost recorded; a model with no price records nothing, and the screen says so).

The words and layout are fixed by the approved mockups, written into console.md before the build.

### 9. The commands keep working (R23 7)

`make tenant-waiting`, `make tenant-approve` and `make tenant-refuse` stay, as a backup and for a computer without
a browser.

### 10. Tests

**Written first, failing on the old code:** every admin route answers 404 to a person not on the list and 401
`ADMIN_SIGN_IN_AGAIN` to an admin signed in more than 12 hours ago; a test fails for an admin route that forgets the
admin check; an admin who is not a member of a shop gets 404 on every shop route; the two functions return nothing
to a transaction that names no admin, or a removed one; the functions' role can read no table outside §1;
approve and refuse work once, send their emails and write the admin as the actor; a shop no longer waiting cannot be
approved or refused; `make admin-add` and `make admin-remove` change the list and nothing else. **In headless
Chrome:** the three screens on desktop and phone, and a non-admin sees no *Admin* link and *No such page* at
`/admin`. **No AI run:** nothing here reaches a model.

## Consequences

- **FiveNeurals approves a shop with two clicks**, and sees every shop and the AI spend without a database query.
- **A second cross-shop function pair and a second `NOLOGIN` role** join ADR-0022's and ADR-0060's. Each answers
  less than the data it reads.
- **console.md §1.1 changes:** the dashboard now has an area for us, and it shows shop facts only.
- **Before NEURA goes online: the admin second step** (R22), and the online email service (K1), because the admin
  signs in by email too.
- **A removed admin keeps any page already open**, until the next click, as a removed shop member does.

## Not decided here

The data agreement, secret keys and removing a shop in the dashboard (AD3 to AD5); the second step's design; adding
or removing admins from the dashboard; admin roles (all admins are equal); FiveNeurals seeing a chat with the shop
owner's permission; billing.
