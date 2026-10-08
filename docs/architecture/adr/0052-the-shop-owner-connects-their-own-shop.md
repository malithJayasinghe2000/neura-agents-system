# ADR-0052 · The Shop Owner Connects Their Own Shop: NEURA Makes The Token And Runs The Check

**Status:** **Accepted** · owner decision, 2026-10-01 (mockup approved: the design canvas, row 10, boards 31-35; the ADR approved the same day with two additions: §4 the check runs in the background, §8 token events go to the audit log) ·
**Built:** 2026-10-01, the same day (what building decided: [console.md §3.4](../../console.md), *Connect your shop*) · **Date:** 2026-10-01 · **Amends:** [console.md §3.4](../../console.md) (*"the connect form is not built"* and *"the
console never displays a stored credential"*) and the console's write surface set by
[ADR-0026](0026-the-merchant-console-and-the-first-human-in-the-system.md) · **Related:**
[ADR-0009](0009-generic-commerce-interface.md), [ADR-0010](0010-read-only-mvp-tools.md),
[ADR-0051](0051-the-public-website-is-its-own-app-and-says-only-what-the-code-does.md),
[CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md) (G3, G10, G17, G18, G19, G23, G46, G47, G48, G49;
ideas D2 and D5)

> **In one sentence:** the shop owner connects their own shop in the dashboard. NEURA makes the shop
> token and shows it once, the owner types the bridge's address, NEURA runs the full check from its own
> server, and the owner presses Connect. NEURA only ever calls public web addresses.

## Context

Connecting a shop has only ever been done by FiveNeurals, in a terminal. Doing it from zero for a new
shop on 2026-09-30 (Ceylon Harvester) showed what that costs:

| Today | Found |
|:--|:--|
| There is no command that makes a shop token; FiveNeurals invents one by hand | G3 |
| Saving the connection needs a powerful one-off key, which the runbook never says to remove | G19 |
| Both secrets are typed on a command line, where the shell keeps them | G23 |
| The check tool exists only inside our code; an outside developer cannot get it | G10 |
| The check's last line points at a file the developer does not have | G17 |
| A green check means the format is right, not the answers; a bridge with nothing built passes | G18, G46 |
| One wrong token shows as 8 failures, most with the wrong advice | G48 |

[console.md §3.4](../../console.md) left the connect form out **on purpose**: *"a browser form that
submits a store credential would be the highest-value target in the application."* That reasoning was
right while nobody but FiveNeurals connected shops. It does not survive the first real merchant: every
connection needs a person at FiveNeurals and a terminal, and the terminal path is the less safe one.

The owner decided on 2026-10-01 to move connecting into the dashboard (ideas **D2**, the check, and
**D5**, the token), and approved the mockup the same day.

## Decision

### 1. NEURA makes the shop token, and shows it once

- The owner presses **Make the token**. NEURA makes a long random secret (from the operating system's
  secure random source) and shows it **once**, with a Copy button and how to send it safely: a password
  manager or a one-time link, never a plain email or chat.
- From that moment it is stored **encrypted**, exactly as a connection's token is today (envelope
  encryption, [security-model.md §5](../security-model.md)). **It is never shown again, not even to the
  owner.** This is the one exception to *"the console never displays a stored credential"*: the moment it
  is made, before it has been stored anywhere a screen could read it back.
- **The browser never sends a token.** NEURA made it, so NEURA already holds it. The form only sends the
  address. That removes the attack console.md §3.4 was worried about: there is no credential field to
  fill in, to phish or to log.
- Who made it and when is recorded in the audit log (§8).

### 2. A new token stops NEURA using the old one; only the developer can stop the shop accepting it

**Make a new token** replaces the stored one. NEURA stops sending the old token at once. **The shop's
bridge still accepts the old one** until the developer puts the new one in its settings, because the
bridge, not NEURA, checks the token (G49). Until then, whoever holds the leaked token can still read the
shop, and the assistant cannot.

The screen says exactly that: *"Tell your developer at once. Your shop still accepts the old token
until they put the new one in."* It must never say the old one *"stops working"*.

### 3. NEURA calls only public web addresses (G47)

Once an owner can type an address, NEURA's server calls whatever is typed. Without a rule, anyone with a
dashboard account could make our server call **our own internal addresses** and read the answers
(known as server-side request forgery).

