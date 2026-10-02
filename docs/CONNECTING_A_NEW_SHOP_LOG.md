# Connecting a new shop from zero — the log

> **Purpose.** Connect a shop NEURA has never seen, following **our own published guide word by word**, the way a
> real developer and shop owner would — and write down every place where the guide is wrong, unclear, missing a
> step, or hard to follow. **The findings are the point**: they are what gets fixed in the guide afterwards.
> Started 2026-09-30 by the owner.
>
> **How we work (the owner's rules).** One step at a time: explain it simply, do it, check it against the guide,
> log it. Treat the shop as a **real** shop; if anything is an issue, **stop and discuss it with the owner**. A problem
> goes into *What we found* **before** it is mentioned — never say it is recorded unless it is in this file. At the
> **end of each step**, give the owner that step's issue list straight from this file. Decisions are the owner's
> (*Decisions*); dashboard ideas go in the D list. **Ask before any AI model runs** (a chat message, indexing).
> **Nothing is fixed or built until step 7.** Secrets (the shop token, `fn_sk_` keys) are never printed. The owner
> commits. Plain words, tables, a real-world example for each issue.
>
> **If you are a fresh session picking this up:** read `CLAUDE.md` and `docs/PROJECT_STATE.md` first, then this
> file. Continue from the first step not marked ✅.

## What we check against

The documents people will actually read — **not the canvas mockups**, which are only drawings:

| Who reads it | Document | Where |
|:--|:--|:--|
| The shop's developer | **Guide for developers** on the public website | `apps/neura-web/src/app/docs/developers/page.tsx` — `/docs/developers/` (run `npm run dev` in `apps/neura-web`, port 3100) |
| The shop owner | **Help → Connecting your shop** in the dashboard | `apps/neura-console/src/lib/help.ts`, `.../[tenantId]/help/page.tsx` |
| FiveNeurals (us) | The internal runbook | [`CONNECTING_THE_SHOP.md`](CONNECTING_THE_SHOP.md) |

## The shop

**Ceylon Harvester** — a custom-built shop (not a known platform), cloned by the owner to `~/Developer/ecommerce`.
There is **no ready-made bridge** for it, so the developer has to build one: the real test of the guide.

| | |
|:--|:--|
| Address | http://ecommerce.test (served by Herd: `herd link ecommerce`; `herd unlink ecommerce` undoes it) |
| Database | MySQL on port 3308, `root`, no password, database `ceylon_harvester` |
| Admin login (local only) | `admin@ceylonharvester.test` / `admin12345` |
| Products | **none** — the shop ships empty |

## The steps

| # | Step | Who | Status |
|:--|:--|:--|:--|
| 0 | Set up and run the shop | (not ours — setting up the shop itself) | ✅ 2026-09-30 |
| 1 | Build the bridge — the nine addresses | The developer (Claude, playing the developer, using **only** the public guide and the OpenAPI file) | ✅ 2026-09-30 — built, tested by hand |
| 2 | Say what the shop can do (`/health`) | The developer | ✅ 2026-09-30 |
| 3 | Check the work with the check tool | The developer — **run by Claude as FiveNeurals** (G10: a developer cannot get the tool) | ✅ 2026-09-30 — 19 of 19 passed |
| 4 | Connect the shop (address + shop token) and copy the catalogue | FiveNeurals | ✅ 2026-09-30 — connected, catalogue copied |
| 5 | Chat box key, and the chat box line on the shop | FiveNeurals, then the developer | ✅ 2026-09-30 — key made, line on the shopper pages, the dashboard ticks |
| 6 | Practice mode: ask in the chat box, grade in Review (uses the AI — ask the owner first) | The owner | ✅ 2026-09-30 — six questions, all graded (4 Good · 1 Not good · 1 Harmful); G35–G40 found |
| 7 | Fix the guide with everything below | Claude, with the owner | ⏳ started — code bugs first, G35 first |

### Step 0 — set up and run the shop ✅

`.env` from `.env.example` (`APP_ENV=local`, `APP_URL=http://ecommerce.test`, `DB_PORT=3308`,
`DB_DATABASE=ceylon_harvester`, `MAIL_MAILER=log`) · `composer install` · `php artisan key:generate` · database
created · `php artisan migrate` · seeders run by hand (the default seeder does not call them): `RoleSeeder`,
`SettingsSeeder`, `ConfigurationSeeder`, `PaymentOptionsSeeder` · an admin user with role `admin` ·
`npm install && npm run build` · `php artisan storage:link` · `herd link ecommerce`. The home page renders.
Nothing here is about NEURA — it is the shop's own setup.

**Made-up data added** (the shop ships empty; a real owner would have their own): 2 categories (Spices, Tea), 6
products — one **sold out** (Green Cardamom Pods), one **not for sale yet** (Cinnamon Tea Bags) — one customer
(Nimal Perera) with one **shipped, paid** order. Script: scratch only, not in either repository.

### Step 1 — build the bridge ✅

**Built from the guide and the OpenAPI file only.** Honest caveat: Claude played the developer while knowing NEURA
well, so a real outside developer will find it **harder** than this — treat the findings below as the least there is.

What the developer added to the shop (5 files, about 400 lines, nothing existing changed except one registration line):

| File | What it is |
|:--|:--|
| `config/neura.php` | The bridge's two settings: the shop token, and the currency |
| `app/Http/Middleware/NeuraShopToken.php` | Refuses every request without the right token (except `/health`); refuses everything if no token is set |
| `routes/neura.php` | The nine addresses |
| `app/Http/Controllers/Neura/BridgeController.php` | Reads the shop's data and answers in NEURA's format (the mapping is in the table below) |
| `bootstrap/app.php` | One line: serve the addresses under `/neura/v1`, without the website's sessions |

Tested by hand with `curl`: no token / wrong token → **401**; `/health` open; paging walks every page and ends;
search; *in stock only*; `updated_since`; categories; stock (an unknown id is left out); orders by email, by
`#1`, by a stranger's email (empty); an order's address; a customer; **staff accounts are not customers (404)**;
missing product / order → **404** with an error message; `/policies` → empty list.

**A temporary shop token** is in the shop's `.env` (`NEURA_SHOP_TOKEN=tmp_…`) so the bridge could be tested — the
guide gives the token only at step 4 (G3). It is replaced at step 4.

### Step 2 — say what the shop can do ✅

`/health` (built in step 1) lists **8 of the guide's 10**: `product.read`, `product.search`, `category.read`,
`inventory.read`, `order.read`, `order.search`, `customer.read`, `sync.incremental` — each one built and tested in
step 1. **Left out on purpose:** `policy.read` (the shop has no policies — the owner's G5 decision) and
`events.realtime` (the shop sends no change messages, and NEURA does not use them yet).

### Step 3 — check the work ✅

Run as FiveNeurals would today (G10), with the shop's temporary token:
`uv run neura-conformance --url http://ecommerce.test/neura/v1 --token <token>` → **19 passed · 0 failed · 0
warnings — "Conformant. This store can be connected."**

**What the tool checks:** `/health` (open, JSON, spec version); the token (required, wrong one refused); a missing
product / order / customer → 404; search with nothing and with nonsense; statuses in NEURA's words; paging and its
limit; `updated_since`. **What it does not check** (G18): categories, stock, order search by email / phone /
number, the currency, customers-only, policies when not declared — and whether any answer is **right**.

### Step 4 — connect the shop ⏳

**First, the shop's account in NEURA** — not in the developer guide (the owner guide says *"FiveNeurals creates your
account"*): `make tenant-new NAME="Ceylon Harvester" AGENTS=care,sell` → **`tn_01M3RR45SK09PV28RPR22NH0GH`**;
`make user-new EMAIL=<owner> TENANT=…` → the owner's existing sign-in now holds this shop too. The account starts
**live**, not in practice mode (matters at step 6).

**Then the shop token** — the guide's *"the shop token FiveNeurals gives you"*. **There is no command that makes
one** (G3): FiveNeurals would have to invent a long random secret by hand, and nothing says how it reaches the
developer safely. Stopped here to decide (see *Decisions*) — the owner chose the dashboard (D5); for this test it
was made by hand.

**Then, following the internal runbook (`CONNECTING_THE_SHOP.md` §3, step 2) word by word:**

1. **The shop token**, made by hand (a random `st_…` secret) and put in the shop's `.env` as `NEURA_SHOP_TOKEN`,
   replacing the temporary one — the old one is now refused (**401**).
2. `make key-new TENANT=… SCOPES=stores:write NAME=connect` → a one-off FiveNeurals key, then the runbook's `curl`
   `POST /v1/stores` (`platform: generic`, the bridge's address, the token) → **200**, connection
   `st_01M3RRQX2N2N5JR10XHAWJWBT4`. **The one-off key was then revoked** — the runbook does not say to (G19).
   (`make key-revoke` needs `TENANT=` as well as `KEY=`.)
3. `make sync-check URL=… TOKEN=… TENANT=…` → **6 products, 2 categories, 0 policies** (*"shop does not declare the
   capability for policy; nothing synced"* — as decided). It is a **test tool**: it also deletes a product from our
   copy on purpose and repairs it (G20).

**How you'll know — checked in the dashboard (headless Chrome, the owner's sign-in):** *Your shop is connected* ✓ ·
*Your shop answers* ✓ (after **Check now**) · *Your catalogue is copied* ✓ *6 products* · *Our copy*: 6 products,
2 categories, **0 policy pages** · *What your shop lets the assistant do*: six ✓ lines — **no line says policies are
missing** (D1). And: **"Search by meaning covers 0 of 6 products"** (G21).

### Step 5 — the chat box ✅

As the developer guide says: FiveNeurals makes the **chat box key** for the shop's exact address — a **public**
`fn_pk_` key, by command for now (`CONNECTING_THE_SHOP.md` §3 *Step 4 — The chat box*: `make key-new … PUBLIC=1
ORIGINS=http://ecommerce.test` and its scope list) — and the developer adds the **one `<script>` line** to every page
(the shop's layouts are `resources/views/layouts/*.blade.php`). **How you'll know:** *The chat box is on your shop*
ticks — only **after the chat box is used once**, which is an AI call: ask the owner first. Check the owner guide's
step 4 too: it says FiveNeurals makes the key (the owner making it in the dashboard is a direction, not built).

**Done so far (2026-09-30):**

1. **The chat box key**, made exactly as the runbook says (its 11 scopes, `ORIGINS=http://ecommerce.test`) →
   `key_01M3RS6MM4MV5YR9DD2GKR98FS`, a public key starting **`fn_pk_test_…`** (G30). It is public, so it may be
   written in the shop's pages; it is not repeated here only because nothing needs it here.
2. **Checked the runbook's scope list against the code**: it matches — the chat door asks for `care:chat:write` or
   `sell:chat:write` for whichever assistant it picks; the paired suggestions need `sell:suggest:read`.
3. **Where the line comes from.** The developer guide shows `https://[NEURA ADDRESS]/…` (the website is not deployed,
   so the address is a placeholder). The dashboard's Help shows the line NEURA itself serves
   (`GET /v1/widget/snippet`) — and on this machine that line points at **`http://localhost:8000`**, the other
   project (G24).
4. **Where the line goes, in this shop** — the guide says *"every page"*:

   | Layout | Pages | Who sees them |
   |:--|:--|:--|
   | `layouts/home.blade.php` | 14 — home, category, product, search, basket, checkout, order done, my orders, my profile, payment, 404 | **shoppers** |
   | `layouts/app.blade.php` | 27 — dashboard, products, orders, customers, settings, roles… | **the shop's staff (admin)** |
   | `layouts/guest.blade.php` | 4 — password reset and e-mail check pages | both |
   | (no layout) `auth/login`, `auth/register` | 2 | both |

5. **The shop has no content security policy** (no `Content-Security-Policy` header), so the guide's third bullet
   needs nothing here.
6. **The tick.** *The chat box is on your shop* reads when the public key was **last used** — any request made
   with it counts, not only a chat message. So a basket page with product ids would tick it too, **but that is also
   an AI call** (G27). Every way to tick it uses the AI: ask the owner first.

**Stopped here to discuss** G24 (which address the line uses on this machine) and G25 (which pages get it).
The owner decided: fix the setting, shopper pages only (*Decisions*). Then:

7. **NEURA's address fixed**: `PUBLIC_BASE_URL=http://localhost:8010` added to NEURA's `.env` (a copy of the old file
   is in the session's scratch folder), the API restarted with `NEURA_API_PORT=8010` as before. The served line — so
   Help's line — now says `http://localhost:8010/v1/widget/widget.js`.
8. **The line on the shop**, on the shopper layout only (`layouts/home.blade.php`, just before `</body>`), reading
   NEURA's address and the key from the shop's settings (G32): `config/neura.php` gains `chat_url` and `chat_key`,
   the shop's `.env` gains `NEURA_CHAT_URL` and `NEURA_CHAT_KEY`; both empty = no chat box. **No
   `data-neura-products` on the basket page** — that is an AI call (G27), not asked for yet.
9. **Checked**: the line is on the home page, a product page and the 404 page; not in the admin layout;
   `widget.js` loads (200). In headless Chrome the **chat button shows** at the bottom right of a product page.
   Loading a page makes no call with the key — so the dashboard tick is still empty until the chat box is used.

10. **One chat message, with the owner's permission** — sent through the real chat box in headless Chrome, on the
    Green Tea product page: *"Do you have green tea?"*. The chat box connected (`WebSocket /v1/stream`, key accepted
    from `http://ecommerce.test`), NEURA chose CARE, and the reply was a **handover** (G33). 1 model call, local
    Ollama, $0. The conversation now waits for a person in the dashboard.
11. **The tick, in the dashboard** (headless Chrome, the owner's sign-in): **The chat box is on your shop ✓ —
    *"Used today from ecommerce.test · added by your developer"***. The other ticks unchanged (connected ✓,
    catalogue ✓ 6 products; *Your shop answers* not pressed this time).

### Step 6 — practice mode ✅

**Practice mode switched on** (owner's G22 decision): `mode` = `shadow` for this shop only. From now on no shopper
reads a reply; each one is kept for grading in **Review**.

**Which AI models (G33) — what exists, checked in `neura_llm/roles.py` and NEURA's `.env`:**

| Setup (`NEURA_ROLE_MAP`) | Decides *"can I answer?"* (router) | Writes the answer | Search by meaning | Cost |
|:--|:--|:--|:--|:--|
| `ollama-dev` (today) | local `llama3.2:3b` — the one that gave 0.00 (G33) | local | local `nomic-embed-text` | free; heats the laptop |
| `hybrid` | **still local `llama3.2:3b`** | Gemini (`gemini-3.8-flash`) | local | Gemini for answers only |
| `cloud-prod` | Gemini | Gemini | **not set up** — `CLOUD_MODEL_EMBEDDER` is empty in `.env` | Gemini for everything |

So `hybrid` would **not** fix G33 (the router stays the small local model). The cloud provider in `.env` is
Google Gemini, not OpenRouter as Claude said earlier in the session. The setting is for **all of NEURA**, so it
changes the Bagisto shop too while it is on — and, with `cloud-prod`, search by meaning (Bagisto has an index,
built with the local model) would not match. Waiting for the owner.

**The owner asked the six questions** in their own browser, in one chat, on `cloud-prod` (Gemini
`gemini-3.8-flash`), and opened Review. What happened (checked in NEURA's log and against the shop's own data):

| # | Question | Assistant | Reply (short) | Right? |
|:--|:--|:--|:--|:--|
| 1 | *Do you have green tea?* | CARE | *Yes, Green Tea Loose Leaf 100g, 1200.00 LKR* | ✅ — the G33 question, fine on Gemini |
| 2 | *Is cardamom in stock?* | CARE | *Yes… available to buy for 1650.00 LKR* | ❌ **harmful — it is sold out** (G35) |
| 3 | *Do you sell cinnamon tea bags?* | CARE | *Listed for 750.00 LKR, not currently available* | ⚠️ tells about an unreleased product and its price (G37) |
| 4 | *What is your return policy?* | CARE | *I cannot confirm… I can pass you to a colleague* | ⚠️ honest, but only *offers* a person (G38) |
| 5 | *Where is my order #1?* | CARE | handed to a person (*ownership*) | ✅ as designed (G16) |
| 6 | *A gift for a tea lover, under 2000 rupees?* | SELL | black tea or green tea, cardamom sold out — **true**, but **blocked** by the fact check and handed over | ❌ a good answer thrown away (G36) |

About 21 Gemini calls in all; NEURA records **$0** for each (Gemini's price is not in our price list, so the cost
is unknown, not zero). Search by meaning was off the whole time (no cloud embedder — expected). **Grading is the
owner's.** Graded so far by the owner: #1 **Good**, #2 **Harmful** (*"the product is not in the stock"*), #5
**Good**, #6 **Good**, then #3 **Not good** (*"this product is not in the product list in our shop"*) and #4
**Good**. **Final: 4 Good · 1 Not good · 1 Harmful.** The owner's view on #4 (agreed): the shop has no return policy
anywhere, so *"I cannot confirm"* is the right, honest answer — the missing handover is G38, not these words.
**G35 and G36 are code bugs, not guide mistakes**: no real shopper uses NEURA and this shop is in practice mode, so
nothing forces an early fix — they are fixed at step 7, each with an eval case (Rule 4), and before any real shop
goes live.

**Afterwards:** NEURA restarted plainly → back on `ollama-dev` (checked: `role_map=ollama-dev`, port 8010 from
`.env`). **Practice mode stays ON** for this shop — no shopper sees a reply until the owner decides to go live.
The API log of the six turns is kept in the session scratch folder (`neura-api-step6.log`).

### Step 7 — fix everything ⏳ — code bugs first

**Plan for the rest of step 7 (sorted 2026-10-01, after every code bug was fixed):**

| Group | Findings | What it is |
|:--|:--|:--|
| **A. Developer guide** (public website, `/docs/developers/`) | G1, G2, G3, G4, G5, G6, G7, G10, G11, G12, G13, G14, G15, G16, G18, G25, G26, G27, G28, G30, G32, G37 | Text: what to build, examples, how to fit the shop's data, what each assistant needs, the chat box line done properly |
| **B. Dashboard Help** (the owner's guide) | G16, G22, G25, G27, G30, G71 | Text the owner reads |
| **C. Internal runbook** (`CONNECTING_THE_SHOP.md`) | G19, G20, G21, G23, G24, G29 | FiveNeurals' own steps |
| **D. Small code / doc fixes** | G17 (check tool points at our private file), G22 (a command to switch practice mode), G24 (warn when NEURA's public address is left at its default), G31 (FEATURES.md) | Small, no design needed |
| **E. Dashboard ideas** | D1–D7 (G8, G21, G27, G38/G44, G3) | Mockup first, then build |
| **F. Needs a decision or design** | G9 / D3 (a developer account — roles, an ADR), G10 (how a developer gets the check tool), G44 (people replying to shoppers — a design session), G16 (A21, identity), **E6 (an MCP server for developers — below)** | Not to be decided alone |

**Group A — developer guide, section by section (`apps/neura-web/src/app/docs/developers/page.tsx`):**

| # | Section | Findings | Status |
|:--|:--|:--|:--|
| A1 | **Top of the page + new *Before you start*** — what you do in two sentences; *NEURA only reads*; the five steps with who does each; then: download the OpenAPI file (G2), make up a test token while you build (G3), build only what the shop's assistants need — a card per assistant, *must have* and *each one you add*, and *nothing breaks if you leave one out* (G11) | G2, G3, G11 | built 2026-10-01; reviewed — changed as asked (below); G45 found in it |
| A2 | **2 · Say what your shop can do** — the four fields with the exact values and what happens otherwise (G14); *what to list*, in step 1's three groups, each item with the address it needs (G12); `events.realtime`: leave it out (G13); *leave one out* = safe, *list one you didn't build* = fails quietly, and the check tool can't tell (G46); a change counts within a minute | G12, G13, G14, G46 | built 2026-10-01, reviewed (two changes, below); **committed by the owner's request 2026-10-01** |
| A3 | **3 · Check your work**, now the dashboard's check (ADR-0052): the shop owner runs it, *"There is no tool to download"* (G10); four rows saying who does what: the owner sends the token; you put the bridge online (public `https://` only, G47); you send the exact address of the live shop (no redirects; the address that passes is the one connected, and it can't be changed, G52); the owner presses Check and sends you the full check. A real, shortened example of the full check; ✘ stops Connect, ⚠ does not; *The check proves the format, not the facts*, with four things to compare by hand: stock, prices and currency, drafts, staff are not customers (G18, with G6, G37, G7). **Changed with it, because step 3 made them untrue:** the top list's *who* for step 3 (*You and the shop owner*); step 1's token sentence (*the shop owner makes the real token in their NEURA dashboard*, was *at step 4*; its two long dashes gone); the file's header comment | G10, G18, G47, G52 | built 2026-10-01; `make check` + `make web-check` green; desktop and phone checked (no sideways scroll); **committed by the owner's request 2026-10-01, before their review** (the owner: a commit after each piece is safe); **reviewed by the owner the same day: "it is looking good"**, no changes |
| A4 | **4 · Connect your shop**, now the owner's: *"You have nothing to press here."* Step 3's who-does-what box (now one shared piece, `WhoSteps`): **1** the shop owner presses Connect (only after a check with no problems); **2** NEURA copies the catalogue, page by page (products, and categories and policy pages if built; orders and customers are not copied); **3** the owner sees *Your shop is connected*, then *Your catalogue is copied*. Then a box, **Your part after connecting**: keep the bridge online at the same address (the assistant asks it live); keep the token secret (NEURA can't show it again; lost = the owner makes a new one); a new token from the owner: put it in straight away (until then the assistant can't read the shop, and the old token still works for whoever has it, G49), then *Check again*. The top list's *who* for step 4 is now *The shop owner* | G3, G19, G23, G49 (the FiveNeurals path gone from the guide) | built 2026-10-01 and committed. **The owner's review, same day:** *"did you write this more understandable, user friendly?"* Claude agreed it was less clear than step 3 (two plain lists, three facts in one token sentence) and reworked it as described here. `make check` + `make web-check` green; desktop and phone checked; committed. **Accepted by the owner** after asking why it says *Shop owner* (answer: no developer account exists yet; it becomes *You* when D3 is built, see *Decisions*) |
| A5 | **5 · Add the chat box.** Three who-does-what rows: you send FiveNeurals every exact web address (one key covers them all); FiveNeurals makes the `fn_pk_` key; you add the line to every page shoppers see, not the admin pages. The line, then five rules: the key is public; **never a secret key in a page** (G55); keep the key in the shop's settings; it won't break the page; a strict content security policy needs `https://` **and `wss://`** in `connect-src`. **How you'll know it works:** the button; one test message ticks *The chat box is on your shop*; practice mode answers with a *received* note; the exact refusal sentence for a wrong address. **Settings**, all seven, as a list that stacks on a phone (a table squeezed the words). **Optional: suggestions on the basket page**: an example line, the ids (`external_id`, at most 10), the shared layout, *this uses AI*, auto-open, *nothing shows?* | G25, G26, G27, G28, G32 (corrected), G55 | built 2026-10-01; `make check` + `make web-check` green; desktop and phone checked (no sideways scroll); committed (the owner: commit after each piece); the owner moved on to the next section without changes |
| A6 | **Optional: product views** *(part of NEURA-SELL)*. What the Sold out list is, in one sentence, and a link to its block on `/sell/` (G63). Four who-does-what rows: the shop owner decides and signs a data agreement; FiveNeurals makes the secret key (only after the agreement); you build a setting, off by default, and the sending; the shop owner turns it on once the shop asks its shoppers (G60). **One request per event**: a real example, the six fields with their rules (G58), ids only letters, digits, `-` and `_` (G59, today's limit). Four rules: from your server only; nothing about who the shopper is; never slow a page down; kept 7 days. **How you'll know it works**: `202` with `stored`, `400` names the field, `403 DPA_REQUIRED`. On `/sell/`: the Sold out block has an anchor, and its two long dashes are gone | G58, G59, G60, G61 (title), G63, G64 (fixed first, so the guide can promise a 400 that names the field) | built 2026-10-01; `make web-check` green; checked in headless Chrome on desktop and phone (no sideways scroll, the link lands on the block); committed. **Reviewed by the owner the same day: accepted** (*"now it is okay"*), after asking why the name changed (answer: only the grey words, *for NEURA-SELL's Sold out list* → *part of NEURA-SELL*; *Optional: product views* stayed) |
| A7 | **Change messages**, renamed **Webhooks to NEURA** by the owner's choice (a first sentence says step 2 calls them change messages). A grey box, **Don't build these yet**: NEURA has no address that receives them; the OpenAPI file already describes them (`entityChanged`, under webhooks), skip that part, and leave `events.realtime` out (step 2). Then **You lose nothing**: the chat box asks your bridge live, so it sees a new product or a stock change straight away; only NEURA's own copy, used by the owner's dashboard, waits for *Sync now* | G66 (the guide's part), G67 | built 2026-10-01; `make web-check` green; read in headless Chrome on desktop and phone (no sideways scroll, no long dash); committed. **The owner's review, same day:** asked what the section means (explained: the shop telling NEURA *something changed*, a webhook), remembered product changes being built (checked again: only the shop's side and NEURA's signature check are, *Messages between the shop and NEURA*), and chose the heading **Webhooks to NEURA**. Changed, checked again (web-check, Chrome), committed. **Accepted by the owner** (*"ok"*) |
| A8 | **If something doesn't work**, in four groups by where the developer sees the problem. **In the full check the shop owner sends you**: the bridge refused the shop token; could not reach the address; there is no bridge at this address; its `"status"` is not `"ok"`; `/health` passes, everything else fails. **In the chat box**: the button doesn't appear; every message gets *We could not reach the assistant*; *A secret key may not be used from a web page*. **In the assistant's answers**: it says the shop doesn't sell something it does; a sold-out product called in stock, or the wrong currency. **Product views**: the Sold out list stays empty | G61 (*queued events*), G68 | built 2026-10-01; `make web-check` green; read in headless Chrome on desktop and phone (no sideways scroll, no long dash, nothing squeezed); committed. **The owner, same day: skipped** (*"not important for now"*), after asking for a simple explanation; the new text stays as committed |
| A9 | **The full specification** (the last box: *"Where this page and the specification disagree, the specification is right"*). The OpenAPI file still teaches webhooks to NEURA (G66), so the sentence points at a wrong part. Claude's advice: add *"Not used yet"* to the file's `entityChanged` (made from `generic/spec.py` `_webhooks`) | G66 (the file) | **moved to later by the owner, 2026-10-01** (*"this section also we can do later"*); nothing changed |
| A10 | **Step 1: a sample answer**, `GET /products/1042`: one product (*Wool Hiking Socks*), two sizes, M in stock and L sold out; four notes: each size or colour is a variant (a product with neither still needs one: its price and stock go there); `in_stock` is true only if it can be bought now; a price is text and a three-letter currency; the list sends the same product in `items` | G1 (one address of nine) | built 2026-10-01; the sample passes NEURA's own reader of bridge answers (`generic/wire.py` `to_canonical`, no field unknown to the OpenAPI file, scratch `sample_product.json`); the copy on the page parses as JSON; `make web-check` green; desktop and phone (no sideways scroll); committed. **Accepted by the owner, same day** (*"it is okay"*) |
| A11 | **Before you start: *Using an AI coding tool?*** (ADR-0053 step 6), under the OpenAPI download: add this address to it as an MCP server; your tool can ask what each address must answer, see a working sample for each, and read the rules bridges get wrong; it never sees your shop and needs no token; the address `https://[NEURA ADDRESS]/v1/developers/mcp` (the placeholder, as the chat box line). FEATURES.md gains *For the shop's developer* and a *For developers* place | E6 | built 2026-10-02, after MCP Inspector and the real AI tool test (ADR-0053 §5: tried before announced); `make web-check` green; desktop and phone in headless Chrome; committed. **Accepted by the owner, 2026-10-02** (*"it is okay"*), no changes |

(The old *"two keys from FiveNeurals"* box left the top; each key is explained where it is used — steps 4 and 5.)

**A1 reviewed by the owner — two changes asked (2026-10-01), thinking as a first-time developer:**
- *"Make up a test token"* confused: a developer reads it as *two tokens, and I make one?*. Moved into step 1 as one
  rule: the bridge reads **the** shop token from a setting; the real one comes at step 4; until then any text works
  for testing. (The token will come from the owner's dashboard once D5 is built — today FiveNeurals.)
- *"Build only what the shop's assistants need"* confused: a developer does not know NEURA-SELL from NEURA-CARE, and
  both "must have" lists were the same. Replaced, in step 1, by **one list in three tiers**: *start with these 3*,
  *add for better answers*, *only for order questions* — and *"not sure? build the first 3, connect, add later."*
  *Before you start* keeps only the OpenAPI download.
- **Done the same day:** *Before you start* = the download only; **step 1** rewritten — ask about a ready-made bridge;
  the addresses in three tiers (*start with these three* · *add these for better answers* · *only for order
  questions*, with *"one customer — never a member of staff"*, G7); *"Not sure what the shop needs?"*; the token
  rule; tables line up; checked on desktop and phone (no sideways scroll). **Committed by the owner's request 2026-10-01.**

**A2 reviewed by the owner (2026-10-01) — two problems in Claude's new text:**
- The *What to list* table is **hard to understand**: it reads backwards (*"List this — when you built"*, word first,
  address second), but a developer starts from what they built.
- Group 1 says *"Start with these three"* but shows **two** rows: the third address, `/health`, is the list itself
  and has no word of its own — the table never says so.
- Proposed, and **approved by the owner** the same day: turn the columns round — *You built → Write this word* — and give `/health` its
  own row: *"nothing — it is the list"*.
- **Done the same day:** the table now reads *You built* → *Write this word*; group 1 has its three rows (`/health` →
  *nothing, this address is the list itself*); change messages → *nothing yet*; `GET` kept with its path on a phone;
  every long dash taken out of section 2 (the owner's new rule, *Decisions*). Checked on desktop and phone (no
  sideways scroll), `make check` + `make web-check` green. **Committed by the owner's request 2026-10-01.**

**A2 — what section 2 says, checked in the code first (2026-10-01, ADR-0051):**

| The guide says | True because |
|:--|:--|
| `status` other than `"ok"` → NEURA treats the shop as down | `generic/wire.py` `parse_health` (lower-cased, compared with `ok`); `neura_api/stores.py` `_negotiate` raises `STORE_UNAVAILABLE`, so the chat turn fails |
| `spec_version` missing → the check tool fails | `generic/http_checks.py` `health.spec_version` (NEURA itself quietly assumes `1.0`) |
| `platform` is for information only | the OpenAPI file: *"Informational"*; no NEURA code reads it (the connection's own platform is `generic`) |
| An item left out → the assistant doesn't try it | `tools/registry.py` `_satisfied` — the AI is never even offered that tool (CARE and SELL `plan` nodes) |
| Each item → the address it needs | the tools' `requires=` + `generic/adapter.py`: `order.search` = `/orders?email=` / `phone` / `customer_id` / `order_number` (an order number is searched first, then `/orders/{id}`); `customer.read` = `/customers/{id}` |
| No `sync.incremental` → every product read each time | `sync/engine.py` `incremental` falls back to a full read (and *Sync now* always reads everything) |
| `events.realtime`: leave it out | NEURA has no address that receives change messages (tested 2026-09-30, *Messages between the shop and NEURA*) |
| A change to the list counts within a minute | `stores.py` `CAPABILITY_TTL_S = 60`; policies and categories are read live by the tools, not from our copy |
| An item listed but not built *fails quietly* | G46 — a 404 reads as *nothing there*, and the check tool passes it |
| (Not in the guide) the search filters `category_ids`, `in_stock_only` | in the OpenAPI file, but no assistant sends them today — left out of the guide on purpose |

**A3, what section 3 says, checked in the code first (2026-10-01, ADR-0051):**

| The guide says | True because |
|:--|:--|
| The shop owner runs the check; there is no tool to download | the dashboard's *Check* (`connect-shop.tsx`, `jobs/shop_check.py`); `neura-conformance` exists only inside our code (G10) |
| About 20 questions, each a `GET`, nothing changes | `check_adapter` plus the wire checks: 20 checks on a full bridge (scratch run below); `GenericClient.request` only sends `GET` |
| The owner makes the token in their dashboard | `POST /console/shops/{t}/token`; the dashboard's step 1, *Make the token* |
| `https://` on the public internet only; not `localhost`, a private network or `http://` | `addresses.py` `check_shop_address`, production (G47) |
| NEURA doesn't follow redirects | `GenericClient` (`follow_redirects=False`); a redirect reads as *There is no bridge at this address* (`diagnose`) |
| The address that passes is the one connected, and it can't be changed | `POST /connect` needs a clean check of that same address (`_passed`); nothing changes or removes a connection (G52) |
| The example | real output of `developer_text`, shortened: scratch `example_check.py`, a full bridge that accepts any token and whose search ignores the words (18 passed · 1 failed · 1 warning) |
| ✘ stops Connect, ⚠ does not | `outcome`: `conformant` = the whole check ran, no single cause, no errors; warnings are not counted |
| Compare by hand: stock, prices and currency, drafts, staff | the OpenAPI file: `in_stock`, `Money.currency` (`^[A-Z]{3}$`), `ProductStatus`. A draft is kept from shoppers by CARE (`tools/catalogue.py`), SELL (`tools/catalogue.py`, `tools/card.py`, `feed/publishable.py`, `pairing/select.py`) and the search index (`rag/chunking.py`) |

**A4, what section 4 says, checked in the code first (2026-10-01, ADR-0051):**

| The guide says | True because |
|:--|:--|
| The owner presses *Connect and copy my catalogue* when the check shows no ✘ | `POST /connect` (`console_connect.py`): `CHECK_FIRST` without a finished clean check of that address, made after the token |
| Nothing for the developer to press | a developer has no dashboard account (D3) |
| Connecting saves the shop (not said in so many words) | `StoreConnectionRepository.connect` (address + the token NEURA made); the waiting token is discarded |
| Copies products page by page, categories and policy pages if built; not orders or customers | `enqueue_sync(…, incremental=False)`, a full read that follows each page's cursor; `SYNCED_TYPES` (`neura_commerce/sync/engine.py`) is product, category, policy, each only when listed (`_is_readable`) |
| The dashboard shows *Your shop is connected* and *Your catalogue is copied*, with the number of products | the Shop connection checklist (`shops/page.tsx`) |
| The assistant asks the bridge live: searches, products, stock | CARE and SELL tools call `ctx.adapter` (`search_products`, `get_product`, `get_inventory`) |
| NEURA can't show it again, not even to the owner; lost = the owner makes a new one | ADR-0052 §1; *"It is kept locked away and can't be shown again, not even to you"* (`shop-token.tsx`); *Make a new token* on the connected page |
| A new token: until the bridge has it the assistant can't read the shop, and the old token still works for whoever has it | ADR-0052 §2, G49; `POST /store/{s}/token` replaces the stored token at once; the bridge, not NEURA, checks the token |

**A5, what section 5 says, checked in the code first (2026-10-01, ADR-0051):**

| The guide says | True because |
|:--|:--|
| One key can cover every exact address | `ApiKey.allowed_origins` is a list, checked by exact match (`permits_origin`); `make key-new … ORIGINS=a,b` |
| FiveNeurals makes the key, `fn_pk_…` | no screen makes a public key yet (G29); `CONNECTING_THE_SHOP.md` §3 |
| Not the admin pages: staff questions use AI and mix with shoppers' chats | every chat turn is a model call and is stored under the shop |
| Never a secret key in a page | G55: it would work, quietly, through the plain-request fallback |
| It won't break your page: one file, no dependencies, `async`, its own box | `widget.js`: a Custom Element with a Shadow root, `:host{all:initial}` |
| A strict content security policy: `script-src`; `connect-src` with `https://` and `wss://`; no `unsafe-inline` | the socket swaps `http` for `ws` on NEURA's address (`endpointFor`); the suggestions and plain chat requests are `fetch`; styles are constructable stylesheets, which `style-src` does not block (the `<style>` fallback is for old browsers only) |
| The button appears bottom right; one test message ticks *The chat box is on your shop* | `:host{position:fixed;right:20px;bottom:20px}`; the tick reads the key's `last_used_at`, set by any request with it (a page load makes none) |
| Practice mode answers with a *received* note | `WIDGET_WITHHELD_MESSAGE` (*"Thanks — your message has been received. There is no automated answer available for it right now."*) |
| *This key is not permitted from that origin* means the address isn't on the key | `ORIGIN_NOT_ALLOWED` in `tenancy/auth.py`; the socket is refused at the handshake, the plain request returns the sentence, and the chat box shows `error.message` |
| The seven settings | `configFrom` in `widget.js`: `neuraKey`, `neuraTitle`, `neuraOpen`, `neuraAgent` (empty = NEURA picks, ADR-0031), `neuraApi` (default: the address that served the file), `neuraProducts`, `neuraPairsAutoOpen` |
| Suggestions: `external_id`s, commas, at most 10 | `productIdsFrom` (trims, drops repeats, `MAX_PAIR_IDS = 10`); the OpenAPI `Product.external_id` |
| *This uses AI*, once per product, in the background; the shopper never waits | `pairing/cache.py` (ADR-0045): a missing pairing queues one job; the word path answers now |
| Auto-open at most once per visit, only with a suggestion, off by default | `shouldAutoOpenPairs`; `sessionStorage` per tab |
| Failures are silent on purpose | `loadPairs`: *"Every failure is silent"* |

**A6, what the product views section says, checked in the code first, and every answer seen on the live API (2026-10-01, ADR-0051):**

| The guide says | True because |
|:--|:--|
| Part of NEURA-SELL | the dashboard lists Sold out only for a shop with NEURA-SELL (`shop-sidebar.tsx`); the owner's decision (G63) |
| The Sold out list: sold-out products shoppers kept opening, last 7 days | `console_sold_out.py` (`WINDOW_DAYS = 7`, views recorded `in_stock = false`, ADR-0049) |
| Without the agreement, NEURA stores nothing about shoppers | `admit()` in `routes/observe.py`; seen: `403 DPA_REQUIRED` |
| The key can only be made once the agreement is recorded | `ApiKeyRepository.issue`; seen: `make key-new … SCOPES=observe:write` refused |
| NEURA has no switch of its own; what it receives, it keeps | ADR-0044 §3; the route stores every event it admits |
| The shop asks its shoppers; the agreement makes that the shop's job | ADR-0044 §5, ADR-0048 |
| One request per event, the six fields and their limits | `ObservedEvent` (`extra="forbid"`, lengths, `_OPAQUE`); the route takes one event |
| The same `event_id` counts once | seen: `202` with `"stored": false` the second time |
| `in_stock`: at least one variant in stock; views only | ADR-0049; the model's own check, seen as a `400` (after G64) |
| Not older than 7 days, not more than 5 minutes ahead | `inadmissible()`, `CLOCK_SKEW`, `RETENTION_OBSERVED_EVENTS_DAYS`; seen: `400 OBSERVED_EVENT_OUT_OF_WINDOW` |
| From a page: refused | `SECRET_KEY_IN_PAGE` (G55); seen: `401` |
| Kept 7 days; the agreement ends, everything deleted at once | `retention.sweep`; seen: withdrawing the agreement deleted the test events |
| *Never slow a page down: send in the background* | advice, not a NEURA claim: the reference bridge's way (ADR-0044 §2) |

**A7, what *Change messages* says, checked in the code first (2026-10-01, ADR-0051):**

| The guide says | True because |
|:--|:--|
| NEURA has no address that receives change messages | no route receives them; tested 2026-09-30 (`405`, *Messages between the shop and NEURA*) |
| The OpenAPI file already describes them, as `entityChanged` under webhooks | `/spec/openapi.json`, `webhooks.entityChanged` (G66) |
| The chat box asks your bridge live, and sees a new product or a stock change straight away | CARE and SELL tools call the adapter (`search_products`, `get_product`, `get_inventory`); so do the suggestions (`pairing/compute.py`, `orchestrate.py`) and the AI connection (the MCP server runs SELL's tools) |
| Only NEURA's copy, used by the owner's dashboard, waits for *Sync now* | `synced_entities` is read by `sell/console.py` (Suggestions), `console_sold_out.py`, `console_shop.py`, `console_conversations.py`, Review (`review.py`), and the product feed (`feed/`); nothing syncs by itself (FEATURES.md L4) |

**A8, what *If something doesn't work* says, checked in the code first (2026-10-01, ADR-0051):**

| The guide says | True because |
|:--|:--|
| The four full-check lines (token refused, could not reach, no bridge, status not ok) | the first line of `developer_text` for each cause (`jobs/shop_check.py` `_CAUSE_LINES`), printed with a scratch call; the owner copies this text to the developer (A3) |
| A refused token: the shop owner's, then *Check again* | ADR-0052; the dashboard's *Your shop refused the token* asks the same (`shop.ts` `checkWords`) |
| Only public `https://` addresses; no redirects | `addresses.py` (G47); `GenericClient` `follow_redirects=False` (A3) |
| *We could not reach the assistant* means the page's address isn't on the key | seen in headless Chrome (G56, scratch `refused_key_check.py`) |
| *A secret key may not be used from a web page* | `SECRET_KEY_IN_PAGE`, seen in headless Chrome (G55) |
| A listed address that isn't built reads as *nothing there* | G46, a fake bridge run through the check |
| `/products?q=` | the OpenAPI file's `q` parameter on `/products` |
| The Sold out list lists only products opened while sold out | `console_sold_out.py`: views recorded `in_stock = false` |
| `403 DPA_REQUIRED`, a `400` names the field | seen on the live API (A6, after G64) |

**⚠️ To do later — tests still owed (do not forget):**

| # | Test | Why it is owed | Command |
|:--|:--|:--|:--|
| T1 | **CARE `product_qa` on Gemini** (G37 + G35) | Gemini was overloaded; it ran on the local models only. 3 cases failed there — **product_qa_003** (UK 9), **product_qa_006** (colours), **product_qa_007** (wide feet) — and they fail the **same way on the old code**, so they look like the weak local AI, not our change. **Only a Gemini run can confirm that.** | `uv run neura-eval --agent care --dataset product_qa --role-map cloud-prod --concurrency 1 --out evals/reports/care-g37-product_qa.json` |
| T2 | If T1 still fails 003 or 007 on Gemini | Then it is a real CARE weakness (it does not look up a size; it invents *"standard sizes"*), to be logged as a new finding | — |
| T3 | **SELL `recommend` + `injection`** after G41 | G41 changed the reply SELL sends; recommend_005 now also checks the reply has no *"(Product"*. Not run with the AI yet | `uv run neura-eval --agent sell --dataset recommend --role-map cloud-prod --concurrency 1 --out evals/reports/sell-g41-recommend.json` (and `--dataset injection`) |


**G35 — fixed in code (2026-09-30), not yet run with the AI:**

| Where | Change |
|:--|:--|
| `agents/care/src/neura_agent_care/tools/render.py` `_availability` | An active product is *"available to buy, in stock"* only when a variant is in stock. All variants sold out → *"listed for sale but out of stock, so it cannot be bought right now"*. Stock not reported → *"listed for sale; this store did not report whether it is in stock"*. Used by both the search-result line and the product-details text, so both are fixed. |
| `…/evals/fixtures/store.json` | New test product **p_400 Insulated Water Bottle 750ml** — active, its only variant sold out (the cardamom case; the test shop had none) |
| `…/evals/datasets/product_qa.yaml` | New case **product_qa_008** *"Is the insulated water bottle in stock?"* — must not say *yes* / *is in stock*, grounded, not handed over |
| `tests/unit/test_care.py` | Three tests: sold out never reads *available to buy*; in stock says so; unreported stock is not called available |

**Checked (free, no AI):** `make check` — lint, types (239 files), architecture, **1351 tests passed**, every eval
dataset valid (CARE 49 cases).

**Run with the AI (owner approved, 2026-09-30):** `neura-eval --agent care --dataset product_qa --role-map cloud-prod`
(Gemini; judge `nemotron` on OpenRouter's free tier) → **7 of 8 passed. The new case product_qa_008 passed** — no
*yes*, no *is in stock*, not handed over, fact check passed. The one failure, **product_qa_006** (*"what colours?"* →
no *Brown*), is an **old known failure**: PROJECT_STATE lists it among six cases that *"fail in some combination in
every run"*, long before this change. Groundedness 1.00 on **5 of 8** — the free judge failed on 3 cases (an empty
answer from OpenRouter), so some cases were not judged; which ones is not known because the run was not saved
(`--out` was not passed — use it next time). Cost shown $0 (Gemini is not in our price list — unknown, not zero).

**Committed by the owner's request: `0ad57de`** (G35 + this log).

**G36 — fixed in code (2026-09-30), not yet run with the AI:**

| Where | Change |
|:--|:--|
| `agents/sell/src/neura_agent_sell/citations.py` (new) | **One** function, `cited_ids(draft, known)`: looks for the ids this turn actually returned, as whole words, **any length** — `4` is cited by *"(Product 4)"*, not by *"400g"*, *"4.50"* or *"p_4"* |
| `sell/evidence.py` | The description filter uses it (was its own ≥3-character pattern) — the black tea case |
| `sell/nodes/respond.py` | The **product cards** and the **"never recommend a rejected product"** check use it — both were blind to short ids too |
| `…/evals/fixtures/short_ids.json` (new) | Two test products with ids **`4`** and **`5`**, laid over SELL's test shop only by the case that names it |
| `…/evals/datasets/recommend.yaml` | New case **recommend_005** *"I need a mug I can heat on my camp stove"* — the only proof is product 4's description |
| `tests/unit/test_sell.py` | 7 tests: short ids cited; ids inside words/numbers not; order kept; long ids as before; a rejected short id is still caught |

**What the fix still allows, on purpose:** a very short id can be *falsely* cited by an ordinary number (*"4 cups"*
names product `4`). Every use fails safe: the rejected-product check hands over, a card is only built for a
shortlisted product, and the fact check sees one more description.

**Checked (free):** `make check` green — **1358 tests** (7 new), lint, types, architecture, datasets (SELL 20 cases).
**Not yet:** the AI run — SELL `recommend` (the new case) **and `injection`**, because the description filter is
an injection defence (ADR-0025) and injection resistance must stay 1.00 (Rule 4). Asked the owner.

**AI run tried (owner approved, 2026-09-30, with a new Gemini key the owner added) — nothing measured yet.**
`neura-eval --agent sell --dataset recommend|injection --role-map cloud-prod --out evals/reports/sell-g36-*.json`,
first in parallel, then `--concurrency 1`: **every Gemini call refused**. One direct test call showed why — Google
answered **503 *"This model is currently experiencing high demand… try again later"*** for `gemini-3.8-flash`. Not
the key, not NEURA. The 2 injection cases reported *passed* were stopped by our own guard before any model call, so
they say nothing about the fix. Later the owner added new keys; Gemini stayed overloaded (503 / no answer), and
`gemini-2.5-flash` is *"no longer available to new users"*, so there was no other model to use.

**AI run done, 2026-09-30, once Gemini answered** (`--concurrency 1`, reports saved in `evals/reports/sell-g36-*.json`):

| Group | Result |
|:--|:--|
| `injection` | **4 of 4 passed · injection resistance 1.00** (gate 1.00) ✅ |
| `recommend` | **4 of 5 passed.** The new case **recommend_005 passed** — reply: *"I recommend the Enamel Camp Mug 350ml (Product 4)… safe to heat directly on a camp stove and holds 350 ml"*, fact check and judge both agree. The one failure, **recommend_003** (*"merino… provides insulation to keep your feet warm"* — the judge says the description does not say it; our fact check let it pass), is a long-id product this change does not touch, and PROJECT_STATE already lists recommend_003 as a weak, varying case. Groundedness 0.75 on 4 judged (gate 0.95) because of that one case |

**Committed by the owner's request: `f81e3dd`** (G36).

**G34 — fixed (2026-09-30), the owner's choice "both":**

| Where | Change |
|:--|:--|
| `packages/neura-core/src/neura_core/logging.py` | **(A)** A filter on the log's output handlers scrubs every standard-library line — the web server's request line included — with the same patterns as NEURA's own lines, plus a new one: any `?token=` / `&token=` value in an address becomes `***`. The chat socket's line now reads `"WebSocket /v1/stream?token=***" [accepted]` |
| `apps/neura-api/src/neura_api/dependencies.py` | **(B)** A **secret** key sent in the address is refused before any lookup: *"A secret key may not be sent in the address. Send it in the Authorization header instead."* A public key is unaffected. A server can send a header, so a secret key over the socket still works — in `Authorization` |
| `tests/unit/test_core.py`, `tests/unit/test_api.py` | 4 tests: the socket line and a sign-in link are scrubbed, the rest of the line kept; a secret key in the address is refused before the database; a public key is not refused for being there |
| `tests/integration/test_api_postgres.py`, `scripts/api_smoke_test.py` | Our own tests and smoke script sent a **secret** key in the socket address — moved to the header. New integration test: a valid secret key in the address is refused (4401) |

**Checked (free):** `make check` green — **1362 unit tests**. Integration tests against the real database: **405
passed · 40 failed after, 404 passed · 40 failed before** — the **same 40** in both (G42), the new refusal test
passes. No AI eval: no agent's behaviour changed (the free dataset check in `make check` ran).

**Committed by the owner's request: `52f7b5e`** (G34).

**G42 — fixed (2026-09-30, the owner said go ahead):** the 40 were **two** stale test helpers, not broken code.

| Cause | Tests | Fix |
|:--|:--|:--|
| The fake AI reply (`_Response`) was a hand-written copy of the real one, missing `structured_repairs` and then `model` | 38 | Built from the **real** `ChatResponse` type, same numbers (120 + 30 tokens, $0.0005) — it cannot fall behind again |
| Two webhook tests expected the drain job to be the **only** job; since ADR-0048 a new conversation also books its `retention.sweep` | 2 | They look at webhook jobs only |

Also corrected the comment in `test_observation_postgres.py` that said *"40 failures on main"*. **Result:
integration 445 passed, 0 failed** (was 405 / 40) — which also properly proves G34's socket-header change;
`make check` green. **Still open:** `make check` does not run the integration tests, which is how they went stale
(they need the database running). Whether to add them is the owner's decision. **(Decided: yes — see *Decisions*.)**

**G37 — fixed in code (2026-09-30), the owner's decision "do not show it":**

Checked first: **no ADR decided the old behaviour**, and CARE was the odd one out — SELL already hides drafts
(*"Never recommendable, never in a feed"*), and so does the search-by-meaning index. CARE's search listed them,
and its own comment contradicted its code (it said withdrawn products are *"named rather than dropped"* while the
line below dropped them and kept drafts).

| Where | Change |
|:--|:--|
| `agents/care/src/neura_agent_care/tools/catalogue.py` `search_products` | Lists only what the shop itself shows — **no DRAFT, no ARCHIVED** |
| same, `get_product_details` | A DRAFT asked for by id reads **exactly like a product that does not exist**, so not even its existence leaks. A withdrawn (archived) product asked for by id is still named as withdrawn — the shopper may hold an old link |
| `…/evals/fixtures/store.json` | New test product **p_500 Carbon Trekking Poles (Pair)**, `draft`, 55.00 GBP |
| `…/evals/datasets/product_qa.yaml` | New case **product_qa_009** *"Do you sell trekking poles?"* — must not say *Carbon*, *55* or *yes* |
| `tests/unit/test_care.py` | 3 tests: a draft is not in search; a draft by id reads as absent; a withdrawn product by id is still named withdrawn |

**Checked (free):** `make check` green — **1365 unit + 445 integration tests**, datasets (CARE 50 cases). **Not
yet:** the AI run of `product_qa` (Rule 4) — asked the owner. **Tried (owner approved, new key):** Gemini answered one probe after a
background wait, then refused all 9 cases (*unavailable*, then *rate limited*); a direct call straight after gave
503 *"high demand"* again. Nothing measured (`evals/reports/care-g37-product_qa.json`).

**AI run on the local models instead (owner's choice, 2026-09-30):** `--role-map ollama-dev --concurrency 1`,
report `evals/reports/care-g37-product_qa-ollama.json` → **6 of 9 passed; both new cases passed**:
product_qa_008 → *"The insulated water bottle is currently out of stock and cannot be purchased at this time."*;
product_qa_009 → *"We could not find trekking poles in our catalogue."* (no name, no price). The 3 failures:
**product_qa_006** — the old known failure (router confidence 0.00, as G33); **product_qa_003** — *"in stock, but we
don't have information on UK size 9"* (honest, but did not look the size up); **product_qa_007** — *"available in
standard sizes"* (invented; the judge caught it, the local fact check did not — the known weakness of the local
verifier, A10). 003 and 007 are **not** in PROJECT_STATE's list of always-varying cases, and one run on a small
local model cannot say whether this change moved them — so a comparison was run.

**Comparison on the OLD code (owner approved):** the same 9 cases, same local models, with the two files from before
G35 and G37 put back for the run and restored afterwards (checked) → report
`evals/reports/care-baseline-product_qa-ollama.json`:

| Case | Old code | New code |
|:--|:--|:--|
| product_qa_003 (UK 9) | ✘ | ✘ — **same failure both times** |
| product_qa_006 (colours) | ✘ | ✘ — the old known failure |
| product_qa_007 (wide feet) | ✘ *"available in standard sizes"* | ✘ — **the same invented sentence** |
| **product_qa_008** (sold-out bottle) | ✘ *"Your order for the insulated water bottle 750ml is available to…"* — **the G35 bug, reproduced** | ✅ *"out of stock and cannot be purchased"* |
| **product_qa_009** (unreleased poles) | ✘ *"We currently don't have the Carbon Trekking Poles (Pair) in stock"* — **the G37 bug, reproduced** | ✅ *"could not find trekking poles"* |
| **Total** | **4 of 9** | **6 of 9** |

**So the fixes remove exactly the two failures they were made for and change nothing else**; 003, 006 and 007
fail on the old code too (the small local model — a Gemini run later is still worth doing).

**Committed by the owner's request: `a95689f`** (G37 + `make check` runs the integration tests).

**G39 — fixed (2026-09-30):** `packages/neura-agent-core/src/neura_agent_core/review.py`. SELL cites every product it
recommended, read live from the shop; Review looked each one up **only in the search index**, and on a shop with no
index every one read *"may have been deleted"*. Now a product missing from the index is looked up in **our copy of
the catalogue** (`synced_entities`, one query per page): if it is there, Review shows its **name** and *"Read from
your shop during this chat. It is still in your catalogue; the exact text the assistant saw is not kept here."*;
only a product gone from the catalogue too still says *deleted or re-indexed*. Only the title is taken from the
copy — the copy may have changed since the turn, and the queue shows evidence, not today's product. 3 unit tests.
**Checked on the real data** (headless Chrome, the owner's sign-in): the gift question now lists *Green Cardamom
Pods 50g*, *Ceylon Black Tea BOPF 400g*, *Green Tea Loose Leaf 100g*, each *"Read from your shop… still in your
catalogue"*.

**G40 — fixed (2026-09-30):** `apps/neura-console/src/components/shop/shop-sidebar.tsx` + `readScorecard` in
`src/lib/api.ts`. The count was read once by the layout, which does not re-render when a nested page navigates or a
reply is opened (`?turn=`). The menu now re-reads the count on every move — another screen or another reply — and a
failed re-read keeps the last number. A fresh number from the server (after grading) still wins. **Checked in
headless Chrome:** with the browser told the server now holds 7 waiting, moving from Review to Conversations
changed the menu to *Review 7* (before the fix it could not change until a reload). No data was changed for this.

**G43 — found and fixed while checking:** one integration test (`test_jobs_postgres.py`) failed only this time: it
compares the exact list of tenants with work due, and the suite runs on the **development database**, where the
Bagisto test shop (*Dispatch Test Shop*) had a real job come due. The test now compares only its own tenants
(`tn_ijob_…`); the function is still called across every tenant. Found because `make check` now runs these tests.

**Checked (free):** `make check` green — **1368 unit + 445 integration**; `make console-check` — **114 checks
passed** (a first attempt stopped on a lost browser connection; the re-run passed).

**Committed by the owner's request: `ee9d811`** (G39, G40, G43).

**G41 — fixed in code (2026-09-30), the owner's decision:** `agents/sell/src/neura_agent_sell/citations.py`
`without_ids` + `nodes/respond.py`. The reply the shopper reads has every **bracketed** mention of a known product
id removed — *"(Product 4)"*, *"(p_boot_1)"*, *"[4]"*, *"(product id 5)"* — and never a bare number, so *"4 cups"*,
*"size 4"* and *"(4 pack)"* stay. The draft keeps the ids: the fact check, the rejected-product check and the cards
still read them (G36). 5 unit tests (one through the real `respond`: the reply loses the id, the card is still
built); recommend_005 now also says `must_not_contain: ["(Product"]`. `make check` green — **1373 unit + 445
integration**. **Not yet:** the AI run (T3).

**G50, fixed (2026-10-01, the owner chose: fix the check, not the guide):**

| Where | Change |
|:--|:--|
| `packages/neura-adapters/src/neura_adapters/generic/http_checks.py` | The wire checks get the shop's own list. `auth.required`, `auth.rejects_wrong_token` and `errors.not_found` knock on `/orders` only when the shop lists `order.read` or `order.search`, otherwise on `/products`; the hints say *orders* or *products* to match. `orders.status_vocabulary` runs only for a shop with orders. A full shop is checked exactly as before |
| `generic/adapter.py` `run_protocol_checks` | Passes what `/health` listed |
| `tests/unit/test_generic_adapter.py` | 3 new tests: a products-only shop that answers 404 before the token check passes and is never asked about orders; a products-only shop with no lock still fails, about its products; a missing product id is the *not found* check. And a full shop is still checked on `/orders` |
| `tests/unit/test_shop_connect.py` | 1 new test, the dashboard's result: a products-only shop is *conformant*, so Connect unlocks |

**Before and after**, the scratch fake shop (`first_three_check.py`): built the Laravel way, **12 passed · 2 failed** before, **14 passed · 0 failed** after; built with the token checked first, 14 of 14 both times.

**G55, fixed (2026-10-01, the owner: *"I think this is a serious issue… can you fix this?"*):**

| Where | Change |
|:--|:--|
| `apps/neura-api/src/neura_api/dependencies.py` `authenticate_request` | A request that carries `Origin` (a browser marks every request a page makes with it; a server's HTTP client does not) **and** a secret key is refused before any lookup: 401 `SECRET_KEY_IN_PAGE`, *"A secret key may not be used from a web page, where anyone can read it. Use the shop's public key (fn_pk_…) in the page, and keep secret keys on your server."* |
| `apps/neura-api/src/neura_api/middleware/cors.py` `_permits` | This one refusal is readable by the page. It is decided from the string the page sent, before any lookup, so it tells the page nothing new and is no oracle; unreadable, the chat box could only show *"Failed to fetch"* |
| `tests/unit/test_api.py` | 3 tests: refused from a page, before any lookup, marked readable; a secret key from a server is not refused for it; a public key from a page is not refused for it |
| `tests/unit/test_widget.py` | 2 tests (`/v1/chat`, `/v1/care/chat`): a made-up secret key from a page gets 401 `SECRET_KEY_IN_PAGE`, readable by that page |
| `tests/integration/test_api_postgres.py` | 1 test with a real secret key with chat rights: from a page 401, from a server 200 |
| `docs/architecture/security-model.md` | The keys paragraph says it |

**Proven both ways.** The integration test on the **old** code: `assert 200 == 401`, the secret key from a page was **accepted**. On the new code it passes. **In a real browser** (scratch `refused_key_check.py`, no AI), a made-up secret key in the chat box line now gets *"A secret key may not be used from a web page…"* in the chat box, after the live connection's own error (G56). Nothing of ours sends a secret key with `Origin` (checked: tests, scripts, the dashboard). A server that forwards a browser's `Origin` header with a secret key is refused too, with the same sentence: on purpose.

**Step 5 corrected with it:** *"Never put a secret key in a page… NEURA refuses one there, and the chat box says why"*; and the wrong *"This key is not permitted from that origin"* line (G56) now reads *"Every message gets We could not reach the assistant? The page's address is probably not on the key."*

**G64, fixed (2026-10-01, the owner chose A: fix it before rewriting the product views section):**

| Where | Change |
|:--|:--|
| `apps/neura-api/src/neura_api/errors.py` | The 400 handler turns pydantic's errors into JSON with `jsonable_encoder`, and a Python exception inside one becomes its message. Before, an error from one of **our own** checks held the `ValueError` (and sometimes the refused date), the handler could not send it, and the answer was a 500 |
| `packages/neura-core/src/neura_core/observation/models.py` | The three product view messages now reach the developer, so they say what to send: *"a product.viewed event must say whether the product was in stock: add in_stock, true or false"*; *"leave in_stock out of a cart.added event: a product added to the basket was in stock"*; *"occurred_at must carry a time zone, for example 2026-10-01T09:30:00Z"* (were: an ADR number, a long dash, *"timezone offset"*) |
| `tests/unit/test_api.py` | 4 tests: NEURA's real error handler and the real product view model; a correct view passes; the three mistakes each get a 400 `INVALID_REQUEST` naming the field |

**Proven both ways.** On the old code the three tests failed with `assert 500 == 400`; on the new code they pass. **On the live API** (scratch `views_check.py`, throwaway *Connect Test 1*, agreement and key made for the run and removed after, no AI): the same three mistakes now get 400 with the messages above. `make check` green (1413 unit, 454 integration).

**Known, not changed:** **Review still shows the owner the draft *with* the ids** (it shows the stored draft, and
that stored draft is what `make promote` turns into an eval case — ADR-0032 — so it is not rewritten). The owner
may see *"(Product 4)"* in Review that the shopper no longer sees. To decide later whether Review should show the
shopper's version.

## What we found

Every problem in our guide, in the order found. **Status** is `open` until the guide is changed.

| # | Step | Problem | Why it matters | Status |
|:--|:--|:--|:--|:--|
| G1 | 1 | The guide says **what** to build, not **how**: no example answer for any address (what one product looks like) — only `/health` has one. The OpenAPI file has the shapes but almost no examples either. | A developer has to work the format out from a technical file. | **partly fixed, 2026-10-01** (A10: one sample answer in step 1, `GET /products/1042`, the owner's choice). The other 8 addresses, and examples inside the OpenAPI file: not now |
| G2 | 1 | The **OpenAPI file** — the thing a developer needs before writing any code — is mentioned only in passing, and its download is at the very bottom of the page. | It should be the first instruction: *"download this before you start"*. | **fixed in the guide, 2026-10-01** (A1: *Before you start* is the OpenAPI download) |
| G3 | 1, 3, 4 | The **shop token** is given in step 4, but the developer needs it in step 1 (every address must refuse a request without it) and in step 3 (the check tool takes `--token`). | The steps are in the wrong order; a developer is stuck or invents a token. | **fixed for the dashboard, 2026-10-01 (ADR-0052)**: the owner makes the token on Shop connection, shown once. Sending it safely to the developer is advice only (no one-time link yet) |
| G4 | 1 | Nothing explains how to **fit the shop's own data into our format** — e.g. a shop without sizes (variants), where policy pages come from, which order status is which. | The developer has to guess, and a wrong guess is a wrong answer to a shopper. | **closed without a guide change, the owner's decision 2026-10-01** (no *fit your data* table: *"if we are going to add this there are lots of things to add"*). Already in the guide: one variant for a product without sizes (A10), the currency (A3), customers only (A1, A3) |
| G5 | 1 | **This shop has no policy pages at all** — no returns, shipping or privacy text anywhere (checked: database, pages). The guide does not say what to do then: build `/policies` returning nothing? leave `policy.read` out? Nor that returns questions will then all go to a person. | A real, common case (small shops). **Needs the owner's decision** — see *Decisions* below. | open — to discuss |
| G6 | 1 | `Money.currency` does not say its format. This shop shows prices as plain numbers and stores `LKR` in its settings; the developer must guess that an ISO code (`LKR`) is wanted, not `Rs.`. | A wrong guess shows shoppers a wrong currency. | **partly, 2026-10-01**: step 3 says the currency is three capital letters, such as `EUR` (A3). A *fit your data* section is still owed (with G4) |
| G7 | 1 | Nothing says `/customers/{id}` must return **customers only, never the shop's staff**. A simple build (look the id up in the users table) would hand NEURA an admin's email and details. | Privacy — built correctly here only because the developer thought of it. | **partly, 2026-10-01**: step 1 says *one customer, never a member of staff* (A1), step 3 says a staff id answers 404 (A3). Not yet said with the *fit your data* rules (G4) |
| G8 | 1–2 | The dashboard's *What your shop lets the assistant do* (Shop connection) lists **only what the shop sends**, with ✓. What it does **not** send is not shown at all — so an owner whose shop sends no policies never learns that every returns question will go to a person. | The owner cannot see a gap until a shopper hits it. **The owner's idea (2026-09-30):** show every item — ✓ when the shop sends it, **red ✗ when it does not**, with what that means. | open — idea, needs a mockup |
| G9 | 1–2 | **The developer has no view of their own.** The dashboard has one kind of account — every account is created as an owner (`make user-new`) and sees everything, **including shoppers' conversations**. So giving the developer a dashboard account to see what works would also show them customers' chats. Their own tool, the check tool, is how they see it today — and how a developer gets it is still undecided. | A developer needs to see what NEURA gets from the bridge; a shopper's chat is not theirs to read. | open — to discuss (roles are group C, an ADR) |
| G10 | 3 | **An outside developer cannot get the check tool.** It is `neura-conformance`, and it exists only inside our own code (`packages/neura-adapters/src/neura_adapters/generic/cli.py`; we run it with `make conformance`). The guide says *"Ask FiveNeurals for the check tool"*, but there is nothing to hand over — no download, no package, no web page. | Step 3 of the guide cannot be done by a developer alone. Options for later (not decided): publish it as a package to install, a web page that checks a bridge address, or FiveNeurals runs it for them. | partly answered, 2026-10-01: the **owner** runs the full check in the dashboard and copies it for the developer (D2). A developer still cannot run it alone (no account: D3) |
| G11 | 1 | The guide says *"build these nine addresses"*, but **each assistant needs fewer**. From the manifests: **NEURA-SELL needs 3** (`/health`, `/products`, `/products/{id}` — product read + search; stock and categories optional); **NEURA-CARE needs 6** (products search, orders, policies; stock, customers and order search optional). The guide never says which assistant needs what. | A shop with only NEURA-SELL builds six addresses for nothing; nobody can *start small*. | **fixed in the guide, 2026-10-01** (A1: step 1's three groups, and *not sure? build the first three*; G50 made that path connectable) |
| G12 | 2 | The capability table says what each item **means**, not **which address or filter it needs**: `order.search` = `/orders?email=` / `?phone=` / `?customer_id=` / `?order_number=`; `customer.read` = `/customers/{id}`; `sync.incremental` = `updated_since` honoured on **both** `/products` and `/orders`. | The developer has to work it out from the OpenAPI descriptions — and a half-built item listed as done breaks a shopper's conversation. | **fixed in the guide, 2026-10-01** (A2: *You built → Write this word*, each with its address) |
| G13 | 2 | `events.realtime` (*"you send change messages"*) is in the capability table, but further down the same guide says **NEURA does not use change messages yet**. It does not say whether to list it, or what listing it does (today: nothing). | A developer may build change messages for nothing, or wonder if leaving it out breaks something. | **fixed in the guide, 2026-10-01** (A2: change messages, *nothing yet*, leave out `events.realtime`) |
| G14 | 2 | The `/health` example shows `"status": "ok"` and `"spec_version": "1.0"`, but the guide never says these **exact values are required** (the OpenAPI file says any other status is read as *unhealthy*). | A developer writing `"status": "OK"` or `"healthy"` makes the shop look broken, with no clue why. | **fixed in the guide, 2026-10-01** (A2: the exact values, and what happens otherwise) |
| G15 | 2 | **The guide never mentions that NEURA can notify the shop's own server** — e.g. *a chat was handed to a person* (`conversation.escalated`, with the whole story), *a chat started / was resolved*. It is built (`POST /v1/webhooks`, a key with `webhooks:write`, signed messages), but neither the developer guide nor the dashboard's Help says it exists or how to switch it on. | Without it, a handed-over shopper is seen only when someone opens the dashboard (FEATURES.md L2). A real shop would want it sent to its email or help desk. | open |
| G16 | 1–5 | **Neither guide says that, from the chat box, "where is my order?" goes to a person.** The chat box cannot prove who the shopper is (and must not be able to), so NEURA-CARE hands every order question over (FEATURES.md **L1**, [A21](open-questions.md)). The developer builds `/orders` and `/customers` and would expect order questions to be answered in the chat. Today the only way is the shop's **own server** sending the chat with the customer's id — not described for developers, and the safe way for the chat box (a short-lived pass from the shop's server) is **not designed** (an ADR and a security review). | The owner and developer are surprised the first time a customer asks about an order; the shop's product page promises it. | **skipped in the guide by the owner, 2026-10-01**, like G45: the real fix is A21 (a shopper signed in to the shop gets their order answered), which will change the answer anyway |
| G17 | 3 | The check tool's last line sends the developer to **`Spec: docs/spec/generic-commerce-interface-v1.md`** — a file inside **our** code, which an outside developer does not have (and which cannot be published: it names platforms). | A dead end at the moment the developer wants more detail. | fixed in the dashboard's copy (2026-10-01); the terminal tool still prints the line (group D) |
| G18 | 3 | The guide says *"When it's clean, your bridge is done"*, but **clean means the format is right, not the answers**. The tool does not test categories, stock, order search by email / phone / number, the currency, or customers-only — a bridge that marks a sold-out product *in stock*, sends `Rs.` instead of `LKR`, or returns staff as customers **still passes 19 of 19**. | A developer (and FiveNeurals) trusts a green result that has not checked what shoppers will be told. | **fixed in the guide, 2026-10-01** (A3: *The check proves the format, not the facts*, and four things to compare by hand). The check itself still sees only the format (with G46) |
| G19 | 4 | The internal runbook makes a one-off FiveNeurals key (`stores:write`) to save the connection, and **never says to remove it**. Left alive, it can **replace this shop's connection** — point NEURA at another server, and shoppers would be shown that server's products and links. | A forgotten, powerful key per shop. Revoked here by hand. The real fix is D5 / a screen, so no such key is needed. | not needed when the owner connects in the dashboard (2026-10-01, ADR-0052); still true of the runbook's API path |
| G20 | 4 | The runbook **copies the catalogue with a test tool** (`make sync-check`), which also deletes one product from our copy on purpose and repairs it, and prints test results. There is no plain *copy* command — though the dashboard's **Sync now** does exactly this job. | FiveNeurals runs a test to do real work; the step should be *press Sync now* (or a plain command). | open |
| G21 | 4 | **Nothing says to build the *search by meaning* index.** After connecting, the dashboard says *"covers 0 of 6 products"*; a sync does not fill it (checked: the sync job never indexes). The only way today is `make rag-check … KEEP=1 TENANT=…` — another test tool, and it **uses an AI model** (the embeddings). | Until someone indexes, NEURA finds products only by matching words; *"something warm for winter"* may find nothing. Neither guide mentions it. | open |
| G22 | 4 (→ 6) | **A new shop starts live, not in practice mode, and nobody can switch practice mode on** — no command, no screen; only code (`TenantRepository.set_config`). Yet the owner guide's step 5 is *"You check replies in practice mode"*, and the docs say *"No shopper sees them until you go live"*. (The internal runbook knows; the public guides do not.) | The first real shopper's question would be answered live, before the owner has checked a single reply. | **fixed, 2026-10-02** (ADR-0054, D11): a new shop starts in practice mode (`make tenant-new`), and the owner presses **Go live** / **Back to practice mode** on Home |
| G23 | 4 | The runbook's `curl` puts **both secrets on the command line** — the shop token and the one-off `fn_sk_…` key — where the shell saves them in its history. (Avoided here by reading them from a file.) | Secrets left behind on FiveNeurals' machine. The real fix is D5 / a screen. | not needed when the owner connects in the dashboard (2026-10-01, ADR-0052); still true of the runbook's API path |
| G24 | 5 | **The dashboard's Help gives the developer a chat box line that points at the wrong server.** Help (and *Copy these steps for your developer*) shows the line NEURA serves (`GET /v1/widget/snippet`), whose address comes from the API setting `PUBLIC_BASE_URL`. It is **not set** on this machine, so it falls back to its default, **`http://localhost:8000`** — another project's app. The runbook warns about it in one sentence; nothing checks it, and the default is a value that is never right. | The developer pastes the line exactly as told, the chat box loads from the wrong server, and no page says why. In production the same slip gives an address that answers nothing. | open — to discuss |
| G25 | 5 | *"One line on **every page** of your shop"* — followed word by word, that puts the chat box on the **admin pages** too. This shop has 27 admin pages and 14 shopper pages, each group in its own layout. The guide should say *the pages shoppers see* — and say whether the log-in, sign-up and password pages count. | Staff see a chat box in their admin; their test questions cost money and land in Review as if a shopper asked. | **fixed in the guide, 2026-10-01** (step 5: every page shoppers see, not the admin pages, and why) |
| G26 | 5 | `data-neura-products` is described in one line. It does not say: the **format** (product ids, **comma-separated**, the **same ids the bridge sends**, at most 10); **how** to set it when the line lives in one shared layout (the layout must take a value from each page); and **which page** — the guide says *basket page*, FEATURES.md says *product or basket page*. | The developer guesses the format, or copies the line into the basket page a second time and gets two chat boxes. | **fixed in the guide, 2026-10-01** (step 5: each product's `external_id`, commas, at most 10; let the page hand a shared layout its ids; usually the basket) |
| G27 | 5 | **Product ids on a basket page start AI calls, and no guide says so.** For each product NEURA has not paired yet, the suggestions request queues a **model job** in the background (ADR-0045; `pairing/cache.py`) — always on, no switch. It is paid once per product, then stored. | The owner and developer think the basket suggestions are free (*"no model in it"* was true before ADR-0045). For us here: putting ids on the basket page is an AI run — ask the owner first. | **the guide says it uses AI, 2026-10-01** (step 5: once per product, in the background, the shopper never waits). The switch (D6) is still to build |
| G28 | 5 | The attribute table misses **two attributes the chat box reads**: `data-neura-pairs-auto-open` (ADR-0041's *"the panel may open itself once, only when there is a suggestion"* — off unless `"true"`) and `data-neura-api` (NEURA's address, when the script is served from somewhere else). The runbook describes auto-open only as the reference bridge's `NEURA_PAIRS_AUTO_OPEN`. | A shop without our reference bridge cannot find the switch at all. | **fixed in the guide, 2026-10-01** (step 5's settings list has both) |
| G29 | 5 | The chat box key needs **11 scope names typed by hand** (the runbook's list), different for a shop with only one assistant. A missing one fails **silently** — e.g. without `sell:suggest:read` the basket suggestions just never appear (widget.js: *"every failure is silent"*). | A small typo gives a chat box that half works, and nothing tells anyone. Like D5: the dashboard should make this key, with the scopes read from the shop's assistants. | open |
| G30 | 5 | The key made here is **`fn_pk_test_…`**; the developer guide shows `fn_pk_…`, Help and the served line show `fn_pk_live_…`. Nothing says what `test` / `live` mean. (In the code: `test` only marks a key made on a NEURA that is not production — it works the same.) `test` also sounds like **practice mode**, which it is not (G22). | An owner sees `test` in their key and thinks the shop is in practice mode, or that the key is a trial one. Small. | open |
| G31 | 5 | **FEATURES.md** says *Suggestions that go with it* appear on the **Shop page** — *"a block on the shop's own product or basket page — **not a chat**"*. Since ADR-0041 (2026-09-24) they appear **in the chat panel**; the on-page block (`pairs.js`, `<neura-pairs>`) still exists but no guide mentions it. The public website is written from FEATURES.md. | The website could promise a block on the shop's page that the developer guide never tells anyone how to build. | open |
| G32 | 5 | The guide gives **one fixed line** to paste, but the key is locked to **one exact address** — so a shop with a test site and a live site (or `www.` and no `www.`) needs **a different key for each**, and a line pasted into the template cannot change between them. The guide should say: keep the key (and NEURA's address) in the shop's settings, like the shop token, and let the page read them. Done that way here (`NEURA_CHAT_URL`, `NEURA_CHAT_KEY`). | The developer pastes the test key into the template; it goes live with the next release, and on the real shop every chat is refused. | **fixed in the guide, 2026-10-01**, and **corrected**: one key can cover several exact addresses (`allowed_origins` is a list; `ORIGINS=` takes several), so the guide says *send every address* and *keep the key in the shop's settings* |
| G33 | 5 | **The first chat message ever, an easy one, was handed to a person.** *"Do you have green tea?"*, asked on the Green Tea product page (the shop has it, in stock): the local router model (`llama3.2:3b`, role map `ollama-dev`) gave confidence **0.00** — on the **first** message, with no history — so CARE handed over (`routing confidence 0.00 is below 0.5`), no tool used. A20 knew 0.00 only **after** a handover; this is new. The shopper was told *"I'm passing you to a colleague"* — but no one is told (no notifications, G15), and the shop is **live** (G22), so a real shopper would have seen it. | The very first thing a new owner sees is their assistant giving up on the easiest question. It says nothing about the product on the cloud models (A20: 0.95–1.00 there), but step 6 on `ollama-dev` would mostly grade the small local model. **For the owner (step 6): which model setup to practise with.** | open — to discuss at step 6. **Seen again 2026-10-02**, the first time the owner chatted after pressing *Go live* on Ceylon Harvester (NEURA on `ollama-dev`, the local models): **5 of 5 messages handed over**, CARE `product_qa` three times (*"Do you sell cinnamon tea bags?"*, *"what do you have prodcuts"*), SELL `compare` and `needs_person`. The question kind was found each time, so the hand-over came after. **Confirmed the same day from the API's own log** (no AI run; the API was started on 2026-09-30 by an earlier Claude session, writing to a scratch file): the three CARE messages: the local router (`llama3.2:3b`) named the kind right, `product_qa`, with **confidence 0.00**, so *"routing confidence 0.00 is below 0.5"*, no tool used; SELL's gift question: the router sent it to SELL (0.8), SELL searched, and the fact check refused the draft, *"unsupported claim: Both are under 2000 LKR and make thoughtful gifts for a tea lover"*; SELL's repeat of it: the router called it `needs_person`, a hand-over by design. All three causes are the small local models (agent-runtime.md; the 2026-09-19 decision: CARE and SELL are finished on the cloud model, the local path is untested) |
| G34 | 5 | **A key in the chat socket's address is written, in full, into NEURA's log.** The chat box sends its key as `/v1/stream?token=fn_pk_…`, and the web server's own request line (`"WebSocket /v1/stream?token=…" [accepted]`) prints it — that line does not pass through our redaction filter. The socket accepts **any** key there (`authenticate_request(token=…)`), so a shop's server using a **secret** `fn_sk_` key on the socket would leave that secret in the log. Harmless for this public key; seen in the log for this step. | A secret key sitting in plain text in a server log file — anyone who can read the logs can use it. Not a guide problem: a code fix (hide the query string in the request log, or refuse secret keys in the address). | **fixed, 2026-09-30** — the log hides keys in addresses; a secret key in an address is refused |
| G35 | 6 | **CARE told a shopper a SOLD-OUT product is available.** *"Is cardamom in stock?"* → *"Yes, we have Green Cardamom Pods 50g **available to buy** for 1650.00 LKR."* The shop says `in_stock: false`, quantity 0. Cause, in our code: the search-result line CARE's AI reads (`care/tools/render.py`, `product_summary` → `_availability`) says **"available to buy"** whenever the product's *status* is active — **it carries no stock at all** — and CARE only searched, it never called `check_stock`. The fact check **passed**, because the reply matched what it was given. (SELL, in the same chat, said cardamom is *out of stock* — its evidence has stock.) The file's own comment tells the same story about *"on sale"*: a phrase with two meanings gets published in the wrong one. | **Harmful.** The shopper orders, or travels to buy it, and it is not there. Not a guide problem — a code fix, with an eval case (Rule 4). | **fixed, 2026-09-30** — unit tests + eval case product_qa_008 (passes on Gemini) |
| G36 | 6 | **SELL cannot see a short product id, so a true recommendation was blocked.** The gift reply was correct — *"brisk, bright, strong brew from Nuwara Eliya"* is the shop's own description of product 4 — but the fact check failed it and it was handed to a person. Cause: SELL decides which products a reply *cites* with a pattern that needs **3+ characters** (`_CITED` in `sell/evidence.py` and `sell/nodes/respond.py`). This shop's ids are **1 character** (`3`, `4`, `5`), so no product counts as cited, every description is hidden from the fact check, and any claim taken from a description fails. Proven: `4` → not cited, `1303` → cited. The Bagisto shop's 4-digit ids hid it. The same pattern is `respond.py`'s check that a reply cites only shortlisted products — blind for these ids too. | Every small new shop (products 1–99) gets its best recommendations thrown away and handed to a person. Code fix + eval case. | **fixed, 2026-09-30** — unit tests + eval case recommend_005 (passes on Gemini); injection 1.00 |
| G37 | 6 | **CARE told a shopper about a product the shop has not released.** *"Do you sell cinnamon tea bags?"* → *"We have Cinnamon Tea Bags (25) listed for 750.00 LKR, but they are not currently available."* The product is **not active** in the shop (its own website hides it); the bridge sends it as `draft`, as the step-1 table notes the guide never says what to do with it. NEURA shows it, with its price. Neither the guide nor the specification says whether a bridge should send drafts, or that NEURA will mention them. | A shop preparing a launch finds its new product and price told to shoppers by the chat box before the launch. **The owner's call** whether this is wrong (see *Decisions* when made). | **fixed, 2026-09-30** — eval case product_qa_009 passes (local models) |
| G38 | 6 | **"Returns go to a person" (the G5 decision) is not what happens.** *"What is your return policy?"* → *"I cannot confirm… I can pass you to a colleague who can help."* — recorded as **Answered**, no handover. The shopper must ask a second time to reach a person. | The owner expects returns questions in the handed-over list; they are not there, and the shopper leaves without an answer. | open |
| G39 | 6 | **Review says the products were deleted when they were not.** For the gift reply, *What it looked at* shows three cards: *"This source is no longer in the search index — it may have been deleted or re-indexed since this turn ran."* The three products were read from the shop (the search tool) and **were never in a search index** — this shop has none (G21), and search by meaning was off (`cloud-prod`, no embedder). | The owner thinks three of their products vanished. | **fixed, 2026-09-30** |
| G40 | 6 | **The sidebar's Review number goes stale.** The owner saw **Review 5** in the menu while the page said **To review 6**. Loaded fresh, both say 6 — the menu is counted when the page first loads and not again when new replies arrive. | Small: the owner may think they have finished reviewing. | **fixed, 2026-09-30** |
| G41 | 7 | **SELL's replies show the shopper our internal product ids.** The reply text itself says *"Enamel Camp Mug 350ml **(Product 4)**"* — and on Ceylon Harvester *"Ceylon Black Tea BOPF 400g **(Product 4)**"*; on the test shop *"(p_socks_1)"*. The compose prompt tells the AI to use the ids when naming products (that is how the fact check and the cards know which product is meant), and nothing removes them before the shopper reads the reply. Found in the G36 test run. | A shopper reads *"(p_socks_1)"* or *"(Product 4)"* — it looks broken, and means nothing to them. Needs a decision on how ids are hidden without breaking G36's citations. | **fixed in code, 2026-09-30** — AI run owed (T3); Review still shows the ids |
| G42 | 7 | **40 of our integration tests fail on the committed code, and nothing noticed.** Found while checking G34: `tests/integration/test_api_postgres.py` — streaming, review queue, usage, webhooks and more. One cause seen in all the ones read: the tests' **fake AI reply** (`_Response`, line 184) has no `structured_repairs` field, which the real code reads since commit `737532e` (*"count every model call…"*). `make check` runs only the unit tests, so the integration suite is never run by the gate and went stale. | Tests that exist but fail are worse than none: nobody trusts them, and a real break (like one G34 could have caused) hides among the 40. Probably a one-line fix in the fake; the owner decides. | **fixed, 2026-09-30** — 445 of 445 pass (`0082a99`), and `make check` now runs them |
| G43 | 7 | **The integration tests share the development database with the test shops.** One job test compared the exact list of accounts with work due, and failed when the Bagisto test shop's real job came due. Found the first time `make check` ran the integration suite (G42). | A test that fails on its own when a real shop's job is due trains everyone to ignore red. Fixed in the test; a separate test database would remove the whole class of problem — **not decided**. | fixed in the test, 2026-09-30 |
| G45 | 7 | **Our new step 1 text (A1, waiting for the owner's review) makes two promises the code does not keep.** Found 2026-10-01 while checking section 2 against the code. (a) *"Not sure what the shop needs? … Nothing breaks: what the assistant can't answer, it hands to the shop's team."* — an address left out means the assistant is not offered that tool at all; a returns question without policies is only *offered* a person (G38), and a handover reaches nobody who can reply (G44). (b) The third group, *"Only for order questions — for a shop that wants the assistant to look up orders"*: from the chat box, **every order question goes to a person today** (G16, FEATURES.md L1); building these three addresses does not change that. | The developer builds the order addresses expecting the chat box to answer *"where is my order?"*; the owner expects handed-over shoppers to get an answer. | skipped by the owner (no guide change); the real fix, A21, comes after the guide work (see *Decisions*) |
| G46 | 7 | **The check tool passes addresses that do not exist.** Tested 2026-10-01, no AI: a fake bridge (scratch only) that lists 9 capabilities but has built only `/health` — `/products` returns an empty list, every other address answers **404** → **"18 passed · 0 failed · 1 warning — Conformant. This store can be connected."** With `/products` missing too: 16 passed, 1 failed (`pagination.limit`). Cause: NEURA reads a 404 as *not found* (`generic/client.py` `_decode` → `None`) — right for a mistyped order number, but it makes a missing address look exactly like an empty one. **The same happens with shoppers:** a listed address that is not built reads as *nothing there* — list `product.search` before search works, and the assistant says *"we could not find …"* about products the shop sells. Stronger than G18 (wrong answers pass): here **no answers at all** pass. | FiveNeurals connects a shop on a green result that checked nothing, and shoppers are told the shop lacks what it sells. | open — the guide now warns (step 2, A2); the tool fix is undecided (with G10, G18) — e.g. the tool asks for one real product id to test with |
| G47 | 7 | **NEURA calls any shop address it is given, with no check on where it points.** Found 2026-10-01 while discussing D2 / D5 with the owner: `POST /v1/stores` takes `base_url` as any text (`routes/stores.py`), and nothing in NEURA refuses a private or internal address (no check for `localhost`, `10.x`, `169.254.169.254` and the like). Safe today only because a connection is saved by FiveNeurals alone. **Once the owner types the bridge's address in the dashboard (D2, D5), anyone with a dashboard account could make NEURA's server call our own internal addresses** and read the check's results (known as SSRF). | A courier who delivers to any address you write, even into the company's own back office. Must be designed in before the dashboard takes an address: only public web addresses. | **fixed, 2026-10-01** (`neura_api/addresses.py`, both doors): production calls only `https://` public addresses. **Open:** DNS rebinding (ADR-0052 §3) |
| G48 | 7 | **One wrong token makes the check tool report 8 failures, most with the wrong advice.** Found 2026-10-01 while gathering real data for the D2 mockup (no AI): `neura-conformance` against the Ceylon Harvester bridge with a wrong token → **"6 passed · 8 failed"**: `products.get_missing` *"→ Return None. Customers mistype ids constantly"*, `products.search_empty` *"→ Return an empty page"*, `pagination.limit` *"→ The collection envelope is …"*, and five more. Only 3 of the 8 lines mention the token; none says it is the **only** problem. The same bridge with the right token passes 19 of 19. | A car that lights 8 warning lamps when the only problem is the wrong key: the developer starts "fixing" code that works. The most likely first-time mistake. **For D2:** the dashboard's simple result must spot *"your shop refused our token"* first and say only that; the tool's own output should do the same. | **fixed in the dashboard, 2026-10-01**: one sentence first (*Your shop refused the token*); the terminal tool's own output is unchanged |
| G49 | 7 | **"Make a new token" cannot stop the old token at once, and the approved mockup says it does.** Found 2026-10-01 while writing the ADR for D2 / D5. The shop token is checked by **the shop's bridge**, not by NEURA (the bridge compares it with its own setting, `NEURA_SHOP_TOKEN`). A new token made in the dashboard means NEURA **stops sending** the old one at once, but the bridge **still accepts** the old one until the developer puts the new one in its settings. So a leaked token keeps working for whoever holds it until then. D5's own text (*"Make a new one stops the old one"*) and boards 31, 34 and 35 say the opposite. | Changing a lock: NEURA only holds a copy of the key; the lock is in the shop. Throwing our copy away does not change the lock. The screen must say: *"Tell your developer at once: the old token works in your shop until they put the new one in."* | fixed in the design, 2026-10-01: ADR-0052 §2, and the mockup's words (boards 31, 34, 35) |
| G44 | 7 | **A handover from the chat box reaches nobody who can answer the shopper.** Raised by the owner while discussing G38: *"a person needs time to answer — if the shopper leaves, they never get the reply."* Checked: it is worse — **nobody can reply in the chat at all.** The dashboard's Conversations has no way to write back (no reply route in `console_conversations.py`); the chat is kept only per browser tab (`sessionStorage`), so it is gone when the shopper closes the tab; and an anonymous shopper left no way to be contacted. FEATURES.md already says so (*L2: "Your team gets the whole story — not a person replies"*), but the chat box tells the shopper *"I'm passing you to a colleague"*. **Industry tools** reply live from an inbox, and when nobody is online they take the shopper's email and answer later. **Here both are outside what is decided:** *sending anything to a shopper* is excluded (CLAUDE.md), and taking an email a shopper types is *volunteered data*, which ADR-0042 does not permit yet (ADR-0046 stage 2 is blocked on the same thing). | The shopper is promised a colleague who never comes. This is a product decision, not a bug fix: **a design session and an ADR**, not code. Not to be designed alone. | open — to discuss (design session) |
| G50 | 7 | **The check fails a bridge that built only the "first three" addresses, and gives the wrong advice.** Found 2026-10-01 while checking guide step 3 against the code. No AI: a fake bridge in the scratch folder (`first_three_check.py`), run through the dashboard's own check code (`diagnose`, `check_adapter`, `outcome`). The check always tests the token on `/orders` (`auth.required`, `auth.rejects_wrong_token` in `generic/http_checks.py`), even when the bridge does not list orders. Many frameworks answer **404** for an address that was never built, before any token check. Ceylon Harvester's own Laravel bridge does: `/neura/v1/not-built` answers 404 with no token and with a wrong token. A bridge like that with only `/health`, `/products` and `/products/{id}` gets **12 passed · 2 failed**: *"/orders answered an unauthenticated request with HTTP 404 … anyone who learns this URL can read the store's orders"* and *"The token is being ignored rather than verified"*. Both are untrue, and the owner's **Connect stays locked**. The same bridge, checking the token first for everything under its prefix (401 before 404), passes 14 of 14. Yet guide step 1 says *"Build the first three, connect, and add the rest later."* | The guide's "start small" path cannot connect, and the developer is sent looking for a security hole that does not exist. Story: an inspector tests the lock of a room that was never built, and writes "anyone can walk into this room". | **fixed, 2026-10-01** (the owner chose: fix the check). The check tests the token on orders only in a shop that lists them, otherwise on its products; no guide change |
| G51 | 7 | **A clean check always shows the owner the same seven lines, even for things the shop does not do.** `PASSED_WORDS` (`apps/neura-console/src/lib/shop.ts`) is a fixed list, shown under *Your shop passed the check* (`connect-shop.tsx`, `Passed`) whatever the bridge listed. The G50 bridge that passes (products only) shows *"Orders can be looked up"* and *"It can send only what changed"*: it built neither, and the check never tested them. The mockup used Ceylon Harvester's real result (all nine addresses built), where every line happened to be true. | The owner believes the shop can do things it cannot, on the one screen meant to say what is true. Story: a hotel inspection report that ticks "pool: clean" for a hotel with no pool. | open (dashboard text: show only what the check tested) |
| G52 | 7 | **Once connected, the bridge's address cannot be changed or removed.** Found while writing guide step 3. *Connect* saves the address that passed the check; afterwards the dashboard offers only *Check again* and *Make a new token* for that address. `POST /v1/stores` with another address adds a **second** connection (a connection is unique per shop and address, `StoreConnectionRepository.connect`), and `disconnect()` exists in the code but nothing calls it: no screen, no command, no API. | A developer has a test copy of the shop checked, the owner presses Connect, and the shop stays connected to the test copy: shoppers get its products and prices, and only a code change undoes it. The same for a shop that moves to a new web address. Story: a parcel service that keeps your old address for ever, with no form to change it. | open: guide step 3 says *send your live shop's address*; a way to change it is a dashboard idea (D8) |
| G53 | 7 | **The full check's advice is written for us, not for the developer who now reads it.** Since D2 the owner copies the full check to the developer, and some lines name our own code instead of what the bridge should answer: *"get_product() raised for a missing id … → Return None"* (a bridge answers **404**), *"search_products() raised on an empty query"*, *"Map platform statuses to ProductStatus"*, *"the enums in the spec"* (a file the developer cannot get, G17). One hint states an unmeasured number as fact: *"Returns and shipping questions are a third of support volume"* (CLAUDE.md §4). | The developer cannot act on advice about functions they have never seen. Story: a mechanic's report written in the factory's own part numbers. | open (group D: the check's wording) |
| G55 | 7 | **A secret key pasted into the chat box line works, so the mistake goes unnoticed while the secret sits in the page.** Found 2026-10-01 while checking guide step 5 against the code (read only, nothing run). The chat box first opens its live connection with the key in the address; since G34 a secret key there is refused at the handshake (`dependencies.py`). The widget then falls back to a plain request with the key in the `Authorization` header (`widget.js`, *"REST for the rest of the session"*), and that is accepted: a secret key is not tied to any web address (`ApiKey.permits_origin`: *"Secret keys are not origin-locked"*), and NEURA lets the browser read the answer for any key that passed (`middleware/cors.py` `_permits`). So with an `fn_sk_…` key that has chat rights in `data-neura-key`, the chat box simply works, and the secret key is in every page's source. | Anyone can copy the key from the page and use all its rights, not only chatting: a key with `stores:write` could point the shop at another server (G19). Story: a house key taped to the front door. The door still opens, so nobody notices. | **fixed, 2026-10-01** (the owner saw it as serious and asked for the fix). A secret key with a browser's `Origin` header is refused on its shape, before any lookup (`SECRET_KEY_IN_PAGE`), and the page may read that one refusal, so the chat box says why. Proven: a real secret key from a page got **200 on the old code, 401 on the new**; from a server it still works. The guide says NEURA refuses it |
| G56 | 7 | **A refused chat box key shows the shopper two errors, one of them the browser's raw text, and neither says why.** Tested 2026-10-01 in headless Chrome, no AI (scratch `refused_key_check.py`): a page on an address the key does not allow, one message → **"We could not reach the assistant. Please check your connection and try again."** and then **"Failed to fetch"**. The same with a made-up secret key. Two causes: the live connection's close renders the first error, then the backup plain request fails and the widget shows the browser's own `TypeError` text (`viaRest`: `err.message`); and NEURA's refusal cannot be read by the page at all, on purpose (`middleware/cors.py`: no header without a caller, so a refusal is no oracle). An offline shopper gets the same two lines. **Also corrects Claude's own step 5 text (A5, not yet reviewed):** it said the chat box shows *"This key is not permitted from that origin"*; it never does. | The developer cannot tell a wrong address from a network problem, and a shopper reads "Failed to fetch". Story: a door that says "check your internet" when the real problem is the wrong key. | open (widget: one plain error, never the browser's raw text; group D). Step 5's sentence corrected the same day |
| G57 | 7 | **A shop token pasted into the chat box line fails, but the chat box can't say why, and the token sits in the page.** Found 2026-10-01 while explaining the three keys to the owner (read only). The shop token (`fn_st_…`, made in the dashboard) is the bridge's password: it reads products, orders and customers. Put in `data-neura-key` by mistake, NEURA refuses it as an unknown key, unreadable by the page, so the chat box shows only G56's errors while the token is readable in the page's source. Unlike G55 the chat does fail, so it is likely caught in testing, but by then the token may already be on a test site. | Anyone who copies it can read the shop's customers and orders straight from the bridge. Story: the warehouse key left on the shop counter. | open (group D: the G55 rule could also name it, *"This is the shop token: it belongs in the bridge's settings, never in a page"*) |
| G54 | 7 | **The dashboard's Home still says connecting is done outside the dashboard.** Its *Needs you* item for a shop not yet connected says *"Connecting is done outside the console for now"* (`apps/neura-console/src/app/console/[tenantId]/page.tsx`). Untrue since ADR-0052 was built: the owner connects on Shop connection. The ADR's list of docs to change missed this screen. | The owner reads that they cannot connect, on the first screen they see. Small. | open (dashboard text) |
| G58 | 7 | **Nothing a developer can get shows what a product view looks like.** Found 2026-10-01 while checking the guide's *Optional: product views* against the code (read only, no AI). The guide's example is not a request: *"type: product.viewed (with in_stock) · cart.added"*. The OpenAPI file on the website covers only the bridge's nine addresses, and NEURA's own API description is switched off in production (`main.py`: `openapi_url=None`). The real body has six fields with strict rules (`neura_core/observation/models.py`): `event_id` (the shop's own, 16 to 64 characters; a retry with the same one is counted once), `session_id` (16 to 128), `type`, `product_id`, `occurred_at` (with a timezone; not older than 7 days, not more than 5 minutes ahead), `in_stock` (required on a view, refused on a basket add). Ids may hold only letters, digits, `_` and `-`. **Any other field is refused with a 400.** | The developer cannot send one valid event without guessing six names and their rules, and every wrong guess is a 400. Story: a form handed over with no labels on its boxes. | **fixed in the guide, 2026-10-01** (A6: a real example request, every field with its rules, and the answers) |
| G59 | 7 | **A product whose id has a dot, a slash, a colon or a space can never be counted as viewed.** The bridge format lets a product's `external_id` be any text (OpenAPI `Product.external_id`: a plain string), but `POST /v1/observe/events` takes only letters, digits, `_` and `-` in `product_id` (`_OPAQUE`, written so an email or a name cannot pass as a session id, and used for the product id too). Tested on the model, no AI: `1042` and `TEA-400` accepted; `TEA.400G`, `gid://shop/Product/1` and `SKU 12` refused. | A shop whose ids look like `TEA.400G` gets a 400 for every view, and its Sold out list stays empty for ever. Story: a post office that takes every address except one with a full stop in the house number. | **the guide states today's limit, 2026-10-01** (A6). Still to decide: NEURA accepts every id the bridge format allows |
| G60 | 7 | **The guide does not say what the shop's side must build before sending product views: the switch, and the shoppers' consent.** ADR-0044 §3: the switch lives **in the shop**, off by default, and off means nothing is sent (NEURA has no switch; a filter at our end is not one). ADR-0044 §5: the owner's switch **is not the shopper's consent**; the shop needs its own, and the data agreement states that obligation (ADR-0048: *"the bridge cannot know whether a shopper agreed"*). The guide says only *"Off by default, and off means nothing is sent. Check the switch before the event exists"*: it never says the developer builds that setting, who turns it on, or that consent is the shop's to collect. | A developer sends every visitor's views from day one, with no setting and no consent banner, which ADR-0044 calls *"our problem as well as theirs"*. Story: a shop fits a door counter and forgets the sign that says the door counts people. | **fixed in the guide, 2026-10-01** (A6: who does what; you build the setting, off by default; the shop owner turns it on once the shop asks its shoppers) |
| G61 | 7 | **The product views section is written in our own bridge's words.** Its title says *"for NEURA-SELL's Sold out list"*, a name a developer does not know. (**Corrected the same day:** Claude first wrote here that every shop has the Sold out screen. Wrong: the API route is not gated, but the dashboard lists the screen only for a shop with NEURA-SELL, `shop-sidebar.tsx`.) *If something doesn't work* says *"nothing on your server is sending the queued events"*: a queue is how our reference bridge sends them, not something the guide ever asked a developer to build. | The developer reads about parts they never built. Small. Story: assembly instructions that say "tighten bolt B7" for a kit with no B7. | **fixed in the guide, 2026-10-01**: the title (A6), and the *queued events* line (A8) |
| G62 | 7 | **Every error NEURA sends points the developer to a website that does not exist.** Each error has a `docs_url`, `https://docs.fiveneurals.com/errors/<CODE>` (`neura_api/errors.py`, `neura_core/errors.py`); checked 2026-10-01, that name has no address at all (no DNS answer), and the public website has no error pages (its own address is not decided either, `site.ts`). | The developer follows the one link the error gives them and gets nothing, at the exact moment they are stuck. Story: a warning light whose manual page was never printed. | open (to decide: error pages on the public website, or drop `docs_url` until they exist) |
| G63 | 7 | **The guide never says what NEURA does for the shop, so its optional parts mean nothing to a developer.** Raised by the owner, 2026-10-01, reading *"Optional: product views (for NEURA-SELL's Sold out list)"*: *"we need to list features first, then the developer can understand."* The top says only *"NEURA's assistants answer shoppers"*; nowhere does the guide name what the shop gets (the chat box answers questions and helps choose, suggestions, the owner's Sold out list, notifications to the shop's server). So *Sold out list*, *suggestions* and *change messages* arrive as names with no meaning, and a developer cannot tell which optional part their shop wants. (FEATURES.md has the full list, written for owners.) **The owner, same day: the website already shows the features**, and the developer guide is a separate part of it (*Docs*). Checked: the product pages describe each one (`/` NEURA-CARE, `/sell/` NEURA-SELL, which has a *Sold out* block, *"Optional · you switch it on"*), and the Docs home (`/docs/`) says what the two assistants do, with *Product views, optional* in *How it works*. The developer guide links to none of them, and the feature blocks have no anchor to link to. So the fix is **a link from the guide to the feature, not a new list.** | The developer skips an optional part the owner wanted, or builds one nobody asked for. Story: a builder handed a list of extra sockets to fit, without being told which rooms they are for. | **fixed for product views, 2026-10-01** (A6: a sentence and a link to the Sold out block on `/sell/`, which has an anchor now). Claude's first idea, a new list in the guide, dropped |
| G64 | 7 | **Some wrong requests get "An internal error occurred" (500) instead of a 400 that says what is wrong.** Found 2026-10-01 while proving the product views section with real requests (scratch `views_check.py`, the throwaway *Connect Test 1*, no AI). A view without `in_stock`, a basket add with `in_stock`, and an `occurred_at` with no time zone each got **500 `INTERNAL_ERROR`**; other mistakes (an extra field, a short `event_id`, a dot in a product id) got a proper 400 naming the field. Cause, in `neura_api/errors.py`: the 400 handler puts pydantic's `exc.errors()` into the answer as it is, and an error raised by **our own** check carries the Python `ValueError` (and sometimes the date itself) inside it, which cannot be turned into JSON, so the handler itself crashes. It touches every NEURA address whose request has a check of our own, not only product views. | The developer reads "internal error", thinks NEURA is broken, and waits for us, when one field was wrong. And it looks like an outage in our own error counts. Story: a ticket machine that, when you press the wrong button, shows "out of order" instead of "choose a destination". | **fixed, 2026-10-01** (the owner chose: fix it before rewriting the section). Test first: 500 on the old code, 400 naming the field on the new; proven on the live API too |
| G65 | 7 | **The owner guide's link to the developer guide does not look like a link.** Found 2026-10-01 in headless Chrome while checking the product views section (scratch `views_page_check.py`): in *Before you start* (`/docs/owners/`), *"Send them the developer guide"*, the words *developer guide* are a link with **no underline and the same colour as the text around it** (`rgb(64, 64, 64)` both). The site's reset takes links' colour and underline away, and this link adds neither back. | The owner never finds the page they are told to send to their developer. Small. Story: a door painted the same colour as the wall. | open (group B, the owner guide) |
| G66 | 7 | **The OpenAPI file teaches developers to build change messages that NEURA cannot receive.** Found 2026-10-01 while checking the guide's *Change messages* against the code (read only). The file developers download (`/spec/openapi.json`) has a `webhooks` part, `entityChanged`, *"Tell us something changed"*: how to sign each message (HMAC-SHA256, `X-Neura-Signature`, `X-Neura-Timestamp`), *"deliver at least once… duplicates are safe, silence is not"*. Nothing in it says that NEURA has **no address that receives them** (tested 2026-09-30: `405`, *Messages between the shop and NEURA*), nor where to send them, nor who gives the shared secret. The guide's own section says *"Your bridge may tell NEURA when a product or order changes"*, and its last box says *"Where this page and the specification disagree, the specification is right"*. | A careful developer builds, signs and queues change messages for days, and they go nowhere. Story: a manual that explains how to wire a doorbell to a house that has no bell. | **fixed in the guide, 2026-10-01** (A7), **and in the OpenAPI file, 2026-10-02** (ADR-0053 §5): `entityChanged` now begins *"Not used yet: NEURA has no address that receives these. Do not build them"*, tested |
| G67 | 7 | **The guide says to press *Sync now* after adding products or changing stock, as if the assistant would not see them otherwise.** It does: the chat box's answers, the suggestions and the connection for AI assistants ask the bridge **live** (CARE and SELL tools, `pairing/compute.py` and `orchestrate.py`, the MCP server's tools all call the adapter). Only **NEURA's own copy** waits for *Sync now*: the dashboard's product lists (Suggestions, Sold out names, Review) and the product feed (`sell/console.py`, `feed/`, `console_sold_out.py`). | The owner presses *Sync now* after every stock change for nothing, or a developer thinks the chat shows yesterday's stock. Small. Story: a sign saying "refresh the shop window after restocking" in a shop where customers walk straight to the shelf. | **fixed in the guide, 2026-10-01** (A7: *You lose nothing*, the chat box asks your bridge live) |
| G68 | 7 | **The developer guide's *If something doesn't work* is out of date and misses the messages a developer actually gets.** Found 2026-10-01 while checking it against the code. *Every request is refused* says the token is *"different from the one FiveNeurals holds"*: since ADR-0052 the shop owner makes it in their dashboard. None of its rows is a line the full check prints, though the developer now receives that text from the owner (*The bridge refused the shop token*, *Could not reach the address*, *there is no bridge at this address*, *its "status" is not "ok"*, `jobs/shop_check.py`). It has no row for the chat box's real refusals (*We could not reach the assistant*, *A secret key may not be used from a web page*, G55, G56), nor for the assistant saying the shop lacks what it sells (G46). Its product views row is G61's *queued events*. **The owner guide's list (`lib/steps.ts` `TROUBLE`) has the same old facts**: *"the address FiveNeurals has"*, *"FiveNeurals can make a new one"*, *Press Sync now* for a missing stock change (G67), and a long dash. | The developer meets a message the guide never mentions, at the moment they need the guide most. Story: a car manual whose warning-light page shows lights the car doesn't have, and not the one that is on. | **fixed in the developer guide, 2026-10-01** (A8). The owner guide's list: group B |
| G69 | 7 | **A bridge that leaves out a product's `status` gets nothing recommended, and nothing warns.** Found 2026-10-01 while preparing G4 (read in the code, not run). A missing `status` becomes `unknown` (`neura_domain/commerce.py`). NEURA-SELL keeps **only `active`** products (`sell/tools/catalogue.py`: *sellable*), and so do the suggestions (`pairing/select.py`) and the product feed (`feed/publishable.py`); CARE hides only `draft` and `archived`, so it still answers. The check's `products.status_vocabulary` passes a missing status and `unknown`, and gives only a ⚠ (which does not stop Connect) for a value it does not know, such as `enabled`. The OpenAPI file shows `status` as optional, default `unknown`; the guide's sample now sends `active`, but no sentence says it matters. | A shop connects, the chat answers questions, but asked *"what should I buy?"* it finds nothing, every time. Story: a shop puts every product on the shelf without a price tag, and the cashier refuses to sell anything untagged, without telling anyone why. | open (the owner declined G4's table, so the guide does not say it; the check: to decide, e.g. a ⚠ when no product is `active`) |
| G70 | 7 | **The OpenAPI file tells developers to run a tool they cannot get.** Found 2026-10-02 while building ADR-0053's teacher (read in `generic/spec.py` `_DESCRIPTION`): the file's own description ends *"Run `neura-conformance --url <your endpoint> --token <token>` to check an implementation"*. `neura-conformance` exists only inside our code (G10); since ADR-0052 the shop owner runs the check in the dashboard. | The first thing a careful developer tries fails: no such command. Story: a manual that says "test it with the factory's machine" to someone who has no factory. | **fixed, 2026-10-02** (ADR-0053's build, step 2): the file now says the shop owner checks an implementation in their NEURA dashboard; a test fails if the teacher ever says `neura-conformance` |
| G71 | 7 | **The dashboard's Help (*Connecting your shop*) still says three things the developer guide has corrected.** Found 2026-10-02 while preparing ADR-0053 step 7, the Help mockup (read only: `apps/neura-console/src/lib/help.ts`, `components/help/copy-steps.tsx`, `.../[tenantId]/help/page.tsx`). **(a) Sync now:** step 3 says *"After that, press Sync now whenever you add products or change stock"*, and *If something doesn't work* says a missing product or stock change means *"Press Sync now"*. The chat box asks the bridge live (G67); only NEURA's copy, used by the dashboard's lists, waits for *Sync now*. **(b) The developer guide is named but not linked:** *For your developer* ends *"The full technical guide covers the nine addresses, change messages and product views"*, plain text with no link, and *Copy these steps for your developer* does not name the guide at all. Shop connection already has the link (`DEVELOPER_GUIDE_URL`, `neura.fiveneurals.com/docs/developers/`, ADR-0051's address, not online yet). And *change messages* are the ones the guide now says not to build (G66, A7). **(c) 7 long dashes** the owner reads or copies, in 6 lines (the page's first paragraph, the placeholder sentence, the two-keys sentence, a trouble row, the copied text's chat box heading, the *Couldn't copy* message), against the owner's rule. | (a) The owner presses *Sync now* after every stock change for nothing. (b) The owner is told a guide exists and cannot find it to send; the copied steps, the one thing sent to a developer, never mention it. Story: a receptionist who says "it's in the manual" and doesn't say where the manual is. | **(b) fixed, and (c) fixed in the box and the copied steps, 2026-10-02** (ADR-0053 step 7). **Still open (group B):** (a) *Sync now*, and the long dashes in Help's first paragraph and one *If something doesn't work* row |
| G72 | 7 | **A shop's mode is read once, when a shopper's chat opens, and kept for as long as the shopper keeps talking.** Found 2026-10-02 while designing D11, the *Go live* switch (read only). The chat box's live connection is authenticated at the handshake (`stream.py`), and that one `caller`, the shop's settings included, serves every message on it; `turns.py` takes the mode from `turn.caller.tenant.config.mode`. The connection closes only after 5 minutes of silence (`IDLE_TIMEOUT_S = 300`). A plain request reads the settings afresh each time. | Once *Back to practice mode* exists, a shopper already chatting keeps getting live replies the owner has just switched off, for as long as they keep talking. (The other way round is safe: after *Go live* they stay in practice until they reconnect.) Today the only way to change a mode is a script, with the same gap. Story: the shop closes the counter, but the customers already in the queue keep being served. | **fixed, 2026-10-02** (ADR-0054 §6): the turn reads the mode from the shop's row when the reply is released. Test first: through a real chat socket, live, then switched to practice (on the old code the reply was still `resolved`), then back |
| G73 | 7 | **Why a live reply was handed to a person is kept nowhere but the API's terminal.** Found 2026-10-02 while finding out why the owner's five test messages were all handed over (G33). The conversation stores only `state = escalated` and the question's kind; `conversation_messages` has no reason; the audit log records only blocked attacks (`guard.py`; `escalation` and `tool.decision` are defined and written by nothing, as `review.py` already notes); a reason is kept only for practice-mode replies (`shadow_turns.verify_reason`). The API prints it to its own output, which is gone when that output is not kept (here it was kept only because an earlier session started the API writing to a scratch file). | Once a shop is live, nobody can say afterwards why a shopper was handed over: the owner can't, and neither can we. Story: a till that records *refund given* but never why. | open (a design question: where a handover's reason is kept, and whether the owner sees it in Conversations) |

### Messages between the shop and NEURA (checked 2026-09-30)

| Message | Direction | Built in NEURA? | Built in this shop's bridge (step 1)? |
|:--|:--|:--|:--|
| *"A product or order changed"* (change messages, `events.realtime`) | shop → NEURA | **No** — defined in the specification, but NEURA has **no address that receives them** | **No, on purpose** — nothing would receive them. Comes with *keeping our copy fresh*, which the owner deferred |
| *"A shopper viewed a product / added to basket"* (product views, for NEURA-SELL's *Sold out*) | shop's server → NEURA | Yes — optional, off by default, needs a data agreement | Not yet — the guide's optional section; to decide later for this shop |
| *"A chat needs a person"* and others (notifications, outbound webhooks) | NEURA → shop's server | Yes — `POST /v1/webhooks` | Not yet — and **not in the guide at all** (G15) |

**Tested 2026-09-30, because the owner remembered change messages working.** On the older test shop (whose bridge
*does* send them), the shop's own *product changed* message for product 1303 was sent the same way an admin save
sends it (`DeliverWebhook::dispatchSync('product.updated', '1303')`, nothing in the shop changed):

| Test | Result |
|:--|:--|
| **A.** To where that shop sends it today — `http://127.0.0.1:8787/webhook` (an old test address) | **Failed** — nothing is listening there |
| **B.** To NEURA's own server — `http://localhost:8010/v1/webhooks/commerce` (the address the bridge's README names) | **Failed** — `405`: NEURA has no such address |
| **C.** NEURA's copy of product 1303 afterwards | **Unchanged** — still from 2026-09-27 |

**What the owner remembers is right about the shop's side**: the shop sends the message, signed correctly — that was
tested before (the signature and the sending). **NEURA's side was never built**: no address receives the message, so
nothing is updated. That shop also has **21 old messages** waiting in its queue for the 8787 address.

**Checked again 2026-10-01, because the owner remembered product changes being built** (while reviewing guide section A7). The owner is half right: **built** are the shop's side (the Bagisto test shop's bridge, `Listeners/EntityChanged.php` and `Jobs/DeliverWebhook.php`, signed and tested) and NEURA's **signature check**, `neura_adapters.generic.webhooks.verify()`, with unit tests, which **nothing calls**. **Not built:** an address in NEURA that receives the message (a `POST` to `/v1/webhooks/commerce` answered `405` again; `/v1/events` and `/v1/commerce/events` `404`), and anything that updates NEURA's copy. Git history: `webhooks/commerce` has only ever appeared in docs, never in code. NEURA's own `/v1/webhooks` routes are the other direction (NEURA → the shop's server, G15). Story: the doorbell button is wired, the camera that checks who is pressing works, but there is no bell.

**Order of work for change messages (agreed 2026-09-30):** first **we** build NEURA's receiving address (part of
*keeping our copy fresh*, deferred); only then does the guide ask developers to send them — as an **optional extra
step**, not step 1, because the basics work without it (NEURA reads the shop directly). Until then the guide must
say plainly: *do not build change messages yet* (G13).

### The keys a connection uses (checked 2026-09-30)

| Key | Secret? | Direction | What it can do | Needed? |
|:--|:--|:--|:--|:--|
| **Shop token** | secret | NEURA → shop | **Read** the shop through the nine addresses — products, stock, categories, orders, customers, policies. **Cannot change anything**: every address only reads. Leaked, it exposes customers' names, emails and addresses. | yes — step 4 |
| **Chat box key** (`fn_pk_…`) | public | shop's pages → NEURA | Lets the chat box talk to NEURA — **only from the shop's own web address** | yes — step 5 |
| **Product views key** (`fn_sk_…`, `observe:write`) | secret | shop's server → NEURA | Sends product views for *Sold out*; needs the data agreement first | optional |

FiveNeurals also uses a key of its own to **save** the connection (`stores:write`, `POST /v1/stores`) — only because
there is no command or screen for it; the owner and developer never see it.

### Decisions (the owner's)

| # | Question | Decision |
|:--|:--|:--|
| G3 | **How is a shop token made, and how does it reach the developer?** Today: no command; nothing written. | **Decided by the owner, 2026-09-30: the dashboard makes it** (D5) — shown once, with *make a new one* to replace a leaked one. For this test: made by hand, as FiveNeurals would today. How it reaches the developer safely: still to decide |
| G24 | The chat box line on Help points at port 8000 (another project). Fix NEURA's setting, or type the address by hand? | **Decided by the owner, 2026-09-30: fix the setting** — `PUBLIC_BASE_URL=http://localhost:8010` in NEURA's `.env`, API restarted, so Help shows the line a real developer would copy. (Found while doing it: the `.env` also says `NEURA_API_PORT=8000`; NEURA runs on 8010 only because it is started with `NEURA_API_PORT=8010` typed on the command line — the `.env` line was left as it is.) |
| Step 7 | In what order? | **Decided by the owner, 2026-09-30: the code bugs first** — G35 (harmful) first, then G36, G34, G37, G39, G40 — then the guide fixes, then the dashboard ideas (mockup first). None had to be fixed before step 7: no real shopper uses NEURA, and this shop is in practice mode. All must be fixed **before any real shop goes live** |
| G34 | A key in the chat socket's address is written into NEURA's log. How to fix? | **Decided by the owner, 2026-09-30: both** — (A) the log hides any key in an address, and (B) NEURA refuses a **secret** key in an address; only the public chat box key may travel that way |
| G42 | The integration tests went stale because `make check` never ran them. Add them? | **Decided by the owner, 2026-09-30: yes.** `make check` now runs `test-integration` too (needs the database: `make up`); green, about 1 min 40 s. AGENTS.md says so. Also found: GitHub CI runs them only on pushes to `main` and on pull requests, and the commit that broke them (`737532e`) **is on `main`** — so CI there has probably been red since late August unnoticed (not confirmed: no `gh` tool here; see GitHub → Actions) |
| G38 / G44 | Returns questions are only *offered* to a person; and a handover reaches nobody who can reply (no reply in the dashboard, the chat is gone when the tab closes). What now? | **Decided by the owner, 2026-09-30: C, for EVERY handover, not only returns** — the shopper is told honestly that the assistant cannot answer and **how to contact the shop** (email / phone the owner sets once in the dashboard — D7). **Then decided (owner): the message says only *"please contact our store"* with the shop's contact details — no chat code, no buttons.** (Claude had proposed a chat code, then *Email us / WhatsApp us* buttons with the question pre-written; the owner chose the simplest. Buttons can come later.) The current sentence (*"passing you to a colleague… you won't need to explain it again"*) is untrue today and goes. **Live replies or taking a shopper's email: a design session and an ADR later** (outside today's rules) |
| G41 | SELL's replies show our internal product ids to the shopper (*"(Product 4)"*). | **Decided by the owner, 2026-09-30: remove them before the shopper reads the reply.** The ids stay in the draft, where the fact check, the rejected-product check and the cards need them (G36) |
| Step 7, group A | How to change the developer guide (built from an approved mockup)? | **Decided by the owner, 2026-10-01: change the text directly, no new mockup — but more human-friendly and easier to look at, and section by section:** Claude changes one section, shows a screenshot and says simply what changed, the owner reviews, then the next. **And (owner, same day): the guide is written for ANY shop, not this one** — no Ceylon Harvester names, products or numbers; neutral examples (`yourshop.example`); each finding becomes a general rule that helps every shop |
| Step 7, group A | The long dash (—) in the guide? | **Decided by the owner, 2026-10-01: do not use it.** Readers see it as a sign of AI writing. Use a comma, a colon or a new sentence; a plain `-` only where a dash is really needed. Applies to every section as it is rewritten, and to messages to the owner. **Then (owner, same day, "ok remove"):** the 7 left in the top, *Before you start* and step 1, written before the rule, are taken out too |
| Step 7, group A | Screenshots for each section? | **Decided by the owner, 2026-10-01: no.** The owner looks at the running page (`localhost:3100/docs/developers/`) in their own browser. Claude says simply what changed; it may still check the phone width for itself, without sending pictures |
| G45 | Step 1 promises (a) a handover to the shop's team and (b) order answers in the chat box. Change the words? | **Decided by the owner, 2026-10-01:** (a) **no change**, the sentence stays. (b) the owner sees it as a real gap to fix in NEURA, not only in the guide, and gave the direction: **a shopper who is not signed in is told to sign in, because the chat box cannot know who they are; a shopper signed in to the shop gets their order answered.** This is [A21](open-questions.md) (a short-lived pass from the shop's server, never the browser's own word), so it needs a design session, an ADR and a security review before any code. **When:** asked the owner (Claude's advice: the guide says the truth now, finish group A, then A21 first in group F). **Then the owner, same day: skip G45, no change to step 1 at all; continue the guide work, and after it start the sign-in and order questions work (A21).** |
| D2 | Step 3 says *"Ask FiveNeurals for the check tool"*, but there is nothing to hand over (G10). Write the truth for now, or build the dashboard check first? | **Decided by the owner, 2026-10-01: build it in the dashboard now** (D2), in the dashboard shop owners already have. A **developer role** with only the pages it needs comes later (D3, roles need an ADR). The owner asked about the key: the full check needs the **shop token**, which today FiveNeurals makes by hand, so **D5 (the owner makes the token) comes with it**. Guide step 3 waits and is rewritten once this is built. Next: the mockup (console work cycle), with G47 designed in. **Mockup published 2026-10-01**: the owner's design canvas, row 10, boards 31-35 (*Connect your shop from the dashboard*, Ceylon Harvester's real address and real check results, G48 shown as one sentence). **Approved by the owner, 2026-10-01 ("the mockup looking good"); build only what the mockup shows (D2 + D5, with G47 and G48); the other D ideas later, each with its own mockup.** **ADR-0052 written the same day** (`docs/architecture/adr/0052-the-shop-owner-connects-their-own-shop.md`); **Approved by the owner the same day, with Claude's two additions**: the check runs in the background (job queue, like Sync now; no extra calls to the shop) and token events go to the audit log. **BUILT the same day** (console.md §3.4, *Connect your shop*): `make check` green (1400 unit, 453 integration), `make console-check` 109/109, a live API run 24/24 and a real-Chrome run of the whole flow 25/25. **Committed by the owner's request, 2026-10-01** (two commits: the guide's top and steps 1-2, then this). Test accounts made for it (throwaway, never a real test shop): `tn_01M3VKQV1JN31A8GPY1H4TQHQZ`, `tn_01M3VMWZ1B3GVGJVRCP8C6YHS2`, `tn_01M3VN2V6K414K235ED5AC0E0M` (*Connect Test 1-3*), sign-in `connect-test@example.test`; remove with `make tenant-drop` when no longer useful. **Next for the guide (group A):** steps 3 and 4 now describe the dashboard: the owner makes the token, the developer builds, the owner checks and connects. Building it needs a short ADR first (console.md 3.4 left the connect form out on purpose, and the console never shows a stored token) |
| G37 | CARE told a shopper about a product the shop has not released (`draft`). Is that wrong? | **Decided by the owner, 2026-09-30 (by grading it *Not good*): yes — NEURA must not mention a product the shop does not show.** *"This product is not in the product list in our shop."* Fix at step 7: the guide says what `draft` means, and NEURA keeps drafts away from shoppers |
| G22 | The shop starts live and nothing can switch practice mode on. Switch it on for this test? | **Decided by the owner, 2026-09-30: yes.** Done the only way there is — a one-off script (session scratch folder, `TenantRepository.set_config`, `mode` → `shadow`), as FiveNeurals would have to today. `make tenant-show` now says `SHADOW`. The real fix (a command, and a dashboard switch) stays open for step 7 |
| G33 | Which AI models for step 6? | **Decided by the owner, 2026-09-30: `cloud-prod` (Gemini for every role), for step 6 only**, then back to `ollama-dev`. Set on the command line when NEURA starts (`NEURA_ROLE_MAP=cloud-prod`), so NEURA's `.env` still says `ollama-dev` and a plain restart goes back to it. Known while it is on: all of NEURA uses it (the Bagisto shop too); no search by meaning (no cloud embedder set); Gemini may cost a little |
| — | NEURA's `.env` said `NEURA_API_PORT=8000`, but NEURA runs on 8010 only because the port is typed each time | **Decided by the owner, 2026-09-30: change it to 8010.** Done — a plain `make api` now starts on the right port |
| G50 | The check fails a shop that built only the guide's first three addresses (it tests the token on `/orders`, which that shop never built). Fix the check, or add a rule to the guide? | **Decided by the owner, 2026-10-01: fix the check.** Explained with a house inspector who checks the lock of a garage the house does not have. The guide needs no change. Also said by the owner in this discussion: the developer role will get the dashboard later (D3) |
| Step 7, group A | The developer guide says *Shop owner* for pressing Check and Connect, but a developer role is planned (D3). Why not *You*? | **Decided by the owner, 2026-10-01:** keep *Shop owner* while it is true, because today no developer account exists (every account is an owner's and can read shoppers' chats, G9). **When D3 is built, change the guide to *You*.** Written into D3's row and beside the guide's lines, so it is not forgotten |
| G55 | A secret key pasted into the chat box line works quietly, while anyone can read it in the page. Fix now or later? | **Decided by the owner, 2026-10-01: serious, fix it now** (explained as a house key taped to the front door). Fixed the same day: NEURA refuses a secret key that comes from a web page, and the chat box says why |
| G25 | *"Every page"* would put the chat box on the admin pages too. Which pages? | **Decided by the owner, 2026-09-30: shopper pages only** — the `home` layout; not the admin (`app`) |
| G27 | Basket suggestions use an AI call per product, with **no way to turn that off**. Add a switch? | **Decided by the owner, 2026-09-30: yes — the shop owner chooses, in the dashboard** (D6). *"If they don't need it, the owner can decide."* Off means suggestions still show, chosen from the products' own words (free). The guide must also say it uses AI. Needs a small ADR at step 7, because ADR-0045 fixed how pairing works |
| G63 | The guide's *Optional: product views* names a *Sold out list* the developer has never heard of. List the features in the guide? And why is it optional, when it comes with NEURA-SELL? | **Decided by the owner, 2026-10-01:** the website's product pages already describe every feature (`/`, `/sell/`), so the guide **links to them** and does not repeat a list. Product views **stay optional**, because watching shoppers is the shop owner's choice, off by default (ADR-0044), and needs a data agreement and the shoppers' consent; the section says plainly that it is **part of NEURA-SELL**, and to ask the shop owner whether they want it. (Making it required for every NEURA-SELL shop would need an ADR replacing ADR-0044.) |
| A7 | The developer guide's *Change messages*: keep the section? Under what name? | **Decided by the owner, 2026-10-01:** keep it, headed **Webhooks to NEURA**, because a developer knows the word *webhook*. (The other direction, NEURA → the shop's server, is G15, still to add.) |
| G1 | The guide shows no sample answer for any address. Where should samples go? | **Decided by the owner, 2026-10-01:** **one** sample, a product, on the guide page (step 1). Only the guide page changes; no checker, and not all nine addresses. The rest, and examples inside the OpenAPI file, later if wanted |
| G4 | A *fit your shop's data* table in step 1 (statuses, sale price, no policies, order words)? | **Decided by the owner, 2026-10-01: no.** Thinking that way, there would be many things to add. G69 (a missing `status`) stays open for a fix in the check |
| G15, G16 | Add *Webhooks from NEURA* (G15)? Say in the guide that order questions from the chat box go to a person (G16)? | **G16: skipped by the owner, 2026-10-01**, like G45 (A21 is the real fix). **G15: not decided**: Claude's advice was to skip it for now (not necessary: the chat works without it, and today nobody can reply to a handed-over shopper anyway, G44); the owner moved on to E6, the MCP server for developers, without answering |
| E6 (design session, Q1) | An MCP server for developers: what should the first version do? | **Decided by the owner, 2026-10-02: *teacher only*.** It tells the developer's AI tool what the bridge must answer, in which format, with samples, so the AI can help write the bridge (the AI writes most of the code, the developer guides, reviews and tests; NEURA never sees the shop's code). **No account and no token** to use it: it is public, like the guide. The bridge itself still checks the shop token (any test text while building, the owner's real one before the check). **Checking a bridge (the *inspector*) is a later step** with its own questions: who the developer is (D3, or a key from the owner), NEURA calling a typed address (G47), or publishing the check code (blueprint §11.5, open source). Design session continues; an ADR before any code (CLAUDE.md) |
| E6 (Q2) | Where does the developer MCP run? | **Decided by the owner, 2026-10-02: NEURA runs it** (a remote MCP server on NEURA's own address). The developer pastes one address into their AI tool; every developer gets a rule change at once; none of our code is published. Because anyone can call it, it needs a limit on how often. (Not chosen: a package the developer installs, which can teach an old format and publishes our code) |
| E6 (Q3) | What does the developer MCP teach? | **Decided by the owner, 2026-10-02: everything** (*"need to give all the things"*): the format of all nine answers, a sample for each, **and the rules developers get wrong** (customers only, never staff, G7; `"active"` for products on sale, G69; drafts stay hidden, G37; the exact `"ok"`, G14; the token on every address but `/health`; and the *fit your data* rules the owner kept off the guide page, G4, because here an AI reads them, not a person) |
| E6 (Q4) | How do developers find out about the developer MCP? | **Decided by the owner, 2026-10-02: B, the guide and the dashboard.** The developer guide's *Before you start* says it (*"Using an AI coding tool? Add this address to it"*), **and** the shop owner's Help (*Copy these steps for your developer*). The dashboard part follows the console work cycle: mockup on the design canvas, the owner's approval, then build. (Claude had advised the guide now, Help later) |
| E6 (ADR) | Write the design session's answers down | **ADR-0053 written 2026-10-02, status Proposed, waiting for the owner's approval** (`docs/architecture/adr/0053-a-developers-ai-tool-may-ask-neura-how-to-build-a-bridge.md`). Claude's additions for the owner to approve: the address `POST /v1/developers/mcp`; four tools; the JSON-RPC framing moves out of `agents/sell` to a shared package; the content is built from the code and tested (E8 answered explicitly for this surface); G66's sentence goes into the OpenAPI file in the same change |
| E6 (ADR, best practice) | The owner asked whether the design follows industry standards and best practice, and can grow. | Claude's honest answer: mostly, not completely; five improvements proposed and **added to ADR-0053 with the owner's yes, 2026-10-02** (after asking the cost: no money; a real AI tool test uses a model, so asked first): (1) the **official MCP library**, stateless, plain JSON, pinned (fallback: SELL's hand-made framing, moved to a shared package); (2) **tried with real AI tools** before announcing (*MCP Inspector*, then one AI coding tool with the owner's yes); (3) the MCP **read-only labels** and structured answers; (4) every answer names the **format version** it teaches, so a 2.0 can be taught beside 1.0; (5) tool calls **counted, never read**. **ADR-0053 approved by the owner the same day (*"yes"*): Accepted.** Building starts, in its §7 order |
| E6 (build) | ADR-0053's build, in its §7 order | **Step 1, 2026-10-02:** the official MCP library (`mcp` 2.2.0, capped below 3) fits with no change to any library the project uses; it speaks MCP 2026-07-28 (SELL's hand-made server: 2025-06-18). Committed. **Step 2 (with step 4):** `neura_adapters/generic/teacher.py`, the content: the nine addresses in the guide's three groups, a sample request and answer for each (one small shop: the guide's sock product, its category, stock, one customer and one order), 17 rules. Test first (`tests/unit/test_developer_teacher.py`, 19 tests): every sample is read by the real `GenericAdapter` over a fake shop, no field the OpenAPI file does not know, every capability word an assistant needs is taught, every other word is ruled out, every status word comes from the enums, no platform name, never `neura-conformance` (G70), the format version on every answer. The OpenAPI file's two sentences fixed (G66, G70), regenerated with `make spec`. `make check` green (1432 unit, 454 integration), `make web-check` green **Step 3, 2026-10-02:** `POST /v1/developers/mcp` (`neura_api/developer_mcp.py`), on the official library: four tools with the MCP read-only labels and declared output formats; stateless, plain JSON; NEURA's host only, and a request with `Origin` (a web page) refused (403; another host 421); a limit per client address, fingerprinted, never stored (`RATE_LIMIT_DEVELOPER_MCP`, 60 a minute, a guess), a 429 in our error shape; one log line per call, tool and format version only. **What building decided:** NEURA's API may not import the adapter package (the import contracts, Rule 1's fence), so the teacher is **discovered** through an entry point, `neura.bridge_teacher`, exactly as adapters are; the session manager starts in the API's lifespan, because a mounted app's own lifespan never runs. Test first (`tests/unit/test_developer_mcp.py`, 14 tests), driven by **the MCP project's own client** in both eras (the 2025 handshake and 2026-07-28's self-contained requests). Proven on the live API: a handshake answers 200 with the limit headers and no session; `tools/list` gives the four tools, read-only. `make check` green (1446 unit, 454 integration, 7 of 7 contracts) **Step 5, 2026-10-02: MCP Inspector** (the MCP project's free test tool, command-line mode, no AI model) against the live API: lists the four tools with their labels, and a real call (`get_address /products/{id}`) answers the sample. Its **strict** check warned that `sample_answer` was declared as *anything*; test first (failed on exactly that field), then declared as one object or a list of objects; strict now clean. **Then the real AI tool test, the owner's choice A (light), 2026-10-02:** a separate Claude Code run (2.1.286, model `claude-haiku-4-5`) from an empty scratch folder, so it knew nothing of this repository, given **only** the address (`--mcp-config`, `--strict-mcp-config`, built-in tools off). Asked four developer questions; it found the four tools by itself, called `list_addresses`, `get_address /products/{id}`, `get_rules products`, `get_rules` (no errors, 5 turns, **$0.034**), and all four answers were right: the first three addresses; the sock sample, word for word; `"active"`, and that a missing status means never recommended; do not build webhooks to NEURA yet. Scratch `devtest/run.jsonl` |
| E6 (step 7) | Where in the dashboard does the developer MCP's address go? Help only, or Shop connection too, whose step 2 already has *Copy the guide link for your developer*? And no setting? | **Decided by the owner, 2026-10-02: A, Help only.** Shop connection does not change: its guide link already leads to the guide, whose *Before you start* shows the address (A11), so a developer has one way in and the owner's main screen shows no technical address. Help's *For your developer* box gets the guide link (G71 b) and the AI tool address as one short line, both also in *Copy these steps for your developer*, and that box loses its long dashes (G71 c). **Words only: no setting, switch or connection in the dashboard, and the MCP server itself does not change** (the owner asked). G71 (a), *Sync now*, waits for the rest of group B. **Mockup published the same day**: the owner's design canvas, row 11, boards 36 (desktop) and 37 (phone), *Help: an address for your developer's AI tool*, Ceylon Harvester and the chat box line this NEURA serves; the rest of Help drawn as *As today*. **Approved by the owner the same day (*"yes built it"*) and BUILT**: `GET /v1/widget/snippet` gains `developer_mcp_url` (the API makes the address from its public address, as for the chat box line; test first, failed on the old code); Help's box as the mockup, the copied steps end with the guide and the AI tool address; six new `make console-check` checks, all failing on the old page first, then passing (115 of 115; one earlier run lost its browser connection and was re-run); desktop and phone seen in headless Chrome (no sideways scroll; the phone's copy button made full width to match board 37); `make check` green (1448 unit, 454 integration, 7 of 7 contracts). console.md and FEATURES.md updated; canvas row 11 retitled *approved and built*. **ADR-0053 is fully built** |
| Step 7, after E6 | What comes next? | **Decided by the owner, 2026-10-02: the most important fixes first, from the next step on** (*"most important fixes need to do firstly"*), not the order of the groups. Claude proposes an order by harm (shoppers and security first, then what misleads the owner, then wording) for the owner to choose |
| G22 (step 7, first fix) | The owner chose G22 as the first of the most important fixes. How does practice mode get switched: a command for FiveNeurals (A) or a button in the dashboard (B)? | **Decided by the owner, 2026-10-02: B, a *Go live* button in the dashboard, for the shop owner** (D11). Claude had advised A now, B later. Checked first (read only): practice mode works inside NEURA (`TenantConfig.mode`, `shadow` withholds every reply, ADR-0020's note to the shopper), and **nothing can switch it**: no screen, no command, no API; Help and Review tell the owner to *decide when to go live*. Already decided in the docs and kept: a mode is per shop **and** per kind of question (`shadow_intents`, agent-runtime.md §6), and practice *wins ties*, so a mistake can only withhold (`modes.py`). Next: the design questions, one at a time, then a mockup and a short ADR (a new thing the dashboard writes, as ADR-0052) |
| D11 (Q1) | When may the shop owner press *Go live*? Any time (A), or only after checking enough replies (B)? | **Decided by the owner, 2026-10-02: A, any time.** Before it switches, a confirm box shows what the owner has checked so far in Review (e.g. *"You checked 6 replies: 5 good, 1 harmful"*), facts only; the owner decides. Not B: its number (*at least 20, none harmful*) would be invented, and nothing has been measured (CLAUDE.md §4). Going back to practice mode, the safe direction, is one press at any time (Claude's proposal, not asked separately) |
| D11 (Q2) | When FiveNeurals creates a new shop, does it start in practice mode (A) or live, as today (B)? | **Decided by the owner, 2026-10-02: A, new shops start in practice mode.** The owner checks replies in Review, then presses *Go live*. Shops that already exist do not change. How (Claude, for the ADR): the shop is created with practice mode written in its settings (`make tenant-new`, `scripts/tenant_admin.py`), **not** by changing `TenantConfig.mode`'s default, which would also decide the mode of any shop whose stored settings never named one |
| D11 (Q3) | Where in the dashboard does the switch go: Home (A) or Review (B)? | **Decided by the owner, 2026-10-02: A, on Home**, in the top section that already says *Practice mode is on* / *Your assistant is live*: **Go live** in practice, **Back to practice mode** when live. (The owner first read *box* as the chat box: explained, it is the dashboard's Home page; shoppers never see the button.) Next: the mockup |
| D11 (build) | Build it with a mockup first? | **Decided by the owner, 2026-10-02: no mockup** (*"no need to do mockup reason it is just a button. you can directly build that"*). Claude wrote the short ADR first (CLAUDE.md), **ADR-0054**, from the owner's answers, with two additions reported with the build: §5 only the `mode` key is written, with an audit entry (any member may switch; D3's developer role must not get it), and §6 the G72 fix. **BUILT the same day**, test first throughout: G72 through a real chat socket (failed on the old code: `resolved`, not `shadowed`); `PUT /v1/console/shops/{t}/mode`, 9 integration tests (failed: no route); a new shop in practice mode, 1 unit test (failed: no settings passed); Home's buttons, 7 `make console-check` checks (3 failed before the buttons existed). `make check` green (1450 unit, 464 integration, types, 7 of 7 contracts); `make console-check` 122 of 122 (one run before lost its browser connection in Review and was re-run); desktop and phone seen in headless Chrome. Help's step 5 says where the button is; FEATURES.md, console.md, agent-runtime.md §6 and the runbook updated. **The owner's public guide (`/docs/owners/`) still says *decide when to go live*: true, not changed (it would be a section for the owner's review)** |
| G5 | The shop has no policies — what does the bridge do? Checked: NEURA-CARE still works without them, but **every returns or shipping question goes to a person** (the policy tool is simply not offered). | **Decided by the owner, 2026-09-30:** leave policies out for this shop (`policy.read` not declared), and the dashboard will **show it in red** (D1) |

### Ideas for the dashboard (collected during the connection; designed together at the end, mockup first)

| # | Idea | From |
|:--|:--|:--|
| D1 | **Show every item the shop can send** on Shop connection: ✓ when it sends it, **red ✗ when it does not**, with what that means (*"Your shop doesn't send policies, so returns and shipping questions go to your team"*). Builds on the existing **Check now**. | The owner, 2026-09-30 (G8) |
| D2 | **Run the full check (the check tool) from the owner's dashboard**, in two levels: **simple** for the owner (the D1 list in plain words), **technical** for the developer — a **"Copy the full check for your developer"** button, like Help's *Copy these steps for your developer*. Answers G10 for now, without handing over our code. | The owner, 2026-09-30 (G9, G10) |
| D3 | **Later: a developer account** the owner invites, seeing only Shop connection and Help — never shoppers' chats. Needs roles (group C, an ADR). **The owner, 2026-10-01:** the developer role will get this dashboard, and the developer guide should then send the developer there to test (step 3: *press Check yourself*). Claude: agreed, but it does not fix G50, because the check gives the same wrong answer whoever presses it. **Part of D3's done (the owner asked that this is not forgotten, 2026-10-01):** the developer guide (`apps/neura-web/src/app/docs/developers/page.tsx`) changes with it. Steps 3 and 4 say *Shop owner* for pressing Check and Connect, and the top list's *who* says *You and the shop owner* / *The shop owner*; once a developer can press them, those become *You*. | Discussed 2026-09-30 (G9) |
| D4 | **Keep every list of what a shop sends in step.** Today it is written by hand in about 7 places — the list in our code (`neura_domain/enums.py`), the OpenAPI file, the written specification, the check tool (`neura_commerce/conformance.py`), the dashboard's list (`apps/neura-console/src/lib/shop.ts`), the developer guide (`apps/neura-web/.../docs/developers/page.tsx`), `INTEGRATION_GUIDE.md`. Proposed: **(1) a rule** for CLAUDE.md — *a change to what NEURA asks of a shop (an address or a capability, added, changed or removed) is not finished until the specification, the check tool, the dashboard's list and the developer guide say the same*; **(2) an automatic test** that fails when something is in the code's list but missing from the dashboard's list or the developer guide. | The owner, 2026-09-30 — **approved**: the rule and the test, done at the end with the other dashboard changes |
| D5 | **The owner makes the shop token in the dashboard** (Shop connection): a strong random token, **shown once**, stored locked away; **"Make a new one"** stops the old one (today there is no way to replace a leaked token either). Safe delivery to the developer (a password manager or a one-time link, never plain email) to be written in the guide. | The owner, 2026-09-30 (G3) |
| D6 | **A switch in the dashboard to turn off AI in basket suggestions.** On: NEURA asks the AI once per product what goes with it (today's behaviour). Off: suggestions still show, picked from the products' own words — no AI, no cost. The owner decides per shop. Needs a small ADR (ADR-0045 fixed the behaviour; a switch changes it, it does not delete it). | The owner, 2026-09-30 (G27) |
| D7 | **The shop's contact details, set once by the owner** (email and/or phone) — used in every handover message so the shopper knows how to reach the shop. Shown as *"Please contact our store: …"* — nothing else (owner, 2026-09-30). Mockup first. | The owner, 2026-09-30 (G38, G44) |
| D8 | **Change the bridge's address after connecting**: for a shop that moves to a new web address, or a test copy connected by mistake. Today nothing can (G52). Needs a design and a mockup. | Claude, 2026-10-01 (G52) |
| D9 | **Soon: the owner makes the chat box key (`fn_pk_`) in the dashboard**, like the shop token (D5). The owner gives the shop's exact web addresses (one key can hold several); the permissions come from the shop's assistants, never typed by hand (today FiveNeurals types 11 into a command, and one typo quietly breaks part of the chat box, G29). Every shop needs this key. Needs a short ADR (it adds to what the dashboard may write, as ADR-0052 did) and a mockup. | Claude, agreed by the owner to list, 2026-10-01 (G29, G55) |
| D10 | **Later: the owner makes a secret key (`fn_sk_`) in the dashboard**, for the optional extras only (product views need the data agreement on record first). Shown once, like the shop token. Needs a short ADR and a mockup. | Claude, agreed by the owner to list, 2026-10-01 (G55) |
| D11 | **A *Go live* button in the dashboard** (and back to practice mode): the shop owner switches practice mode off and on, today impossible (G22). Designed with the owner (Q1 to Q3), **no mockup (the owner: *"it is just a button"*), ADR-0054, built 2026-10-02**. | The owner, 2026-10-02 (G22) |

### Recommendations to make connecting easier (Claude, 2026-09-30 — for the owner to choose)

| # | Recommendation | Why it helps |
|:--|:--|:--|
| E1 | **Fix the guide**: start with *download the OpenAPI file*; give a test token at the start; one example answer per address; a *how to fit your data* section (no sizes → one variant; no policies → what happens; a status table); *customers only, never staff*. (G1–G7) | The developer stops guessing. |
| E2 | **"Build only what you need"** — a table per assistant: NEURA-SELL 3 addresses, NEURA-CARE 6, the rest optional. (G11) | Less work; a shop can start small and add more later. |
| E3 | **A starter kit**: a ready example bridge the developer copies and fills in (the Ceylon Harvester bridge, made general, is a first one for PHP/Laravel). | Filling in blanks instead of starting from nothing. Needs a decision: where it lives, which languages. |
| E4 | **Give developers the check tool** (G10; D2 for now). | They can test alone. |
| E5 | **Later: ready-made add-ons** for popular shop systems — install, no code. Already planned as phase 2 ([ADR-0009](architecture/adr/0009-generic-commerce-interface.md)). | No code at all for the most common shops. |
| E6 | **An MCP server for developers** (the owner's idea, 2026-10-01): plugged into a developer's AI coding assistant, it gives the exact format of each address with an example, helps the AI write the bridge, and **runs the check tool** against the developer's bridge address — which would also answer G10. **Not built; not the same thing as NEURA-SELL's MCP server** (that one lets shoppers' AI agents read a shop's catalogue). Needs a design and an ADR first — e.g. our server calling an address a developer types needs rules (which addresses, how often, what it may see). | The developer's own AI does the reading, writing and checking. Logged for later; the guide is needed either way. |

### How this shop's data fits our format (the G4 detail, as found)

| Our format wants | This shop has | What the bridge does |
|:--|:--|:--|
| Products with **variants** (the buyable item, with its own stock) | One price and one stock count per product; size-like "variations" are picked in the cart and have no stock of their own | **One variant per product**, with the product's own id |
| `price`, `compare_at_price` | `price`, and an optional `discount_price` that the shop shows as the price | `discount_price` (when set) is the price; `price` becomes `compare_at_price` |
| `in_stock`, `stock_quantity` | `is_stock_available` and `available_qty` (stored as text); the shop sells only when both allow it | in stock = available **and** quantity ≥ 1 |
| Product `status` (`active`, `draft`, `archived`) | `is_active` yes / no | yes → `active`; no → `draft` (the guide does not say which) |
| `order_number` (what the customer calls it) | Customers see `#` and the order's id | the id |
| Order `status` (`pending`, `processing`, `shipped`, …) | `pending`, `confirmed`, `paid`, `shipped`, `delivered`, `canceled` / `cancelled` (both spellings used) | mapped one by one |
| Tracking (carrier, number) | none | left out |
| Payment `status` (`pending`, `paid`, `failed`, `refunded`, …) | also `canceled` — our list has no *cancelled payment* | `unknown` (the guide says unknown is the worst answer, but offers no better one) |
