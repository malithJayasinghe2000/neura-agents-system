# ADR-0074 · GROW Counts The Clicks On The Links An Owner Posts

**Status:** **Accepted** · the owner's decisions 2026-11-01, R105 to R118 (D16, D18) · everything marked
*(Claude)* is Claude's design, approved with the mockup (R119; canvas row 22, boards 80 to 83, version 65;
console.md §3.15) · **built 2026-11-02** ([ADR-0075](0075-links-what-the-build-decided.md): what the build decided, and what was and was not tested; one sentence of §6 differs, R122) · **Date:** 2026-11-01 · **Builds on:**
[ADR-0072](0072-grow-plans-a-campaign-for-each-date-the-shop-keeps.md) (the plans the links belong to) · **Changes, in
part:** ADR-0072 §1's *"Not built: a results report"*: clicks per post are now counted; sales still are not ·
**Related:** [ADR-0042](0042-we-may-hold-what-the-merchant-already-holds-and-never-watch-a-shopper.md),
[ADR-0044](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md) (why this is not an observed event,
§5)

> **In one sentence:** each post in a campaign plan, and any product the owner chooses on a new **Links** page, gets
> a ready link through `go.fiveneurals.com` that adds 1 to that post's count and sends the shopper straight on to the
> product's page, so the owner sees which post brought people; we keep the count and nothing about the person.

## Context

While the Marketing calendar was being built, the owner asked for *"basic attribution: UTM links plus our own
first-party event tracking"* (D16), so that after a campaign the owner knows **which post brought shoppers**. Later
the same day the owner pasted a fuller version: labelled links, a JavaScript snippet on the store recording landings,
views, cart adds and orders, order matching, and a dashboard of visitors, orders and revenue per channel (R107).

Three things in that version clash with what is decided, and the talk settled each:

| In the paste | What stands in the way | Settled |
|:--|:--|:--|
| A script of ours on the store | [ADR-0044 §2](0044-a-shopper-may-be-observed-only-when-the-shop-switches-it-on.md): nothing of ours runs in a shopper's browser | Not built (R108) |
| Views and cart adds sent by the shop | Built for *Product views* ([ADR-0048](0048-observation-phase-1-what-the-build-decided.md)), but optional, off by default, and it needs a data agreement, a secret key, 3 settings in the shop and a bridge update to carry the labels. The owner: *"setup on the shop's side is not good; count on our side"* | Not built (R108) |
| Orders and revenue per post | Orders are not synced (ADR-0072 §1) | Not counted by us; the labels are passed on, so the shop's own analytics tool can show sales (R109) |

What is left is the smallest thing that answers the owner's question for **every shop, with no setup in the shop**:
a link that counts its own clicks.

## Decision

### 1. What is built, and what is not

**Built:**

- **Links on a plan** (R110, R111, R112): under each social post (teaser, launch, last chance) a link for
  **Facebook**, **Instagram** and **WhatsApp**; under the email, one link; **the banner gets none** (whoever sees it
  is already in the shop). Each post's links open **the product the owner picks** for that post, starting on the
  plan's first product.
- **A Links page** in GROW (D18, R114): a counted link for **any product, any day**, named by the owner.
- **The click counter** (R108, R117): the link points at `go.fiveneurals.com`, which counts the click and forwards the
  shopper, **with the campaign labels** (R109).

**Not built:**

- **Sales, orders, revenue, cart adds per post.** We count clicks only (R105, R109).
- **A script in the shopper's browser** (ADR-0044 §2) and **labelled views from the shop's server** (R108).
- **The shop's own name in the link** (it needs setup in the shop, R117): a later extra, for shops that ask.
- **A counted link on the banner** (R112).
- **QR codes, charts by day, a line on Home** *(Claude)*: each later, if owners ask.

### 2. The link *(Claude, within R108, R110, R111, R117)*

`go.fiveneurals.com/k7m2qa`: the address FiveNeurals sets up (AD13) and **a code of 6 random lowercase letters and
digits**, unique across every shop, with the look-alikes (`0`, `o`, `1`, `l`) left out.