- **In production:** the address must be `https://`, and its host must resolve only to public internet
  addresses: never loopback, private, link-local, shared, multicast or reserved ranges (for example
  `localhost`, `10.x`, `192.168.x`, `169.254.169.254`).
- Checked **before every call** NEURA makes to a typed address: the check, and Connect. Not only once when
  it is typed: a name can be pointed somewhere else later.
- **Outside production** (`NEURA_ENV` is not `production`), private addresses and `http://` are allowed,
  because our test shops run on the developer's own machine. Production refuses them; there is no setting
  that turns the rule off in production.
- **The same rule applies to `POST /v1/stores`**, the API door FiveNeurals uses today. Two doors, one
  rule.
- **Known limit, stated now:** checking a name and then connecting to it resolves the name twice, so a
  name that changes its answer in between (DNS rebinding) could still slip through. The build closes this
  if it can do so simply (connect to the address that was checked); if it cannot, it is written down as
  open, not hidden.

### 4. The check is the check tool, run by NEURA's server

- The dashboard runs **the same check** a developer would run (`check_store`, both suites): one
  implementation, as console.md §3.4 already required. It only reads (every address is a `GET`), so
  nothing in the shop changes.
- It runs **only when pressed**, never on a page load or a schedule, and **one at a time per shop**.
- **It runs in the background**, on the job queue *Sync now* already uses, never inside the page's own
  request. The check asks the shop about 20 questions and each may wait up to 10 seconds, so a slow shop
  would otherwise hold one of our servers for minutes; with many shops, everyone would wait. The page
  shows *Checking…* and asks **our own** server every few seconds whether the result is ready, as *Sync
  now* does. Running it in the background adds **no** calls to the shop.
- **The owner sees plain words:** a few lines instead of 19 check names. **When the shop refused the
  token, that is said first and alone** (G48): *"Your shop refused the token"*, with what to do.
- **The developer gets the full technical result** with *Copy the full check for your developer*,
  without the line that points at our private file (G17).
- **It says what it cannot see** (G18, G46): *"The check proves the format, not the facts."*
- After connecting, **Check again** runs the same full check, replacing today's *Check now*, which only
  asked `/health`.

### 5. Connect only after a clean check

**Connect and copy my catalogue** is allowed only after a check with **no failures**, on the same
address. It saves the connection (the address and the token NEURA made) and queues the full copy of the
catalogue that *Sync now* already runs. The developer guide's step order follows: check, then connect.

### 6. Who

The shop's **owner**, the only role there is, protected like every other dashboard action (the session
cookie, and the shop taken from the membership, never from the request). **A developer has no dashboard
account** ([D3](../../CONNECTING_A_NEW_SHOP_LOG.md), roles need their own ADR); they get the token and the
full check from the owner.

### 7. What does not change

- NEURA still only reads the shop ([ADR-0010](0010-read-only-mvp-tools.md)).
- FiveNeurals may still connect a shop through `POST /v1/stores`, now with the address rule (§3).
- The dashboard still never shows a stored token, other than the moment it is made (§1).
- What the check proves is unchanged: the format, not the facts.

### 8. Token events go to the audit log

Making a token, replacing it, and connecting a shop each write an **audit event**: which shop, who, when.
**Never the token itself**, nor any part of it. This is the standard record for a secret: when something
goes wrong, it says who did what. (Today the audit log records only blocked messages, S11; these are the
first events a person causes.)

## Consequences

- **A shop can be connected without FiveNeurals at the keyboard**, and without a powerful one-off key
  (G19) or a secret on a command line (G23).
- **The dashboard gains its highest-value action.** That is why the token is made by NEURA rather than
  typed (§1), why addresses are restricted (§3), and why the check is pressed, not automatic (§4).
- **Each check sends about 20 requests to the typed address.** One at a time per shop keeps that from
  becoming a tool for flooding someone else's server.
- **Docs to change when it is built:** console.md §3.4; the dashboard's Help (*FiveNeurals connects
  it* is no longer true); the developer guide's steps 3 and 4; the internal runbook
  ([CONNECTING_THE_SHOP.md](../../CONNECTING_THE_SHOP.md)); [FEATURES.md](../../FEATURES.md).

## Not decided here

- **A one-time link** for sending the token to the developer. Advice only for now (a password manager).
- **A developer account** (D3).
- **Whether a new shop should start in practice mode** (G22). It still starts live.
- **The other dashboard ideas** (D1, D4, D6, D7): each gets its own mockup.
