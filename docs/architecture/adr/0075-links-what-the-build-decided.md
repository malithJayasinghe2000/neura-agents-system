# ADR-0075 · Links: What The Build Decided

**Status:** **Accepted** · built 2026-11-02, in five pieces (`9f0da91` data, `857207b` the redirect, `35eccfa` the
routes, the screens, and the docs) · Everything here is Claude's, decided while building
[ADR-0074](0074-grow-counts-the-clicks-on-the-links-an-owner-posts.md) inside what the owner decided (R105 to R119)
and the approved mockup (canvas row 22, boards 80 to 83) · **Date:** 2026-11-02 · **Related:**
[ADR-0073](0073-the-marketing-calendar-what-the-build-decided.md) (the pattern followed), console.md §3.15,
FEATURES.md L8; the log's R120 to R122, G127, G128 and AD13

> **In one sentence:** ADR-0074 is built on the other GROW pages' pattern (tables in the shared core, the console's
> own routes, no agent named), plus one thing new to this codebase: a public address, `/go/<code>`, that runs before
> the shop is known, through one narrow database function; this records every gap the ADR and the boards left, how
> each was settled, and what was and was not tested.

## Decision

### 1. Two tables, one function

`neura_agent_core/links.py`: **`links`** (a plan's link names its date by `date_key` and `day`, as `calendar_plans`,
never by the plan's id, because the plan is deleted 30 days after its date and the link is not; an own link has a
`name`) and **`link_clicks`** (one row per link per **UTC** day, R121). Both under the ordinary tenant policy.

**A tap** runs `neura_follow_link(code, count)`: `SECURITY DEFINER`, owned by the `NOLOGIN` role
`neura_link_follower`, the pattern of `neura_due_tenants()` (ADR-0022) and `neura_waiting_tenants()` (ADR-0058). The
role may read seven columns of `links` (never who made it, its name or its campaign), a catalogue **product's**
document (a policy scoped to `entity_type = 'product'`: never an order or a customer), and add to `link_clicks`.
Each of its three policies is scoped `TO neura_link_follower`, so none widens anything for `neura_app`. It runs in
**`Database.follow_session()`**, a transaction that names no shop and sees nothing (tested). Not `READ ONLY`, unlike
the dispatch session, because counting is a write.

### 2. Where a tap goes (R120)

**The catalogue's address at each tap**, so a page a sync moved needs no update step. **A product gone from the
catalogue, or a catalogue address that is not `http(s)`** (a `javascript:` one was found in a test fixture), opens
the front page of the address the link was made with. The labels are stored with the link, made in Python
(`urlencode`), and added by the function before any `#part`, keeping the address's own query. **The request is never
read for a destination**: tested with `?next=` and a `Referer` pointing elsewhere.

### 3. The code and the address

6 characters from `abcdefghijkmnpqrstuvwxyz23456789` (no `0`, `o`, `1`, `l`), drawn with `secrets`; unique across
every shop by an index, drawn again on a clash (at most 5 times). Anything not shaped like a code is refused before
the database. **`LINKS_BASE_URL`**: `https://go.fiveneurals.com` in production (AD13), and when empty
`PUBLIC_BASE_URL/go`, so a link works on any machine. The route is mounted **outside `/v1`** and left out of the API
description, because its address is in shoppers' posts for good.

### 4. What is not kept (ADR-0074 §5, R118)

The route reads the browser name to tell a robot and nothing else; it sets no cookie; it answers `302` with
`Cache-Control: no-store` and `X-Robots-Tag: noindex`. **uvicorn's own access line prints the phone's address**
(`203.0.113.9:51234 - "GET /go/k7m2qa"`): a logging filter drops that line **for `/go/` only**; our request log
(`RequestContextMiddleware`) writes the path and status, never an address. Nothing else in the API records the client
address for this route (no tracing middleware is installed).

**Robots** (`is_robot`): known preview fetchers and search engines by name, anything with `crawler`, `spider`,
`bot/`, `bot;` or `+http` in its name, scripts (`curl/`, `python-`, `go-http-client`), an empty name, and a name
starting `WhatsApp/` (its preview fetcher; a person's WhatsApp opens the phone's own browser). Facebook's and
Instagram's in-app browsers, and a phone called *CUBOT*, are counted (tested).

### 5. A shop without NEURA-GROW (R122): differs from ADR-0074 §6