**One link is one product and one place**, and either one post of one plan (*Avurudu 2027, teaser, Facebook*) or one
name on the Links page (*Tuesday post, Facebook*). A plan's link is made **the first time the owner copies it**, not
when the plan is made, so the count of links stays the count of links used. Copying the same post, place and product
again gives the same link. **Changing a post's product makes a new link**: the old one, already in a post, keeps its
product and keeps counting.

**Made by code, never by the AI.** ADR-0072 §6 still holds: a draft text may not hold a link, and the plan writer is
not changed. The owner pastes the link into the post themselves.

### 3. Where a link sends the shopper *(Claude, within R110 and R113)*

- **The product's own page, from the synced catalogue**, as it was when the link was made, and updated when a sync
  brings a new address for that product.
- **Never an address taken from the request, typed by anyone, or written by a model.** So a link can only ever open
  a page of the shop that made it, and our address can never be used to send people to another website.
- **A product no longer in the catalogue:** the shop's front page (the product address's own `https://host/`), not
  an error (R113).
- **A shop removed from NEURA:** its links are deleted with it, so we no longer know where they go; a plain page
  says *"This link is no longer active."*

**The answer is a temporary redirect (`302`) marked not to be stored** (`Cache-Control: no-store`), so every tap
reaches us and is counted; a permanent one would be remembered by the phone and skip us.

### 4. The labels passed on (R109) *(Claude: the values)*

Added to the product's address when forwarding; any query the address already has is kept.

| Label | Campaign link | Link from the Links page |
|:--|:--|:--|
| `utm_source` | `facebook`, `instagram`, `whatsapp`, `email` | the same, or `other` |
| `utm_medium` | `social`, or `email` | `social`, `email` or `other` |
| `utm_campaign` | the date and year: `avurudu-2027`, `black-friday-2027`, an own date's name in the same form | the link's name: `tuesday-post` |
| `utm_content` | `teaser`, `launch`, `last-chance`, `email` | left out |

A shop with a website analytics tool sees each visit's campaign and post there, and with it whatever that tool
tracks, sales included. **We read none of it.**

### 5. What is counted, and what is kept (R116, R118)

**Kept: one number per link per day.** A click on Avurudu's Facebook teaser on April 1 adds 1 to that link's April 1.

**Never kept:** the phone's internet address, its browser name, the page it came from, a cookie, a visit number,
anything about the person. **No cookie is set.** The phone's address is used for one thing, sending the answer back,
as for any web request, and **our request log for this address leaves it out** *(Claude)*.

**Robots are forwarded and not counted** *(Claude, as G117)*: Facebook, WhatsApp and the other apps fetch a link to
draw its preview, and search engines follow links. A request whose browser name is a known preview or search robot,
or says *bot*, *crawler* or *spider*, gets the same redirect and adds nothing. The browser name is read, never stored.
A robot that does not say what it is still counts.

**A click is a tap, not a person.** One person tapping twice counts twice; anyone can tap on purpose to raise a
number. Nothing acts on these numbers by itself, so that is a limit to say on the page, not a risk to guard.

