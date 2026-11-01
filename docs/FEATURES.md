# FEATURES — what each assistant does, in plain words

**Last checked against the code:** 2026-09-30; NEURA-GROW's lines 2026-11-01.

This is the one list of what the product does. The public product site and the setup guides are written
from it, so a line here is a promise that a page may repeat.

- **One line per feature**, in words a shop owner understands.
- **Checked against the code, not the plans.** A feature that is designed but not built says so.
- **The rule:** *a feature is not finished until its line here is updated* (CLAUDE.md §6).
- **The public website** (`apps/neura-web`, [ADR-0051](architecture/adr/0051-the-public-website-is-its-own-app-and-says-only-what-the-code-does.md)) is written from this file. A change here that
  changes what a page says means that page changes in the same commit.
- **No numbers** — no results, percentages, prices or time estimates. None have been measured
  ([CLAUDE.md §4](../CLAUDE.md)).
- **No commerce platform names** ([Rule 1](../AGENTS.md)).

## How to read the tables

| Status | Meaning |
|:--|:--|
| ✅ **Built** | Works today, in the code. |
| ✅ **Built, off by default** | Works, but a shop must switch it on first. |
| 🟡 **Built, with a limit** | Works, but a limit a public page must not hide — see *Limits* below. |
| ⬜ **Decided, not built** | An accepted ADR says what it is. No code. |
| ⬜ **Not designed** | Nothing is decided. Do not describe it anywhere. |

| Where it runs | What that is |
|:--|:--|
| **Chat box** | The assistant a shopper talks to, on the shop's pages. |
| **Dashboard** | The shop owner's console. |
| **For AI tools** | A connection other AI assistants use to read the shop's catalogue. |
| **Shop's server** | Something the shop's own server sends to us. Nothing of ours runs in a shopper's browser for it. |
| **For developers** | Something the shop's developer uses while building the bridge. A shopper never meets it. |

---

## NEURA-CARE — answers what the shop has

The shopper asks, CARE answers from the shop's own data, and hands to a person when it cannot.

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **Order status** | Tells a shopper **signed in to the shop** where their order is: status, items, tracking. It first checks the order is **theirs**; for any other number the reply is the same *"no order with that reference"*, so nobody can guess real order numbers. A shopper who is not signed in is asked to sign in, or to contact the shop. | 🟡 Built, with a limit (L1) | Chat box | `agents/care/tools/orders.py`, `neura_core/tenancy/customer_pass.py`, ADR-0057 |
| **Product questions** | Answers questions about products — what it is, sizes, materials, whether it is in stock — from the shop's catalogue. | ✅ Built | Chat box | `agents/care/tools/catalogue.py` |
| **Returns and shipping questions** | Answers from the shop's own policy pages — returns, shipping, refunds, warranty, payment, privacy. Chosen by plain matching in code, no AI guessing which page applies. | ✅ Built | Chat box | `agents/care/tools/policies.py` |
| **Hand to a person** | Passes the chat to the shop's team when the shopper asks, when they want something changed or refunded, or when CARE cannot answer from the shop's data. The team gets the whole story: the question, what was looked up, and a draft reply that was **not** sent. **A shopper who is not signed in may leave their email in the chat box; a signed-in shopper is never asked** (the shop already has their email). The chat then waits in the dashboard, and the shop's Owner or Support **answers from the shop's own email app**: NEURA sends nothing to a shopper. The shopper also reads the shop's own email or phone (set on Shop connection), and is never promised a person. **When CARE or SELL cannot help, they offer only that someone at the shop can answer**, and a shopper who says yes reaches the handover. | 🟡 Built, with a limit (L2) | Chat box → Dashboard | `graph/nodes/escalate.py`, ADR-0055, ADR-0062 |

## NEURA-SELL — helps the shopper choose

