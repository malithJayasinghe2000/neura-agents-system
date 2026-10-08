# ADR-0055 · A Handover Tells The Shopper How To Contact The Shop

**Status:** **Accepted** · owner decisions: 2026-09-30, G38/G44 (*"C, for every handover: the shopper is told
honestly that the assistant cannot answer and how to contact the shop … the message says only 'please contact
our store' with the shop's contact details, no chat code, no buttons"*, and idea D7, *"set once by the owner"*);
2026-10-02, the most important fixes first, G44 next, the details typed **on Shop connection**, and *"you can
directly build that without mockup"* ([CONNECTING_A_NEW_SHOP_LOG.md](../../CONNECTING_A_NEW_SHOP_LOG.md),
*Decisions*). §3's words when no details are set, and §5, are Claude's, reported with the build · **Date:**
2026-10-02 · **Amends:** the console's write surface ([ADR-0026](0026-the-merchant-console-and-the-first-human-in-the-system.md)),
as [ADR-0052](0052-the-shop-owner-connects-their-own-shop.md) and [ADR-0054](0054-the-shop-owner-switches-practice-mode-and-a-new-shop-starts-in-it.md)
did · **Related:** [ADR-0020](0020-a-withheld-turn-says-so.md) (the withheld turn's words, the same kind of
sentence), [agent-runtime.md §5](../agent-runtime.md) (escalation), the log's G38, G44, G74 and idea D7

> **In one sentence:** when the assistant hands a shopper over, the shopper reads *"I can't help with this
> here. Please contact our store:"* and the shop's own email or phone, typed once by the owner on Shop
> connection; never a promise that a person will come.

## Context

Every handover tells the shopper *"I'm passing you to a colleague. They'll have everything we've talked about,
so you won't need to explain it again"* (CARE) or *"… a member of the team. They'll have everything we've
discussed"* (SELL and the shared node). **Nobody comes** (G44): the dashboard cannot reply to a shopper, the chat
lives only in the shopper's browser tab, and an anonymous shopper left no way to be reached. The owner saw it on
their own shop on 2026-10-02, five times in a row.

Live replies from a person, or taking a shopper's email, are outside what is decided: sending anything to a
shopper is excluded, and an address a shopper types is *volunteered data*, which ADR-0042 does not permit
(ADR-0046 stage 2 waits on the same thing). Telling the shopper how to reach the shop needs neither.

## Decision

### 1. The shop's contact details, typed once on Shop connection

A section on Shop connection, *Your shop's contact details*: an **email** and a **phone**, both optional. Saved
in the shop's settings (`TenantConfig.contact_email`, `contact_phone`), the same place as ADR-0020's withheld
message. They are the shop's own public details, not a shopper's.

### 2. Every handover names them

*"I can't help with this here. Please contact our store: hello@yourshop.example, +94 11 234 5678."* Both, one, as
the owner set them. Nothing else: no promise of a person, of a time, or that the conversation is passed on.

### 3. With no details set, the same sentence stops short (Claude's words)

*"I can't help with this here. Please contact our store."* True with nothing set, and the owner's own words of
2026-09-30.

### 4. Built where every reply is released

The sentence is made in `neura_core` (`handover_message`) and put on the reply by the turn service, in the
transaction that releases it (`turns.py`, where ADR-0054 §6 already reads the shop's row): **one place, for both
assistants, for the plain request and the live connection alike** (a handover is fixed text, sent whole, never
streamed). The engine's own fallback and CARE's `escalation_message.md` say the no-details sentence too, so a path
that does not pass through the turn service (an eval) cannot say the old one.

### 5. What the dashboard writes (Claude's addition)

`GET` and `PUT /v1/console/shops/{tenant_id}/contact`, behind the console session and the membership, as every
console write. Only the two keys are written (merged, as ADR-0054 §5). The email must look like one; the phone is
digits, spaces, `+`, `-` and brackets; an empty field clears it. An audit entry names **which** fields changed,
not their values.

## Consequences

- **A handed-over shopper gets a way to reach the shop**, and the untrue promise is gone from every handover.
- **What the AI itself offers is not changed here** (G74): the instructions that tell it to offer *a colleague*
  change what it writes, so they need an AI test and the owner's words, separately.
- **Rule 4:** the sentence is fixed text, not a model's. Tested deterministically: the sentence for every
  combination, the served turn's reply on both transports, and the route. The CARE prompt file changes, so the
  owed AI run (T3 and CARE) covers it, with the owner's yes.
- The dashboard still calls such a conversation *handed to a person*; renaming it is not decided here.

## Not decided here

- **G74**, the AI's own offers of a colleague.
- A contact page link, opening hours, or different details per assistant.
- A reply to the shopper from the dashboard, or taking the shopper's email (G44's larger half, a design session).