**Why this is not an observed event, and needs no data agreement (R118).** The *observed* column of ADR-0042 and the
switch of ADR-0044 exist to stop us **watching a person**: following one shopper from page to page and keeping a
record about them. A day's count holds no person and cannot follow anyone: there is nothing to join a second tap to.
**The condition is the whole decision:** if a later change wants to keep anything about a tap beyond the day's count
(a session, a time, a device), it is observation, it falls under ADR-0044 (the shop's switch, the agreement), and it
is its own ADR. **The legal text (AD9) should still say in one line that a shopper's tap passes through our server.**

**How long:** a link and its counts stay until the owner removes it (R116), so next year shows last year's numbers.
**Removing** deletes its counts and keeps only what forwarding needs (the code and the address), so a link in an old
post keeps opening its product (R113). A plan's deletion, 30 days after its date (ADR-0072 §8), does not touch its
links. A shop's removal deletes everything.

### 6. Who, and where (R115) *(Claude: the permission and the menu)*

**The Owner and Support**, a new permission `shop:links:write`, never the Developer; only in a shop with NEURA-GROW.
**Links** in the menu after *Marketing calendar*. A shop that loses NEURA-GROW: its links keep forwarding and stop
counting; the page says GROW is not part of the plan, as the other GROW pages do.

**On a plan** (board 80): under each social post, *"This post's link opens"* with the product chooser, then **Copy
Facebook link**, **Copy Instagram link**, **Copy WhatsApp link**, and *"Clicks so far: Facebook 40 · WhatsApp 25 ·
Instagram 5"*; under the email, **Copy the link** and its clicks; under the banner, why it has none. One line on
Instagram: a link inside a post's text can't be tapped there, so it goes in the bio or a story.

**The Links page** (board 81): the owner's own links (name, product, place, clicks, **Copy**, **Remove**), then the
campaigns' links grouped by campaign, with **See the plan** while the plan exists. **Make a link** (board 82):
product, place, name, then the link to copy.

### 7. Data *(Claude)*

Two tables in the shared core, beside the calendar's, so the console reads them without naming an agent (G88):

- `links`: id, `tenant_id`, `code` (unique), `product_id`, the address, the place, either the plan's date and year
  and the post, or the owner's name; who made it and when; `removed_at`.
- `link_clicks`: `link_id`, `tenant_id`, the day, the count; one row per link per day.

Both under the same row-level security as every tenant table. **The redirect is the one place a request arrives
before we know the shop**: it has only the code. It goes through **one narrow database function** that takes a code
and a *count it* flag, adds 1 to today's row when asked, and returns only the address, nothing else from any shop
(Rule 3: tenant isolation is code). It is the only read across shops this feature has.

### 8. Testing (Rule 4)

**No model is on this surface**, and the plan writer is not changed, so the calendar's eval and its injection
resistance of 1.00 stand as they are. The tests are the code's: the labels for each post and place; the robot list;
a code is never reused; **another shop's link is never listed or counted**; the function returns the address and
nothing more; **no address in a request ever becomes a destination**; a removed link still forwards and does not
count; a product gone from the catalogue forwards to the front page. Facebook's and WhatsApp's previews of a link
(drawn from the product's page after our redirect) are checked by hand once, on Ceylon Harvester.

### 9. The falsification test

**If owners who have it copy no link over a season of dates, delete the counter and the Links page**, and keep the
links already posted forwarding (R113). Not "add sales", not "add a script".

## Consequences

- **A shopper's tap now reaches our server**, the first time outside the chat box. What we keep is set by §5; the
  temptation to keep "just the time" or "just the device" is exactly the change §5 makes an ADR.
- **`go.fiveneurals.com` must run for good** (AD13): links in old posts keep working only while it does. Every shop
  shares it, so one shop's misuse could get it blocked on Facebook for all (R117); §3's rule (a link opens only its
  own shop's pages) is the protection, and AD13 says FiveNeurals finds the link and the shop if a warning comes.
- **The first GROW number that is not about what shoppers asked**, and the first that answers part of ADR-0072 §1's
  *results report*. The claim it supports: *"see which post brought people to your shop"*. Not *"which post sold"*,
  not *"tracks your customers"*.
- The console grows by one more screen (Links) beyond console.md §2's five.

## Not decided here

- Sales, orders or cart adds per post: each needs the shop to send data, so ADR-0044's conditions and its own ADR.
- The shop's own name in the link; QR codes; charts by day; a line on Home.
- The page's layout and words: the mockup.

## Alternatives considered

- **Links with labels only, no counter of ours** (R106 A): the owner reads numbers in their own tools; a shop with
  no analytics tool sees nothing for the email. Superseded by R107 and R108.
- **A script in the shopper's browser** (the paste, R107): ADR-0044 §2; it also needs setup in the shop.
- **The shop's server sends labelled views** (R108 B): visits and cart adds, but only for shops that switch views on,
  sign the agreement and update the bridge; none does yet (FEATURES.md L3).
- **One link per post** (R111 B), **the home page** (R110 C), **a counted banner** (R112 B), **counts deleted with
  the plan** (R116 B), **`neura.fiveneurals.com/go/`** (R117 B), **a data agreement required** (R118 B): refused,
  each for the reason in its R.
