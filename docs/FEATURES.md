# FEATURES — what each assistant does, in plain words

**Last checked against the code:** 2026-09-30.

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
| **Shop page** | A block on the shop's own product or basket page — not a chat. |
| **Dashboard** | The shop owner's console. |
| **For AI tools** | A connection other AI assistants use to read the shop's catalogue. |
| **Shop's server** | Something the shop's own server sends to us. Nothing of ours runs in a shopper's browser for it. |
| **For developers** | Something the shop's developer uses while building the bridge. A shopper never meets it. |

---

## NEURA-CARE — answers what the shop has

The shopper asks, CARE answers from the shop's own data, and hands to a person when it cannot.

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **Order status** | Tells a shopper where their order is: status, items, tracking. It first checks the order is **theirs**; for any other number the reply is the same *"no order with that reference"*, so nobody can guess real order numbers. | 🟡 Built, with a limit (L1) | Chat box | `agents/care/tools/orders.py` |
| **Product questions** | Answers questions about products — what it is, sizes, materials, whether it is in stock — from the shop's catalogue. | ✅ Built | Chat box | `agents/care/tools/catalogue.py` |
| **Returns and shipping questions** | Answers from the shop's own policy pages — returns, shipping, refunds, warranty, payment, privacy. Chosen by plain matching in code, no AI guessing which page applies. | ✅ Built | Chat box | `agents/care/tools/policies.py` |
| **Hand to a person** | Passes the chat to the shop's team when the shopper asks, when they want something changed or refunded, or when CARE cannot answer from the shop's data. The team gets the whole story: the question, what was looked up, and a draft reply that was **not** sent. | 🟡 Built, with a limit (L2) | Chat box → Dashboard | `graph/nodes/escalate.py` |

## NEURA-SELL — helps the shopper choose

