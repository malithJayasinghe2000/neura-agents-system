# ADR-0073 · The Marketing Calendar: What The Build Decided

**Status:** **Accepted** · built 2026-11-01, overnight, in five pieces (`8656031` data, `6baba21` the plan writer,
`4b5a310` the routes, `0f6a7aa` the screens, and the docs) · Everything here is Claude's, decided while building
[ADR-0072](0072-grow-plans-a-campaign-for-each-date-the-shop-keeps.md) inside what the owner decided (R82 to R90),
G119 and the approved mockup (canvas row 21), **with no one to ask** (the owner asleep; the handoff's rule: choose the
best-practice option, write it down, never change a decided rule) · **Date:** 2026-11-01 · **Related:**
[ADR-0069](0069-shoppers-asked-for-what-the-build-decided.md) and
[ADR-0066](0066-missing-from-your-pages-what-the-build-decided.md) (the pattern followed),
[ADR-0065](0065-fiveneurals-may-switch-off-one-feature-for-one-shop.md) (the switch),
[grow.md](../../agents/grow.md) §14, console.md §3.14, FEATURES.md L7; the log's R91 to R104 and G120 to G125

> **In one sentence:** ADR-0072 is built on the other GROW pages' pattern (tables in the shared core, the console's
> own route, GROW's night run the only writer), with one Gemini call per plan behind ADR-0072 §6's checks in code;
> this records every gap the ADR and the boards left, how each was settled, and what was and was not tested.

## Decision

### 1. What counts as *kept* (R91)

A **suggested date counts once its year's list is saved** (*Save this year's dates*; ADR-0072 §3: *"Save keeps the
list"*) and its box is ticked. An **own date counts from the moment it is added**, while ticked. Before the first
Save, no suggested date gets a plan and nothing is spent: Home's *Add this year's special dates* and a note on the page
ask for the Save. **Next year's suggested dates count once next year's list is saved**; the page is always *this* year
(R100), so the list opens on 1 January, as Home's line says. A suggested date added to the code later is shown ticked
and counts from the next Save.

### 2. The dates in code

The list is `neura_agent_core/calendar.py` `SUGGESTED`, one entry per date, in the boards' order. Fixed and rule dates
are computed: Christmas, Valentine's Day, 11.11, Mother's Day (the second Sunday of May), Black Friday (the day after
the fourth Thursday of November), Cyber Monday (Black Friday plus 3 days), Payday (**the last Monday to Friday of each
month**, R92: public holidays move and no list of them is kept). **The moving dates (Avurudu, Vesak, Poson, Deepavali,
Ramadan and Eid al-Fitr) are left unset**: `MOVING_DAYS` is empty and is filled in by hand each January (AD12), never
from memory. *Ramadan and Eid al-Fitr* is one date, on Eid's day. A moving date not set shows *Date not set yet*, with
*usually in [month]* where the month is stable (none for Eid, which moves through the year), and the owner may set its
day for their shop (it then wins over the January list for that shop and year). An own date marked *every year*
repeats on the same day from the year it was added; 29 February falls on the 28th in other years (R93).

### 3. Three tables, and the shop's day

`calendar_settings` (the country: Sri Lanka, or another; no row is Sri Lanka, G119), `calendar_dates` (a suggested
date's tick and an owner-set day per saved year; an own date's name, day and *every year*), `calendar_plans` (one per
kept date and day: the checked answer, the owner's edits, when made, the prompt revision, the last failure, *Make it
again* waiting). Migration `3f7c1a9e5b84`, row-level security on all three, in shop removal's list. **No shopper's
words are stored**: a plan holds labels and counts only (ADR-0072 §8). **A plan is deleted 30 days after its date** by
the retention sweep, which GROW's step books in the same transaction that stores a plan. Days are counted in
Asia/Colombo for a Sri Lankan shop and UTC for another (G119); the console writes a calendar day from its own digits,
never moved by a browser's clock.

### 4. The night run (R94, R96)

GROW's daily job keeps its kind, `grow.gaps.scan`, so jobs already queued keep running; it now has **two steps, each
with its own switch** (ADR-0065): the night check (`grow.gaps`) and the calendar's plans (`grow.calendar`, *The
calendar's AI plans*). The shop's budget is checked once, before both. **The calendar step plans every kept date 21
days away or closer that has no plan**, so a date kept late still gets one, while it is ahead (R94); at most 20 a run.
**The night run now reaches a shop with no chats** (ADR-0072 §8): it is booked when FiveNeurals approves a shop (the
admin page and `make tenant-approve`) and by every calendar save, which also reaches GROW shops approved before this
build (R96).

