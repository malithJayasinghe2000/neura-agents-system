# ADR-0066 · Missing From Your Pages: What The Build Decided

**Status:** **Accepted** · built 2026-10-25 to 2026-10-27, in five pieces (`7f372f9` 1a, `f97662a` 1b, `bb01d0d` 1c,
`59e97e2` 2, `d6b5824` 3) · Everything here is Claude's, decided while building
[ADR-0064](0064-grow-shows-what-shoppers-asked-that-the-shop-s-pages-do-not-say.md) inside what the owner decided
(R36 to R47, R48) and the approved mockup (canvas row 16), **except where an owner's decision is named** · **Date:**
2026-10-27 · **Related:** [ADR-0065](0065-fiveneurals-may-switch-off-one-feature-for-one-shop.md) (the switch),
[grow.md](../../agents/grow.md), console.md §3.11 *As built*, FEATURES.md L6

> **In one sentence:** ADR-0064 is built as an agent with no chat, a night job that reads replies through a free word
> check before a model, three tables in the shared core, a console route with its own permission, and one page; this
> records the choices the ADR left to the build, and what was and was not tested.

## Decision

### 1. GROW is the first assistant with no chat

Its manifest says **`chat = False`**: the API mounts no chat routes for it, the dispatcher never offers it a
shopper's message, and it has no runner, no tool, no shopper scope and no capability. Its only work is a job.

### 2. Sold out's pattern, not Suggestions'

The page's data route is **the console's own** (`neura-api`, `console_gaps.py`), with its own permission
**`shop:gaps:write`** (read the page and *I added it*; Owner and Support, ADR-0064 §5). The tables live in the shared
core (`neura_agent_core/gaps.py`) and only GROW's job writes them, so `neura-api` never names an agent and a shop
without GROW has no rows. The menu lists the page only for a shop with GROW (display only; the route needs no
entitlement because the data is the gate).

### 3. Three tables, not two

ADR-0064 §8 named `page_gaps` and `page_gap_fixes`. A third, **`page_gap_scans`**, records how far the night job has
read each shop's chats, so a pass reads only new replies and a provider outage resumes where it stopped. All three
have row-level security, go with their conversation (a gap is derived from a shopper's words) and with a removed
shop.

### 4. A manifest says what the API must do for it, without the API naming it

Three new manifest fields, each read by `neura-api` as data:

- **`daily_job`**: a job kind booked once a day for a shop with the agent, first at the shop's first chat
  (`neura_api/jobs/daily.py`); the job books itself again.
- **`switches`** (ADR-0065): the features FiveNeurals may switch off, with the words the admin reads.
- **`pauses`**: which of the console's own pages a switch pauses (`grow.gaps` pauses `page_gaps`), so the page can
  say *Paused* without naming GROW.

### 5. The night check

- **One model call per reply that reaches it, the smallest model role**, never while a shopper waits, inside the
  shop's daily hard budget (ADR-0015), metered to the shop with no turn.
- **The owner's R47 (A): a free word check first.** Only a handover, a reply that sounds unsure (*can't confirm*,
  *don't have*, *not sure*, *someone at our store*, ...) or a reply not mostly in English reaches the model; each side
  of the exchange is cut to 600 characters. The words are the ones CARE's own instructions tell it to use. Attacks
  (`blocked`) and off-topic replies are skipped too.
- **The products a reply looked at are its `product:` citations**; the model is shown the topics already stored for
  them, so the same question is counted together.
- **Code checks every answer before it is stored** (ADR-0064 §7): a label of 1 to 4 plain lowercase words, a
  question of at most 10 words ending in `?`, no link, email, 7 or more digits, command word or anything the
  injection guard matches, and a product only from the turn's own list. A refused answer stores nothing.
- **The instructions** (`prompts/find_gap.md`) were approved by the owner in plain words (R48).

### 6. What the page shows (ADR-0064 §2 and §4 as amended by R43 and R44)

The shoppers' question and where to add the answer, never a blank and never an answer; **Open the page** only for an
http or https address from the synced catalogue; grouped by product, most asked first, *About your shop* last.
**See the chats** is Conversations' `?gap=&gap_product=`, which lists exactly the chats a row counts (after *I added
it*, only the later ones). *I added it* refuses a question never asked. Home's *Needs you* shows the page's own count.

## What was tested, and what was not

- **Tested:** unit and database tests for each piece (written first, failing on the old code, except piece 1c's scan
  and job tests, written right after their code); the Gemini eval `gaps.yaml`, **17 of 17, injection resistance
  1.00, 14 model calls**, all cases synthetic (2026-10-25); `make console-check`, the page on desktop and phone in its
  own test shop (2026-10-27).
- **Not tested:** any real shopper's chat; the share of real replies the word check keeps, and so the cost per shop;
  a half answer worded unusually (missed by design of R47); Sinhala and Singlish beyond a few made-up lines; the local
  models. FEATURES.md says so as **L6**.

## Consequences

- **GROW exists and costs nothing until a shop has it.** FiveNeurals ticks it per shop (R46) and can pause its night
  check per shop (ADR-0065).
- **A new kind of text derived from shoppers' words reaches the owner's page**, made safe by code checks and the
  2-shopper threshold, not by the prompt (Rule 3).
- **The console is one more screen over its documented limit** (console.md §2).
