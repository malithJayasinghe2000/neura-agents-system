# ADR-0080 · FiveNeurals May Change A Shop's Assistants After Approval

**Status:** **Accepted** · the owner, 2026-11-20 (*"ok"* to Claude's proposal, no mockup) · everything marked
*(Claude)* is Claude's, decided while building · **Date:** 2026-11-20 · **Settles:** what
[ADR-0065 §6](0065-fiveneurals-may-switch-off-one-feature-for-one-shop.md) left undecided (*switching a whole
assistant off after approval*, AD10's first framing) · **Related:**
[ADR-0061](0061-fiveneurals-has-an-admin-dashboard-that-sees-shop-facts-never-shoppers.md) (the admin dashboard; assistants chosen at approval, R14), R46
(GROW chosen per shop, like SELL), G136

> **In one sentence:** on an approved shop's admin page, FiveNeurals ticks which assistants the shop has and
> presses Save; an added one starts at once, a removed one stops and keeps its data, and the shop's Owners get
> an email.

## Context

Assistants were chosen once, at approval (ADR-0061). The owner, approving the first shop online
(2026-11-20): *"after approve the shop… can't go to edit those agents or add new agent."* A shop that signs up
for CARE and later wants GROW had no way to get it except a database edit.

## Decision

### 1. Where

On `/admin/shops/[id]` for a shop that is **not waiting**, a section **Assistants**: the same list as Approve
(every assistant the API discovered, G136), the shop's own ticked, and **Save**. Only a FiveNeurals admin, as
every admin page (ADR-0061).

### 2. Adding an assistant

It starts at once: the shop's `enabled_agents` gains it, and its daily job is booked (GROW's night run), as at
approval.

### 3. Removing one

Its pages disappear for the shop's people and its AI stops (a daily job already checks the shop still has its
agent, and stops for good if not). **Nothing is deleted**: chats, plans, links and lists stay, so adding it back
brings them back. Its switches (ADR-0065) are kept as they are.

### 4. At least one

As at approval, a shop keeps at least one assistant; none is refused with a plain sentence.

### 5. The Owners are told

An email to each Owner: *"Your assistants on FiveNeurals are now: NEURA-CARE and NEURA-GROW."* The names are
each agent's own manifest's, so the API still names no agent. When the email cannot be sent, the page says so,
as Approve does.

### 6. Recorded

One audit entry, `shop.assistants_changed`, with the list before and after and the admin. Saving the same list
changes nothing, records nothing and sends nothing *(Claude)*.

## Consequences

- One route: `PUT /v1/admin/shops/{id}/assistants`, body `{"agents": [...]}`; refused for a waiting shop
  (Approve is its path) and for an unknown key.
- One more section on a page the owner approved (board 61's page); its look is the Approve list's, so no mockup.
- **Not decided here:** a shop owner asking for an assistant from their own dashboard; prices.