### 5. *Make it again* (R95, R103)

`neura-api` may not name an agent, so the manifest gained **`on_demand`**: a job kind the console may book to run now,
by the console page it fills (`calendar_plans` → `grow.calendar.plans`), found as `pauses` is. *Make it again* marks
the plan and books that job; the worker answers within seconds and only the plans asked for. A request made while the
job runs is looked at again 5 seconds later. **Refused while paused** (409 `PAUSED`) and **once the date has passed**
(409 `DATE_PASSED`); allowed up to the day itself. When a draft was edited the page asks first (ADR-0072 §5).

### 6. The plan writer (R97, R98)

`agents/grow/.../campaign.py`, one **REASONER** call (R98) with a structured answer. The model is given the date and
its post days, the shop's name, **up to 100 products in stock** (published, and not every variant that reports stock
says it is out), each an id, a title and a category, and **up to 10 labels with counts** from each of *Shoppers asked
for* and *Missing from your pages* (with the same 30 days and 2-shopper rule; a thing the owner hid stays out), all
inside `<untrusted_shop_data>`. **Never a shopper's question, never a conversation id** (a `Fact` has no field for
either). The model chooses products and facts **by id** (`w1`, `g2`), and writes the theme, the idea and the drafts.

**The checks** (ADR-0072 §6, in code): a product id it was not given, 2 or 3 products (fewer only when the shop has
fewer), a fact it was not given or more than 3; a price or offer (`%`, *per cent*, a currency sign or code, a number
followed by *off*, and also *free*, *half price*, *buy one get one*); a claim word from the fixed English list; a link,
an email address, an `@` handle or a phone number; **and, Claude's (R97):** a count of shoppers, customers, people or
orders (counts come from our data), a bracket other than **[your offer]**, anything the injection guard's rules match;
every field 1 character to its limit. **One retry, told which rule broke** (and, for a claim, which word: G120).
Refused twice, the plan is stored as *could not be made* and **is not tried again by itself**: only *Make it again*
asks again, so a date never costs more than two calls a night unasked. An unreachable model is not a refusal: the step
stops and the queue retries.

### 7. What the page shows, and from where

The products' names, photos, prices and links come from the synced catalogue (a link only when http or https); the
counts under *Act on this first* from the stored plan; the days under *When to post* from code. The sentences under
*Act on this first* are the console's own, with the label in quotes: *"**8 shoppers** asked for "tea gift box" in the
last 30 days. You don't sell it: consider adding it before [launch day]."*, *"**3 shoppers** asked about "[label]" for
[product]. Your page doesn't say. Add it before you promote it."* **Support sees a plan whole** (R86 gives Support the
plans), **but the link to *Shoppers asked for* shows only to a role that may open it** (R61): R99, for the owner to
confirm (G122).

### 8. What saves when, and the owner's words (R101, R102)

On *This year's dates*, *Add* and *Remove* of an own date act at once; the ticks, a moving date's day and *Your shop is
in* wait for *Save this year's dates* (R101). An own date may be from today to the end of next year. **The owner's
edits are not checked** beyond 1 to 3000 characters: they are the shop's own words, a real offer included (R102). A
plan made again drops the edits, after asking.

### 9. Words not on the boards (Claude's)

