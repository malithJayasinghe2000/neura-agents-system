# ADR-0062 · A Handed-Over Shopper May Leave An Email, And The Shop Answers From Its Own

**Status:** **Accepted** · owner decisions 2026-10-11, a design session, R25 to R32
([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md), *Decisions*, *Handover*) · mockups approved 2026-10-11 (canvas row 15) · **built 2026-10-11/12**; what the build decided, and the
Gemini check, is [ADR-0063](0063-the-handover-answered-by-email-what-the-build-decided.md) · Everything marked *(Claude)* was Claude's proposal, accepted by the owner with R32 · **Date:** 2026-10-11 ·
**Amends:** [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md) §1 (a third
kind of data, *volunteered*, for this one purpose) and §2 (no data agreement checked for it, R29);
[ADR-0055](0055-a-handover-tells-the-shopper-how-to-contact-the-shop.md) §2 (what a handed-over shopper reads) ·
**Resolves:** [ADR-0058](0058-a-shops-dashboard-has-people-with-roles-and-a-shop-signs-up.md) §8 (Support answers
shoppers) · **Unchanged:** *send anything to a shopper* stays excluded (CLAUDE.md §2); NEURA sends nothing ·
**Related:** [ADR-0057](0057-a-signed-in-shopper-may-ask-about-their-orders-in-the-chat-box.md) (the signed-in
customer), [ADR-0043](0043-a-recovery-list-is-a-fifth-surface-and-the-merchant-sends-the-email.md) (the merchant
sends the email, the same shape), [ADR-0046](0046-a-sold-out-product-that-people-want-is-a-fact-the-merchant-should-have.md)
§4 (volunteered data, still not approved for it), [ADR-0059](0059-people-and-roles-what-the-build-decided.md) §1 (how
permissions are named), the log's G44, G74, G102, G103, AD9 and FEATURES.md L2

> **In one sentence:** when an assistant hands a chat over, a shopper who is not signed in may leave their email in
> the chat box, a signed-in shopper is never asked, the chat waits in the dashboard for the shop's team, and a person
> on the team answers **from the shop's own email app**; NEURA sends nothing, keeps the typed email only until the
> question is answered (at most 30 days), and the AI never sees it.

## Context

A handover reaches nobody who can answer the shopper (G44). ADR-0055 made the handover honest: the shopper reads the
shop's own email and phone, and nobody is promised. What is still missing is the shop answering the question the
shopper already asked:

- **Conversations is read only.** There is no reply route (`console_conversations.py`).
- **The chat lives in the shopper's browser tab** (`sessionStorage`, on purpose: a chat can hold order details, and
  a browser-wide store would resume a stranger's chat on a shared computer). A closed tab is a lost chat.
- **An anonymous shopper leaves no way to be reached.** A signed-in one does: since ADR-0057 the conversation keeps
  the customer's id (`customer_external_id`), and the shop's bridge can give that customer's email (`get_customer`,
  the optional `customer.read`).
- **Nobody is told.** The `conversation.escalated` webhook reaches the shop's server only if it set one up (L2).

**The owner's fact that shaped the design (R25):** *"always there is no support user when this happen"*. A small shop
has nobody watching a dashboard when CARE hands a chat over, so a reply inside the chat box would arrive after the
shopper has gone. The answer must be able to reach the shopper **later**. Help-desk tools solve this by taking the
shopper's email when nobody is online; two documented rules stood in the way: *send anything to a shopper* is
excluded, and an email a shopper types is *volunteered* data, which ADR-0042 does not name (ADR-0046 §4 found the
same gap).

## Decision

### 1. The answer reaches the shopper later, by email, and the shop sends it (R25, R27)

A person on the shop's team answers a handed-over shopper **by email, from the shop's own email app**. The dashboard
gives them the address and the question; their own email program sends it. **NEURA sends nothing to a shopper**, so
the exclusion in CLAUDE.md §2 is unchanged, and this is ADR-0043's shape (the merchant sends) applied to one
conversation.

Why the shop sends rather than NEURA (the owner: B): the shopper gets the answer from the shop they know, a reply
goes straight back to the shop, and FiveNeurals does not become a sender of email to shoppers (spam complaints,
sender records per shop, an email service that is not ready, K1).

**The cost, accepted with it:** NEURA cannot see whether the email was sent. The team member presses **Mark as
answered** (§7).

### 2. Who is asked for an email (R26, the owner's split)

| The shopper | At a handover |
|:--|:--|
| **Signed in** (a valid customer pass, ADR-0057), and the shop's bridge lists `customer.read` | **Never asked.** NEURA reads the email from the shop when a team member opens the chat (§6) |
| **Not signed in**, or signed in on a shop whose bridge does not list `customer.read` | **Asked**, and may skip it (**No thanks**) |