ADR-0074 §6 says its links *"keep forwarding and stop counting"*. **Built: they keep forwarding and keep counting,
unseen.** Stopping the count would teach the redirect, or its database function, an agent's name, which `neura-api`
may not know (G88); the Links page is not shown without GROW, and a count is a number per day, nothing about a
person. If GROW comes back, the counts include the gap.

### 6. The routes

`console_links.py`, all `shop:links:write` (the Owner and Support): `GET …/links` (own links newest first with their
clicks; campaigns grouped by date and day, the latest first, posts in the order they are posted: teaser, launch,
email, last chance; `plan_id` while the plan is kept), `GET …/links/products?q=` (the chooser: products with a web
page and not archived, by name, 20 at a time with `more`; `%` and `_` typed are taken literally), `POST …/links`,
`DELETE …/links/{id}` and `POST …/calendar/plans/{id}/links` (**only the plan's own products**, R110, and **only the
post's own places**, R111). The plan's `GET` gains **`post_links`**: each post's product (its newest link's, so the
chooser starts where the owner left it) and its clicks per place, every product's links added together; `null` for
a role without Links. A product with no page of its own gets no link (`NO_PRODUCT_PAGE`).

*Remove* works on any of the shop's links through the API; the page offers it on the owner's own links only, as
board 81 shows. A removed link's clicks are deleted and the row is kept with `removed_at`, so it keeps forwarding
(R113) and is never counted again; copying that post again makes a new link.

### 7. Copying a link that is still being made

The link is made by the API **when the button is pressed** (ADR-0074 §2). Safari lets a page write to the clipboard
only during the tap, and the request takes longer than that, so the page hands the clipboard **a promise** of the
text (`ClipboardItem` with a promise), which Safari and Chrome both accept; a browser without it waits for the link
and copies it the ordinary way; a refusal shows the link to copy by hand. Tested in Chrome with a real click; **not
tested in Safari**.

### 8. Words not on the boards (Claude's)

- The board's ***"· posted"*** after a past post's date is **left out**: we know the day passed, not that the owner
  posted it.
- A deleted plan's campaign says ***"its plan was deleted; the clicks stay here"***, not *"deleted on [date]"*: a plan
  is also deleted when the owner removes its own date, so the day is not always 30 days after.
- *Remove* asks first: *"Remove this link? Its clicks are deleted. The link keeps opening its product."*
- No links yet: *"No links yet. Make one for any product, or copy one from a campaign plan."*
- A plan whose products have no page: *"None of this plan's products has a page in your shop, so there is no link to
  copy."*
- A long catalogue: a search box above the chooser (*"Type to find a product"*) once there are more than 20.
- The menu icon is Lucide's `Link`, as the board's.

## What was tested, and what was not

**Tested:** `tests/unit/test_links.py` (codes, labels, places, robots and real browsers, the access-line filter);
`tests/integration/test_links_postgres.py` (16: made once, a tap counted or not, the catalogue's address now, the
front page, `javascript:` refused, labels before `#`, *Remove*, the lists, a plan's posts, **the follow session sees
no row of any table**, another shop's links invisible, two shops never share a code); `tests/integration/test_go.py`
(4); `tests/integration/test_console_links.py` (9: who, made once, only the plan's products and the post's places,
the plan's clicks, *Make a link* and its refusals, the chooser, the Links page before and after the plan is deleted,
*Remove*); `make console-check`'s new *links* section in real headless Chrome (the plan's buttons on desktop and
phone, a real click with the clipboard read back, a tap through the running API counted and a preview not, *Make a
link*, the Links page on desktop and phone, *Remove*, the menu, Support and the Developer each signed in).

**Not tested:** Safari's clipboard (§7); **Facebook's and WhatsApp's own previews of a link** after the redirect (to
check by hand on Ceylon Harvester once `go.fiveneurals.com` exists, ADR-0074 §8); `go.fiveneurals.com` itself (not
set up, AD13); a real shop's owner posting a link; load (G128: no rate limit yet).

## Consequences

- `neura-api` has its first public address outside `/v1`, and the database its third `SECURITY DEFINER` function.
  Both are listed here so the next one is not a surprise.
- G128 (a rate limit) is open before going online; Claude's suggestion is a limit at the proxy in front of
  `go.fiveneurals.com`, which never reaches our code or logs.
- The ADR index (`docs/architecture/adr/README.md`) stopped at 0064 (G127); fixed in the same docs change.
