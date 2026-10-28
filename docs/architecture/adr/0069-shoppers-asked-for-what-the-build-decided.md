# ADR-0069 · Shoppers Asked For: What The Build Decided

**Status:** **Accepted** · built 2026-10-28, in four pieces (`3803367` data, `fe217fa` night check, `3a606ea` route,
`a42b67d` screens) · Everything here is Claude's, decided while building
[ADR-0068](0068-grow-shows-what-shoppers-asked-for-that-the-shop-does-not-sell.md) inside what the owner decided
(R59 to R63), the AI's new words (R64), the switch's words (R65) and the approved mockup (canvas row 19), **except
where an owner's decision is named** · **Date:** 2026-10-28 · **Related:**
[ADR-0066](0066-missing-from-your-pages-what-the-build-decided.md) (the pattern followed),
[ADR-0065](0065-fiveneurals-may-switch-off-one-feature-for-one-shop.md) (the switch), [grow.md](../../agents/grow.md),
console.md §3.12, FEATURES.md L6

> **In one sentence:** ADR-0068 is built on *Missing from your pages*' own pattern, with one night call that now
> answers *gap*, *wanted* or *none*, two tables in the shared core, an Owner-only route and one page; this records
> the choices the ADR left to the build, and what was and was not tested.

## Decision

### 1. One answer field, so one reply is never both (R64)

The model's answer is `found: gap | wanted | none` with `topic` and `question` (`Finding`; it was `gap: bool` and
`fact`). A gap and a wanted thing cannot both come from one reply because the answer has one field, not because a
check looks for it. The words are the ones the owner approved (R64), **A**: the right kind of product in a size or
price the shop does not have is *not* wanted.

### 2. The same code checks, and no product

`clean` runs exactly the gap's checks on a wanted label and question (plain words, length, no link, email, long
number or command word, nothing the injection guard matches). A wanted thing never keeps a product id, even one the
model names: the shop does not sell it. The model is shown the labels already found in 30 days
(`WantedRepository.labels_since`), so *matcha powder* is counted with *matcha*.

### 3. The word check sends *don't carry*, *don't sell*, *don't stock*, *no products matching*

ADR-0068 §6 named three; *don't stock* was added because it is the same sentence. SELL's own *"I can't find anything
matching"* already passed. A wrong *yes* costs one call.

### 4. Two tables beside `page_gaps`

`wanted_items` (one row per reply, keyed by its message id, so a reply met twice counts once) and `wanted_hides` (by
label, with who and when). Migration `8e2a4c6f1d57`, row-level security on both, deleted with the chat by
`ConversationRepository.delete_older_than`, and listed in shop removal (G76). The night check's cursor
(`page_gap_scans`) is shared: one pass, one call per reply, both kinds stored.

### 5. The permission, and the filter behind *See the chats*

`shop:wanted:read`, the Owner's alone (R61), named in ADR-0068 §4; it also covers *Hide*. **Conversations'
`?wanted=` is refused to any role without it**, because Support reads every chat and could otherwise rebuild the
Owner's page through the filter. (*Missing from your pages*' `?gap=` needs no such check: Support may open that page.)

### 6. One switch, two pages

The manifest's `pauses` became a tuple per switch: `grow.gaps` pauses `page_gaps` and `wanted_items`, read by the
same `paused(…, page)`. The switch was renamed on the Admin page by the owner (R65): *The night AI check*.

### 7. What the page shows beyond the boards

As *Missing from your pages* says it: the *Paused* note (*"…the check that finds these things…"*), the line above
Conversations' filtered list (*"The chats where shoppers asked for "Matcha"…"*), and the *not part of this shop's
plan* note. The label is shown with a capital first letter (*Matcha*), as on board 67, as plain text. The menu icon is
Lucide's bag with a plus drawn as on the board, since Lucide has none. The empty box matches the first GROW page's,
not board 69's centring.

## What was tested, and what was not

- **Tested:** the grouping, the 2-shopper rule, the 30 days, *Hide* and its return, isolation, deletion with the chat
  (`test_wanted_postgres.py`, 11); the three answers and the checks (`test_grow_finding.py`, `test_grow_eval_target.py`);
  the night pass storing wanted rows (`test_grow_scan_postgres.py`); the route, Owner only, *See the chats*, *Paused*,
  Home (`test_console_wanted.py`, 8); the whole integration suite (686 passed). **The Gemini eval (cloud-prod):
  25 of 25 cases, injection resistance 1.00**, 22 calls; 8 new *wanted* cases and `gaps_006` changed. **In headless
  Chrome** (`make console-check`): the page, the menu, Home's line, *See the chats*, *Hide*, *Paused*, desktop and
  phone, and the Admin switch's new words; 273 checks, 0 failed.
- **Not tested:** a real shop's chats with the new words (Ceylon Harvester's next night check is the first); the cost
  of the slightly longer answer; Support and the Developer opening the page's address in a browser (the API's 403 is
  tested). Every eval case is synthetic.

## Consequences

- No extra AI call per reply; the answer is a little longer.
- The console has a third GROW screen, further over console.md §2's limit.
- Text derived from shoppers' words reaches the owner's page, behind the same code checks and the 2-shopper rule.