### 3. The typed email: a third kind of data, for one purpose (R26, R29). Amends ADR-0042

ADR-0042 §1 permits data the shop already **holds**; ADR-0044 added data **observed** in an opted-in shop. This ADR
adds a third, **volunteered**: an email a shopper types into the chat box after a handover, **for one purpose only:
so the shop can answer that conversation.** It is never used for anything else, never sent to the shop's server,
never exported, never shown outside that conversation.

**No data agreement is checked for it** (R29, the owner: B). ADR-0042 §2 says no shop stores shoppers' personal data
until a data agreement with that shop is on record; for this one case the chat box asks in every shop. Product views
keep their agreement check (ADR-0044).

**Claude's honest note, recorded with the decision:** under GDPR (Art. 28) a company that keeps personal data for a
shop needs a written agreement with that shop, whatever the shopper typed; the shopper's consent does not replace
it. So **before real shops use this, every shop needs the agreement**: the log's **AD9**, a must before NEURA goes
online. The code does not enforce it; that is the decision.

**ADR-0046 stage 2 is still not approved.** This ADR names the volunteered category for a handover's answer only.
Stage 2 (*tell me when it is back*) would be a second purpose, and needs its own decision.

### 4. Kept until answered, at most 30 days (R30)

- **Mark as answered** deletes the typed email at once.
- **Unanswered after 30 days**, the retention job deletes it (`RETENTION_HANDOVER_EMAILS_DAYS`, default 30), and the
  chat leaves the waiting list. 30 is a guess (CLAUDE.md §4).
- **The deletion is a job that runs, in the same change as the table** (ADR-0042 §3), on the `retention.sweep` that
  already deletes conversations and observed events.
- A conversation deleted after 90 days (`RETENTION_CONVERSATIONS_DAYS`) takes its waiting row with it, and
  `make tenant-drop` removes the table's rows (its list, G76).

### 5. The words the shopper reads (R31, the owner: A)

Fixed text, never the AI's, put on the reply where every reply is released (`turns.py`, as ADR-0055 §4 and
ADR-0057 §7). The contact line is left out when the shop set no details (ADR-0055 §3).

| Case | Words |
|:--|:--|
| Not signed in, at the handover | *"I can't answer this here. Leave your email so our store can answer you."* An email box, **Send**, **No thanks**. Then *"Or contact our store: hello@yourshop.example, +94 11 234 5678."* |
| After **Send** | *"Thanks. Your question is with our store, and they can answer you at saman@example.com."* |
| Signed in, or a later handover in a chat that already has an email | *"I can't answer this here. Your question is with our store, and they can answer you by email."* Then the contact line |
| An email typed wrong | *"Please check your email address."* |
| A later handover after **No thanks**, and in practice mode | ADR-0055's sentence, unchanged |

**Can, not will, on purpose:** NEURA cannot promise that the shop answers.

The reply carries a mark (`ask_email: true`) so the chat box knows when to show the box; it never guesses from the
words, as `sign_in: true` already works *(Claude)*.

### 6. The team sees waiting chats in the dashboard (R28, R32 5)

**A chat is waiting** when a handover happened and the shop has a way to answer: a typed email, or a signed-in
customer. A chat where the shopper pressed **No thanks** is not waiting (nobody can answer it) and stays *handed to a
person*, as today.

