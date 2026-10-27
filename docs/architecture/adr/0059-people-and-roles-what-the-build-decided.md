# ADR-0059 · People And Roles: What The Build Decided

**Status:** **Accepted** · owner decisions 2026-10-10 (R12, R13), and the permission names ADR-0058 left to the
build · **built 2026-10-10** (pieces 1 and 2 of ADR-0058's build) · **Date:** 2026-10-10 · **Implements:**
[ADR-0058](0058-a-shops-dashboard-has-people-with-roles-and-a-shop-signs-up.md) §1 to §6 · **Amends:** ADR-0058 §4
(*"clicking it signs the person in"*), for an account that already exists ·
**Related:** [CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md) G88, G89, G92, G93, *Decisions*
*Roles (R12)* and *Roles (R13)*

> **In one sentence:** building ADR-0058 met three questions it did not answer (what the permissions are called,
> what Home shows to Support and the Developer, and whether an invite link may sign in someone who already uses
> NEURA); the owner decided the second and the third, the ADR had left the first to the build, and this records
> all three with the smaller defaults the build chose.

## Context

ADR-0058 is accepted and its mockups approved (console.md §3.8). Three things in it were open or did not hold once
the code was written:

| # | Question | Found as |
|:--|:--|:--|
| 1 | The draft permission names put `care:` and `sell:` on screens `neura-api` serves, which AGENTS.md forbids (*neura-api may not learn an agent's name*). The ADR marked them *fixed in the build*. | G88 |
| 2 | Home is *every member's*, but nearly all of Home reads Usage, which only the Owner may open. | G92 |
| 3 | §4: *"clicking it signs the person in"*. A session opens every shop a person is in, so for someone who already uses NEURA an invite link would be a **7-day sign-in to their other shops**, for whoever the email reached. A sign-in link works 15 minutes. | G93 |

## Decision

### 1. The permission names (G88, left to the build)

A screen the console serves names no agent; a screen an agent serves names its agent. Every name has three parts,
`<area>:<thing>:<read|write>`.

| Permission | Opens | Owner | Support | Developer |
|:--|:--|:--|:--|:--|
| `shop:home:read` | Home's own facts (§2 below) | ✅ | ✅ | ✅ |
| `shop:conversations:read` | Conversations (CARE's and SELL's) | ✅ | ✅ | ❌ |
| `shop:review:write` | Review: read and grade | ✅ | ✅ | ❌ |
| `sell:suggestions:write` | Suggestions (declared by SELL, on SELL's routes) | ✅ | ❌ | ❌ |
| `shop:sold_out:read` | Sold out | ✅ | ❌ | ❌ |
| `shop:connection:write` | Shop connection: read, Check, Sync now, the shop token, the sign-in secret | ✅ | ❌ | ✅ |
| `shop:connect:write` | Shop connection: Connect | ✅ | ❌ | ✅ |
| `shop:contact:write` | Shop connection: the contact details | ✅ | ❌ | ✅ |
| `shop:mode:write` | *Go live* and back to practice | ✅ | ❌ | ❌ |
| `usage:cost:read` | Usage and cost | ✅ | ❌ | ❌ |
| `people:members:write` | People: the list, invites, roles, removal | ✅ | ❌ | ❌ |

Who may open what is ADR-0058 §2's table unchanged; only the names differ from its draft. The Owner holds every
permission, also one an agent brings later.

### 2. Home for Support and the Developer (R12, the owner: A)

Each sees on Home only the parts about their own work:

- **Support:** whether practice mode is on, as a sentence with no button; replies waiting for review; chats handed
  to a person.
- **Developer:** the same mode sentence (they test against it, G86); *your shop isn't connected yet* when true; the
  Catalogue card.
- **Neither** sees the 7-day numbers, money or *Go live*.

So that Home asks for nothing a role may not have, one route gives the two facts that otherwise live on Usage:
`GET /console/shops/{tenant}/home` (`shop:home:read`, every role) answers the **mode** to every member and **how
many chats were handed to a person in the last 7 days** only to a role that may read chats, `null` to any other.
The owner's words: *"later I think we can add feature for them"* (the log's D12).

### 3. An invite link signs in only a new account (R13, the owner: A; amends ADR-0058 §4)

- **A brand-new person** (the email had no account): the link makes the account, adds the shop and signs them in,
  as §4 said.
- **Someone who already has an account:** the link **adds the shop and does not sign them in**. They sign in as
  usual, with the 15-minute email link. The owner's example: Amali works in Shop X; Shop Y's invite, if forwarded,
  must not open Shop X.
- **Someone already signed in as that very person** goes straight in. For an existing account, a browser signed in
  as **somebody else** is left signed in as that person: no cookie is written over theirs. (A new account is signed
  in wherever its link is opened: the link is its only way in.)

### 4. Smaller defaults the build chose (Claude, following the approved design)

| Default | Why |
|:--|:--|
| A person who never gave a name is shown by their email (invites ask only for an email), on People and in *Made … by …* | The screen names someone real rather than inventing a name |
| A second invite to the same email replaces the waiting one: new role, new link, the old link stops | One open invite per email per shop; the Owner typing it again means *send it now* |
| An invite that ran out stays on People as *"The link ended on [date]"*, with Send again and Cancel | The Owner sees it ran out instead of it vanishing |
| Accepting an invite never changes the role of someone already in the shop | Only an Owner changes a role, under the Owner rule |
| The Owner's own row has no Remove; another Owner can remove them | Board 38 drew the own row without Remove; leaving a shop is not designed |
| The link names its shop (`/auth/invite?shop=…&token=…`), and the token is looked up in that shop's own session | The invites table stays tenant-scoped and forced; a link with another shop in it finds nothing |
| Audit entries (`people.change`) hold ids and roles, **never an email** | The audit log is append-only and kept |
| `make invite-link` makes a new link for a waiting invite (as *Send again*), prints it, and records it as done by `console_admin` | Until the online email service (K1) exists |
| When the invite email could not be sent, People says so: *"The invite for [email] is ready, but the email could not be sent. Try Send again in a moment."* | The Owner is signed in and learns nothing about anyone else from it |

## Consequences

- **Every dashboard route states its permission on the route**, checked before the request's body is read (G89),
  and a test fails for a route that forgets (`tests/unit/test_console_roles.py`).
- **The dashboard keeps no copy of the map:** `/me` gives each membership its `permissions`, worked out by the API
  from what the routes declare.
- **An existing account needs two emails to join a new shop** (the invite, then a sign-in link). That is the cost
  of §3, accepted.
- **ADR-0058 §4's sentence is now true only for a new account.** Read it together with §3 above.

## Not decided here

Everything ADR-0058 lists, and: names for invited people (asking for one when they join), leaving a shop by
yourself, and a rate limit on invites.
