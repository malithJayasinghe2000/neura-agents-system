# ADR-0067 · An Admin Signs In With A Code From Their Phone

**Status:** **Accepted** (the owner approved the ADR and canvas row 18, 2026-10-28, R57) · **built 2026-10-28** (console.md §3.9, *The code from the admin's phone*; the QR code by `segno`; the reset is logged, not in a shop's record, because an admin belongs to no shop) · owner decisions R22 (2026-10-11: a second step is a MUST before going online), R55 and
R56 (2026-10-27) ([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, *AD8*) · Everything marked *(Claude)* was Claude's proposal, accepted with R57 · **Date:** 2026-10-27 ·
**Amends:** [ADR-0061](0061-fiveneurals-has-an-admin-dashboard-that-sees-shop-facts-never-shoppers.md) §4 (*"Not
designed here"*: the second step) · **Answers:** AD8

> **In one sentence:** after the email link, a FiveNeurals admin types a 6-digit code from an authenticator app on
> their phone before any admin page opens, at every admin sign-in; a lost phone is cleared by another admin with one
> command.

## Context

An admin sees every shop's facts and approves shops (ADR-0061). Today the only lock is the email link and a sign-in
from the last 12 hours, so **a stolen admin inbox is a stolen admin**. R22 made a second step a MUST before NEURA goes
online. Shop pages are not part of this: a shop's own people keep the email link alone.

## Decision

### 1. A code from an authenticator app (R22)

The standard one (*TOTP*, RFC 6238): 6 digits, a new one every 30 seconds, from any authenticator app (Google
Authenticator, Microsoft Authenticator, 1Password and the like). No SMS: a phone number can be moved to another SIM.

### 2. Asked at every admin sign-in (R56: A)

After the email link, the first admin page asks for the code. **Once typed, it holds for that sign-in**, which admin
pages already limit to 12 hours. A new sign-in asks again. A shop's pages never ask.

### 3. A lost phone: another admin clears it with one command (R55: A)

`make admin-reset-code EMAIL=…` clears the admin's code; at their next admin page they set up a new phone. No backup
codes. Like adding an admin (ADR-0061 §4), it is a command, never a button.

### 4. Setting it up *(Claude)*

- **An admin with no code yet sees only the setup page** at `/admin`: a QR code to scan, the same key as text for an
  app that cannot scan, and a box for the first code. **Nothing else of the admin area opens until a correct code is
  typed**, so every admin has the second step from their next sign-in after this ships.
- The key is shown **only on that page, and only until setup is finished** (as built, G116: the same key each time the page opens, so a page opened twice at once cannot show one key and store another). It is stored **encrypted**, as a shop's credentials are (`neura_core`'s
  envelope encryption), and no route ever returns it again.

### 5. How it is checked *(Claude)*

- **By the API, on every admin route**, as the 12-hour rule is (ADR-0061 §4): the dashboard only shows the pages. An
  admin route without the code answers **401 `ADMIN_CODE_NEEDED`** (or `ADMIN_CODE_SETUP` before setup), and the
  dashboard shows the code page.
- **The sign-in records that the code was typed**: the session cookie is issued again with the time of the code, so
  a new email sign-in starts without it.
- **A code works once**, and a code from the 30 seconds before or after is accepted (phone clocks drift).
- **5 wrong codes in a row stop that admin for 15 minutes**, with a plain sentence; each wrong code and each
  success is logged, never the code itself.
- Written with the standard library (HMAC-SHA1, as the RFC), checked against the RFC's own test values; the QR code is
  drawn by a small library without other dependencies *(the build names it)*.

## Tests

**Written first, failing on the old code:** an admin route answers 401 `ADMIN_CODE_SETUP` to an admin with no code and
`ADMIN_CODE_NEEDED` to one who has not typed it in this sign-in; setup works with a correct first code and refuses a
wrong one; a correct code opens every admin route until the sign-in ends; a used code is refused the second time; 5
wrong codes stop the admin for 15 minutes; the reset command clears the code and nothing else; the key is never
returned after setup; the TOTP matches RFC 6238's test values; shop routes never ask. **In headless Chrome:** the
setup page and the code page, desktop and phone. **No AI run:** nothing here reaches a model.

## Consequences

- **A stolen admin inbox is no longer enough.** AD8 is done when this is built.
- **Every admin needs an authenticator app**, and sets it up at their next admin sign-in.
- **A lost phone needs a second admin** (or someone with the server) to run one command. With one admin and no server
  access, nobody could get in: FiveNeurals should keep **at least two admins**.

## Not decided here

Passkeys or security keys; a second step for shop people; remembering a computer (R56 chose not to).