- **Conversations gets *Waiting for an answer*** (no new screen), and a **count beside the chats item in the side
  menu**; **Home** says *"2 shoppers are waiting for an answer"*. Both open the waiting chats. **No email to the team**
  (R28, the owner: B): nobody learns of a waiting shopper until someone opens the dashboard. An email to the team is
  possible later and changes no rule (it goes to the shop's team, not to a shopper).
- **A waiting chat opens with a box at the top:** the shopper's email with **Copy**, **Answer by email**, **Mark as
  answered**. For a signed-in shopper the email is read from the shop **when the chat is opened, never stored**; if
  the shop cannot give it, the box shows the customer's id to find in the shop's own admin.
- **The look is a mockup first** (the console work cycle).

### 7. Answer by email and Mark as answered (R32 6, 7)

- **Answer by email** opens the team member's email app with the shopper's address, the subject *"Your question to
  [shop]"*, and the shopper's question quoted. **The AI's unsent draft is never put in**: it was held back because
  it may be wrong. **Copy** is there for a computer with no email app set up. *(Claude: the question is quoted as
  stored, so a card number or email the shopper typed in it appears as its token, `[EMAIL_1]`, as Conversations
  already shows it.)*
- **Mark as answered** deletes the email at once (§4), records who and when, and the chat leaves the waiting list.
  **It cannot be undone.** An audit entry names who did it, never the email.

### 8. One feature for both assistants; the permission (R32 1, G102)

The handover is built once, in the shared `escalate` node and the turn service, and SELL hands over as CARE does.
So this is **one feature for every assistant, served by `neura-api`**, and its permission names no agent (ADR-0059
§1, G88): **`shop:handovers:write`**, held by **Owner and Support**, not the Developer. It opens the shopper's email,
**Answer by email** and **Mark as answered**; the waiting list itself is read with `shop:conversations:read`. This
replaces ADR-0058 §8's example name (`care:handover:write`).

### 9. Only a real handover asks, and a chat asks once (R32 2)

- **Not in practice mode:** a held handover reached nobody (`ConversationState.SHADOWED`), so there is nothing to
  wait for.
- **Not a blocked message, and not ADR-0057's sign-in sentence** (not a handover).
- **A chat asks once.** A later handover in the same chat says §5's third or fifth line.

### 10. The typed email never reaches the AI (R32 3) *(Claude)*

- The chat box sends the email in **its own request**, never as a chat message, so it never enters
  `conversation_messages`, the guard, the model or a trace.
- The request is accepted only for a conversation of the key's own shop that was **really handed over** (§9) and has
  no email yet, with the same public key and scope the chat box already sends messages with (`<agent>:chat:write`,
  the agent read from the conversation as data), so **no shop makes a new key**.
- Checked as an email; one per conversation; rate-limited per key and per address, as the chat is.
- Kept in **its own table** under the shop's row-level security, the unprivileged app role (ADR-0042 §5).
- Never in a log line or an error answer.

### 11. Not in this version (R32 8)

- **A live reply inside the chat box** (R25: at most an extra, for when someone happens to be online).
- **An email to the team** (R28).
- **The email in the `conversation.escalated` webhook.** The webhook is unchanged.
- **The AI's own offers of a colleague (G74):** its own change, with an AI test and the owner's words.

### 12. Tests (R32 9)

**Written first, failing on the old code:** the four sentences and the mark for each case of §2 and §5; no mark in
practice mode, on a blocked message or on the sign-in sentence; a chat asks once; the email request refused for a
conversation never handed over, of another shop, already holding an email, with a key of another shop, and for a bad
address; the email never in `conversation_messages`, a log line or an error answer; the waiting list, the count and
Home's line; **Mark as answered** deletes the email and writes the audit entry; `shop:handovers:write` for Owner and
Support only (Developer 403, a stranger 404); a signed-in customer's email read from the shop and not stored; the
retention job deletes an email after 30 days; `make tenant-drop` removes the rows. **Through a real chat box in
headless Chrome**, on the real API: not signed in (Send, No thanks, a wrong email), signed in. **The dashboard** on
desktop and phone.

**One AI run on Gemini (cloud-prod)**, because the new words enter the chat history the AI reads (G103; A20 showed
the old handover words there could break the router): a handover with the new words, then an ordinary question, for
CARE and SELL; and CARE's injection suite, which must stay **1.00** (Rule 4). The local path stays untested (the
2026-09-19 decision).

## Consequences

- **A handed-over shopper can get an answer after they have left**, from the shop's own address, and G44's larger
  half is closed for every shop whose team opens the dashboard.
- **NEURA now keeps a shopper's typed email**, for at most 30 days. *"We hold what the merchant already holds"* is no
  longer the whole sentence; the accurate one is: *we hold what the merchant already holds, and an email a shopper
  gives us to be answered, until they are.* *"We never message a shopper"* stays true.
- **No data agreement is checked** (R29), and the law expects one with every shop: **AD9 must be done before NEURA
  goes online.** Until then this is fit for test shops, and for a real shop only with a signed agreement.
- **The team must look.** With no email to the team (R28), a shop that never opens the dashboard leaves shoppers
  waiting, and the chat box only says *"can answer you"*. The waiting count on Home is the whole reminder.
- **Someone can type another person's email.** That person gets one email from the shop, quoting a question they
  never asked. Low harm, the shop's own address, nothing sent by us; accepted.
- **FEATURES.md *Hand to a person* and L2 change when this is built**, not before.

## Not decided here

- A live reply in the chat box, an email to the team, or a daily summary of waiting chats.
- The email in the webhook, or in any export.
- G74, the AI's own offers of a colleague.
- ADR-0046 stage 2 (*tell me when it is back*): a second purpose for volunteered data, its own decision.
- The data agreement's text and how a shop accepts it (AD9).
