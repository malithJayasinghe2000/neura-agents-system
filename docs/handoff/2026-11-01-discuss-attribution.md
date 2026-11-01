Discuss **D16, basic attribution: UTM links plus our own first-party event tracking**, with the owner, for GROW's
*Marketing calendar*. **This session is a discussion first, not a build.** Write no code until the owner has decided
and approved what is to be built (the console work cycle: discuss, then an ADR and a mockup, the owner's approval,
then the build).

## 1. The idea, in the owner's words

*"Basic attribution: UTM links plus your own first-party event tracking."* Raised by the owner on 2026-11-01, while the
Marketing calendar (ADR-0072) was being built. The point: after a campaign, the owner knows **which post brought
shoppers**.

## 2. Read first, in this order

1. `CLAUDE.md`, then `docs/PROJECT_STATE.md` (the top entry, *SESSION HANDOFF*, 2026-11-01), `AGENTS.md`,
   `docs/glossary.md` (*held vs observed*, *observed event*, *DPA*).
2. **The idea and Claude's first view:** `docs/CONNECTING_A_NEW_SHOP_LOG.md`, the D list, **D16** (and D17, G126 beside
   it: pictures for the posts, later).
3. **The feature it builds on:** ADR-0072 (`docs/architecture/adr/0072-grow-plans-a-campaign-for-each-date-the-shop-keeps.md`):
   §1 (what was **not** built: scheduled posts and emails, customer birthdays, **a results report**), §5 (what a plan
   holds, the schedule worked out in code), §6 (the checks: **the AI never writes a link**), §10 (the falsification
   test). ADR-0073 (what the build decided), console.md §3.14 (the screens, *As built*), FEATURES.md (the GROW section,
   **L3** and **L7**).
4. **What decides "our own tracking":** ADR-0042 (we may hold what the merchant already holds), **ADR-0044** (a
   shopper may be observed only when the shop switches it on: off by default, the shop's **server** sends the events,
   nothing of ours runs in a shopper's browser), **ADR-0048** (phase 1, built: two event types, `product.viewed` and
   `cart.added`, a data agreement required, **kept 7 days**), ADR-0049 (`in_stock` on a view), ADR-0071 (*Rarely added
   to cart*, the latest use of the events), `docs/spec/generic-commerce-interface-v1.md` (how a shop sends events).
5. **The code, if a detail is needed:** `packages/neura-agent-core/src/neura_agent_core/calendar.py` (dates, plans,
   `post_days`), `agents/grow/src/neura_agent_grow/campaign.py` (the plan writer and its checks),
   `apps/neura-api/src/neura_api/routes/console_calendar.py`, `apps/neura-console/src/app/console/[tenantId]/calendar/`,
   `apps/neura-api/src/neura_api/routes/observe.py`, `packages/neura-core/src/neura_core/observation/`.

## 3. Claude's first view (D16), to start the talk from

- **A. Links only (small).** Each plan gets a ready link per post (teaser, launch, last chance, email, banner), **built
  by our code** from the shop's own product pages, with campaign labels (`utm_source`, `utm_campaign`, `utm_content`).
  The owner pastes them into the posts and reads the results in tools they already use. We store nothing new; ADR-0072
  §6 still holds, because the AI writes no link. It also partly answers *"best post"*, which ADR-0072 left out for
  needing social media data.
- **B. Our own attribution (big).** The shop's server sends the campaign label with each product view and cart add,
  and GROW shows per post: visitors and cart adds. What stands in the way, each a fact in the documents:
  1. it is the **results report** ADR-0072 §1 and R84 left out: a new ADR that replaces that part of the decision;
  2. events are **kept 7 days** (ADR-0048) while a campaign runs about 3 weeks: daily totals would have to be kept,
     a decision of its own;
  3. **orders are not synced**: visits and cart adds can be counted, sales cannot;
  4. **no real shop sends views yet** (FEATURES.md L3), and observation is **off by default** and needs a data
     agreement and the shop's developer.
- **Claude's recommendation so far:** A first, as a small step; B only after a real shop sends views and owners use the
  plans.

## 4. Questions to settle with the owner, one at a time

1. What should the owner learn after a campaign: visitors per post, cart adds, or sales?
2. A, B, or A now and B later?
3. For A: where each post's link goes (a product's page, the home page, or the owner chooses), and the labels
   (the source per channel: Facebook, Instagram, email, banner; the campaign: the date's name and year; the content:
   teaser, launch, last chance).
4. For B, only if chosen: which events carry the label, how long the totals are kept, where they show (a *Results*
   part on the plan?), and who sees them (the Owner and Support, as the calendar, R86?).

## 5. Rules that hold

- **Do not decide alone** (CLAUDE.md §2). Give options and a recommendation; the owner chooses. **Never change a
  decided rule quietly** (R82 to R104, ADR-0072, ADR-0044, ADR-0048): a change is a new ADR.
- **No numbers as facts** (CLAUDE.md §4): no conversion or cost figures.
- **Never message a shopper; nothing of ours runs in a shopper's browser** (ADR-0044). No platform names outside
  `packages/neura-adapters/` (Rule 1). Authorisation is code (Rule 3).
- **Write it down in the same turn:** each decision in the log's *Decisions* (next **R105**), each problem in *What we
  found* (next **G127**), each idea in the D list (next **D18**), FiveNeurals' hand jobs in *Admin needs* (next
  **AD13**); and `docs/PROJECT_STATE.md` at the end.
- **The owner's style:** plain, simple English; one question at a time, with options and Claude's recommendation;
  **never the long dash "—"**.

## 6. Housekeeping from the last session

The last session left **uncommitted doc changes**: the log's G126 and D17 rows, a line in `docs/PROJECT_STATE.md`, and
this file. Commit them with this session's first docs change (only the files named). **Never push**: the owner pushes.