Read-only, like CARE. Six parts; only the chat is an assistant in the usual sense.

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **Recommend** | A shopper describes what they need; SELL shows products from the shop that fit, as product cards (picture, price, in stock or not, link). | ✅ Built | Chat box | `agents/sell/nodes/`, ADR-0023, ADR-0030 |
| **Compare** | A shopper names two or more products; SELL compares them from the shop's own descriptions. | ✅ Built | Chat box | `nodes/route.py` |
| **Honest "we don't carry that"** | When nothing fits, SELL says so, lists the shop's categories, and never pretends a near-miss fits. If the shopper's own budget ruled everything out, it says how many were found and at what price. | ✅ Built | Chat box | `nodes/no_match.py`, ADR-0027 |
| **Suggestions that go with it** | On a product or basket page, the chat box shows up to **two** products from the shop that go with what the shopper is looking at, in its own panel (it may open itself once per visit, if the shop switches that on). Chosen from the products' own words — **never** from what other people bought. Shows nothing rather than something silly. | ✅ Built | Chat box | `pairing/`, ADR-0040, ADR-0041, ADR-0045 |
| **The owner chooses suggestions** | The shop owner picks a product's suggestions (or *show nothing*) in the dashboard. Their choice wins over the automatic one, is the same for every shopper, and is how the owner upsells. | ✅ Built | Dashboard | `pairing/choices.py`, ADR-0050 |
| **Sold out — people still looking** | Lists the shop's sold-out products that shoppers kept viewing in the last 7 days, and says whether each is still sold out right now. Counts only — never who looked. | ✅ Built, off by default (stage 1; L3) | Dashboard | `console_sold_out.py`, ADR-0046 |
| **Rarely added to cart** | A second tab beside *Sold out*: products **in stock** that 10 or more visitors opened in the last 7 days and fewer than 1 in 10 of them added to the cart, so the owner knows which product pages to look at again. Counts only, never who looked; no AI. Says *added to cart*, never *bought* (orders are not copied). | ✅ Built, off by default (L3) | Dashboard | `console_sold_out.py`, ADR-0071 |
| **Product feed** | A private address that serves the shop's catalogue in a format machines read. Exists only after the shop turns it on; the address can be replaced or switched off. | ✅ Built, off by default | For AI tools | `feed/`, `routes.py` |
| **Connection for AI assistants (MCP)** | Other AI assistants can search the shop's catalogue, read a product, check stock and list categories — four read-only tools — through a key the shop controls. That key reaches one shop's catalogue and nothing else. | ✅ Built | For AI tools | `mcp/`, ADR-0023 |
| Sold out, stage 2 — *"email me when it's back"* in chat | — | ⬜ Blocked (needs a new data category in ADR-0042) | — | ADR-0046 |
| Sold out, stage 3 — logged-in customers | — | ⬜ Blocked (needs A21's identity token) | — | ADR-0046 |
| Recovery list — checkouts started and not finished | Shown to the owner, exported and sent **by the owner**. We never message a shopper. | ⬜ Decided, not built | Dashboard | ADR-0043 |

## NEURA-GROW — shows what the shop's pages are missing

No shopper talks to GROW: it has no chat. It reads the shop's chats once a night, in the background, and shows the owner what to add to the shop's pages, and what shoppers asked for that the shop doesn't sell. It also keeps the shop's special dates and writes a campaign plan for each, for the owner to post themselves. **FiveNeurals ticks it per shop.**

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **Missing from your pages** | The questions **at least 2 shoppers** asked in the last 30 days that the shop's pages don't answer (*"Is it organic?"*, *"Can I pay cash on delivery?"*), grouped by product, most asked first. Each says where to add the answer, with a link to the product's page. **GROW never writes the answer**: only the owner knows it. *See the chats* opens the chats behind a question; *I added it* takes it off the list until shoppers ask again. Counts only, never who asked. The Owner and Support see it, never the Developer. A line on Home says how many there are. | 🟡 Built, with a limit (L6) | Dashboard | `agents/grow/`, `console_gaps.py`, ADR-0064 |
| **Shoppers asked for** | The things **at least 2 shoppers** asked for in the last 30 days that the shop doesn't sell (*"Do you have matcha?"*), most asked first, so the owner can decide to start selling them. *See the chats* opens the chats behind each; *Hide* takes it off the list until shoppers ask for it again, and the hidden things are listed under the page with *Show again*. Counts only, never who asked. The Owner only. A line on the Owner's Home says how many there are. | 🟡 Built, with a limit (L6) | Dashboard | `agents/grow/`, `console_wanted.py`, ADR-0068 |
| **The night check** | Once a night, an AI reads each new reply that handed the shopper over, could not give a fact, or said the shop doesn't have something, and names the question or the thing asked for (one AI call per reply for both pages). A free word check first sends only those replies to the AI. Code checks every answer before it is stored: no links, emails, phone numbers or instructions. Inside the shop's daily spending limit. FiveNeurals can pause it for one shop. | 🟡 Built, with a limit (L6) | — | `agents/grow/scan.py`, ADR-0064, ADR-0065 |
| **Marketing calendar** | The shop's special dates for the year: Sri Lanka's festivals and payday, the worldwide shopping days (a shop in another country gets those only), and **the shop's own** (its birthday, a sale). The owner unticks what doesn't fit, once a year; no AI chooses the dates. **21 days before each kept date, an AI writes a campaign plan from the shop's own data**: a theme and the idea, 2 or 3 of its products, what its shoppers asked that matters for the date, when to post, and draft texts (three social posts, an email, a banner line) with **[your offer]** for the owner to fill in. Code checks every plan before it is shown: no price or offer, no health or *best* claim, no link, phone number or email. The owner edits, copies and **posts it themselves: nothing is posted, scheduled or sent**. *Make it again* asks for a fresh plan. The Owner and Support see it, never the Developer. Home says when a plan is ready, and when to add the year's dates. FiveNeurals can pause the plans for one shop. | 🟡 Built, with a limit (L7) | Dashboard | `agents/grow/campaign.py`, `console_calendar.py`, ADR-0072 |

## What both assistants share

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **One chat box, the right assistant** | The shopper never chooses an assistant. Each message goes to CARE or SELL by what it asks. | ✅ Built | Chat box | ADR-0031 |
| **Says it is AI** | Every assistant message carries *"You are chatting with an AI assistant."* — not only the first. | ✅ Built | Chat box | `widget.js` |
| **Read only** | Neither assistant can change anything in the shop — no refunds, cancels or edits. | ✅ Built | Everywhere | ADR-0010 |
| **Answers only from the shop's data** | Replies are checked against what was looked up; an answer that cannot be backed up is not sent. | ✅ Built | Chat box | `verify` node |
| **Protection from tricks** | Blocks known prompt tricks, and hides shoppers' emails and phone numbers from the AI. Rules in code, not a prompt. | ✅ Built | Chat box | ADR-0011 |
| **Practice mode** | The assistant works on real questions but the shopper does not get its reply; the owner reads and grades each one first. Shoppers see *"your message has been received"*. **A new shop starts in practice mode.** The owner presses **Go live** on Home when ready (it first shows what they checked in Review), and **Back to practice mode** at any time; a switch reaches chats already open. | ✅ Built | Chat box + Dashboard | ADR-0026, ADR-0054 |
| **Search by meaning** | Finds products by what the shopper means, not only matching words. Covers the products that have been indexed. | 🟡 Built, with a limit (L5) | Chat box | `neura-agent-core/rag`, ADR-0047 |
| **A copy of the catalogue** | We keep a copy of the shop's products to answer fast; **Sync now** refreshes it. | 🟡 Built, with a limit (L4) | Dashboard | `console_shop.py` |
| **Daily spending limit** | Near the limit the assistant does less; at the limit every chat passes to a person. | ✅ Built | — | ADR-0015 |
| **Product views** | The shop's server may tell us which products shoppers viewed and added to basket. **Off unless the shop switches it on**, needs a signed data agreement, and is deleted after 7 days. Feeds *Sold out*. | ✅ Built, off by default | Shop's server | ADR-0044, ADR-0048 |
| **Chats deleted after 90 days** | Conversations are deleted by a job, not only by a promise. | ✅ Built | — | ADR-0048 |
| **Notifications to the shop's systems** | Signed messages to the shop's server when a chat starts, is resolved, or is handed to a person (with the whole story). | ✅ Built | Shop's server | `neura-core/webhooks` |

### The dashboard

| Screen | What the owner does there | Status |
|:--|:--|:--|
| **Sign in** | A one-time link by email. No password. | ✅ Built |
| **Home** | One shop at a glance, starting with how many shoppers wait for an answer. Support and the Developer see only the parts about their own work, and never money or *Go live*. | ✅ Built |
| **Conversations** | Read every chat, search, filter by assistant. **Waiting for an answer**: the handed-over shoppers who left a way to reach them, with *Answer by email* (opens your own email app) and *Mark as answered* (their email is deleted). | ✅ Built |
| **Review** | Grade replies — the ones held in practice mode, and sent ones. | ✅ Built |
| **Suggestions** (NEURA-SELL) | See and choose what shows with each product. Shown only to a shop with NEURA-SELL. | ✅ Built |
| **Product views** (NEURA-SELL; called *Sold out* until 2026-11-01) | Two tabs: *Sold out*, sold-out products people kept looking at, and *Rarely added to cart*: in-stock products many opened and few added to the cart. Shown only to a shop with NEURA-SELL, to the Owner. | ✅ Built (ADR-0046, ADR-0071) |
| **Missing from your pages** (NEURA-GROW) | What shoppers asked that the shop's pages don't say, with *See the chats* and *I added it*. Shown only to a shop with NEURA-GROW, to the Owner and Support. | ✅ Built (ADR-0064) |
| **Shoppers asked for** (NEURA-GROW) | What shoppers asked for that the shop doesn't sell, with *See the chats* and *Hide*, and a *Hidden* list with *Show again*. Shown only to a shop with NEURA-GROW, to the Owner. | ✅ Built (ADR-0068, ADR-0070) |
| **Marketing calendar** (NEURA-GROW) | The shop's special dates for the year, and a campaign plan for each, written by AI 21 days before: read it, edit it, copy it and post it yourself. Shown only to a shop with NEURA-GROW, to the Owner and Support. | ✅ Built (ADR-0072, ADR-0073) |
| **Usage and cost** | Chats, AI use and its cost, by assistant. | ✅ Built |
| **Shop connection** | **The owner connects their own shop**: makes the shop token (shown once), checks the developer's bridge (the full check, said in plain words, with any *things to look at*, such as products that don't say they are on sale) and connects. Then a setup checklist, **Check again**, **Sync now**, what the shop lets the assistant do, and **a new token** for a leaked one. **The shop's contact details** (email, phone), named to a shopper the assistant cannot help, with the exact sentence they read. **The secret for order questions from signed-in shoppers** (shown once, *make a new one*), which the owner gives their developer. **Each secret says who made it.** The shop's developer, invited as Developer, sees and does everything on this page, except *Go live*. | ✅ Built (ADR-0052, ADR-0055, ADR-0057) |
| **Help** | *Connecting your shop*, step by step, and what to send your developer: the guide for developers, the address for an AI coding tool, and the chat box line. | ✅ Built |
| Settings and keys (the owner makes the chat box key) | — | ⬜ Not designed (needs an ADR) |
| **People and roles** (Owner, Support, Developer; invite by email) | The owner adds people to the shop's dashboard by email, each seeing only what their role allows, checked on every click; a developer never sees shoppers' chats. The owner changes a role or removes a person at any time, and a shop always keeps one Owner. Every change is kept in the shop's record, with who did it. | ✅ Built (ADR-0058, ADR-0059) |
| **Create an account** (sign up, then FiveNeurals approves) | A new shop owner signs up with their email, shop name and website, and confirms by an emailed link. The shop then waits for approval: nothing runs and nothing costs anything until FiveNeurals approves it and emails the owner. Someone who already has an account can sign up a second shop the same way. | ✅ Built (ADR-0058, ADR-0060) |
| **FiveNeurals admin** (our own area, never shown to a shop) | FiveNeurals approves or refuses shops that signed up (choosing their assistants), sees every shop's state, and the AI use and cost across all shops. It can also switch one feature off for one shop, and on again, when its AI costs too much (ADR-0065; today GROW's night check and the calendar's AI plans each have one). Shop facts only: no admin page can show a shopper's chat or details. Admins are added by command; an admin signs in again after 12 hours, and **types a code from an authenticator app on their phone at each sign-in** (ADR-0067; a lost phone is reset by another admin). | ✅ Built (ADR-0061, ADR-0065, ADR-0067) |