Read-only, like CARE. Six parts; only the chat is an assistant in the usual sense.

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **Recommend** | A shopper describes what they need; SELL shows products from the shop that fit, as product cards (picture, price, in stock or not, link). | ✅ Built | Chat box | `agents/sell/nodes/`, ADR-0023, ADR-0030 |
| **Compare** | A shopper names two or more products; SELL compares them from the shop's own descriptions. | ✅ Built | Chat box | `nodes/route.py` |
| **Honest "we don't carry that"** | When nothing fits, SELL says so, lists the shop's categories, and never pretends a near-miss fits. If the shopper's own budget ruled everything out, it says how many were found and at what price. | ✅ Built | Chat box | `nodes/no_match.py`, ADR-0027 |
| **Suggestions that go with it** | On a product or basket page, up to **two** products from the shop that go with what the shopper is looking at. Chosen from the products' own words — **never** from what other people bought. Shows nothing rather than something silly. | ✅ Built | Shop page | `pairing/`, ADR-0040, ADR-0045 |
| **The owner chooses suggestions** | The shop owner picks a product's suggestions (or *show nothing*) in the dashboard. Their choice wins over the automatic one, is the same for every shopper, and is how the owner upsells. | ✅ Built | Dashboard | `pairing/choices.py`, ADR-0050 |
| **Sold out — people still looking** | Lists the shop's sold-out products that shoppers kept viewing in the last 7 days, and says whether each is still sold out right now. Counts only — never who looked. | ✅ Built, off by default (stage 1; L3) | Dashboard | `console_sold_out.py`, ADR-0046 |
| **Product feed** | A private address that serves the shop's catalogue in a format machines read. Exists only after the shop turns it on; the address can be replaced or switched off. | ✅ Built, off by default | For AI tools | `feed/`, `routes.py` |
| **Connection for AI assistants (MCP)** | Other AI assistants can search the shop's catalogue, read a product, check stock and list categories — four read-only tools — through a key the shop controls. That key reaches one shop's catalogue and nothing else. | ✅ Built | For AI tools | `mcp/`, ADR-0023 |
| Sold out, stage 2 — *"email me when it's back"* in chat | — | ⬜ Blocked (needs a new data category in ADR-0042) | — | ADR-0046 |
| Sold out, stage 3 — logged-in customers | — | ⬜ Blocked (needs A21's identity token) | — | ADR-0046 |
| Recovery list — checkouts started and not finished | Shown to the owner, exported and sent **by the owner**. We never message a shopper. | ⬜ Decided, not built | Dashboard | ADR-0043 |

## What both assistants share

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **One chat box, the right assistant** | The shopper never chooses an assistant. Each message goes to CARE or SELL by what it asks. | ✅ Built | Chat box | ADR-0031 |
| **Says it is AI** | Every assistant message carries *"You are chatting with an AI assistant."* — not only the first. | ✅ Built | Chat box | `widget.js` |
| **Read only** | Neither assistant can change anything in the shop — no refunds, cancels or edits. | ✅ Built | Everywhere | ADR-0010 |
| **Answers only from the shop's data** | Replies are checked against what was looked up; an answer that cannot be backed up is not sent. | ✅ Built | Chat box | `verify` node |
| **Protection from tricks** | Blocks known prompt tricks, and hides shoppers' emails and phone numbers from the AI. Rules in code, not a prompt. | ✅ Built | Chat box | ADR-0011 |
| **Practice mode** | The assistant works on real questions but the shopper does not get its reply; the owner reads and grades each one first. Shoppers see *"your message has been received"*. **A new shop starts in practice mode.** The owner presses **Go live** on Home when ready (it first shows what they checked in Review), and **Back to practice mode** at any time; a switch reaches chats already open. | ✅ Built | Chat box + Dashboard | ADR-0026, ADR-0054 |
| **Search by meaning** | Finds products by what the shopper means, not only matching words. Covers the products that have been indexed. | 🟡 Built, with a limit (L5) | Chat box, Shop page | `neura-agent-core/rag`, ADR-0047 |
| **A copy of the catalogue** | We keep a copy of the shop's products to answer fast; **Sync now** refreshes it. | 🟡 Built, with a limit (L4) | Dashboard | `console_shop.py` |
| **Daily spending limit** | Near the limit the assistant does less; at the limit every chat passes to a person. | ✅ Built | — | ADR-0015 |
| **Product views** | The shop's server may tell us which products shoppers viewed and added to basket. **Off unless the shop switches it on**, needs a signed data agreement, and is deleted after 7 days. Feeds *Sold out*. | ✅ Built, off by default | Shop's server | ADR-0044, ADR-0048 |
| **Chats deleted after 90 days** | Conversations are deleted by a job, not only by a promise. | ✅ Built | — | ADR-0048 |
| **Notifications to the shop's systems** | Signed messages to the shop's server when a chat starts, is resolved, or is handed to a person (with the whole story). | ✅ Built | Shop's server | `neura-core/webhooks` |

### The dashboard

| Screen | What the owner does there | Status |
|:--|:--|:--|
| **Sign in** | A one-time link by email. No password. | ✅ Built |
| **Home** | One shop at a glance. | ✅ Built |
| **Conversations** | Read every chat, search, filter by assistant. | ✅ Built |
| **Review** | Grade replies — the ones held in practice mode, and sent ones. | ✅ Built |
| **Suggestions** (NEURA-SELL) | See and choose what shows with each product. Shown only to a shop with NEURA-SELL. | ✅ Built |
| **Sold out** (NEURA-SELL) | Sold-out products people kept looking at. Shown only to a shop with NEURA-SELL. | ✅ Built |
| **Usage and cost** | Chats, AI use and its cost, by assistant. | ✅ Built |
| **Shop connection** | **The owner connects their own shop**: makes the shop token (shown once), checks the developer's bridge (the full check, said in plain words) and connects. Then a setup checklist, **Check again**, **Sync now**, what the shop lets the assistant do, and **a new token** for a leaked one. | ✅ Built (ADR-0052) |
| **Help** | *Connecting your shop*, step by step, and what to send your developer: the guide for developers, the address for an AI coding tool, and the chat box line. | ✅ Built |
| Settings and keys (the owner makes the chat box key) | — | ⬜ Not designed (needs an ADR) |

---

## For the shop's developer

| Feature | What it does | Status | Where | Source |
|:--|:--|:--|:--|:--|
| **Help for AI coding tools (MCP)** | The developer adds one NEURA address to their AI coding tool. The tool can then ask what each of the nine addresses must answer, see a working sample for each, and read the rules bridges get wrong, and help write the bridge. It only teaches: it never calls a shop, needs no account and no token, and is limited per visitor. Checking a bridge stays the shop owner's, in the dashboard. The address is in the developer guide, and on the shop owner's Help, which copies it for the developer. | ✅ Built | For developers | `developer_mcp.py`, `generic/teacher.py`, ADR-0053 |

---

## Limits a public page must not hide

| # | Limit | What a page may say |
|:--|:--|:--|
| **L1** | **From the chat box, order status always passes to a person today.** The chat box cannot prove who the shopper is, and it must not be able to ([A21](open-questions.md)). Order status answers only when the shop's **own server** sends the chat and says who the customer is. | Not *"tracks every order in the chat"*. Say it checks the order is theirs, and hands over when it cannot. |
| **L2** | **We notify nobody.** A handover shows in the dashboard, and goes to the shop's server only if the shop set up notifications. No email, no SMS. | *"Your team gets the whole story"* — not *"a person replies"*. |
| **L3** | **Sold out needs product views switched on** (off by default) and a data agreement. With neither, the screen is empty. | Say it is optional and needs the shop to send views. |
| **L4** | **Nothing syncs by itself yet.** The copy of the catalogue changes when someone presses **Sync now**. | Nothing about "always up to date". |
| **L5** | **Search by meaning covers only indexed products**; the others are found by their words. | Do not promise it for every product. |

## Assistants not designed

**NEURA-MIND, NEURA-GROW, NEURA-GUARD** — names only. Nothing is designed ([docs/agents/README.md](agents/README.md)).
Do not describe them on any page.