*Plan tonight* (a date due with no plan yet), *No plan while paused*, *Making a new plan* (pill, and on the plan: *"Your
assistant is writing it now. It takes about a minute, and it shows here when it is ready."*), *Your plan could not be
made* (*"Your assistant wrote it twice, and both times it held words we don't let through, such as a price, a health
claim or a phone number. Make it again to try once more."*), *A new plan could not be made just now. This is your
earlier plan.*, *This plan is gone*, the note *Add this year's special dates* on the page before the year is saved,
the two empty *Coming up* lines, *A shop outside Sri Lanka gets the shopping days and its own dates.*, *Saved. Your
assistant writes a plan 21 days before each ticked date.*, the cut-catalogue line, *No longer in your synced
catalogue*, and **Passed** under *When to post* for a step whose day came before the plan was made (*Done* would not be
true; a date kept late, R94). On the Admin page, each switch now carries its own *Turn off* words from its manifest
(`switch_notes`); the night check's are the approved ones, unchanged; the calendar's are Claude's (G124).

### 10. Where the build differs from the boards

- **Home's calendar lines come after the shoppers waiting for an answer**, as board 78 draws them, not *first* as
  console.md §3.14 wrote it (G123): a person waiting stays first (ADR-0062 §6).
- **Payday has no *Set the date***: board 77 shows one, but its days are computed.
- **Avurudu shows *Date not set yet***: the boards showed April 14; AD12 leaves the moving dates unset.
- Dates read as the boards write them (*Apr 14*, *April 14*), whatever the browser's language.
- A product with no photo shows a placeholder.

## What was tested, and what was not

- **Tested:** the dates in code against the boards' 2027 days, the moving dates left unset, what is kept, *every
  year*, the shop's day (`test_calendar.py`, 21); every check in ADR-0072 §6 and R97, the retry and what it says, what
  the model is and is not given, the switch and the jobs (`test_grow_campaign.py`); the calendar eval's runner and its
  invariants (`test_grow_eval_target.py`); the tables, a save, own dates and their plans, a plan made again, a failed
  try, the sweep at 30 days, isolation (`test_calendar_postgres.py`, 8); the night run's step: 21 days and not 22, a
  date kept late, the save, labels and counts only, products in stock, refused twice, an outage, the sweep booked, a
  shop with no chats reached and metered, the switch, *Make it again* and its outage (`test_grow_plans_postgres.py`,
  11); the routes: who, *Coming up*, *This year's dates*, own dates, a plan, edits, *Make it again*, paused, a date
  passed, another shop's plan, Home (`test_console_calendar.py`, 16); approval booking the night run, the two switches
  (`test_admin.py`). **The Gemini eval (cloud-prod), `calendar.yaml`, 10 cases, 4 of them attacks:** run 1, 9 of 10,
  injection resistance 1.00, 11 calls (G120, *treats*); after the fix, run 2, **10 of 10, injection resistance 1.00,
  intent 1.00**, 10 calls; plus 1 call to look at the failed case. **In headless Chrome** (`make console-check`, its own
  GROW shop): the page, a plan, *This year's dates*, Home's lines, *Paused*, desktop and phone, the Owner, Support and
  the Developer, *Copy* read back from the clipboard, and the Admin page's two switches. **One real run on Ceylon
  Harvester (2026-11-01):** the own date *Test date (made by Claude)* for 21 November, added on *This year's dates*;
  the night job moved to now; the API's worker made the plan with **1 Gemini call (1,330 prompt and 298 completion
  tokens)**, no refusal; the checks re-run on the stored plan pass; 2 products, both in stock; shown on desktop and
  phone; *Coming up* says *Plan ready*. **Left for the owner**, who removes it with *Remove*.
- **Not tested:** a real owner reading, editing or posting a plan (ADR-0072 §10's test has not started);
  *Make it again* on the real model (its job is tested with a fake model and its booking through the route; the real
  call was not spent); a suggested date's plan on a real shop (the real run used an own date); the year turning over
  in January (tested with dates, not lived); any festival plan, since `MOVING_DAYS` is empty until AD12's January
  check; Sinhala and Tamil (R88); the cost in money (the eval reports $0 without `LLM_PRICING_JSON`: counted in calls
  and tokens only); a real phone's clipboard; a catalogue of more than 100 products in stock (unit tests only); a plan
  that chose a fact on a real shop: Ceylon Harvester's one fact (*organic*, about its green tea) did not fit a plan
  about cinnamon and black tea, and the page then said *"Your shoppers haven't asked about anything for this yet"*
  (G125).

## Consequences

- GROW's third page, and the first GROW cost that does not depend on chats: one Gemini call per kept date (two when
  the first answer is refused), plus each *Make it again*.
- **AD12 now matters**: until FiveNeurals writes the moving dates in each January, the festivals show *Date not set
  yet* and get no plan unless the owner sets the day.
- The console has a fourth GROW-or-SELL screen beyond console.md §2's five, and the Admin page a second switch.
- The plans' AI instructions are Claude's words (G121): the owner reads them before the feature is shown to a real
  shop.