---

## For the shop's developer

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **A developer account** | The shop owner invites the developer by email, as Developer. The developer then opens Shop connection and Help themselves: makes the shop token and the sign-in secret and puts them straight into the shop's settings, presses Check and Connect. Never shoppers' chats, Review, Usage or *Go live*. | ✅ Built | Dashboard | `console_people.py`, ADR-0058, ADR-0059 |
| **Help for AI coding tools (MCP)** | The developer adds one NEURA address to their AI coding tool. The tool can then ask what each of the nine addresses must answer, see a working sample for each, and read the rules bridges get wrong, and help write the bridge. Since 2026-10-09 the rules also teach the **customer pass** a shop's pages make for order questions from signed-in shoppers (ADR-0057), with the same two safety rules as the developer guide. It only teaches: it never calls a shop, needs no account and no token, and is limited per visitor. Checking a bridge stays the shop owner's, in the dashboard. The address is in the developer guide, and on the shop owner's Help, which copies it for the developer. | ✅ Built | For developers | `developer_mcp.py`, `generic/teacher.py`, ADR-0053 |

---

## Limits a public page must not hide

| # | Limit | What a page may say |
|:--|:--|:--|
| **L1** | **Order status in the chat box answers only a shopper signed in to the shop, and only once the shop's developer has made its pages send a short-lived customer pass** (a few lines on the shop's server, with a secret the owner makes on Shop connection; [ADR-0057](architecture/adr/0057-a-signed-in-shopper-may-ask-about-their-orders-in-the-chat-box.md)). Until then, and for anyone not signed in, including a guest who bought without an account, every order question gets *"please sign in, or contact the shop"*. A guest by order number and email is not built. **Run on one test shop with demo data only** (2026-10-09); no real shop or shopper has used it. | *"Answers 'Where is my order?' for shoppers signed in to your shop"*, and that it needs a small change on the shop's server. Not *"tracks every order in the chat"*, and not *"for every shopper"*. |
| **L2** | **We notify nobody and send nothing.** A waiting shopper shows only in the dashboard (a count in the menu and on Home); nobody on the team is emailed, so shoppers wait until someone opens it. The answer goes from the shop's own email app. A handover goes to the shop's server only if the shop set up notifications. An email a shopper types is kept until the chat is marked answered, at most 30 days. **No data agreement is checked for it yet: one is needed with every shop before real shops use it** (AD9). Tried on test shops only (2026-10-12); no real shopper has left an email. | *"Shoppers can leave their email, and your team answers them from your own inbox"*. Not *"a person replies in the chat"*, not *"we email your shoppers"*, not *"you get notified"*. |
| **L3** | **Sold out and *Rarely added to cart* need product views switched on** (off by default) and a data agreement. With neither, both are empty. **The shop leaves out known search-engine robots before sending** (G117); a robot it does not recognise still counts as a visitor. No real shop has sent views yet. | Say it is optional and needs the shop to send views. Not *"see why shoppers don't buy"*: it shows where they stop, not why. |
| **L4** | **Nothing syncs by itself yet.** The copy of the catalogue changes when someone presses **Sync now**. | Nothing about "always up to date". |
| **L5** | **Search by meaning covers only indexed products**; the others are found by their words. | Do not promise it for every product. |
| **L6** | **Missing from your pages and Shoppers asked for have been tried on few real chats.** Missing from your pages was tried once on a test shop (Ceylon Harvester, 2026-10-27); Shoppers asked for once on the same test shop (*"do you have matcha?"* in 4 chats, 2026-10-30), otherwise on made-up chats. The night check's cost per shop is not measured, and Sinhala and Singlish are tried on a few made-up lines only. A half answer, or a *"we don't have it"*, worded in an unusual way can be missed. Something shows only after the next night's check, and only when 2 shoppers asked it. | *"Shows what shoppers asked that your pages don't say"*, *"shows what shoppers asked for that you don't sell"*. Not *"finds every missing answer"*, not *"tells you what to sell"*, not *"writes your product pages"*, not *"in real time"*. |
| **L7** | **The Marketing calendar's plans are written by AI, in English only, and nothing is sent.** A plan is a draft from the shop's own data; code checks it for prices, offers, links, phone numbers and a fixed list of English claim words, so a claim in another language would not be caught (R88: Sinhala and Tamil come later, after a test). **The moving dates (Avurudu, Vesak, Poson, Deepavali, Ramadan and Eid) show *Date not set yet*** until FiveNeurals checks them each January (AD12) or the owner sets them, and get no plan until then. Payday is the last Monday to Friday of the month; a public holiday is not known. A shop with no chats gets plans from its products alone. Nothing is posted, scheduled or emailed, and there is no results report. Tried on made-up shops; no real owner has used a plan yet. | *"Plans a campaign for each of your special dates, from your shop's own data, for you to edit and post"*. Not *"posts for you"*, not *"schedules your campaigns"*, not *"in Sinhala and Tamil"*, not *"knows every festival date"*, not *"tells you what sold"*. |

## Assistants not designed

**NEURA-MIND, NEURA-GUARD** — names only. Nothing is designed ([docs/agents/README.md](agents/README.md)).
Do not describe them on any page. **NEURA-GROW** has three designed and built features, above; its other ideas are not designed.
