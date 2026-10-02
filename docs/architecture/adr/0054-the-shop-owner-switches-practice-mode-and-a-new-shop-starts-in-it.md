# ADR-0054 · The Shop Owner Switches Practice Mode, And A New Shop Starts In It

**Status:** **Accepted** · owner decisions, 2026-10-02: G22 chosen as the first of the most important fixes, then
*B, a button in the dashboard*, then three answers (Q1 *any time, after a confirm that shows the facts*; Q2 *new
shops start in practice mode*; Q3 *on Home*), then *"no need to do mockup, it is just a button, you can directly
build that"* ([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, G22 and D11 Q1 to
Q3). §5 and §6 are Claude's additions, the same kind ADR-0052 §8 made, reported to the owner with the build ·
**Date:** 2026-10-02 · **Amends:** the console's write surface ([ADR-0026](0026-the-merchant-console-and-the-first-human-in-the-system.md),
as [ADR-0052](0052-the-shop-owner-connects-their-own-shop.md) did) · **Related:**
[agent-runtime.md §6](../agent-runtime.md) (the modes), [ADR-0020](0020-a-withheld-turn-says-so.md) (what a shopper
sees in practice mode), the log's G22 and G72, idea D11

> **In one sentence:** the shop owner presses **Go live** on Home to let shoppers read the assistant's
> replies, and **Back to practice mode** to stop; a shop FiveNeurals creates starts in practice mode; and
> a switch reaches a chat that is already open.

## Context

Practice mode (the code's `shadow`) was built in milestone 1.15: the assistant writes every reply, the
shopper reads a short *received* note instead (ADR-0020), and the reply waits in Review. **Nothing switches
it** (G22): no screen, no command, no API. A new shop starts **live** (`TenantConfig.mode` defaults to
`live`), so its first shopper gets an answer nobody has checked, while Help and Review tell the owner to
*"decide when to go live"*. The one shop put in practice mode for the connection test was switched by a
one-off script.

Designing the switch found **G72**: the chat box's live connection reads the shop's mode once, when it opens,
and keeps it for as long as the shopper keeps talking (it closes after 5 quiet minutes). A switch the owner
presses would not reach shoppers already chatting.

## Decision

### 1. The switch is on Home (Q3)

In the section at the top of Home that already says *Practice mode is on* or *Your assistant is live*: in
practice, **Go live**; when live, **Back to practice mode**. Shoppers never see it.

### 2. Go live may be pressed at any time, after a confirm that shows the facts (Q1)

Pressing **Go live** opens a confirm in the same section: what going live means (*shoppers see your
assistant's replies as soon as it writes them*), and what Review holds, as counts: how many replies the owner
checked (good, not good, harmful) and how many still wait. **No threshold.** A rule such as *at least 20,
none harmful* would need a number nobody has measured ([CLAUDE.md §4](../../../CLAUDE.md)); the owner decides.

### 3. Back to practice mode is one press

The safe direction: it can only withhold. No confirm, at any time.

### 4. A new shop starts in practice mode (Q2)

`make tenant-new` (`scripts/tenant_admin.py`, the one way a shop is created) writes `mode: shadow` into the new
shop's settings. **`TenantConfig.mode`'s default stays `live`**: it also decides the mode of a shop whose stored
settings never named one, and changing it would switch such a shop off without anyone pressing anything.
Shops that exist today keep their mode.

### 5. What the switch writes (Claude's addition)

- `PUT /v1/console/shops/{tenant_id}/mode`, `{"mode": "live" | "shadow"}`, the code's own words. Behind the
  console session, the shop taken from the membership (`acting_for`), like every console write.
- **Only the `mode` key** of the shop's settings changes. `TenantConfig` drops keys it does not know, on
  purpose (`modes.py`), so reading the whole settings and writing them back could erase a newer deployment's
  setting; the write merges one key instead.
- **Per kind of question practice (`shadow_intents`) is not touched and not shown.** No shop uses it today, and
  practice still wins ties (`resolve_turn_mode`), so a live shop that named one keeps it withheld.
- **An audit entry**, in the same transaction: `config.change`, `mode.live` or `mode.practice`, who, and the
  mode before and after. Pressing the button for the mode the shop is already in changes nothing and records
  nothing.
- **Anyone with a membership may switch**, as with every other console action today (ADR-0026: no roles before a
  merchant asks for them). **When the developer role (D3) is designed, this switch is not for it**: going live
  is the shop owner's decision.

### 6. A switch reaches a chat that is already open (G72; Claude's addition)

The mode is read **when the reply is released**, in the same transaction that writes the turn, not taken from
what the chat's connection read when it opened. *Back to practice mode* withholds the very next reply of a
shopper who is still talking; after *Go live*, their next reply is shown. One read of the shop's own row per
turn, inside a transaction the turn already opens.

## Consequences

- **The console gains a write that changes what shoppers read.** Until now its writes changed our copy, a grade,
  a token or a connection. A member of the shop can now make the assistant answer shoppers; that power is the
  membership's, as ADR-0026 decided, and D3 must not inherit it.
- **The first answer a new shop's shopper gets is the received note, not an AI reply**, until the owner presses
  Go live. Help's step 5 says where the button is.
- **Rule 4:** no model of ours is in the switch. What replaces an eval here ([E8](../../open-questions.md)) is the
  deterministic set: the route's tests (only the mode changes, other settings kept, the audit entry, no change
  for the same mode, a stranger refused, a wrong value refused), G72's test through the real chat socket, and
  `make console-check` pressing the buttons in a real browser.

## Not decided here

- **Per kind of question practice in the dashboard** (`shadow_intents`): agent-runtime.md §6's *live for order
  status, watched for returns*. No shop has asked.
- **History**: *live since*, who switched. The audit log holds it; no screen reads it.
- **The other two modes** of agent-runtime.md §6, `SUGGEST` and `SUPERVISED`.
- **The roles** (D3).
