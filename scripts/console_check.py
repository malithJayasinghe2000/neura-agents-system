#!/usr/bin/env python3
"""Sign in to the merchant console, in a real browser. ADR-0026.

    make console-check

Free — no models, no cost. Needs the API and the console both running, and it
says so plainly rather than failing with a connection error somebody has to
decode.

**Why a browser and not `curl`.** Everything about this flow is a browser
behaviour that a request library does not have and cannot fake:

* the ``__Host-`` cookie prefix is enforced by the browser, not the server. curl
  stores whatever it is sent. If we ever emit a cookie that Chrome refuses, only
  Chrome will tell us — and the symptom in production is "sign-in silently does
  nothing", the least debuggable failure there is.
* ``HttpOnly`` is only meaningful against script. Asserting that
  ``document.cookie`` cannot see the session is the actual claim, and it can only
  be made from inside a page.
* the redirect after redemption is client-side routing.

It now covers **screen 3, Review**, as well, and for the same class of reason:
the three rules `console.md §3.2` sets for that screen — show the evidence, make
a withheld turn look withheld, invent no numbers — are all claims about what a
*rendered page* contains. A pytest assertion on a JSON body cannot make any of
them; it can only prove that the server offered the material the screen might
have ignored.

To have something to grade, this seeds two shadow turns for the first shop the
person can act for, and removes exactly those rows afterwards. It never touches
anything it did not create.

This is the console's half of the deterministic bar in `console.md §6`, and it
follows `make widget-check` deliberately: the same hand-rolled CDP driver, the
same argument. *A control nothing runs is not a control that works.*
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import create_async_engine
from widget_check import Chrome, find_chrome

from neura_agent_core.conversations import (
    ConversationRepository,
    ConversationState,
    conversation_messages,
    conversations,
)
from neura_agent_core.rag.schema import document_chunks
from neura_agent_core.shadow import ShadowRepository, ShadowTurn, shadow_turns
from neura_agent_core.waiting import WaitingAnswerRepository, waiting_answers
from neura_commerce.pagination import Cursor
from neura_commerce.sync.schema import sync_checkpoints, synced_entities
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, memberships_for, request_sign_in_link
from neura_core.jobs import job_queue
from neura_core.observation import (
    ObservedEvent,
    ObservedEventRepository,
    ObservedEventType,
    observed_events,
)
from neura_core.tenancy.schema import api_keys, shop_checks, tenant_stores, tenant_usage
from neura_core.tenancy.usage import UsageDelta, UsageMeter, today

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
OFF = "\033[0m"


async def reachable(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.get(url)
    except Exception:
        return False
    return True


async def main() -> int:
    load_env()
    settings = get_settings()
    console = settings.console_base_url.rstrip("/")
    # NOT `settings.api_port`. That defaulted to 8000, where an unrelated
    # application was listening — so the reachability check passed against the
    # wrong server and every failure below was misattributed. A check that can
    # pass against something else is not a check (open question E6, again).
    api = os.environ.get("API_BASE_URL", "http://localhost:8010").rstrip("/")

    email = sys.argv[1] if len(sys.argv) > 1 else ""
    if not email:
        print("\n  usage: make console-check EMAIL=owner@shop.com\n")
        return 2

    print(f"\n  {BOLD}console sign-in — a real browser, a real link{OFF}")
    print(f"  {DIM}console  {console}{OFF}")
    print(f"  {DIM}api      {api}{OFF}\n")

    for label, url in (("API", f"{api}/v1/console/me"), ("console", console)):
        if not await reachable(url):
            print(f"  {RED}✘ the {label} is not running at {url}{OFF}")
            print(f"  {DIM}Start it, then re-run. Nothing below was measured.{OFF}\n")
            return 1

    db = Database.from_settings()
    failures: list[str] = []
    seeded: dict[str, str] = {}
    sell_seeded: dict[str, str] = {}
    seeded_choice: dict[str, str] = {}

    try:
        async with db.identity_session() as session:
            minted = await request_sign_in_link(session, email=email, console_base_url=console)
        if not minted.minted:
            print(f"  {RED}✘ no account for {email}{OFF}")
            print(f"  {DIM}Create one: make user-new EMAIL={email} TENANT=tn_...{OFF}\n")
            return 1

        # Which shop this person may act for — asked the same way the API asks,
        # so a check that passes here is a check about the real membership and
        # not about a tenant id typed into this file.
        async with db.identity_session(minted.user_id) as session:
            held = await memberships_for(session, minted.user_id)

        # Since 2026-09-30 a shop without NEURA-SELL is not shown Sold out, so
        # the Sold out checks need a shop WITH it — seeded separately when the
        # first shop lacks it, and removed by id like the first. The first shop
        # stays the one every other screen is checked on. A shop without SELL
        # is also checked for the screens it must NOT show.
        with_sell = [m.tenant_id for m in held if await _holds_sell(db, m.tenant_id)]
        without_sell = [m.tenant_id for m in held if m.tenant_id not in with_sell]
        if held:
            seeded = await _seed_shop(db, held[0].tenant_id)
            seeded["sell"] = "yes" if held[0].tenant_id in with_sell else ""
            sell_seeded = seeded if seeded["sell"] else {}
            if not sell_seeded and with_sell:
                sell_seeded = await _seed_shop(db, with_sell[0])
        else:
            print(f"  {DIM}no membership — the Review checks below are skipped, not passed{OFF}")

        chrome = find_chrome()

        async with Chrome(chrome) as browser:
            # 1. The signed-out screen.
            await browser.goto(console)
            await asyncio.sleep(2)
            heading = await browser.evaluate("document.body.innerText")
            _check(
                "the sign-in screen offers a link, not a password", "Sign in" in heading, failures
            )
            # The element, not the word — the screen legitimately says "No password
            # to remember", and matching on the copy failed for the right reason.
            password_inputs = await browser.evaluate(
                "document.querySelectorAll('input[type=password]').length"
            )
            _check("no password field exists", password_inputs == 0, failures)

            # 2. Follow the link, exactly as a person clicking mail would.
            await browser.goto(minted.url)
            await asyncio.sleep(4)

            landed = await browser.evaluate("window.location.pathname")
            _check("the link lands on the console", landed == "/console", failures)

            body = await browser.evaluate("document.body.innerText")
            _check("the console lists the person's shops", "Your shops" in body, failures)
            if held:
                # By the name the shop has on record — `tn_01M…` means nothing
                # to an owner, and the landing page must not ask them to read it.
                name = await _shop_name(db, held[0].tenant_id)
                _check(
                    "a shop is listed by its name, not its id",
                    bool(name) and name in body,
                    failures,
                )

            # 3. The claim HttpOnly actually makes. Only a page can test this.
            visible = await browser.evaluate("document.cookie")
            _check(
                "the session cookie is invisible to script",
                COOKIE_NAME not in (visible or ""),
                failures,
            )

            # 4. The rule the whole console rests on (ADR-0026 §3).
            _check(
                "no API key was handed to the browser",
                "fn_sk_" not in body and "fn_pk_" not in body,
                failures,
            )

            # 5. Screen 3 — Review. Skipped rather than passed when there is no
            #    shop to review for: a check with nothing to look at has told us
            #    nothing, and scoring that as a pass is how a green run stops
            #    meaning anything (open question E6, the same lesson).
            if seeded:
                print(f"\n  {BOLD}home — what needs the owner, said first{OFF}")
                await _check_home(browser, console, seeded, failures)
                await _check_mode_switch(browser, console, seeded, failures)

                print(f"\n  {BOLD}review — grading what the agent would have said{OFF}")
                await _check_review(browser, console, seeded, failures)

                print(f"\n  {BOLD}conversations — what it actually said{OFF}")
                await _check_conversations(browser, console, seeded, failures)

                print(f"\n  {BOLD}a handed-over shopper waits — answer by email{OFF}")
                await _check_handover(browser, console, db, seeded, failures)

                print(f"\n  {BOLD}shop and usage — connection, and honest numbers{OFF}")
                await _check_shop_and_usage(browser, console, seeded, failures)
                await _check_contact(browser, console, seeded, failures)
                await _check_customer_secret(browser, console, seeded, failures)

                print(f"\n  {BOLD}help — connecting your shop{OFF}")
                await _check_help(browser, console, seeded, failures)

                print(f"\n  {BOLD}people — each role sees only its screens{OFF}")
                await _check_people_and_roles(browser, console, seeded, minted.user_id, failures)

                print(f"\n  {BOLD}a shop not connected yet — Home and a passed check{OFF}")
                await _check_before_connecting(browser, console, minted.user_id, failures)

                if sell_seeded:
                    print(f"\n  {BOLD}sold out — demand, counted, never who{OFF}")
                    await _check_sold_out(browser, console, sell_seeded, failures)
                    print(f"\n  {BOLD}rarely added to cart: Sold out's second tab{OFF}")
                    await _check_rarely_added(browser, console, sell_seeded, failures)
                else:
                    print(f"  {DIM}no shop with SELL — the Sold out checks are skipped{OFF}")

                print(f"\n  {BOLD}missing from your pages — GROW's page, Home's line{OFF}")
                await _check_gaps(browser, console, db, minted.user_id, seeded, failures)
                print(f"\n  {BOLD}shoppers asked for: GROW's second page, Home's line{OFF}")
                await _check_wanted(browser, console, db, minted.user_id, seeded, failures)
                print(f"\n  {BOLD}marketing calendar: GROW's third page, Home's lines{OFF}")
                await _check_calendar(browser, console, db, minted.user_id, seeded, failures)
                print(f"\n  {BOLD}links: GROW's fourth page, a plan's post links{OFF}")
                await _check_links(browser, console, api, db, minted.user_id, seeded, failures)

            print(f"\n  {BOLD}sign up — Create an account, the waiting screen, approval{OFF}")
            await _check_sign_up(console, failures)

            print(f"\n  {BOLD}FiveNeurals admin — shops, approve, refuse, switches, AI use{OFF}")
            await _check_admin(console, email, failures)

            if without_sell:
                print(f"\n  {BOLD}a shop without NEURA-SELL — its screens are not shown{OFF}")
                await _check_without_sell(browser, console, without_sell[0], failures)
            else:
                print(f"  {DIM}every shop has SELL — the without-SELL checks are skipped{OFF}")

            # Screen 7 needs a shop with SELL, which the first membership may not
            # have. Found rather than assumed, and skipped — not passed — when
            # this person holds no such shop.
            sell_shop = await _seed_choice(db, held) if held else None
            if sell_shop:
                seeded_choice = sell_shop
                print(f"\n  {BOLD}suggestions — the owner's choice wins{OFF}")
                await _check_suggestions(browser, console, db, sell_shop, failures)
            else:
                print(f"  {DIM}no shop with SELL — the Suggestions checks are skipped{OFF}")

            # 6. The link is single use. Reloading it must not sign anyone in again.
            await browser.goto(minted.url)
            await asyncio.sleep(3)
            second = await browser.evaluate("document.body.innerText")
            _check(
                "a used link is refused the second time",
                # The page renders a typographic apostrophe; matching on the two
                # words either side avoids depending on which one React emitted.
                "work" in second and "new link" in second.lower(),
                failures,
            )
    finally:
        if seeded:
            await _unseed_shop(db, seeded)
        if sell_seeded and sell_seeded is not seeded:
            await _unseed_shop(db, sell_seeded)
        if seeded_choice:
            await _unseed_choice(db, seeded_choice)
        await db.dispose()

    print()
    if failures:
        print(f"  {RED}{len(failures)} check(s) failed.{OFF}\n")
        return 1
    print(f"  {GREEN}The console works in a real browser.{OFF}")
    print(f"  {DIM}Evidence about THIS build and THIS browser, and nothing more.{OFF}\n")
    return 0


#: ADR-0062: two handed-over shoppers waiting for the shop's answer.
SEEDED_WAITING_QUESTION = "Can I return an opened pack of console-check tea?"
SEEDED_SIGNED_IN_QUESTION = "Can you change the delivery address on my console-check parcel?"
SEEDED_SHOPPER_EMAIL = "console-check-shopper@example.com"
SEEDED_CUSTOMER = "console-check-385"
SEEDED_ASK = "I can't answer this here. Leave your email so our store can answer you."
SEEDED_WITH_STORE = (
    "I can't answer this here. Your question is with our store, and they can answer you by email."
)

#: What the seeded shopper asks. Distinctive enough that finding it on the page
#: cannot be a coincidence, and about a policy so that the cited evidence is a
#: document rather than a tool.
SEEDED_QUESTION = "can I return these boots after 20 days?"

#: The merchant's own words, which is what "show the evidence" means. The check
#: below fails unless this exact sentence is rendered on the review screen.
SEEDED_POLICY = "Returns are accepted within 30 days of delivery, unworn."

#: A reply a shopper genuinely received, for the Conversations screen. Review
#: holds what the agent *would* have said; this is what it *did* say.
SEEDED_REPLY = "Unworn boots can be returned within 30 days of delivery."

#: What the agent *would* have said to SEEDED_QUESTION, held in practice mode.
#: Since 2026-09-28 the chat page shows it under the question, marked not sent.
SEEDED_DRAFT = "Yes — unworn boots can be returned within 30 days of delivery."

#: The cited policy's title in the synced catalogue. The chat page names what a
#: reply looked at by this, never as `policy:console-check-returns`.
SEEDED_POLICY_TITLE = "Console-check Returns Policy"

#: A message carrying the guard's placeholders. On the screen these must be
#: **explained** — `[EMAIL_1]` left bare reads to a merchant as lost data.
SEEDED_TOKENISED = "my email is [EMAIL_1] and my address is [ADDRESS_1] — where is my order?"

#: Written into the seeded store's `credentials` and `wrapped_dek`.
#:
#: The point of a recognisable placeholder: "no credential reached the screen"
#: has to be an assertion about a string that is **really in the row**. Without a
#: seeded store the check passes against an empty screen, which proves nothing —
#: the same class of false pass as an API check that succeeded against the wrong
#: server (open question E6).
# S105 reads this as a hardcoded password, the same way it reads the `lgt_` id
# prefix in `neura_core.ids`. It is neither: it is a marker written into a
# throwaway row so that the assertion *"this never reaches the page"* is about a
# string that is really in the database. A real secret here would defeat the
# check — the whole point is that it is worthless and recognisable.
SEEDED_SECRET = "CONSOLE-CHECK-SECRET-MUST-NEVER-BE-RETURNED"  # noqa: S105

#: The platform the seeded store claims. Not a real one: `AGENTS.md` rule 1 keeps
#: platform names out of every file outside `neura-adapters`, and a fixture is a
#: file.
SEEDED_PLATFORM = "console-check"

#: Screen 6's seeded demand (ADR-0046 stage 1). The session tokens are
#: recognisable on purpose: the check is that neither ever reaches the page.
SEEDED_SOLD_OUT_TITLE = "Console-check Sold-out Jumper"
SEEDED_IN_STOCK_TITLE = "Console-check In-stock Jumper"
SEEDED_SOLD_OUT_ID = "console-check-sold-out"
SEEDED_IN_STOCK_ID = "console-check-in-stock"
SEEDED_SESSIONS = ("consolechecksessionAAAAAAAAAAAAAAAA", "consolechecksessionBBBBBBBBBBBBBBBB")
#: *Rarely added to cart* (ADR-0071): an in-stock product 12 visitors opened
#: and 1 of them added to the cart, so it is listed (fewer than 1 in 10).
SEEDED_RARELY_TITLE = "Console-check Rarely-added Teapot"
SEEDED_RARELY_ID = "console-check-rarely-added"
SEEDED_RARELY_URL = "https://shop.example/console-check-teapot"
SEEDED_RARELY_SESSIONS = tuple(f"consolechecksessionR{n:015d}" for n in range(12))

#: Screen 7's seeded products (ADR-0050). Two, so the owner's choice of one
#: for the other can be seen on the page. Filed under this check's own
#: platform string and fingerprint, so cleanup finds exactly these rows.
SEEDED_CHOICE_ANCHOR = ("console-check-anchor", "Console-check Plain Tee")
SEEDED_CHOICE_PICK = ("console-check-pick", "Console-check Better Tee")

#: The agent this check bills its seeded usage to.
#:
#: **Not `care`.** This writes into a developer's own database, where the tenant
#: may be a real shop with real metered usage in it, and `tenant_usage` is keyed
#: by (tenant, day, agent) — so a teardown that removed today's `care` row would
#: delete a real one. A key nothing else uses makes the cleanup exact.
SEEDED_AGENT = "console-check"


async def _check_review(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """The three rules of `console.md §3.2`, asserted against a rendered page.

    Every one of them is a claim about what a *grader sees*. The API returning
    the right JSON is necessary and is not the claim — a screen that fetched the
    evidence and never rendered it would satisfy every pytest assertion in
    `tests/integration/test_console_review.py` and still be the wrong screen.
    """
    review = f"{console}/console/{seeded['tenant']}/review"
    await browser.goto(review)
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")

    _check("the queue lists what the agent drafted", SEEDED_QUESTION in page, failures)

    # Rule 2, half one: the screen says, before anything else, that no shopper
    # saw any of it. Said once, at the top, since the 2026-09-27 redesign.
    _check("a withheld turn says so", "No shopper saw any of these replies" in page, failures)

    # Rule 4 on the queue: counts only. An unreviewed queue is not a queue that
    # failed review, so there is no percentage, and the graded tab says plainly
    # that nothing has been graded.
    _check("no unmeasured cost is printed as a figure", "$0" not in page, failures)
    await browser.goto(f"{review}?show=graded")
    await asyncio.sleep(3)
    nothing_graded = await browser.evaluate("document.body.innerText")
    _check(
        "an ungraded queue reports no agreement figure",
        "%" not in page and "%" not in nothing_graded and "graded yet" in nothing_graded,
        failures,
    )

    # Rule 1. A grader who cannot see what the agent worked from is grading
    # fluency (E7) — so the evidence is on the page *with the buttons*, in the
    # reply that is open, not behind another click.
    await browser.goto(f"{review}?turn={seeded['answered']}")
    await asyncio.sleep(3)
    opened = await browser.evaluate("document.body.innerText")
    _check(
        "the evidence is on the page, not behind a click",
        SEEDED_POLICY in opened and "send this" in opened,
        failures,
    )
    _check("no API key reached the review screen", "fn_sk_" not in opened, failures)

    # Rule 2, half two, and the one a hurried build breaks: the turn the agent
    # *declined* is in the queue and explains itself instead of rendering an
    # empty box (ADR-0020).
    await browser.goto(f"{review}?turn={seeded['declined']}")
    await asyncio.sleep(3)
    declined = await browser.evaluate("document.body.innerText")
    _check(
        "the turn the agent declined is in the queue and explains itself",
        "handed this to a person" in declined,
        failures,
    )

    # The filters narrow, say that they narrow, and match nothing honestly.
    await browser.goto(f"{review}?state=escalated")
    await asyncio.sleep(3)
    narrowed = await browser.evaluate("document.body.innerText")
    _check(
        "a filtered queue says it is filtered and how to clear it",
        "Showing 1 of" in narrowed and "Show all" in narrowed,
        failures,
    )
    await browser.goto(f"{review}?asked=today")
    await asyncio.sleep(3)
    _check(
        "a date filter finds today's replies in the reader's own day",
        SEEDED_QUESTION in await browser.evaluate("document.body.innerText"),
        failures,
    )
    await browser.goto(f"{review}?asked=custom&from=2020-01-01&to=2020-01-02")
    await asyncio.sleep(3)
    _check(
        "a date filter with nothing in it says so",
        "No waiting reply matches" in await browser.evaluate("document.body.innerText"),
        failures,
    )

    # And the write path, through the real button rather than through fetch:
    # a screen whose grade does not persist is a screen that produces no
    # graded turns, which is the entire reason this one was built first (E1).
    await browser.goto(f"{review}?turn={seeded['answered']}")
    await asyncio.sleep(3)
    clicked = await browser.evaluate(_CLICK_VERDICT)
    _check("the queue offers a verdict to click", bool(clicked), failures)

    if clicked:
        await asyncio.sleep(4)
        # Good opens the next waiting reply by itself — the inbox's whole point.
        _check(
            "grading a reply opens the next one",
            seeded["declined"] in await browser.evaluate("window.location.search"),
            failures,
        )
        # And the count in the side menu follows at once, rather than reading
        # two until somebody reloads (a layout is not re-rendered on its own).
        badge = await browser.evaluate(
            "document.querySelector('#shop-menu a[href$=\"/review\"]')?.textContent || ''"
        )
        _check("the side menu's count goes down with it", "1 waiting" in badge, failures)
        await browser.goto(f"{review}?show=graded")
        await asyncio.sleep(3)
        after = await browser.evaluate("document.body.innerText")
        _check(
            "a verdict given in the browser is still there after a reload",
            "Good" in after and SEEDED_QUESTION in after,
            failures,
        )


#: Click the first "Good — I'd send this" button on the page.
#:
#: By its text, because that text is what a merchant reads — a `data-testid`
#: would let the label change to something wrong while this stayed green. The
#: apostrophe is matched loosely for the reason the sign-in check gives: React
#: may emit either form.
_CLICK_VERDICT = """
(() => {
  const button = [...document.querySelectorAll('button')]
    .find((b) => /send this/i.test(b.textContent || ''));
  if (!button) return false;
  button.click();
  return true;
})()
"""


async def _check_home(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """The shop's Home (2026-09-27), against the rendered page.

    Home is the screen most likely to become the dashboard console.md §3.5
    warns about, so it is held to the same rules as Usage: the mode before any
    figure, every count with its period, no rate, no `$0`. Also the frame: a
    side menu with the shop's name, and on a phone one menu button and no
    sideways scrolling.
    """
    # A desktop window, said explicitly: headless Chrome's default is narrower
    # than the width at which the side menu stops folding into a button, and
    # `innerText` — rightly — does not read what is folded away.
    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=1280,
        height=900,
        deviceScaleFactor=1,
        mobile=False,
    )
    await browser.goto(f"{console}/console/{seeded['tenant']}")
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")

    _check("home renders", "Needs you" in page, failures)
    _check(
        "the mode is stated before any figure",
        ("Practice mode is on" in page or "Your assistant is live" in page)
        and page.find("Practice mode is on" if "Practice mode is on" in page else "is live")
        < page.find("Last 7 days"),
        failures,
    )
    # The seed left two drafts ungraded; Review has not run yet.
    _check(
        "the drafts waiting are what needs the owner", "waiting for your review" in page, failures
    )
    _check("every count names its period", "Last 7 days" in page, failures)
    _check("no rate of any kind is shown", "%" not in page, failures)
    _check("no unmeasured cost is printed as a figure", "$0" not in page, failures)
    _check(
        "the side menu carries the shop and its screens",
        "Switch shop" in page and "Shop connection" in page and "Usage and cost" in page,
        failures,
    )
    _check("no API key reached home", "fn_sk_" not in page and "fn_pk_" not in page, failures)

    # A phone: the menu folds into one button, and nothing scrolls sideways.
    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=390,
        height=844,
        deviceScaleFactor=1,
        mobile=True,
    )
    try:
        await browser.goto(f"{console}/console/{seeded['tenant']}")
        await asyncio.sleep(3)
        _check(
            "on a phone the menu is one button",
            await browser.evaluate("!!document.querySelector('button[aria-controls=shop-menu]')"),
            failures,
        )
        _check(
            "on a phone nothing scrolls sideways",
            await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            failures,
        )
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")


async def _shop_name(db: Database, tenant_id: str) -> str | None:
    from neura_core.tenancy import TenantRepository

    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).get(tenant_id)
    return tenant.name if tenant is not None and tenant.name else None


async def _check_conversations(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """Screen 2, against a rendered page.

    The claims here are all about **not flattening** something the data keeps
    apart. A transcript screen is the easiest place in the product to turn five
    conversation states into "done" and a tokenised message into what looks like
    lost data, and neither shows up in a JSON assertion.
    """
    await browser.goto(f"{console}/console/{seeded['tenant']}/conversations")
    await asyncio.sleep(3)

    page = await browser.evaluate("document.body.innerText")

    _check("the conversation list renders", "Conversations" in page, failures)

    # ADR-0012: an escalation costs a person's time and a withheld turn costs
    # nobody anything. A screen that called both "done" would hide the only
    # distinction a merchant acts on.
    _check(
        "an escalated thread says a person was handed it",
        "Handed to a person" in page,
        failures,
    )
    _check(
        "a shadowed thread says it is held for review, not answered",
        "Held for your review" in page,
        failures,
    )

    # 2026-09-27: a row leads with what the shopper asked, and a tokenised one
    # is explained on the list as well as in the transcript.
    _check("each row leads with the shopper's question", SEEDED_QUESTION in page, failures)
    _check(
        "a tokenised question on the list is explained there",
        "[EMAIL_1]" in page and "replaced before the model saw it" in page,
        failures,
    )
    _check("the list says how many there are", "Showing 1\u2013" in page, failures)
    # The seeded chats are CARE's. Named as the merchant buys it (the owner's
    # decision, 2026-09-28), never by its key.
    _check("an assistant is named as the merchant buys it", "NEURA-CARE" in page, failures)

    await browser.goto(f"{console}/console/{seeded['tenant']}/conversations?q=boots")
    await asyncio.sleep(3)
    found = await browser.evaluate("document.body.innerText")
    _check(
        "a search finds what the shopper wrote, and only that",
        SEEDED_QUESTION in found and "where is my order?" not in found and "that match" in found,
        failures,
    )

    await browser.goto(
        f"{console}/console/{seeded['tenant']}/conversations?q=console-check-matches-nothing"
    )
    await asyncio.sleep(3)
    nothing = await browser.evaluate("document.body.innerText")
    _check(
        "a search with no match says so, not an empty page",
        "No conversation matches" in nothing,
        failures,
    )

    _check(
        "no credential reached the list",
        "MUST-NEVER" not in page and "fn_sk_" not in page,
        failures,
    )

    # One transcript, opened the way a merchant opens one.
    await browser.goto(
        f"{console}/console/{seeded['tenant']}/conversations/{seeded['answered_conversation']}"
    )
    await asyncio.sleep(3)
    thread = await browser.evaluate("document.body.innerText")

    _check("the transcript shows both sides", SEEDED_REPLY in thread, failures)
    _check("the shopper's own words are there", "where is my order?" in thread, failures)

    # The tokens. Left bare, `[EMAIL_1]` reads to a merchant as data the product
    # lost — so the screen has to say what it is, in the same place it appears.
    _check("a tokenised message is rendered", "[EMAIL_1]" in thread, failures)
    _check(
        "and the screen explains what the token is",
        "replaced before the model saw it" in thread,
        failures,
    )

    # 2026-09-28: what a reply looked at, by the name the owner knows it by —
    # and none of our words (`policy:…`, `order_status`) on the page.
    _check(
        "a reply's source is named from the catalogue, not by its id",
        SEEDED_POLICY_TITLE in thread and "policy:console-check-returns" not in thread,
        failures,
    )
    _check("the question type is not shown", "order_status" not in thread, failures)

    # A held chat shows what the assistant wrote, under the question, each reply
    # with its own way to Review. By now Review has graded the answered draft
    # and left the declined one waiting, so both states are on this page.
    await browser.goto(
        f"{console}/console/{seeded['tenant']}/conversations/{seeded['conversation']}"
    )
    await asyncio.sleep(3)
    held = await browser.evaluate("document.body.innerText")
    _check(
        "a held chat shows the reply the assistant wrote, marked as not sent",
        SEEDED_DRAFT in held and "Held — not sent" in held,
        failures,
    )
    _check(
        "and says the shopper saw none of it",
        "The shopper saw none of the replies below." in held,
        failures,
    )
    _check(
        "a held turn with no reply says why rather than showing an empty bubble",
        "handed this to a person" in held,
        failures,
    )
    _check("a graded reply says it is graded", "You graded this" in held, failures)
    links = await browser.evaluate(
        "[...document.querySelectorAll('a')]"
        ".filter((a) => /Grade this reply/.test(a.textContent || ''))"
        ".map((a) => a.getAttribute('href'))"
    )
    waiting = f"/console/{seeded['tenant']}/review?turn={seeded['declined']}"
    _check(
        "a waiting reply links to exactly that reply in Review",
        waiting in (links or []),
        failures,
    )
    await browser.goto(f"{console}{waiting}")
    await asyncio.sleep(3)
    _check(
        "and the link opens it there, beside the grade buttons",
        seeded["declined"] in await browser.evaluate("window.location.search")
        and "Would you have sent this?" in await browser.evaluate("document.body.innerText"),
        failures,
    )

    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=390,
        height=844,
        deviceScaleFactor=1,
        mobile=True,
    )
    try:
        await browser.goto(
            f"{console}/console/{seeded['tenant']}/conversations/{seeded['conversation']}"
        )
        await asyncio.sleep(3)
        _check(
            "on a phone the chat does not scroll sideways",
            await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            failures,
        )
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")


async def _check_handover(
    browser: Chrome, console: str, db: Database, seeded: dict[str, str], failures: list[str]
) -> None:
    """ADR-0062 §6 and §7, console.md §3.10, against rendered pages: who waits,
    the box at the top of a waiting chat, *Answer by email* (a `mailto:` link,
    since NEURA sends nothing), *Mark as answered* asking first, and Home."""
    tenant = seeded["tenant"]
    base = f"{console}/console/{tenant}"

    await browser.goto(f"{base}/conversations")
    await asyncio.sleep(3)
    chip = await browser.evaluate(
        "(document.querySelector('[data-waiting-chip]') || {}).innerText || ''"
    )
    menu = await browser.evaluate(
        "(document.querySelector('[data-waiting-count]') || {}).innerText || ''"
    )
    _check(
        "Conversations offers Waiting for an answer, with how many",
        "Waiting for an answer" in chip and "2" in chip,
        failures,
    )
    _check("the menu shows the same count beside Conversations", menu.strip() == "2", failures)

    await browser.goto(f"{base}/conversations?state=waiting")
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")
    _check(
        "the waiting list says how many wait, and why they can be reached",
        "2 shoppers are waiting for an answer." in page,
        failures,
    )
    _check(
        "it holds both waiting chats and nothing else",
        SEEDED_WAITING_QUESTION in page
        and SEEDED_SIGNED_IN_QUESTION in page
        and SEEDED_QUESTION not in page,
        failures,
    )
    _check(
        "each row says how to reach the shopper",
        "left an email" in page and "signed in to your shop" in page,
        failures,
    )
    _check("no address is on the list", SEEDED_SHOPPER_EMAIL not in page, failures)

    await browser.goto(f"{base}/conversations/{seeded['waiting_conversation']}")
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")
    mailto = await browser.evaluate(
        "(document.querySelector('[data-answer-by-email]') || {}).href || ''"
    )
    _check(
        "a waiting chat opens with the box at the top",
        "This shopper is waiting for an answer" in page and SEEDED_SHOPPER_EMAIL in page,
        failures,
    )
    _check(
        "Answer by email opens the team member's own email app, filled in",
        mailto.startswith(f"mailto:{SEEDED_SHOPPER_EMAIL}?subject=Your%20question%20to%20")
        and "You%20asked%20us%20in%20the%20chat%20on%20our%20website" in mailto
        and "console-check%20tea" in mailto,
        failures,
    )
    _check(
        "the chat says where the shopper left their email, without it",
        "The shopper left their email for an answer" in page,
        failures,
    )

    await browser.goto(f"{base}/conversations/{seeded['signed_in_conversation']}")
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")
    _check(
        "a signed-in shopper the shop cannot give is named, to find in the shop's admin",
        f"Find customer {SEEDED_CUSTOMER} in your shop's admin" in page
        and not await browser.evaluate("!!document.querySelector('[data-answer-by-email]')"),
        failures,
    )

    await browser.goto(base)
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")
    links = await browser.evaluate(
        "[...document.querySelectorAll('a')].filter((a) => a.textContent.trim() === 'Answer them')"
        ".map((a) => a.getAttribute('href'))"
    )
    _check(
        "Home says first who is waiting, and opens them",
        "shoppers are waiting for an answer" in page
        and f"/console/{tenant}/conversations?state=waiting" in (links or []),
        failures,
    )

    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=390,
        height=844,
        deviceScaleFactor=1,
        mobile=True,
    )
    try:
        await browser.goto(f"{base}/conversations/{seeded['waiting_conversation']}")
        await asyncio.sleep(3)
        _check(
            "on a phone a waiting chat does not scroll sideways",
            await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            failures,
        )
        heights = await browser.evaluate(
            "[...document.querySelectorAll('[data-waiting-box] a, [data-waiting-box] button')]"
            ".map((b) => b.getBoundingClientRect().height)"
        )
        _check(
            "and its buttons are 44px high",
            bool(heights) and all(height >= 44 for height in heights),
            failures,
        )
        dot = await browser.evaluate("!!document.querySelector('[data-waiting-dot]')")
        _check("the phone's menu button carries a dot while someone waits", dot, failures)
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")

    # Last, because it changes what waits: Mark as answered asks first.
    await browser.goto(f"{base}/conversations/{seeded['waiting_conversation']}")
    await asyncio.sleep(3)
    await browser.evaluate(
        "(document.querySelector('[data-mark-answered]') || { click() {} }).click() || true"
    )
    await asyncio.sleep(1)
    asked = await browser.evaluate("document.body.innerText")
    _check(
        "Mark as answered asks first, and says the email goes",
        "Mark as answered?" in asked and "We delete the shopper's email" in asked,
        failures,
    )
    await browser.evaluate(
        "(document.querySelector('[data-confirm-answered]') || { click() {} }).click() || true"
    )
    await asyncio.sleep(3)
    done = await browser.evaluate("document.body.innerText")
    async with db.tenant_session(tenant) as session:
        row = await WaitingAnswerRepository(session).get(tenant, seeded["waiting_conversation"])
    _check(
        "then it says who answered, and the address is gone from the database",
        "The shopper's email is deleted." in done
        and row is not None
        and row.email is None
        and row.answered_at is not None,
        failures,
    )
    menu = await browser.evaluate(
        "(document.querySelector('[data-waiting-count]') || {}).innerText || ''"
    )
    _check("and the menu's count drops by one", menu.strip() == "1", failures)


async def _check_shop_and_usage(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """Screens 4 and 5, against rendered pages.

    Two claims, and both are about what must **not** be on the screen. A
    credential that is never displayed and a figure that never pretends to be a
    measurement are properties of the rendered page, and neither survives being
    asserted only against JSON: a screen can perfectly well fetch a safe payload
    and then print `$0.00` under the word "cost".
    """
    checks_before = await _shop_checks_of(seeded["tenant"])
    await browser.goto(f"{console}/console/{seeded['tenant']}/shops")
    await asyncio.sleep(3)
    shop = await browser.evaluate("document.body.innerText")
    checks_after_load = await _shop_checks_of(seeded["tenant"])

    # The connection has to be *on* the screen, or every assertion below passes
    # against an empty page and proves nothing (open question E6, again).
    _check(
        "the connected shop is on the screen",
        "console-check.invalid" in shop,
        failures,
    )
    # What the last sync WROTE — new or changed — which is what the count is;
    # "118 read" claimed a read count nobody records (2026-09-28).
    _check("what the last sync changed is reported", "118 new or changed" in shop, failures)

    # The 2026-09-28 redesign (console.md §3.4): a checklist, with one set of
    # connection steps per connection this shop holds — counted in the database,
    # because whether this shop had one of its own before the seed is not ours
    # to assume — and the seed's among them.
    connections = await browser.evaluate(
        "document.querySelectorAll('[data-item=connected]').length"
    )
    held = await _store_count(seeded["tenant"])
    _check(
        f"the setup checklist lists every connection ({connections} of {held})",
        connections == held
        and "Get set up" in shop
        and await browser.evaluate(
            f"!!document.querySelector('[data-item=connected][data-store=\"{seeded['store']}\"]')"
        ),
        failures,
    )
    _check(
        "the chat box, the agreement and product views are on the checklist",
        await browser.evaluate(
            "['chat-box','agreement','views'].every(i => document.querySelector(`[data-item=${i}]`))"
        )
        if seeded["sell"]
        # The two optional steps are for Sold out, which a shop without SELL is not shown.
        else await browser.evaluate("!!document.querySelector('[data-item=chat-box]')"),
        failures,
    )
    # Since ADR-0052 the page opens on the LAST check, read from our own table,
    # so a connection checked before shows that result. The claim is about the
    # shop: loading the page starts no check, and the seeded connection, never
    # checked, says so.
    _check(
        "the shop is not asked on a page load",
        checks_after_load == checks_before
        and await browser.evaluate(
            f"(document.querySelector('[data-item=check][data-store=\"{seeded['store']}\"]')"
            " || {dataset: {}}).dataset.step === 'not-yet'"
        )
        and "Press Check now above to ask your shop." in shop,
        failures,
    )
    _check("variants are not counted", "Variants" not in shop, failures)
    _check("freshness is said honestly", "nothing syncs by itself yet" in shop, failures)
    _check("the read-only promise is on the screen", "Read only." in shop, failures)
    # Never any part of a chat box key — the tick is its time and its address.
    prefixes = await _key_prefixes(seeded["tenant"])
    _check(
        "no chat box key or prefix reaches the shop screen",
        "fn_pk_" not in shop and not any(prefix in shop for prefix in prefixes),
        failures,
    )

    # Check now, on the seeded connection only: its address is `.invalid` and its
    # token deliberately unreadable, so the failure path runs and the owner's
    # real shop is never asked. Since ADR-0052 it is the full check, run in the
    # background by the worker, so the result takes a few seconds, not one.
    store = seeded["store"]
    await browser.evaluate(
        f"document.querySelector('[data-store=\"{store}\"] [data-check-now]').click() || true"
    )
    step = ""
    for _ in range(25):
        await asyncio.sleep(1)
        step = await browser.evaluate(
            f"(document.querySelector('[data-item=check][data-store=\"{store}\"]') || "
            "{dataset: {}}).dataset.step || ''"
        )
        if step == "failed":
            break
    _check(
        "Check now asks the shop only when pressed, and shows the failure",
        step == "failed",
        failures,
    )

    # Sync now, on the seeded connection: one job, for that store, a full read —
    # and the screen says it asked. The job is removed with the seed.
    await browser.evaluate(
        f"document.querySelector('[data-store=\"{store}\"] [data-sync-now]').click() || true"
    )
    await asyncio.sleep(2)
    line = await browser.evaluate(
        f"(document.querySelector('[data-store=\"{store}\"] [data-sync-line]') || {{}})"
        ".innerText || ''"
    )
    queued = await _sync_jobs(seeded["tenant"], store)
    _check(
        "Sync now queues one full read of our copy and says so",
        "Asked your shop for a fresh copy" in line and queued == [False],
        failures,
    )

    # G75: a clean check's warnings reach the owner in their own words, not
    # only the developer's copy. Stored as the seeded connection's newest check,
    # and removed with the seed by its store's id.
    await _seed_passed_check(seeded)
    await browser.goto(f"{console}/console/{seeded['tenant']}/shops")
    await asyncio.sleep(3)
    row = await browser.evaluate(
        f"(document.querySelector('[data-item=check][data-store=\"{store}\"]') || {{}})"
        ".innerText || ''"
    )
    counted = re.search(r"(\d+) of (\d+) ·", row)
    _check(
        "a clean check shows the owner its warnings, in plain words (G75)",
        "Your shop passes the check" in row
        and "2 things to look at" in row
        and "Some products don't say they are on sale, so NEURA never recommends them." in row
        and "1 technical detail for your developer." in row
        and await browser.evaluate(
            f'!!document.querySelector(\'[data-item=check][data-store="{store}"] '
            "[data-check-warnings]')"
        ),
        failures,
    )
    _check(
        "a warning is not counted as passed",
        counted is not None and int(counted.group(2)) - int(counted.group(1)) == 2,
        failures,
    )
    _check(
        "the owner can copy that check for their developer",
        "Copy the full check for your developer" in row,
        failures,
    )

    # `console.md §3.4`: never a stored credential, not even masked, because a
    # field that can be revealed is a field that gets revealed in a screen-share.
    # This is only a real check because the row above genuinely contains it.
    _check(
        "no stored credential reaches the shop screen",
        SEEDED_SECRET not in shop and "wrapped_dek" not in shop and "fn_sk_" not in shop,
        failures,
    )

    # A cursor is opaque by design (api-design.md §5) and a merchant can do
    # nothing with it but paste it somewhere it will go stale.
    _check(
        "the opaque sync cursor is not rendered",
        Cursor(state={"page": 2}).encode() not in shop,
        failures,
    )

    # The write this screen deliberately does not have: nothing on a connected
    # shop's screen asks for a credential (NEURA makes the token, ADR-0052 §1).
    # Since ADR-0055 it has one form, the shop's own public contact details,
    # which is not a credential; any other field, or any secret-looking one,
    # still fails.
    token_fields = await browser.evaluate(
        "document.querySelectorAll('input[type=password], "
        "form:not([data-contact-form]) input, "
        "input[name*=token i], input[name*=secret i], input[name*=key i]').length"
    )
    _check("no credential form exists on the shop screen", token_fields == 0, failures)

    await browser.goto(f"{console}/console/{seeded['tenant']}/usage?period=all")
    await asyncio.sleep(3)
    usage = await browser.evaluate("document.body.innerText")

    _check("the usage screen renders", "Usage" in usage, failures)

    # Rule 4, the one `console.md §5` says a dashboard usually breaks. Zero is
    # what a free local model records *and* what an unpriced hosted model
    # records, so it must never be printed as an amount of money.
    _check("no unmeasured cost is printed as a figure", "$0" not in usage, failures)

    # And no derived ratio anywhere. "2 of 41" is checkable; "95% deflected" is
    # a claim nobody has measured (CLAUDE.md §4).
    _check(
        "no deflection or resolution rate is claimed",
        "% deflect" not in usage.lower()
        and "deflection rate" not in usage.lower().replace("not a deflection rate", ""),
        failures,
    )

    # A total with no period is not a total. A screen that silently changed
    # window between two visits would look like traffic changing.
    _check(
        "every total names the period it covers",
        "Everything recorded · since" in usage,
        failures,
    )
    # The owner's word since 2026-09-27 (console.md §3.0), on this screen too
    # since the 2026-09-28 redesign.
    _check(
        "it says questions, never turns",
        "shoppers asked" in usage or "a shopper asked" in usage,
        failures,
    )
    _check("the word 'turns' is gone", re.search(r"\bturns?\b", usage.lower()) is None, failures)
    # The split by assistant follows the period chosen — it was today only. The
    # seed bills this check's own agent, so its row must be in "everything".
    _check(
        "the split by assistant covers the period chosen",
        "By assistant · Everything recorded" in usage
        and await browser.evaluate(f"!!document.querySelector('[data-agent=\"{SEEDED_AGENT}\"]')"),
        failures,
    )


async def _check_help(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """Help — *Connecting your shop* (2026-09-28, ADR-0026 §7), rendered.

    Rule 1 reaches the console: no commerce platform is named, and the chat box
    line is the API's own. No time estimates: nothing about setting up a shop
    has been measured.
    """
    await browser.goto(f"{console}/console/{seeded['tenant']}/help")
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")
    lowered = page.lower()

    _check("the help page renders", "Connecting your shop" in page, failures)
    _check(
        # Five: Sold out is a NEURA-SELL feature, not a connection step (owner, 2026-09-30).
        "it lists the five connection steps with how you'll know",
        await browser.evaluate("document.querySelectorAll('[data-help-step]').length") == 5
        and page.count("How you'll know") == 5,
        failures,
    )
    snippet = await browser.evaluate(
        "(document.querySelector('[data-snippet]') || {}).innerText || ''"
    )
    _check(
        "the chat box line is the one the API serves",
        "/v1/widget/widget.js" in snippet and "data-neura-key" in snippet,
        failures,
    )
    await _check_for_your_developer(browser, snippet, failures)
    _check(
        "no commerce platform is named on the help page",
        not any(name in lowered for name in ("bagisto", "shopify", "woocommerce", "magento")),
        failures,
    )
    _check(
        "no time estimate on the help page",
        re.search(r"\b(minutes?|hours?|days?)\b", lowered) is None,
        failures,
    )
    _check("no secret key on the help page", "fn_sk_" not in page, failures)
    # G71 (a): the chat box asks the shop live, so Sync now is not needed after a
    # stock change; only NEURA's copy, used by the dashboard's lists, waits for it.
    _check(
        "Help does not send the owner to Sync now after every stock change (G71)",
        "whenever you add products or change stock" not in page
        and "Your assistant asks your shop live" in page,
        failures,
    )
    # The owner's rule, 2026-10-01: no long dash in anything they read (G71 c).
    _check("no long dash on the help page (G71)", "\u2014" not in page, failures)

    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=390,
        height=844,
        deviceScaleFactor=1,
        mobile=True,
    )
    try:
        for path in ("help", "shops"):
            await browser.goto(f"{console}/console/{seeded['tenant']}/{path}")
            await asyncio.sleep(3)
            _check(
                f"on a phone the {path} page does not scroll sideways",
                await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
                failures,
            )
        await browser.evaluate(
            "document.querySelector('button[aria-controls=shop-menu]').click() || true"
        )
        await asyncio.sleep(0.5)
        _check(
            "Help is in the side menu",
            await browser.evaluate(
                "[...document.querySelectorAll('#shop-menu a')].some(a => a.pathname.endsWith('/help'))"
            ),
            failures,
        )
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")


async def _check_for_your_developer(browser: Chrome, snippet: str, failures: list[str]) -> None:
    """Help's *For your developer* box (ADR-0053 §6, G71; canvas boards 36-37).

    It links the guide for developers, names the address a developer's AI tool
    uses (NEURA's own, from the same public address as the chat box line, and
    one that really answers as an MCP server), and the steps it copies carry
    both. No long dash in the box or in what it copies (the owner's rule).
    """
    box = "document.querySelector('section[aria-labelledby=dev]')"
    _check(
        "For your developer links the guide for developers",
        await browser.evaluate(f"!!{box}?.querySelector('a[href$=\"/docs/developers/\"]')"),
        failures,
    )
    origin = re.search(r'src="([^"]+)/v1/widget/widget\.js"', snippet)
    mcp = await browser.evaluate(
        "(document.querySelector('[data-developer-mcp]') || {}).innerText || ''"
    )
    _check(
        "it shows the AI coding tool address, on the chat box line's address",
        bool(origin) and mcp.strip() == f"{origin.group(1) if origin else ''}/v1/developers/mcp",
        failures,
    )
    answers = False
    if mcp.strip():
        async with httpx.AsyncClient(timeout=10) as http:
            response = await http.post(
                mcp.strip(),
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-06-18",
                },
            )
            answers = response.status_code == 200 and bool(
                response.json().get("result", {}).get("tools")
            )
    _check("that address answers as an MCP server", answers, failures)
    _check(
        "no long dash in For your developer",
        "—" not in (await browser.evaluate(f"{box}?.innerText || ''")),
        failures,
    )
    # What *Copy these steps for your developer* hands over, read by standing
    # in for the clipboard: a headless browser may refuse the real one.
    clipboard = await browser.call(
        "Runtime.evaluate",
        returnByValue=True,
        awaitPromise=True,
        expression="""new Promise((resolve) => {
          Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: { writeText: (text) => { resolve(text); return Promise.resolve(); } },
          });
          document.querySelector('[data-copy-steps]').click();
          setTimeout(() => resolve(''), 3000);
        })""",
    )
    copied = str(clipboard.get("result", {}).get("value") or "")
    _check(
        "the copied steps carry the guide link and the AI coding tool address",
        "/docs/developers/" in copied and bool(mcp.strip()) and mcp.strip() in copied,
        failures,
    )
    _check("no long dash in the copied steps", "—" not in copied, failures)


async def _check_contact(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """*Your shop's contact details* on Shop connection (ADR-0055, G44).

    Typed the way a person types (the input's own setter, then an input event, so
    React sees it), saved with the button, and held to the database. The test
    shop's details are put back afterwards, whatever they were.
    """
    from neura_core.tenancy import TenantRepository

    tenant = seeded["tenant"]

    async def details() -> tuple[str | None, str | None]:
        db = Database.from_settings()
        try:
            async with db.tenant_session(tenant) as session:
                config = (await TenantRepository(session).require(tenant)).config
                return config.contact_email, config.contact_phone
        finally:
            await db.dispose()

    async def put_back(email: str | None, phone: str | None) -> None:
        db = Database.from_settings()
        try:
            async with db.tenant_session(tenant) as session:
                await TenantRepository(session).set_contact(tenant, email=email, phone=phone)
        finally:
            await db.dispose()

    async def type_into(selector: str, value: str) -> None:
        await browser.evaluate(
            f"""(() => {{
              const el = document.querySelector('{selector}');
              const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              set.call(el, {value!r});
              el.dispatchEvent(new Event('input', {{ bubbles: true }}));
              return true;
            }})()"""
        )

    original = await details()
    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=1280,
        height=900,
        deviceScaleFactor=1,
        mobile=False,
    )
    try:
        await browser.goto(f"{console}/console/{tenant}/shops")
        await asyncio.sleep(3)
        page = await browser.evaluate("document.body.innerText")
        _check(
            "Shop connection asks for the shop's contact details",
            "Your shop's contact details" in page
            and await browser.evaluate("!!document.querySelector('[data-contact-form]')"),
            failures,
        )

        await type_into("#contact-email", "not an email")
        await type_into("#contact-phone", "")
        await browser.evaluate("document.querySelector('[data-save-contact]').click() || true")
        await asyncio.sleep(2)
        said = await browser.evaluate(
            "(document.querySelector('[data-contact-error]') || {}).innerText || ''"
        )
        _check(
            "a wrong email is refused in plain words, and nothing is saved",
            said.startswith("Email:") and await details() == original,
            failures,
        )

        await type_into("#contact-email", "hello@yourshop.example")
        await type_into("#contact-phone", "+94 11 234 5678")
        await browser.evaluate("document.querySelector('[data-save-contact]').click() || true")
        await asyncio.sleep(2)
        sentence = await browser.evaluate(
            "(document.querySelector('[data-handover]') || {}).innerText || ''"
        )
        _check(
            "saved details are in the shop's settings",
            await details() == ("hello@yourshop.example", "+94 11 234 5678"),
            failures,
        )
        _check(
            "the screen shows the sentence a handed-over shopper reads, with them",
            sentence == "I can't answer this here. Leave your email so our store can answer you.\n"
            "Or contact our store: hello@yourshop.example, +94 11 234 5678.",
            failures,
        )

        await browser.call(
            "Emulation.setDeviceMetricsOverride",
            width=390,
            height=844,
            deviceScaleFactor=1,
            mobile=True,
        )
        await asyncio.sleep(1)
        _check(
            "on a phone the contact details do not scroll sideways",
            await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            failures,
        )
    finally:
        await put_back(*original)
        await browser.call("Emulation.clearDeviceMetricsOverride")


async def _check_customer_secret(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """*Order questions from signed-in shoppers* on Shop connection (ADR-0057 §3).

    Pressed only on a shop with **no** secret yet, and that secret deleted again
    after: this runs against a developer's own database, and replacing a real
    shop's secret would sign out every one of its shoppers at once.
    """
    from neura_core.tenancy import CustomerSecretRepository
    from neura_core.tenancy.schema import customer_secrets

    tenant = seeded["tenant"]

    async def stored() -> str | None:
        db = Database.from_settings()
        try:
            async with db.tenant_session(tenant) as session:
                return await CustomerSecretRepository(session).secret(tenant)
        finally:
            await db.dispose()

    async def secret_shown() -> str:
        return str(
            await browser.evaluate(
                "(document.querySelector('[data-secret-once] code') || {}).innerText || ''"
            )
        )

    await browser.goto(f"{console}/console/{tenant}/shops")
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")
    _check(
        "Shop connection offers order questions for signed-in shoppers",
        "Order questions from signed-in shoppers" in page
        and await browser.evaluate("!!document.querySelector('[data-customer-secret]')"),
        failures,
    )
    if not await browser.evaluate(
        "!!document.querySelector('[data-make-secret], [data-new-secret]')"
    ):
        return
    if await stored() is not None:
        print(f"  {DIM}this shop already has a secret: the buttons are not pressed{OFF}")
        return

    try:
        _check(
            "with no secret, it says shoppers are asked to sign in",
            "Not set up yet" in page and "asked to sign in" in page,
            failures,
        )
        await browser.evaluate("document.querySelector('[data-make-secret]').click() || true")
        await asyncio.sleep(2)
        first = await secret_shown()
        _check(
            "Make the secret shows it once, with a Copy button, and it is the one stored",
            first.startswith("fn_cs_") and first == await stored(),
            failures,
        )

        await browser.goto(f"{console}/console/{tenant}/shops")
        await asyncio.sleep(3)
        page = await browser.evaluate("document.body.innerText")
        _check(
            "after a reload it says when it was made, and never shows the secret",
            "Made" in page and "fn_cs_" not in page,
            failures,
        )

        await browser.evaluate("document.querySelector('[data-new-secret]').click() || true")
        await asyncio.sleep(1)
        asked = await browser.evaluate(
            "(document.querySelector('[data-new-secret-ask]') || {}).innerText || ''"
        )
        _check(
            "Make a new secret asks first, and says the old one stops at once",
            "stops working at once" in asked,
            failures,
        )
        await browser.evaluate(
            "document.querySelector('[data-new-secret-confirm]').click() || true"
        )
        await asyncio.sleep(2)
        second = await secret_shown()
        _check(
            "a new secret replaces the old one",
            second.startswith("fn_cs_") and second != first and second == await stored(),
            failures,
        )

        await browser.call(
            "Emulation.setDeviceMetricsOverride",
            width=390,
            height=844,
            deviceScaleFactor=1,
            mobile=True,
        )
        await asyncio.sleep(1)
        _check(
            "on a phone the secret does not scroll sideways",
            await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            failures,
        )
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")
        db = Database.from_settings()
        try:
            async with db.tenant_session(tenant) as session:
                await session.execute(delete(customer_secrets))
        finally:
            await db.dispose()


async def _check_mode_switch(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """*Go live* and *Back to practice mode* on Home (ADR-0054), pressed for real.

    Starts the shop in practice mode, whatever it was, and puts it back after.
    The confirm's numbers are held to the database: a sentence that says
    *"you checked 6"* has to be about the same 6 Review would show.
    """
    from neura_core.tenancy import TenantRepository, TurnMode

    tenant = seeded["tenant"]

    async def mode_now() -> str:
        db = Database.from_settings()
        try:
            async with db.tenant_session(tenant) as session:
                row = await TenantRepository(session).require(tenant)
                return row.config.mode.value
        finally:
            await db.dispose()

    async def set_mode(mode: TurnMode) -> None:
        db = Database.from_settings()
        try:
            async with db.tenant_session(tenant) as session:
                await TenantRepository(session).set_mode(tenant, mode)
        finally:
            await db.dispose()

    async def press(selector: str, wait: float = 1.0) -> None:
        await browser.evaluate(f"document.querySelector('{selector}')?.click() || true")
        await asyncio.sleep(wait)

    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant) as session:
            verdicts = (
                await session.execute(
                    select(shadow_turns.c.verdict).where(shadow_turns.c.tenant_id == tenant)
                )
            ).all()
    finally:
        await db.dispose()
    checked = sum(1 for row in verdicts if row.verdict)
    waiting = sum(1 for row in verdicts if not row.verdict)

    original = TurnMode(await mode_now())
    await set_mode(TurnMode.SHADOW)
    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=1280,
        height=900,
        deviceScaleFactor=1,
        mobile=False,
    )
    try:
        await browser.goto(f"{console}/console/{tenant}")
        await asyncio.sleep(3)
        _check(
            "in practice mode, Home offers Go live",
            await browser.evaluate("!!document.querySelector('[data-go-live]')"),
            failures,
        )

        await press("[data-go-live]")
        confirm = await browser.evaluate(
            "(document.querySelector('[data-go-live-confirm]') || {}).innerText || ''"
        )
        said = (
            f"You checked {checked} " if checked else "You haven't checked any replies"
        ) in confirm
        _check(
            "Go live asks first, with what Review holds",
            "Go live?" in confirm and said and (not waiting or f"{waiting} " in confirm),
            failures,
        )
        _check("asking changed nothing yet", await mode_now() == "shadow", failures)

        await browser.call(
            "Emulation.setDeviceMetricsOverride",
            width=390,
            height=844,
            deviceScaleFactor=1,
            mobile=True,
        )
        await asyncio.sleep(1)
        _check(
            "on a phone the Go live question does not scroll sideways",
            await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            failures,
        )
        await browser.call(
            "Emulation.setDeviceMetricsOverride",
            width=1280,
            height=900,
            deviceScaleFactor=1,
            mobile=False,
        )

        await press("[data-stay-practice]")
        _check(
            "Stay in practice mode closes the question and changes nothing",
            not await browser.evaluate("!!document.querySelector('[data-go-live-confirm]')")
            and await mode_now() == "shadow",
            failures,
        )

        await press("[data-go-live]")
        await press("[data-confirm-go-live]", wait=4)
        page = await browser.evaluate("document.body.innerText")
        _check(
            "Go live makes the shop live, and Home says so",
            await mode_now() == "live" and "Your assistant is live" in page,
            failures,
        )

        await press("[data-back-to-practice]", wait=4)
        page = await browser.evaluate("document.body.innerText")
        _check(
            "Back to practice mode is one press, and Home says so",
            await mode_now() == "shadow" and "Practice mode is on" in page,
            failures,
        )
    finally:
        await set_mode(original)
        await browser.call("Emulation.clearDeviceMetricsOverride")


async def _store_count(tenant_id: str) -> int:
    """How many shop connections this tenant holds, the seed's included."""
    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant_id) as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(tenant_stores)
                    .where(tenant_stores.c.tenant_id == tenant_id)
                )
                or 0
            )
    finally:
        await db.dispose()


async def _key_prefixes(tenant_id: str) -> list[str]:
    """Every key prefix this shop holds — none of which may appear on a page."""
    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant_id) as session:
            rows = await session.execute(
                select(api_keys.c.token_prefix).where(api_keys.c.tenant_id == tenant_id)
            )
            return [str(row.token_prefix) for row in rows]
    finally:
        await db.dispose()


async def _sync_jobs(tenant_id: str, store_id: str) -> list[bool]:
    """The sync jobs queued for one store — each one's `incremental` flag."""
    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant_id) as session:
            rows = await session.execute(
                select(job_queue.c.payload)
                .where(job_queue.c.tenant_id == tenant_id)
                .where(job_queue.c.kind == "sync.store")
                .where(job_queue.c.payload["store_id"].astext == store_id)
            )
            return [bool(row.payload.get("incremental", True)) for row in rows]
    finally:
        await db.dispose()


async def _holds_sell(db: Database, tenant_id: str) -> bool:
    """Whether this shop has NEURA-SELL — its entitlement, read as the API reads it."""
    from neura_core.tenancy import TenantRepository

    async with db.tenant_session(tenant_id) as session:
        tenant = await TenantRepository(session).get(tenant_id)
    return tenant is not None and tenant.may_use("sell")


async def _check_without_sell(
    browser: Chrome, console: str, tenant_id: str, failures: list[str]
) -> None:
    """A shop without NEURA-SELL is not shown NEURA-SELL's screens (2026-09-30).

    The owner found *Sold out* in the menu of a shop with NEURA-CARE only — a gym
    app showing the pool to a member without the pool. Checked on a real shop of
    the signed-in person's that lacks SELL, never on one made up for the check.
    """
    base = f"{console}/console/{tenant_id}"
    await browser.goto(base)
    await asyncio.sleep(3)
    menu = await browser.evaluate(
        "[...document.querySelectorAll('nav[aria-label=Screens] a')].map(a => a.innerText).join('|')"
    )
    _check(
        "its menu lists neither Suggestions nor Product views",
        "Home" in menu and "Suggestions" not in menu and "Product views" not in menu,
        failures,
    )
    home = await browser.evaluate("document.body.innerText")
    _check(
        "its Home shows no Suggestions or Sold out card", "Open Product views" not in home, failures
    )

    await browser.goto(f"{base}/sold-out")
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")
    _check(
        "opened by its address, Product views says it is not part of this shop's plan",
        "comes with NEURA-SELL" in page and "Is it working?" not in page,
        failures,
    )

    await browser.goto(f"{base}/shops")
    await asyncio.sleep(3)
    _check(
        "its checklist has no Sold out steps",
        await browser.evaluate(
            "!document.querySelector('[data-item=agreement]') && !document.querySelector('[data-item=views]')"
        ),
        failures,
    )

    await browser.goto(f"{base}/help")
    await asyncio.sleep(3)
    help_page = await browser.evaluate("document.body.innerText")
    _check(
        "its Help does not mention Product views or Sold out",
        "Product views" not in help_page and "Sold out" not in help_page,
        failures,
    )


async def _check_sold_out(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """Screen 6 — ADR-0046 stage 1, redesigned 2026-09-28, against the rendered page.

    The seeded sold-out product must be on it, and three things must not: the
    product that was in stock when viewed (ADR-0049's whole point), either
    session token, and any word that turns a session into a person.

    Since the redesign the screen also asks the shop whether each product can be
    bought **now**. The seeded product is one no real shop has, so whatever the
    shop does — answers, or does not — it must read *Couldn't check*, never
    *Still sold out*: a product nobody vouched for is not reported as sold out.
    """
    await browser.goto(f"{console}/console/{seeded['tenant']}/sold-out")
    await asyncio.sleep(4)
    page = await browser.evaluate("document.body.innerText")
    row = await browser.evaluate(
        f"document.querySelector('[data-product=\"{SEEDED_SOLD_OUT_ID}\"]')?.innerText ?? ''"
    )
    now = await browser.evaluate(
        f"document.querySelector('[data-product=\"{SEEDED_SOLD_OUT_ID}\"] [data-now]')"
        "?.innerText ?? ''"
    )

    _check(
        "the sold-out screen renders, saying what it is for",
        "couldn't buy, or didn't buy" in page,
        failures,
    )
    _check(
        "the page and its menu item are called Product views (G118)",
        await browser.evaluate("document.querySelector('main h1')?.innerText") == "Product views"
        and "Product views"
        in await browser.evaluate(
            "[...document.querySelectorAll('nav[aria-label=Screens] a')].map(a => a.innerText)"
            ".join('|')"
        ),
        failures,
    )
    _check(
        "two tabs, the first one open (ADR-0071)",
        await browser.evaluate(
            "[...document.querySelectorAll('[data-tabs] a')].map(a => "
            "a.innerText + (a.getAttribute('aria-current') ? '*' : '')).join('|')"
        )
        == "Sold out*|Rarely added to cart",
        failures,
    )
    _check(
        "the in-stock teapot is not on the sold-out tab",
        SEEDED_RARELY_TITLE not in page,
        failures,
    )
    _check(
        "each product is a sentence, not VIEWS and SESSIONS columns",
        "Opened 3 times, in 2 visits" in row,
        failures,
    )
    _check(
        "a product the shop did not vouch for is never called sold out",
        now == "Couldn't check",
        failures,
    )
    _check(
        "it says the shop was asked, or that it could not be",
        await browser.evaluate("!!document.querySelector('[data-stock-line]')"),
        failures,
    )
    _check(
        "'Is it working?' says views are arriving",
        "Is it working?" in page and "Some arrived in the last" in page,
        failures,
    )
    _check("'How this works' is on the screen", "How this works" in page, failures)
    _check(
        "a product viewed while sold out is listed by its name",
        SEEDED_SOLD_OUT_TITLE in page,
        failures,
    )
    _check(
        "a product that was in stock when viewed is not",
        SEEDED_IN_STOCK_TITLE not in page,
        failures,
    )
    _check(
        "no session token reaches the page",
        not any(token in page for token in SEEDED_SESSIONS),
        failures,
    )
    _check(
        "it says a visit is not a person",
        "not one person" in page and "customers" not in page.lower(),
        failures,
    )

    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=390,
        height=844,
        deviceScaleFactor=1,
        mobile=True,
    )
    try:
        await browser.goto(f"{console}/console/{seeded['tenant']}/sold-out")
        await asyncio.sleep(4)
        _check(
            "on a phone the sold-out screen does not scroll sideways",
            await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            failures,
        )
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")


async def _check_rarely_added(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """ADR-0071, console.md §3.13: the second tab, Home's line, and a phone.

    The teapot is listed (12 visitors, 1 added); the jumper viewed once in
    stock is not (fewer than 10 visitors), nor the sold-out one (Sold out's).
    No session token, and the shop is never asked from this tab.
    """
    base = f"{console}/console/{seeded['tenant']}"
    await browser.goto(f"{base}/sold-out?tab=rarely")
    await asyncio.sleep(4)
    page = await browser.evaluate("document.body.innerText")
    row = await browser.evaluate(
        f"document.querySelector('[data-product=\"{SEEDED_RARELY_ID}\"]')?.innerText ?? ''"
    )
    _check(
        "the second tab is open, its line and its hint above the list",
        "Rarely added to cart*"
        in await browser.evaluate(
            "[...document.querySelectorAll('[data-tabs] a')].map(a => "
            "a.innerText + (a.getAttribute('aria-current') ? '*' : '')).join('|')"
        )
        and "few added to the cart" in page
        and "Check the price, photos and description." in page,
        failures,
    )
    _check(
        "the teapot: 12 visitors, 1 added it to the cart, its price",
        SEEDED_RARELY_TITLE in row
        and "12 visitors, 1 added it to the cart" in row
        and "LKR" in row,
        failures,
    )
    _check(
        "Open the page opens the shop's page in a new tab",
        await browser.evaluate(
            f'(() => {{ const a = document.querySelector(\'[data-product="{SEEDED_RARELY_ID}"] '
            f"[data-open-page]'); return !!a && a.href === '{SEEDED_RARELY_URL}' "
            "&& a.target === '_blank'; })()"
        ),
        failures,
    )
    _check(
        "a product with too few visitors and a sold-out one are not listed",
        SEEDED_IN_STOCK_TITLE not in page and SEEDED_SOLD_OUT_TITLE not in page,
        failures,
    )
    _check(
        "'How this works' states the rule, and the cart-adds caveat is shown",
        "10 or more visitors" in page
        and "fewer than 1 in 10" in page
        and "We see cart adds, not orders" in page,
        failures,
    )
    _check(
        "no session token reaches the tab",
        not any(token in page for token in (*SEEDED_SESSIONS, *SEEDED_RARELY_SESSIONS)),
        failures,
    )

    await browser.goto(base)
    await asyncio.sleep(3)
    line = await browser.evaluate(
        "(() => { const li = [...document.querySelectorAll('li')].find(l => "
        "l.innerText.includes('rarely added to cart')); if (!li) return ''; "
        "const a = li.querySelector('a'); return li.innerText + '|' + (a ? a.href : ''); })()"
    )
    _check(
        "Home says how many products are rarely added, opening the tab",
        "viewed a lot but rarely added to cart" in line and line.endswith("sold-out?tab=rarely"),
        failures,
    )

    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=390,
        height=844,
        deviceScaleFactor=1,
        mobile=True,
    )
    try:
        await browser.goto(f"{base}/sold-out?tab=rarely")
        await asyncio.sleep(4)
        _check(
            "on a phone the second tab does not scroll sideways, Open the page shown",
            await browser.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
                f' && !!document.querySelector(\'[data-product="{SEEDED_RARELY_ID}"] '
                "[data-open-page]')?.offsetWidth"
            ),
            failures,
        )
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")


async def _check_suggestions(
    browser: Chrome, console: str, db: Database, made: dict[str, str], failures: list[str]
) -> None:
    """Screen 7 — ADR-0050, redesigned 2026-09-28, against the rendered page.

    The redesign's promise is a preview of what a basket shows, asked of the
    shop when the owner opens a product — and **never a model run**. That last
    part is a claim about the job queue, so it is checked there.
    """
    base = f"{console}/console/{made['tenant']}/suggestions"
    anchor = SEEDED_CHOICE_ANCHOR
    # Wide: on a phone the list and the open product are one at a time.
    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=1280,
        height=900,
        deviceScaleFactor=1,
        mobile=False,
    )
    try:
        # Home's Suggestions card, for this shop — which has SELL, so the card
        # must count rather than say "not in this shop's plan". Counted by the
        # server across the whole catalogue, never from the list's first page:
        # that is how a 38-product shop lost its number when pages went from 50
        # to 25 (2026-09-28).
        await browser.goto(f"{console}/console/{made['tenant']}")
        await asyncio.sleep(3)
        home = await browser.evaluate("document.body.innerText")
        _check(
            "home's Suggestions card counts the whole catalogue",
            re.search(r"Automatic for all \d+|Your choice for \d+ of \d+", home) is not None,
            failures,
        )

        await browser.goto(f"{base}?q=Console-check")
        await asyncio.sleep(3)
        page = await browser.evaluate("document.body.innerText")
        _check("the suggestions screen renders", "Suggestions" in page, failures)
        _check(
            "the owner's choice is shown as theirs",
            "Your choice" in page and anchor[1] in page,
            failures,
        )
        _check(
            "it says the choice is the same for every shopper",
            "Same for every shopper" in page,
            failures,
        )
        _check(
            "each filter says how many it holds",
            await browser.evaluate(
                "[...document.querySelectorAll('nav[aria-label=\\'Show products that are\\'] a')]"
                ".every((a) => /\\d/.test(a.textContent || ''))"
            ),
            failures,
        )
        _check("no API key reached the suggestions screen", "fn_sk_" not in page, failures)

        await browser.goto(f"{base}?q=Console-check&mode=owner")
        await asyncio.sleep(3)
        rows = await browser.evaluate(
            "[...document.querySelectorAll('[data-product-list] [data-product]')]"
            ".map((a) => a.getAttribute('data-product'))"
        )
        _check(
            "the 'Your choice' filter shows only products the owner chose",
            rows == [anchor[0]],
            failures,
        )

        # The seeded products carry no category: exactly what "No category"
        # is for — the products that can never get an automatic suggestion.
        await browser.goto(f"{base}?q=Console-check&category=none")
        await asyncio.sleep(3)
        uncategorised = await browser.evaluate(
            "[...document.querySelectorAll('[data-product-list] [data-product]')]"
            ".map((a) => a.getAttribute('data-product'))"
        )
        listed = await browser.evaluate("document.body.innerText")
        _check(
            "the 'No category' filter lists products with no category",
            anchor[0] in (uncategorised or []),
            failures,
        )
        _check("the list says where its page sits", "Showing 1\u2013" in listed, failures)

        await browser.goto(f"{base}?q=Console-check&product={anchor[0]}")
        await asyncio.sleep(5)
        opened = await browser.evaluate(
            "document.querySelector('[data-open-product]')?.innerText || ''"
        )
        _check(
            "opening a product says what a basket shows with it, or why it cannot",
            anchor[1] in opened
            and any(
                words in opened
                for words in (
                    "Recommended with your",
                    "Nothing is shown with this product",
                    "did not answer just now",
                )
            ),
            failures,
        )
        _check(
            "and offers the owner's way to change it",
            "Change these" in opened or "Choose suggestions" in opened,
            failures,
        )

        # A real product of the shop that the AI has never run for — the case
        # where a shopper's basket WOULD queue it — opened the way an owner opens
        # one. The basket's own code runs against the live shop, and the job
        # queue must not grow. Chosen from the database so the check cannot pass
        # on a product that would not have queued anyway (E6).
        never = await _never_paired(db, made["tenant"])
        if never is None:
            print(f"  {DIM}every product has an AI result — the no-queue check is skipped{OFF}")
        else:
            before = await _pairing_jobs(db, made["tenant"])
            await browser.goto(f"{base}?product={never}")
            await asyncio.sleep(6)
            _check(
                "opening a product never queues the AI",
                await _pairing_jobs(db, made["tenant"]) == before,
                failures,
            )
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")

    await browser.call(
        "Emulation.setDeviceMetricsOverride",
        width=390,
        height=844,
        deviceScaleFactor=1,
        mobile=True,
    )
    try:
        await browser.goto(f"{base}?q=Console-check&product={anchor[0]}")
        await asyncio.sleep(4)
        _check(
            "on a phone one product is open at a time, and nothing scrolls sideways",
            "All products" in await browser.evaluate("document.body.innerText")
            and await browser.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
            failures,
        )
    finally:
        await browser.call("Emulation.clearDeviceMetricsOverride")


async def _never_paired(db: Database, tenant_id: str) -> str | None:
    """A synced product of this shop with no stored AI pairing at all, or None."""
    from neura_agent_sell.pairing.schema import sell_pairings

    async with db.tenant_session(tenant_id) as session:
        found = await session.scalar(
            select(synced_entities.c.external_id)
            .where(synced_entities.c.tenant_id == tenant_id)
            .where(synced_entities.c.entity_type == "product")
            .where(synced_entities.c.platform != SEEDED_PLATFORM)
            .where(
                ~select(sell_pairings.c.id)
                .where(sell_pairings.c.tenant_id == tenant_id)
                .where(sell_pairings.c.product_id == synced_entities.c.external_id)
                .exists()
            )
            .order_by(synced_entities.c.external_id)
            .limit(1)
        )
    return str(found) if found is not None else None


async def _pairing_jobs(db: Database, tenant_id: str) -> int:
    """How many pairing computations this shop has ever queued."""
    from neura_core.jobs.schema import job_queue

    async with db.tenant_session(tenant_id) as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(job_queue)
                .where(job_queue.c.tenant_id == tenant_id)
                .where(job_queue.c.kind == "sell.pairing.compute")
            )
            or 0
        )


async def _seed_choice(db: Database, held: list[Any]) -> dict[str, str] | None:
    """Two synced products and one owner choice, in the first held shop with SELL."""
    from neura_agent_sell.pairing.choices import DatabaseOwnerChoices
    from neura_core.tenancy import TenantRepository

    for membership in held:
        tenant_id = membership.tenant_id
        async with db.tenant_session(tenant_id) as session:
            tenant = await TenantRepository(session).get(tenant_id)
            store_id = await session.scalar(
                select(tenant_stores.c.id)
                .where(tenant_stores.c.tenant_id == tenant_id)
                .order_by(tenant_stores.c.created_at)
                .limit(1)
            )
        if tenant is None or not tenant.may_use("sell") or store_id is None:
            continue

        async with db.tenant_session(tenant_id) as session:
            for product_id, title in (SEEDED_CHOICE_ANCHOR, SEEDED_CHOICE_PICK):
                await session.execute(
                    synced_entities.insert().values(
                        tenant_id=tenant_id,
                        platform=SEEDED_PLATFORM,
                        entity_type="product",
                        external_id=product_id,
                        neura_id=ids.new_id(ids.NEURA_ENTITY),
                        fingerprint="console-check",
                        document={"title": title},
                    )
                )
        await DatabaseOwnerChoices(db, tenant_id=tenant_id, store_id=str(store_id)).choose(
            SEEDED_CHOICE_ANCHOR[0], [SEEDED_CHOICE_PICK[0]], chosen_by="console-check"
        )
        return {"tenant": tenant_id, "store": str(store_id)}
    return None


async def _unseed_choice(db: Database, made: dict[str, str]) -> None:
    """Exactly the rows above: one choice by its product id, two products by platform."""
    from neura_agent_sell.pairing.choices import DatabaseOwnerChoices

    await DatabaseOwnerChoices(db, tenant_id=made["tenant"], store_id=made["store"]).reset(
        SEEDED_CHOICE_ANCHOR[0]
    )
    async with db.tenant_session(made["tenant"]) as session:
        await session.execute(
            delete(synced_entities)
            .where(synced_entities.c.tenant_id == made["tenant"])
            .where(synced_entities.c.platform == SEEDED_PLATFORM)
        )


async def _seed_passed_check(seeded: dict[str, str]) -> None:
    """The seeded connection's newest check: clean, with two warnings (G75)."""
    from neura_adapters.generic.reference import Defect, ReferenceStore

    await _seed_check(
        seeded["tenant"],
        store_id=seeded["store"],
        shop=ReferenceStore(defects=frozenset({Defect.NO_PRODUCT_STATUS, Defect.IGNORES_LIMIT})),
        warnings=2,
    )


async def _seed_check(tenant: str, *, store_id: str | None, shop: Any, warnings: int) -> str:
    """A clean check stored as the shop's newest, with ``warnings`` warnings.

    Made by the real check against the built-in test shop, so the screen is
    tested on what the worker stores rather than on a result written by hand.
    Removed by the caller, by the id returned.
    """
    from neura_adapters.generic.adapter import GenericAdapter
    from neura_adapters.generic.reference import DEFAULT_TOKEN
    from neura_api.jobs.shop_check import outcome
    from neura_commerce import check_adapter
    from neura_core.tenancy import ShopCheckRepository

    adapter = GenericAdapter(
        base_url=shop.base_url(), tenant_id=tenant, token=DEFAULT_TOKEN, transport=shop.transport()
    )
    try:
        report = await check_adapter(adapter)
    finally:
        await adapter.aclose()
    address = "https://console-check.invalid/neura/v1"
    result = outcome(address, cause=None, report=report)
    if not result["conformant"] or result["warnings"] != warnings:
        raise RuntimeError(
            f"the seeded check is not clean with {warnings} warning(s):\n{result['text']}"
        )

    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant) as session:
            checks = ShopCheckRepository(session)
            made = await checks.create(
                tenant, address=address, store_id=store_id, requested_by="console-check"
            )
            await checks.finish(made, result=result)
        return made
    finally:
        await db.dispose()


async def _check_before_connecting(
    browser: Chrome, console: str, user_id: str, failures: list[str]
) -> None:
    """A shop not connected yet: Home's first item (G54) and a passed check (G51, G75).

    Every shop this account holds may already be connected, so a throwaway one
    is made, with a membership for this person, and removed afterwards **by id**:
    never `make tenant-drop`, which misses tables (G76), and never by tenant.
    """
    from neura_adapters.generic.reference import Defect, ReferenceStore
    from neura_core.identity.schema import memberships
    from neura_core.tenancy.schema import tenants
    from neura_domain import Capability

    tenant = ids.new_id(ids.TENANT)
    membership = ids.new_id(ids.MEMBERSHIP)
    check_id: str | None = None
    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant) as session:
            await session.execute(
                tenants.insert().values(
                    tenant_id=tenant, name="Console check, not connected", enabled_agents=["care"]
                )
            )
            await session.execute(
                memberships.insert().values(
                    id=membership, tenant_id=tenant, user_id=user_id, role="owner"
                )
            )
        # The guide's first three addresses only, and products with no status.
        check_id = await _seed_check(
            tenant,
            store_id=None,
            shop=ReferenceStore(
                capabilities=frozenset({Capability.PRODUCT_READ, Capability.PRODUCT_SEARCH}),
                defects=frozenset({Defect.NO_PRODUCT_STATUS}),
            ),
            warnings=1,
        )

        await browser.goto(f"{console}/console/{tenant}")
        await asyncio.sleep(3)
        home = await browser.evaluate("document.body.innerText")
        _check(
            "Home says the owner connects the shop on Shop connection (G54)",
            "Your online shop isn't connected yet" in home
            and "outside the console" not in home
            and "Connect it on Shop connection" in home,
            failures,
        )

        await browser.goto(f"{console}/console/{tenant}/shops")
        await asyncio.sleep(4)
        lines = await browser.evaluate(
            "[...document.querySelectorAll('[data-check-result=passed] li')].map(li => li.innerText)"
        )
        box = await browser.evaluate(
            "(document.querySelector('[data-check-result=passed]') || {}).innerText || ''"
        )
        _check(
            "a passed check lists only what the check tested (G51)",
            lines
            == [
                "Your shop answers, and says what it can do",
                "Only your token gets in",
                "Products can be read",
                "Products can be searched",
                "Long lists come page by page",
                "Something missing answers \u201cnot found\u201d",
            ],
            failures,
        )
        _check(
            "before connecting, the owner sees the check's warning (G75)",
            "1 thing to look at" in box
            and "Some products don't say they are on sale, so NEURA never recommends them." in box,
            failures,
        )
    finally:
        async with db.tenant_session(tenant) as session:
            if check_id:
                await session.execute(delete(shop_checks).where(shop_checks.c.id == check_id))
            await session.execute(delete(memberships).where(memberships.c.id == membership))
            await session.execute(delete(tenants).where(tenants.c.tenant_id == tenant))
        await db.dispose()


async def _shop_checks_of(tenant_id: str) -> int:
    """How many full checks this shop has: a page load must not add one."""
    db = Database.from_settings()
    try:
        async with db.tenant_session(tenant_id) as session:
            return int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(shop_checks)
                        .where(shop_checks.c.tenant_id == tenant_id)
                    )
                ).scalar_one()
            )
    finally:
        await db.dispose()


async def _seed_shop(db: Database, tenant_id: str) -> dict[str, str]:
    """Two shadowed turns, one real conversation, and one policy to cite.

    Two, because one would not exercise the rule that matters: an **answered**
    turn proves the evidence is rendered, and a **declined** one proves the queue
    does not quietly omit the turns the agent refused. Written through the same
    repositories the turn service uses, so this is the shape a real turn records
    and not an approximation of it.
    """
    made = {
        "tenant": tenant_id,
        "conversation": ids.new_id(ids.CONVERSATION),
        "answered_conversation": ids.new_id(ids.CONVERSATION),
        "chunk": ids.new_id(ids.CHUNK),
        "store": ids.new_id(ids.STORE),
    }

    async with db.tenant_session(tenant_id) as session:
        conversations = ConversationRepository(session)
        await conversations.start(tenant_id, conversation_id=made["conversation"], agent_key="care")
        message_id = await conversations.append_shopper_message(
            tenant_id, made["conversation"], shopper=SEEDED_QUESTION
        )

        # A second thread, this one the shopper actually read — and it ends
        # **escalated**, because a Conversations screen that only ever showed
        # answered threads would let a build collapsing five states into "done"
        # pass every check here.
        await conversations.start(
            tenant_id, conversation_id=made["answered_conversation"], agent_key="care"
        )
        await conversations.append_turn(
            tenant_id,
            made["answered_conversation"],
            shopper=SEEDED_TOKENISED,
            reply=SEEDED_REPLY,
            state=ConversationState.ESCALATED,
            intent="order_status",
            citations=[{"type": "policy", "id": "console-check-returns"}],
        )

        await session.execute(
            document_chunks.insert().values(
                id=made["chunk"],
                tenant_id=tenant_id,
                embedding_model="console-check",
                dimensions=3,
                # pgvector's text form, exactly as `rag/postgres` writes it. The
                # value is irrelevant: nothing here searches.
                embedding="[0,0,0]",
                content=SEEDED_POLICY,
                content_hash="console-check",
                source_type="policy",
                source_id="console-check-returns",
                chunk_index=0,
            )
        )

        # Screen 4 needs a connection to *fail* to leak. Placeholders rather
        # than a real envelope: nothing here decrypts, and the assertion is that
        # these strings never reach the page.
        await session.execute(
            tenant_stores.insert().values(
                id=made["store"],
                tenant_id=tenant_id,
                platform=SEEDED_PLATFORM,
                base_url="https://console-check.invalid/neura/v1",
                credentials=SEEDED_SECRET,
                wrapped_dek=SEEDED_SECRET,
                status="active",
            )
        )
        await session.execute(
            sync_checkpoints.insert().values(
                tenant_id=tenant_id,
                platform=SEEDED_PLATFORM,
                entity_type="product",
                cursor=Cursor(state={"page": 2}).encode(),
                updated_through=datetime.now(UTC),
                completed_at=datetime.now(UTC),
                last_run_count=118,
            )
        )

        # Screen 5 needs something to count. A usage screen with nothing in it
        # renders its empty state, and a check that only ever sees the empty
        # state has told us nothing about the figures.
        await UsageMeter(session).record(
            tenant_id,
            SEEDED_AGENT,
            UsageDelta(
                conversations=2,
                turns=3,
                llm_calls=6,
                tool_calls=1,
                escalations=1,
                prompt_tokens=3100,
                completion_tokens=640,
                # Zero, deliberately: this is the ambiguous value the screen has
                # to refuse to print as money.
                cost_usd=Decimal("0"),
            ),
        )

        # Screen 6 needs demand to count: three views of a product while it was
        # sold out, from two sessions, and one view of a product in stock that
        # must NOT be listed. Titles come from the synced catalogue, as they do
        # for a real shop — under this check's own platform string, so cleanup
        # can find exactly these rows.
        events = ObservedEventRepository(session)
        made["observed"] = ",".join(
            await _seed_views(events, tenant_id, SEEDED_SOLD_OUT_ID, in_stock=False, count=3)
            + await _seed_views(events, tenant_id, SEEDED_IN_STOCK_ID, in_stock=True, count=1)
            + await _seed_rarely(events, tenant_id)
        )
        for product, document in (
            (SEEDED_SOLD_OUT_ID, {"title": SEEDED_SOLD_OUT_TITLE}),
            (SEEDED_IN_STOCK_ID, {"title": SEEDED_IN_STOCK_TITLE}),
            (
                SEEDED_RARELY_ID,
                {
                    "title": SEEDED_RARELY_TITLE,
                    "url": SEEDED_RARELY_URL,
                    "price_range_min": {"amount": "2450.00", "currency": "LKR"},
                },
            ),
        ):
            await session.execute(
                synced_entities.insert().values(
                    tenant_id=tenant_id,
                    platform=SEEDED_PLATFORM,
                    entity_type="product",
                    external_id=product,
                    neura_id=ids.new_id(ids.NEURA_ENTITY),
                    fingerprint="console-check",
                    document=document,
                )
            )
        # The policy the escalated reply cited, by its title, as a real shop's
        # sync would record it — so the chat page can name it.
        await session.execute(
            synced_entities.insert().values(
                tenant_id=tenant_id,
                platform=SEEDED_PLATFORM,
                entity_type="policy",
                external_id="console-check-returns",
                neura_id=ids.new_id(ids.NEURA_ENTITY),
                fingerprint="console-check",
                document={"title": SEEDED_POLICY_TITLE},
            )
        )

        shadow = ShadowRepository(session)
        made["answered"] = await shadow.record(
            ShadowTurn(
                tenant_id=tenant_id,
                conversation_id=made["conversation"],
                message_id=message_id,
                agent_key="care",
                mode="shadow",
                state="resolved",
                intent="policy_question",
                draft=SEEDED_DRAFT,
                grounded=True,
                citations=[{"type": "policy", "id": "console-check-returns"}],
                cost_usd=Decimal("0"),
                latency_ms=1180,
            )
        )
        # ADR-0062: two handed-over shoppers waiting for an answer, one who left
        # an email in the chat box and one who was signed in. The shop's store
        # is a placeholder, so the signed-in one shows the customer's id.
        made["waiting_conversation"] = ids.new_id(ids.CONVERSATION)
        made["signed_in_conversation"] = ids.new_id(ids.CONVERSATION)
        await conversations.start(
            tenant_id, conversation_id=made["waiting_conversation"], agent_key="care"
        )
        await conversations.append_turn(
            tenant_id,
            made["waiting_conversation"],
            shopper=SEEDED_WAITING_QUESTION,
            reply=SEEDED_ASK,
            state=ConversationState.ESCALATED,
        )
        await conversations.start(
            tenant_id,
            conversation_id=made["signed_in_conversation"],
            agent_key="care",
            customer_external_id=SEEDED_CUSTOMER,
        )
        await conversations.append_turn(
            tenant_id,
            made["signed_in_conversation"],
            shopper=SEEDED_SIGNED_IN_QUESTION,
            reply=SEEDED_WITH_STORE,
            state=ConversationState.ESCALATED,
        )
        waiting = WaitingAnswerRepository(session)
        await waiting.leave_email(tenant_id, made["waiting_conversation"], SEEDED_SHOPPER_EMAIL)
        await waiting.wait_for_customer(tenant_id, made["signed_in_conversation"])

        made["declined"] = await shadow.record(
            ShadowTurn(
                tenant_id=tenant_id,
                conversation_id=made["conversation"],
                message_id=message_id,
                agent_key="care",
                mode="shadow",
                state="escalated",
                draft="",
                escalated=True,
            )
        )

    return made


async def _seed_views(
    events: ObservedEventRepository, tenant_id: str, product: str, *, in_stock: bool, count: int
) -> list[str]:
    """``count`` views of one product, alternating between the two seeded sessions."""
    made: list[str] = []
    for n in range(count):
        event_id = ids.new_id("obs")
        await events.record(
            tenant_id,
            ObservedEvent(
                event_id=event_id,
                session_id=SEEDED_SESSIONS[n % 2],
                type=ObservedEventType.PRODUCT_VIEWED,
                product_id=product,
                occurred_at=datetime.now(UTC),
                in_stock=in_stock,
            ),
        )
        made.append(event_id)
    return made


async def _seed_rarely(events: ObservedEventRepository, tenant_id: str) -> list[str]:
    """12 visitors opened the teapot in stock; the first added it to the cart."""
    made: list[str] = []
    kinds = [(ObservedEventType.PRODUCT_VIEWED, s) for s in SEEDED_RARELY_SESSIONS]
    for kind, session_id in [*kinds, (ObservedEventType.CART_ADDED, SEEDED_RARELY_SESSIONS[0])]:
        event_id = ids.new_id("obs")
        await events.record(
            tenant_id,
            ObservedEvent(
                event_id=event_id,
                session_id=session_id,
                type=kind,
                product_id=SEEDED_RARELY_ID,
                occurred_at=datetime.now(UTC),
                in_stock=True if kind is ObservedEventType.PRODUCT_VIEWED else None,
            ),
        )
        made.append(event_id)
    return made


async def _unseed_shop(db: Database, seeded: dict[str, str]) -> None:
    """Remove exactly the rows above, by id.

    By id and never by tenant: this runs against a developer's own database,
    where the tenant it just wrote to may be a real shop with real traffic in it.
    A cleanup that deleted "this tenant's shadow turns" would be a data-loss bug
    living inside a test.
    """
    async with db.tenant_session(seeded["tenant"]) as session:
        # Exactly this run's events, by id — never "this tenant's events", which
        # on a real shop would delete real shoppers' views.
        await session.execute(
            delete(observed_events)
            .where(observed_events.c.tenant_id == seeded["tenant"])
            .where(observed_events.c.event_id.in_(seeded["observed"].split(",")))
        )
        await session.execute(
            delete(synced_entities)
            .where(synced_entities.c.tenant_id == seeded["tenant"])
            .where(synced_entities.c.platform == SEEDED_PLATFORM)
        )
        await session.execute(
            delete(shadow_turns).where(
                shadow_turns.c.id.in_([seeded["answered"], seeded["declined"]])
            )
        )
        await session.execute(
            delete(document_chunks).where(document_chunks.c.id == seeded["chunk"])
        )
        threads = [
            seeded["conversation"],
            seeded["answered_conversation"],
            seeded["waiting_conversation"],
            seeded["signed_in_conversation"],
        ]
        await session.execute(
            delete(waiting_answers).where(waiting_answers.c.conversation_id.in_(threads))
        )
        await session.execute(
            delete(conversation_messages).where(
                conversation_messages.c.conversation_id.in_(threads)
            )
        )
        await session.execute(delete(conversations).where(conversations.c.id.in_(threads)))
        await session.execute(delete(tenant_stores).where(tenant_stores.c.id == seeded["store"]))
        # The full check Check now asked for, for the seeded store only (ADR-0052):
        # its row by the store's id, and its job by that row's id, never "this
        # tenant's checks", which would take the owner's own with them.
        seeded_checks = [
            row.id
            for row in (
                await session.execute(
                    select(shop_checks.c.id).where(shop_checks.c.store_id == seeded["store"])
                )
            ).all()
        ]
        await session.execute(delete(shop_checks).where(shop_checks.c.id.in_(seeded_checks)))
        await session.execute(
            delete(job_queue)
            .where(job_queue.c.tenant_id == seeded["tenant"])
            .where(job_queue.c.kind == "shop.check")
            .where(job_queue.c.payload["check_id"].astext.in_(seeded_checks))
        )
        # The sync Sync now queued for the seeded store — by that store's id,
        # never "this tenant's jobs", which would take a real sync with it.
        await session.execute(
            delete(job_queue)
            .where(job_queue.c.tenant_id == seeded["tenant"])
            .where(job_queue.c.kind == "sync.store")
            .where(job_queue.c.payload["store_id"].astext == seeded["store"])
        )
        # By platform, which is this check's own string and nothing else's — not
        # "this tenant's checkpoints", which would take a real sync's position
        # with it and silently restart a merchant's next crawl from the top.
        await session.execute(
            delete(sync_checkpoints)
            .where(sync_checkpoints.c.tenant_id == seeded["tenant"])
            .where(sync_checkpoints.c.platform == SEEDED_PLATFORM)
        )
        # Exactly this run's usage row, by its three-part key. Never "today's
        # usage for this tenant" — that would take a real agent's row with it.
        await session.execute(
            delete(tenant_usage)
            .where(tenant_usage.c.tenant_id == seeded["tenant"])
            .where(tenant_usage.c.usage_date == today())
            .where(tenant_usage.c.agent_key == SEEDED_AGENT)
        )


async def _check_people_and_roles(
    browser: Chrome, console: str, seeded: dict[str, str], owner: str, failures: list[str]
) -> None:
    """People, and what Support and the Developer see (ADR-0058, console.md §3.8).

    Two made-up people are invited **in the database** (`PeopleRepository`), so
    this check never sends an email, whatever mail server the API has. Their
    links are opened in two more browsers, each its own person, on desktop and
    phone. The Owner then changes a role and removes both on the People screen,
    and every row this made is removed by its email afterwards. The invite
    *form* is held by `tests/integration/test_console_people.py`, through the API.
    """
    from neura_core.identity.people import PeopleRepository
    from neura_core.identity.schema import login_tokens, membership_invites, memberships, users

    tenant = seeded["tenant"]
    base = f"{console}/console/{tenant}"
    suffix = ids.new_id(ids.USER).lower()
    support_email = f"people-check-support-{suffix}@example.com"
    developer_email = f"people-check-developer-{suffix}@example.com"
    db = Database.from_settings()

    async def menu(page: Chrome) -> list[str]:
        return list(
            await page.evaluate(
                "[...document.querySelectorAll('nav[aria-label=Screens] a')]"
                ".map(a => a.innerText.trim().split('\\n')[0])"
            )
        )

    async def phone(page: Chrome, on: bool) -> None:
        await page.call(
            "Emulation.setDeviceMetricsOverride",
            width=390 if on else 1280,
            height=844 if on else 900,
            deviceScaleFactor=1,
            mobile=on,
        )

    async def fits(page: Chrome) -> bool:
        return bool(
            await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        )

    async def opened(page: Chrome, url: str, wait: float = 3) -> str:
        await page.goto(url)
        await asyncio.sleep(wait)
        return str(await page.evaluate("document.body.innerText"))

    try:
        # Desktop first: an earlier section may have left the window at phone
        # size, where the menu is folded away and the switcher is not read.
        await phone(browser, False)
        page = await opened(browser, f"{base}/people")
        _check("Owner: People is in the menu", "People" in await menu(browser), failures)
        _check("Owner: the switcher says You're the Owner", "You're the Owner" in page, failures)
        _check(
            "Owner: People says who can open the dashboard",
            "Who can open" in page and "What each role can do" in page,
            failures,
        )

        links: dict[str, str] = {}
        async with db.tenant_session(tenant) as session:
            people = PeopleRepository(session)
            for role, email in (("support", support_email), ("developer", developer_email)):
                sent = await people.invite(
                    tenant, email=email, role=role, by=owner, console_base_url=console
                )
                links[role] = sent.url
        page = await opened(browser, f"{base}/people")
        _check(
            "Owner: two invites wait, each with Send again and Cancel",
            page.count("Waiting · the link works until") == 2 and page.count("Send again") == 2,
            failures,
        )

        async with Chrome(find_chrome()) as support:
            await phone(support, False)
            page = await opened(support, links["support"], wait=4)
            _check(
                "Support: the link lands in the shop",
                await support.evaluate("location.pathname") == f"/console/{tenant}",
                failures,
            )
            _check(
                "Support: the menu is Home, Review, Conversations, Help",
                await menu(support) == ["Home", "Review", "Conversations", "Help"],
                failures,
            )
            _check(
                "Support: Home says the mode, with no Go live and no 7 days",
                ("Practice mode is on" in page or "Your assistant is live" in page)
                and "Go live" not in page
                and "Last 7 days" not in page,
                failures,
            )
            page = await opened(support, f"{base}/usage")
            _check(
                "Support: Usage says You can't open this page, the role and what it lacks",
                "You can't open this page" in page
                and "is Support, which doesn't include Usage and cost" in page,
                failures,
            )
            page = await opened(support, f"{base}/people")
            _check("Support: People is refused too", "You can't open this page" in page, failures)
            # The link works once. Opened again by someone who joined, it sends
            # them to sign in, not back to the owner (G96).
            page = await opened(support, links["support"], wait=4)
            _check(
                "Support: the used link says to sign in, with a Sign in button",
                "If you already joined, sign in" in page
                and bool(
                    await support.evaluate("!!document.querySelector('[data-invite-sign-in]')")
                ),
                failures,
            )
            await phone(support, True)
            await opened(support, base)
            _check(
                "Support: Home on a phone does not scroll sideways", await fits(support), failures
            )

        async with Chrome(find_chrome()) as developer:
            await phone(developer, False)
            page = await opened(developer, links["developer"], wait=4)
            _check(
                "Developer: the menu is Home, Shop connection, Help",
                await menu(developer) == ["Home", "Shop connection", "Help"],
                failures,
            )
            _check(
                "Developer: Home has no Go live and no Review count",
                "Go live" not in page and "waiting for your review" not in page,
                failures,
            )
            page = await opened(developer, f"{base}/conversations")
            _check(
                "Developer: shoppers' chats are refused, with a way to Shop connection",
                "is Developer, which doesn't include shoppers' chats" in page
                and "Go to Shop connection" in page,
                failures,
            )
            page = await opened(developer, f"{base}/shops", wait=4)
            _check(
                "Developer: Shop connection opens, the same page as the Owner's",
                "You can't open this page" not in page and "Your shop's contact details" in page,
                failures,
            )
            await phone(developer, True)
            await opened(developer, f"{base}/conversations")
            _check(
                "Developer: the refusal on a phone does not scroll sideways",
                await fits(developer),
                failures,
            )

        async with db.identity_session() as session:
            made = {
                str(row.email): str(row.id)
                for row in (
                    await session.execute(
                        select(users.c.id, users.c.email).where(
                            users.c.email.in_([support_email, developer_email])
                        )
                    )
                ).all()
            }
        page = await opened(browser, f"{base}/people")
        _check("Owner: both people joined", page.count("Joined") == 2, failures)

        # A role changed on the screen, then read back from the server.
        await browser.evaluate(
            f"""(() => {{
              const box = document.querySelector('[data-role-of="{made[support_email]}"]');
              Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')
                .set.call(box, 'developer');
              box.dispatchEvent(new Event('change', {{ bubbles: true }}));
              return true;
            }})()"""
        )
        await asyncio.sleep(2.5)
        async with db.tenant_session(tenant) as session:
            changed = await session.scalar(
                select(memberships.c.role).where(
                    memberships.c.tenant_id == tenant,
                    memberships.c.user_id == made[support_email],
                    memberships.c.revoked_at.is_(None),
                )
            )
        _check("Owner: a role changed on the screen is saved", changed == "developer", failures)

        await phone(browser, True)
        await opened(browser, f"{base}/people")
        _check("Owner: People on a phone does not scroll sideways", await fits(browser), failures)
        await phone(browser, False)
        await opened(browser, f"{base}/people")

        for email in (support_email, developer_email):
            await browser.evaluate(
                f"document.querySelector('[data-remove=\"{made[email]}\"]').click(), true"
            )
            await asyncio.sleep(0.6)
            asked = str(await browser.evaluate("document.body.innerText"))
            _check(
                "Owner: Remove asks first",
                "can't open this shop's dashboard from the next click" in asked,
                failures,
            )
            await browser.evaluate("document.querySelector('[data-confirm-remove]').click(), true")
            await asyncio.sleep(2.5)
        page = str(await browser.evaluate("document.body.innerText"))
        _check("Owner: after removing both, nobody else is listed", "Joined" not in page, failures)
    finally:
        async with db.identity_session() as session:
            gone = list(
                (
                    await session.execute(
                        select(users.c.id).where(
                            users.c.email.in_([support_email, developer_email])
                        )
                    )
                ).scalars()
            )
        async with db.tenant_session(tenant) as session:
            await session.execute(delete(memberships).where(memberships.c.user_id.in_(gone)))
            await session.execute(
                delete(membership_invites).where(
                    membership_invites.c.email.in_([support_email, developer_email])
                )
            )
        async with db.identity_session() as session:
            await session.execute(delete(login_tokens).where(login_tokens.c.user_id.in_(gone)))
            await session.execute(delete(users).where(users.c.id.in_(gone)))
        await db.dispose()


async def _check_sign_up(console: str, failures: list[str]) -> None:
    """Create an account, the waiting screen and approval (ADR-0058 §7, boards 42 to 45).

    In its own browser, signed out, as a new shop owner. The form is sent once
    with a website that is not one, which the API refuses before anything is
    stored or mailed; the request itself is then made **in the database**
    (`request_sign_up`), so this check never sends an email, whatever mail
    server the API has. The link is opened as the new owner would, the waiting
    screen read on desktop and phone, the shop approved in the database (no
    email), and Home must then open. Afterwards the shop is removed as
    `make tenant-refuse` removes one, and the account by its email.
    """
    from widget_check import deprovision

    from neura_core.identity.schema import login_tokens, sign_up_requests, users
    from neura_core.identity.sign_up import approve_shop, request_sign_up

    email = f"sign-up-check-{ids.new_id(ids.USER).lower()}@example.com"
    shop = "Sign Up Check Shop"
    db = Database.from_settings()
    tenant = ""

    async def phone(page: Chrome, on: bool) -> None:
        await page.call(
            "Emulation.setDeviceMetricsOverride",
            width=390 if on else 1280,
            height=844 if on else 900,
            deviceScaleFactor=1,
            mobile=on,
        )

    async def fits(page: Chrome) -> bool:
        return bool(
            await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        )

    async def opened(page: Chrome, url: str, wait: float = 3) -> str:
        await page.goto(url)
        await asyncio.sleep(wait)
        return str(await page.evaluate("document.body.innerText"))

    async def type_into(page: Chrome, selector: str, value: str) -> None:
        await page.evaluate(
            f"""(() => {{
              const el = document.querySelector('{selector}');
              const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              set.call(el, {value!r});
              el.dispatchEvent(new Event('input', {{ bubbles: true }}));
              return true;
            }})()"""
        )

    async def menu(page: Chrome) -> int:
        return int(
            await page.evaluate("document.querySelectorAll('nav[aria-label=Screens] a').length")
        )

    try:
        async with Chrome(find_chrome()) as page:
            for on in (False, True):
                size = "phone" if on else "desktop"
                await phone(page, on)
                shown = await opened(page, f"{console}/")
                _check(
                    f"Sign in offers New to NEURA? Create an account ({size})",
                    "New to NEURA?" in shown and "Create an account" in shown,
                    failures,
                )
                await page.evaluate("document.querySelector('[data-create-account]').click(), true")
                await asyncio.sleep(2.5)
                shown = str(await page.evaluate("document.body.innerText"))
                _check(
                    f"Create an account opens from Sign in ({size})",
                    await page.evaluate("location.pathname") == "/sign-up"
                    and "Tell us about your shop" in shown,
                    failures,
                )
                _check(
                    f"it asks for the email, the shop's name and its website ({size})",
                    all(
                        words in shown
                        for words in (
                            "Your email address",
                            "Your shop's name",
                            "Your shop's website",
                            "Create my account",
                            "FiveNeurals looks at every new shop before its assistant starts.",
                            "Already have an account?",
                        )
                    ),
                    failures,
                )
                _check(f"Create an account fits the screen ({size})", await fits(page), failures)

            await phone(page, False)
            await opened(page, f"{console}/sign-up")
            await type_into(page, "#email", email)
            await type_into(page, "#shop-name", shop)
            await type_into(page, "#website", "not a site")
            await page.evaluate("document.querySelector('form button[type=submit]').click(), true")
            await asyncio.sleep(2.5)
            shown = str(await page.evaluate("document.body.innerText"))
            _check(
                "a website that is not one is refused in plain words, nothing sent",
                "Enter your shop's website, like yourshop.com." in shown
                and "Check your email" not in shown,
                failures,
            )

            async with db.identity_session() as session:
                link = await request_sign_up(
                    session,
                    email=email,
                    name=shop,
                    website="sign-up-check.example.com",
                    console_base_url=console,
                )
            await opened(page, link.url, wait=5)
            path = str(await page.evaluate("location.pathname"))
            tenant = path.split("/")[2] if path.startswith("/console/tn_") else ""
            _check("the link signs the new owner in and opens their shop", bool(tenant), failures)
            if not tenant:
                return

            for on in (False, True):
                size = "phone" if on else "desktop"
                await phone(page, on)
                shown = await opened(page, f"{console}/console/{tenant}")
                _check(
                    f"the waiting screen: the shop waits, we'll email them ({size})",
                    f"{shop} is waiting for approval" in shown
                    and email in shown
                    and "Until then nothing runs and nothing costs anything." in shown,
                    failures,
                )
                _check(
                    f"it offers the owner guide and Sign out, no menu, no Your shops ({size})",
                    "While you wait: the guide for shop owners" in shown
                    and "Sign out" in shown
                    and "Your shops" not in shown
                    and await menu(page) == 0,
                    failures,
                )
                _check(f"the waiting screen fits the screen ({size})", await fits(page), failures)

            await phone(page, False)
            shown = await opened(page, f"{console}/console/{tenant}/conversations")
            _check(
                "a typed address to another screen still shows the waiting screen",
                "is waiting for approval" in shown and await menu(page) == 0,
                failures,
            )
            shown = await opened(page, f"{console}/console")
            _check(
                "Your shops says Waiting for approval", "Waiting for approval" in shown, failures
            )

            async with db.tenant_session(tenant) as session:
                await approve_shop(session, tenant, agents=["care"])
            shown = await opened(page, f"{console}/console/{tenant}")
            _check(
                "once approved, Home opens with the Owner's menu",
                "is waiting for approval" not in shown
                and "You're the Owner" in shown
                and await menu(page) > 0,
                failures,
            )

            shown = await opened(page, link.url, wait=4)
            _check(
                "a used sign-up link says so, with Sign in and Create an account",
                "work once" in shown and "Sign in" in shown and "Create an account" in shown,
                failures,
            )
    finally:
        if tenant:
            await deprovision(tenant)
        async with db.identity_session() as session:
            gone = list(
                (await session.execute(select(users.c.id).where(users.c.email == email))).scalars()
            )
            await session.execute(delete(sign_up_requests).where(sign_up_requests.c.email == email))
            await session.execute(delete(login_tokens).where(login_tokens.c.user_id.in_(gone)))
            await session.execute(delete(users).where(users.c.id.in_(gone)))
        await db.dispose()


async def _check_admin(console: str, email: str, failures: list[str]) -> None:
    """The FiveNeurals admin dashboard (ADR-0061, boards 46 to 49), in its own browser.

    The check's own person is not an admin at first: Your shops shows no *Admin*
    link and `/admin` says *No such page*. Then they are made one in the
    database, and two shops waiting for approval are made **with no owner**, so
    approving and refusing them on the screen can never send an email, whatever
    mail server the API has. One is approved and one refused on the screen, on
    desktop; Shops and AI use and cost are read on desktop and phone; a live shop
    with GROW has its night check turned off and on again on the screen (ADR-0065,
    boards 61 and 63), on desktop and phone; an admin sign-in older than 12 hours
    is shown *Sign in again*. Afterwards the person
    is taken off the admin list and every shop this made is removed.
    """
    from sqlalchemy import text as sql

    from neura_core.identity import COOKIE_NAME as SESSION
    from neura_core.identity import issue
    from neura_core.identity.admin_codes import reset as reset_admin_code
    from neura_core.identity.admins import add_admin
    from neura_core.identity.totp import STEP_SECONDS, code_at
    from neura_core.tenancy import TenantConfig, TenantRepository, TenantStatus, TurnMode
    from neura_core.tenancy.removal import remove_tenant
    from neura_core.tenancy.switches import SwitchRepository

    db = Database.from_settings()
    suffix = ids.new_id(ids.USER).lower()[-8:]
    approve_name, refuse_name = f"Admin Check Approve {suffix}", f"Admin Check Refuse {suffix}"
    switch_name = f"Admin Check Switch {suffix}"
    made: list[str] = []
    user = ""

    async def phone(page: Chrome, on: bool) -> None:
        await page.call(
            "Emulation.setDeviceMetricsOverride",
            width=390 if on else 1280,
            height=844 if on else 900,
            deviceScaleFactor=1,
            mobile=on,
        )

    async def fits(page: Chrome) -> bool:
        return bool(
            await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        )

    async def opened(page: Chrome, url: str, wait: float = 3) -> str:
        await page.goto(url)
        await asyncio.sleep(wait)
        return str(await page.evaluate("document.body.innerText"))

    async def click(page: Chrome, selector: str, wait: float = 2.5) -> str:
        await page.evaluate(f"document.querySelector('{selector}').click(), true")
        await asyncio.sleep(wait)
        return str(await page.evaluate("document.body.innerText"))

    async def type_code(page: Chrome, value: str) -> None:
        await page.evaluate(
            f"""(() => {{
              const el = document.querySelector('[data-code-input]');
              const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              set.call(el, {value!r});
              el.dispatchEvent(new Event('input', {{ bubbles: true }}));
              return true;
            }})()"""
        )

    def now_code(key: str, ahead: int = 0) -> str:
        step = int(datetime.now(UTC).timestamp()) // STEP_SECONDS
        return code_at(key.replace(" ", ""), step + ahead)

    async def sign_in_cookie(page: Chrome, signed_in: datetime) -> None:
        """A sign-in made at ``signed_in``, with no code typed in it (ADR-0067)."""
        await page.call(
            "Network.setCookie",
            name=SESSION,
            value=issue(user, get_settings().secret_key, now=signed_in),
            url=console,
            path="/",
            secure=True,
            httpOnly=True,
        )

    async def waiting_shop(name: str) -> str:
        tenant_id = ids.new_id(ids.TENANT)
        async with db.tenant_session(tenant_id) as session:
            await TenantRepository(session).create(
                tenant_id=tenant_id,
                name=name,
                status=TenantStatus.WAITING,
                website="admin-check.example.com",
                config=TenantConfig(mode=TurnMode.SHADOW),
            )
        made.append(tenant_id)
        return tenant_id

    try:
        async with db.identity_session() as session:
            minted = await request_sign_in_link(session, email=email, console_base_url=console)
        user = minted.user_id
        async with Chrome(find_chrome()) as page:
            await phone(page, False)
            await opened(page, minted.url, wait=4)
            shown = await opened(page, f"{console}/console")
            _check(
                "not an admin: Your shops has no Admin link",
                "Your shops" in shown
                and not await page.evaluate("!!document.querySelector('[data-admin-link]')"),
                failures,
            )
            shown = await opened(page, f"{console}/admin")
            _check("not an admin: /admin says No such page", "No such page" in shown, failures)

            async with db.identity_session() as session:
                await add_admin(session, email=email)
            approve_id = await waiting_shop(approve_name)
            refuse_id = await waiting_shop(refuse_name)

            shown = await opened(page, f"{console}/console")
            _check(
                "an admin: Your shops has the Admin link",
                bool(await page.evaluate("!!document.querySelector('[data-admin-link]')")),
                failures,
            )

            # ADR-0067: before any admin page, the code from the admin's phone.
            shown = await opened(page, f"{console}/admin", wait=4)
            key = str(
                await page.evaluate("document.querySelector('[data-code-key]')?.innerText ?? ''")
            )
            _check(
                "the code: an admin with none sets it up first (QR code and key)",
                "Protect your admin sign-in" in shown
                and bool(await page.evaluate("!!document.querySelector('[data-admin-code] img')"))
                and len(key.replace(" ", "")) == 32
                and "Shops"
                not in str(await page.evaluate("document.querySelector('nav')?.innerText ?? ''")),
                failures,
            )
            await type_code(page, "000000")
            shown = await click(page, "[data-code-submit]", wait=2)
            _check("the code: a wrong first code is refused", "didn't work" in shown, failures)
            await type_code(page, now_code(key))
            shown = await click(page, "[data-code-submit]", wait=2.5)
            _check("the code: the right one sets it up", "Your phone is set up" in shown, failures)
            shown = await click(page, "[data-go-to-shops]", wait=4)
            _check(
                "the code: then the admin area opens",
                "All shops ·" in shown or "Waiting for approval ·" in shown,
                failures,
            )
            for on in (False, True):
                size = "phone" if on else "desktop"
                await phone(page, on)
                shown = await opened(page, f"{console}/admin")
                _check(
                    f"Shops: the waiting shops first, then every shop ({size})",
                    "Waiting for approval ·" in shown
                    and approve_name in shown
                    and "Look and decide" in shown
                    and "All shops ·" in shown
                    and "no shopper's chat or details" in shown,
                    failures,
                )
                _check(f"Shops fits the screen ({size})", await fits(page), failures)
            await phone(page, False)
            shown = str(await page.evaluate("document.body.innerText"))
            _check(
                "the side menu: FiveNeurals admin, Shops, AI use and cost",
                "FiveNeurals admin" in shown
                and "You're an admin" in shown
                and "AI use and cost" in shown,
                failures,
            )

            shown = await opened(page, f"{console}/admin/shops/{approve_id}")
            _check(
                "a waiting shop: its facts, CARE ticked, SELL not",
                "Look at the website before you decide" in shown
                and bool(
                    await page.evaluate("document.querySelector('[data-assistant=care]').checked")
                )
                and not await page.evaluate(
                    "document.querySelector('[data-assistant=sell]').checked"
                ),
                failures,
            )
            shown = await click(page, "[data-refuse]", wait=1.5)
            _check(
                "Refuse asks first, and says it can't be undone",
                f"Refuse {approve_name}?" in shown and "can't be undone" in shown,
                failures,
            )
            await page.evaluate(
                "[...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Keep waiting').click(), true"
            )
            await asyncio.sleep(1)
            shown = await click(page, "[data-approve]", wait=4)
            async with db.tenant_session(approve_id) as session:
                approved = await TenantRepository(session).get(approve_id)
            _check(
                "Approve: the shop is approved with NEURA-CARE, in practice mode",
                f"{approve_name} is approved" in shown
                and "With NEURA-CARE, in practice mode" in shown
                and approved is not None
                and approved.status is TenantStatus.ACTIVE
                and approved.enabled_agents == frozenset({"care"}),
                failures,
            )

            shown = await click(page, "[data-back-to-shops]", wait=4)
            _check(
                "Back to Shops: the approved shop no longer waits",
                await page.evaluate("location.pathname") == "/admin"
                and not await page.evaluate(
                    f"!!document.querySelector('[data-waiting-shop=\"{approve_id}\"]')"
                ),
                failures,
            )

            await opened(page, f"{console}/admin/shops/{refuse_id}")
            await click(page, "[data-refuse]", wait=1.5)
            shown = await click(page, "[data-confirm-refuse]", wait=4)
            async with db.tenant_session(refuse_id) as session:
                refused = await TenantRepository(session).get(refuse_id)
            _check(
                "Refuse: the shop is refused and removed",
                f"{refuse_name} is refused and removed" in shown and refused is None,
                failures,
            )

            for on in (False, True):
                size = "phone" if on else "desktop"
                await phone(page, on)
                shown = await opened(page, f"{console}/admin/usage?period=7d")
                _check(
                    f"AI use and cost: totals, by shop, why Not priced ({size})",
                    "AI use and cost" in shown
                    and "handed to a person" in shown
                    and "By shop" in shown
                    and 'Why "Not priced".' in shown,
                    failures,
                )
                _check(f"AI use and cost fits the screen ({size})", await fits(page), failures)

            # ADR-0065: a live shop with GROW, and no owner, so nothing is emailed.
            switch_id = ids.new_id(ids.TENANT)
            async with db.tenant_session(switch_id) as session:
                await TenantRepository(session).create(
                    tenant_id=switch_id, name=switch_name, enabled_agents=["care", "grow"]
                )
            made.append(switch_id)
            for on in (False, True):
                size = "phone" if on else "desktop"
                await phone(page, on)
                shown = await opened(page, f"{console}/admin/shops/{switch_id}")
                _check(
                    f"a shop with GROW: its night check, On ({size})",
                    "Switch a feature off" in shown
                    and "The night AI check" in shown
                    # R65: the switch names both pages it pauses.
                    and "Missing from your pages and Shoppers asked for" in shown
                    and bool(
                        await page.evaluate(
                            "!!document.querySelector('[data-switch=\"grow.gaps\"] [data-switch-off]')"
                        )
                    ),
                    failures,
                )
                shown = await click(page, '[data-switch="grow.gaps"] [data-switch-off]', wait=1.5)
                _check(
                    f"Turn off asks first, and says those chats are never read ({size})",
                    f"Turn off the night check for {switch_name}?" in shown
                    and "never read later" in shown
                    and "can't turn it back on" in shown,
                    failures,
                )
                _check(f"the shop page fits the screen ({size})", await fits(page), failures)
                shown = await click(
                    page, '[data-switch="grow.gaps"] [data-confirm-switch-off]', wait=3
                )
                async with db.tenant_session(switch_id) as session:
                    off = not await SwitchRepository(session).is_on(switch_id, "grow.gaps")
                _check(
                    f"Turn off: it is off, by you, and stored ({size})",
                    "Off since" in shown and "by you" in shown and off,
                    failures,
                )
                shown = await click(page, '[data-switch="grow.gaps"] [data-switch-on]', wait=3)
                async with db.tenant_session(switch_id) as session:
                    back = await SwitchRepository(session).is_on(switch_id, "grow.gaps")
                _check(
                    f"Turn on: on again, from now on ({size})",
                    "On again since" in shown and "from now on" in shown and back,
                    failures,
                )
            # ADR-0072 §5: the calendar's own switch, with its own words (G123).
            await phone(page, False)
            shown = await opened(page, f"{console}/admin/shops/{switch_id}")
            _check(
                "a shop with GROW: the calendar's AI plans, a switch of its own",
                "The calendar's AI plans" in shown
                and "AI writes a campaign plan" in shown
                and bool(
                    await page.evaluate(
                        "!!document.querySelector('[data-switch=\"grow.calendar\"] [data-switch-off]')"
                    )
                ),
                failures,
            )
            shown = await click(page, '[data-switch="grow.calendar"] [data-switch-off]', wait=1.5)
            _check(
                "Turn off asks first, in the calendar's own words",
                f"Turn off the calendar's AI plans for {switch_name}?" in shown
                and "no plan is made" in shown
                and "Chats from that time" not in shown,
                failures,
            )
            shown = await click(
                page, '[data-switch="grow.calendar"] [data-confirm-switch-off]', wait=3
            )
            async with db.tenant_session(switch_id) as session:
                calendar_off = not await SwitchRepository(session).is_on(switch_id, "grow.calendar")
                night_on = await SwitchRepository(session).is_on(switch_id, "grow.gaps")
            _check(
                "the calendar's plans off, the night check still on",
                "Off since" in shown and calendar_off and night_on,
                failures,
            )
            shown = await click(page, '[data-switch="grow.calendar"] [data-switch-on]', wait=3)
            _check(
                "on again, in its own words",
                "Plans that are due are made again from the next night." in shown,
                failures,
            )
            shown = await opened(page, f"{console}/admin/shops/{approve_id}")
            _check(
                "a shop without GROW has no switch",
                "Switch a feature off" not in shown,
                failures,
            )

            for on in (False, True):
                size = "phone" if on else "desktop"
                await phone(page, on)
                await sign_in_cookie(page, datetime.now(UTC) - timedelta(seconds=5))
                shown = await opened(page, f"{console}/admin")
                _check(
                    f"the code: a new sign-in asks for it before any admin page ({size})",
                    "Type the code from your phone" in shown and "Lost your phone?" in shown,
                    failures,
                )
                _check(f"the code page fits the screen ({size})", await fits(page), failures)
            await type_code(page, "000000")
            shown = await click(page, "[data-code-submit]", wait=2)
            _check("the code: a wrong code at sign-in is refused", "didn't work" in shown, failures)
            await type_code(page, now_code(key, ahead=1))
            shown = await click(page, "[data-code-submit]", wait=4)
            _check(
                "the code: the right one opens the admin area",
                "All shops ·" in shown or "Waiting for approval ·" in shown,
                failures,
            )

            await phone(page, False)
            old = issue(
                user, get_settings().secret_key, now=datetime.now(UTC) - timedelta(hours=13)
            )
            await page.call(
                "Network.setCookie",
                name=SESSION,
                value=old,
                url=console,
                path="/",
                secure=True,
                httpOnly=True,
            )
            shown = await opened(page, f"{console}/admin")
            _check(
                "an admin signed in 13 hours ago is asked to sign in again",
                "Sign in again" in shown and "last 12 hours" in shown,
                failures,
            )
    finally:
        for tenant_id in made:
            async with db.tenant_session(tenant_id) as session:
                await remove_tenant(session, tenant_id)
        async with db.identity_session() as session:
            await reset_admin_code(session, user)
        engine = create_async_engine(str(get_settings().database_migration_url))
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    sql(
                        "DELETE FROM platform_admins WHERE user_id IN "
                        "(SELECT id FROM users WHERE email = :e)"
                    ),
                    {"e": email},
                )
        finally:
            await engine.dispose()
        await db.dispose()


async def _check_gaps(
    browser: Chrome,
    console: str,
    db: Database,
    user_id: str,
    seeded: dict[str, str],
    failures: list[str],
) -> None:
    """*Missing from your pages* (ADR-0064, console.md §3.11, boards 57 to 62).

    In **a shop of its own** with NEURA-GROW, where this person is the Owner, so
    nothing real is touched: two products and their questions are seeded (one
    asked by 3 shoppers, one by 2, one by only 1, which must not show; one about
    the shop). Checked on desktop and phone: the menu item, the rows, *Open the
    page*, *See the chats* narrowing Conversations, *I added it*, Home's line and
    the *Paused* note (ADR-0065). The first shop, which has no GROW, must not
    list the page. Everything made here is removed at the end.
    """
    from neura_agent_core.gaps import GapKind, PageGap, PageGapRepository
    from neura_core.identity.schema import memberships
    from neura_core.tenancy import TenantRepository
    from neura_core.tenancy.removal import remove_tenant
    from neura_core.tenancy.switches import SwitchRepository

    tenant = ids.new_id(ids.TENANT)
    base = f"{console}/console/{tenant}"
    shop_name = f"Gaps Check {tenant[-6:].lower()}"

    async def ask(product: str | None, fact: str, question: str, hours: int) -> None:
        conversation = ids.new_id(ids.CONVERSATION)
        async with db.tenant_session(tenant) as session:
            repository = ConversationRepository(session)
            await repository.start(tenant, conversation_id=conversation, agent_key="care")
            await repository.append_turn(
                tenant,
                conversation,
                shopper=question,
                reply="I can't confirm that.",
                state=ConversationState.RESOLVED,
            )
            await PageGapRepository(session).record(
                tenant,
                PageGap(
                    conversation_id=conversation,
                    message_id=f"msg_{conversation}",
                    kind=GapKind.HALF_ANSWERED,
                    product_id=product,
                    fact=fact,
                    question=question,
                    asked_at=datetime.now(UTC) - timedelta(hours=hours),
                ),
            )

    async def phone(on: bool) -> None:
        await browser.call(
            "Emulation.setDeviceMetricsOverride",
            width=390 if on else 1280,
            height=844 if on else 900,
            deviceScaleFactor=1,
            mobile=on,
        )

    async def shown(url: str, wait: float = 3.5) -> str:
        await browser.goto(url)
        await asyncio.sleep(wait)
        return str(await browser.evaluate("document.body.innerText"))

    try:
        async with db.tenant_session(tenant) as session:
            await TenantRepository(session).create(
                tenant_id=tenant, name=shop_name, enabled_agents=["care", "grow"]
            )
            await session.execute(
                memberships.insert().values(
                    id=ids.new_id(ids.MEMBERSHIP), tenant_id=tenant, user_id=user_id, role="owner"
                )
            )
            for product, title in (("5", "Gaps Check Green Tea"), ("4", "Gaps Check Black Tea")):
                await session.execute(
                    synced_entities.insert().values(
                        tenant_id=tenant,
                        platform="generic",
                        entity_type="product",
                        external_id=product,
                        neura_id=f"nr_{product}",
                        fingerprint="f" * 32,
                        document={"title": title, "url": f"http://shop.example/product/{product}"},
                    )
                )
        for hours in (2, 3, 4):
            await ask("5", "organic", "Is it organic?", hours)
        for hours in (5, 6):
            await ask("4", "caffeine", "How much caffeine?", hours)
        await ask("5", "cups per pack", "How many cups per pack?", 1)
        for hours in (7, 8):
            await ask(None, "cash on delivery", "Can I pay cash on delivery?", hours)

        for on in (False, True):
            size = "phone" if on else "desktop"
            await phone(on)
            page = await shown(f"{base}/gaps")
            _check(
                f"the page: heading, count line, products, About your shop ({size})",
                "Missing from your pages" in page
                and "3 things" in page
                and "in 3 groups" in page
                and "Gaps Check Green Tea" in page
                and "About your shop" in page
                and "Is it organic?" in page
                and "Asked by 3 shoppers" in page,
                failures,
            )
            _check(
                f"a question only 1 shopper asked is not shown ({size})",
                "How many cups per pack?" not in page,
                failures,
            )
            _check(
                f"Open the page goes to the shop's own page, in a new tab ({size})",
                bool(
                    await browser.evaluate(
                        "!![...document.querySelectorAll('a[target=_blank]')]"
                        ".find(a => a.href === 'http://shop.example/product/5')"
                    )
                ),
                failures,
            )
            _check(
                f"GROW never writes the answer; the page says where to add it ({size})",
                "Add the answer to its description in your shop." in page
                and "Only you know the answers" in page,
                failures,
            )
            _check(
                f"the page fits the screen ({size})",
                bool(
                    await browser.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth + 1"
                    )
                ),
                failures,
            )
        await phone(False)

        menu = await browser.evaluate(
            "[...document.querySelectorAll('nav a')].some(a => a.innerText.trim() === "
            "'Missing from your pages')"
        )
        _check("the menu lists Missing from your pages for a shop with GROW", bool(menu), failures)

        home = await shown(base)
        _check(
            "Home's Needs you: the page's count, with See them",
            "things shoppers asked that your pages don't say" in home
            and bool(
                await browser.evaluate(
                    f"!!document.querySelector('a[href=\"/console/{tenant}/gaps\"]')"
                )
            ),
            failures,
        )

        await shown(f"{base}/gaps")
        await browser.evaluate(
            "document.querySelector('[data-gap=\"5|organic\"] [data-see-chats]').click(), true"
        )
        await asyncio.sleep(3.5)
        listed = str(await browser.evaluate("document.body.innerText"))
        rows = await browser.evaluate(
            "document.querySelectorAll('ul a[href*=\"/conversations/\"]').length"
        )
        _check(
            "See the chats: Conversations shows exactly the 3 chats behind the row",
            rows == 3 and "Is it organic?" in listed,
            failures,
        )

        await shown(f"{base}/gaps")
        await browser.evaluate(
            "document.querySelector('[data-gap=\"5|organic\"] [data-added]').click(), true"
        )
        await asyncio.sleep(2.5)
        after = str(await browser.evaluate("document.body.innerText"))
        _check(
            "I added it: the row says it leaves the list",
            "Marked as added." in after and "comes back here" in after,
            failures,
        )
        again = await shown(f"{base}/gaps")
        _check(
            "I added it: after a reload the question is gone",
            "Is it organic?" not in again and "2 things" in again,
            failures,
        )

        async with db.tenant_session(tenant) as session:
            await SwitchRepository(session).set(tenant, "grow.gaps", on=False, by=user_id)
        paused = await shown(f"{base}/gaps")
        _check(
            "Paused: the note says FiveNeurals paused it, and the rows stay",
            "Paused since" in paused
            and "FiveNeurals has paused the check" in paused
            and "How much caffeine?" in paused,
            failures,
        )

        if seeded.get("tenant"):
            await shown(f"{console}/console/{seeded['tenant']}")
            _check(
                "a shop without GROW does not list the page",
                not await browser.evaluate(
                    "[...document.querySelectorAll('nav a')].some(a => a.innerText.trim() === "
                    "'Missing from your pages')"
                ),
                failures,
            )
    finally:
        async with db.tenant_session(tenant) as session:
            await remove_tenant(session, tenant)


async def _check_wanted(
    browser: Chrome,
    console: str,
    db: Database,
    user_id: str,
    seeded: dict[str, str],
    failures: list[str],
) -> None:
    """*Shoppers asked for* (ADR-0068, console.md §3.12, boards 67 to 70).

    In **a shop of its own** with NEURA-GROW, where this person is the Owner, so
    nothing real is touched: things shoppers asked for are seeded (matcha by 3
    shoppers, oolong tea by 2, honey by only 1, which must not show). Checked on
    desktop and phone: the menu item, the rows, *See the chats* narrowing
    Conversations, *Hide*, *Hidden* and *Show again* (ADR-0070), Home's line
    and the *Paused* note. The first shop,
    which has no GROW, must not list the page. Everything made here is removed
    at the end.
    """
    from neura_agent_core.wanted import WantedItem, WantedRepository
    from neura_core.identity.schema import memberships
    from neura_core.tenancy import TenantRepository
    from neura_core.tenancy.removal import remove_tenant
    from neura_core.tenancy.switches import SwitchRepository

    tenant = ids.new_id(ids.TENANT)
    base = f"{console}/console/{tenant}"
    shop_name = f"Wanted Check {tenant[-6:].lower()}"

    async def ask(label: str, question: str, hours: int) -> None:
        conversation = ids.new_id(ids.CONVERSATION)
        async with db.tenant_session(tenant) as session:
            repository = ConversationRepository(session)
            await repository.start(tenant, conversation_id=conversation, agent_key="sell")
            await repository.append_turn(
                tenant,
                conversation,
                shopper=question,
                reply="I can't find anything matching that.",
                state=ConversationState.RESOLVED,
            )
            await WantedRepository(session).record(
                tenant,
                WantedItem(
                    conversation_id=conversation,
                    message_id=f"msg_{conversation}",
                    label=label,
                    question=question,
                    asked_at=datetime.now(UTC) - timedelta(hours=hours),
                ),
            )

    async def phone(on: bool) -> None:
        await browser.call(
            "Emulation.setDeviceMetricsOverride",
            width=390 if on else 1280,
            height=844 if on else 900,
            deviceScaleFactor=1,
            mobile=on,
        )

    async def shown(url: str, wait: float = 3.5) -> str:
        await browser.goto(url)
        await asyncio.sleep(wait)
        return str(await browser.evaluate("document.body.innerText"))

    try:
        async with db.tenant_session(tenant) as session:
            await TenantRepository(session).create(
                tenant_id=tenant, name=shop_name, enabled_agents=["care", "sell", "grow"]
            )
            await session.execute(
                memberships.insert().values(
                    id=ids.new_id(ids.MEMBERSHIP), tenant_id=tenant, user_id=user_id, role="owner"
                )
            )
        for hours in (2, 3, 4):
            await ask("matcha", "Do you have matcha?", hours)
        for hours in (5, 6):
            await ask("oolong tea", "Do you sell oolong tea?", hours)
        await ask("honey", "Do you sell honey?", 1)

        empty = await shown(f"{base}/wanted")
        _check(
            "the page is not empty once 2 shoppers asked",
            "Nothing asked for right now" not in empty,
            failures,
        )
        for on in (False, True):
            size = "phone" if on else "desktop"
            await phone(on)
            page = await shown(f"{base}/wanted")
            _check(
                f"the page: heading, count line, things, most asked first ({size})",
                "Shoppers asked for" in page
                and "2 things shoppers asked for. Most asked first." in page
                and "Matcha" in page
                and "A shopper asked: \u201cDo you have matcha?\u201d" in page
                and "Asked by 3 shoppers" in page
                and page.index("Matcha") < page.index("Oolong tea"),
                failures,
            )
            _check(
                f"a thing only 1 shopper asked for is not shown ({size})",
                "Honey" not in page,
                failures,
            )
            _check(
                f"counts only, never who asked ({size})",
                "Counts only, never who asked." in page,
                failures,
            )
            _check(
                f"the page fits the screen ({size})",
                bool(
                    await browser.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth + 1"
                    )
                ),
                failures,
            )
        await phone(False)

        menu = await browser.evaluate(
            "[...document.querySelectorAll('nav a')].map(a => a.innerText.trim())"
        )
        _check(
            "the menu lists Shoppers asked for, after Missing from your pages",
            isinstance(menu, list)
            and "Shoppers asked for" in menu
            and menu.index("Shoppers asked for") == menu.index("Missing from your pages") + 1,
            failures,
        )

        home = await shown(base)
        _check(
            "Home's Needs you: the page's count, with See them",
            "things shoppers asked for that you don't sell" in home
            and bool(
                await browser.evaluate(
                    f"!!document.querySelector('a[href=\"/console/{tenant}/wanted\"]')"
                )
            ),
            failures,
        )

        await shown(f"{base}/wanted")
        await browser.evaluate(
            "document.querySelector('[data-wanted=\"matcha\"] [data-see-chats]').click(), true"
        )
        await asyncio.sleep(3.5)
        listed = str(await browser.evaluate("document.body.innerText"))
        rows = await browser.evaluate(
            "document.querySelectorAll('ul a[href*=\"/conversations/\"]').length"
        )
        _check(
            "See the chats: Conversations shows exactly the 3 chats behind the row",
            rows == 3 and "The chats where shoppers asked for" in listed,
            failures,
        )

        await shown(f"{base}/wanted")
        await browser.evaluate(
            "document.querySelector('[data-wanted=\"matcha\"] [data-hide]').click(), true"
        )
        await asyncio.sleep(2.5)
        after = str(await browser.evaluate("document.body.innerText"))
        _check(
            "Hide: the row says it leaves the list, and comes back if asked for again",
            "Hidden." in after and "comes back here" in after,
            failures,
        )
        await browser.evaluate(
            "document.querySelector('[data-wanted=\"matcha\"] [data-show-again]').click(), true"
        )
        await asyncio.sleep(2.5)
        _check(
            "Show again on the grey row puts the row back (ADR-0070)",
            bool(
                await browser.evaluate(
                    "!!document.querySelector('[data-wanted=\"matcha\"] [data-hide]')"
                )
            )
            and "2 things shoppers asked for" in await shown(f"{base}/wanted"),
            failures,
        )
        await browser.evaluate(
            "document.querySelector('[data-wanted=\"matcha\"] [data-hide]').click(), true"
        )
        await asyncio.sleep(2.5)
        again = await shown(f"{base}/wanted")
        _check(
            "Hide: after a reload the thing is gone, and Hidden (1) is closed under the list",
            "Matcha" not in again
            and "1 thing shoppers asked for" in again
            and "Hidden (1)" in again,
            failures,
        )
        for on in (False, True):
            size = "phone" if on else "desktop"
            await phone(on)
            await shown(f"{base}/wanted")
            await browser.evaluate(
                "document.querySelector('[data-hidden-things] summary').click(), true"
            )
            await asyncio.sleep(0.5)
            opened = str(await browser.evaluate("document.body.innerText"))
            _check(
                f"Hidden, opened: what was hidden, with Show again ({size})",
                "Things you hid." in opened
                and "Matcha" in opened
                and "Asked by 3 shoppers \u00b7 hidden on" in opened
                and bool(
                    await browser.evaluate(
                        '!!document.querySelector(\'[data-hidden-thing="matcha"] '
                        "[data-show-again]')"
                    )
                )
                and bool(
                    await browser.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth + 1"
                    )
                ),
                failures,
            )
        await phone(False)
        await browser.evaluate(
            "document.querySelector('[data-hidden-thing=\"matcha\"] [data-show-again]').click(),"
            " true"
        )
        await asyncio.sleep(3.5)
        back = str(await browser.evaluate("document.body.innerText"))
        _check(
            "Show again in Hidden: the thing is back on the list and Hidden is gone",
            "2 things shoppers asked for" in back and "Matcha" in back and "Hidden (" not in back,
            failures,
        )

        async with db.tenant_session(tenant) as session:
            await SwitchRepository(session).set(tenant, "grow.gaps", on=False, by=user_id)
        paused = await shown(f"{base}/wanted")
        _check(
            "Paused: the night check's switch pauses this page too, and the rows stay",
            "Paused since" in paused
            and "FiveNeurals has paused the check that finds these things" in paused
            and "Oolong tea" in paused,
            failures,
        )

        if seeded.get("tenant"):
            await shown(f"{console}/console/{seeded['tenant']}")
            _check(
                "a shop without GROW does not list the page",
                not await browser.evaluate(
                    "[...document.querySelectorAll('nav a')].some(a => a.innerText.trim() === "
                    "'Shoppers asked for')"
                ),
                failures,
            )
    finally:
        async with db.tenant_session(tenant) as session:
            await remove_tenant(session, tenant)


async def _check_calendar(
    browser: Chrome,
    console: str,
    db: Database,
    user_id: str,
    seeded: dict[str, str],
    failures: list[str],
) -> None:
    """The Marketing calendar (ADR-0072, console.md §3.14, boards 75 to 79).

    In **a shop of its own** with NEURA-GROW, where this person is the Owner, so
    nothing real is touched: four own dates (a ready plan, one due tonight, one
    planned later, one whose plan could not be made) and, once the year is saved,
    the suggested list. Checked on desktop and phone: the menu item, *Coming up*,
    a plan (its sections, *Copy*, *Edit* and *Save*, *Make it again* asking
    first), *Making a new plan*, a failed plan, *This year's dates* (untick, set a
    moving date, *Save*, another country, *Add* and *Remove*), Home's lines and
    *Paused*. Support and the Developer, each in a browser of their own: Support
    sees the page without the link to the Owner's page; the Developer is refused.
    **No AI is called**: *Make it again* is only asked, never confirmed, and no
    job of the shop's is ever due. Everything made here is removed at the end.
    """
    from neura_agent_core.calendar import CalendarRepository, calendar_plans, shop_today
    from neura_agent_core.calendar import Country as CalendarCountry
    from neura_core.identity.schema import login_tokens, memberships, users
    from neura_core.tenancy import TenantRepository
    from neura_core.tenancy.removal import remove_tenant
    from neura_core.tenancy.switches import SwitchRepository

    tenant = ids.new_id(ids.TENANT)
    base = f"{console}/console/{tenant}"
    shop_name = f"Calendar Check {tenant[-6:].lower()}"
    today = shop_today(CalendarCountry.SRI_LANKA, datetime.now(UTC))
    people: list[str] = []
    answer = {
        "theme": "A console-check tea week",
        "idea": "Tea for the whole family. Show three teas and remind shoppers 2 days before.",
        "products": ["cc-tea", "cc-cinnamon"],
        "act_on": [
            {"kind": "wanted", "label": "tea gift box", "shoppers": 8, "product_id": None},
            {"kind": "gap", "label": "caffeine", "shoppers": 3, "product_id": "cc-tea"},
        ],
        "texts": {
            "teaser": "Something is coming to our shop. [your offer] soon.",
            "launch": "Our console-check teas are here: [your offer].",
            "last_chance": "Last 2 days for [your offer].",
            "email_subject": "Our console-check tea week",
            "email_body": "Hello,\n\nOur tea week is here. [your offer].\n\nThe shop",
            "banner": "Tea week: [your offer]",
        },
        "catalogue_cut": False,
    }

    async def phone(page: Chrome, on: bool) -> None:
        await page.call(
            "Emulation.setDeviceMetricsOverride",
            width=390 if on else 1280,
            height=844 if on else 900,
            deviceScaleFactor=1,
            mobile=on,
        )

    async def shown(page: Chrome, url: str, wait: float = 3.5) -> str:
        await page.goto(url)
        await asyncio.sleep(wait)
        return str(await page.evaluate("document.body.innerText"))

    async def fits(page: Chrome) -> bool:
        return bool(
            await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        )

    async def click(selector: str, wait: float = 2.5) -> str:
        await browser.evaluate(f"document.querySelector('{selector}').click(), true")
        await asyncio.sleep(wait)
        return str(await browser.evaluate("document.body.innerText"))

    async def type_into(selector: str, value: str, kind: str = "HTMLInputElement") -> None:
        await browser.evaluate(
            f"""(() => {{
              const el = document.querySelector('{selector}');
              const set = Object.getOwnPropertyDescriptor({kind}.prototype, 'value').set;
              set.call(el, {value!r});
              el.dispatchEvent(new Event('input', {{ bubbles: true }}));
              return true;
            }})()"""
        )

    async def menu(page: Chrome) -> list[str]:
        return list(
            await page.evaluate(
                "[...document.querySelectorAll('nav[aria-label=Screens] a')]"
                ".map(a => a.innerText.trim().split('\\n')[0])"
            )
        )

    async def own(name: str, days: int, *, every_year: bool = False) -> Any:
        async with db.tenant_session(tenant) as session:
            return await CalendarRepository(session).add_own(
                tenant,
                name=name,
                day=today + timedelta(days=days),
                every_year=every_year,
                by=user_id,
            )

    try:
        async with db.tenant_session(tenant) as session:
            await TenantRepository(session).create(
                tenant_id=tenant, name=shop_name, enabled_agents=["care", "grow"]
            )
            await session.execute(
                memberships.insert().values(
                    id=ids.new_id(ids.MEMBERSHIP), tenant_id=tenant, user_id=user_id, role="owner"
                )
            )
            for product_id, title, amount in (
                ("cc-tea", "Console-check Breakfast Tea", "1850.00"),
                ("cc-cinnamon", "Console-check Cinnamon", "1290.00"),
            ):
                await session.execute(
                    synced_entities.insert().values(
                        tenant_id=tenant,
                        platform=SEEDED_PLATFORM,
                        entity_type="product",
                        external_id=product_id,
                        neura_id=f"nr_{product_id}",
                        fingerprint="c" * 32,
                        document={
                            "title": title,
                            "url": f"https://shop.example/{product_id}",
                            "price_range_min": {"amount": amount, "currency": "LKR"},
                        },
                    )
                )
        launch = await own("Console-check launch", 12)
        await own("Console-check sale", 20)
        await own("Console-check birthday", 45, every_year=True)
        fair = await own("Console-check fair", 8)
        async with db.tenant_session(tenant) as session:
            repository = CalendarRepository(session)
            plan = await repository.store_plan(
                tenant,
                date_key=launch.date_key,
                day=launch.day,
                name="Console-check launch",
                answer=answer,
                prompt_revision="console-check",
                at=datetime.now(UTC),
            )
            failed = await repository.fail_plan(
                tenant,
                date_key=fair.date_key,
                day=fair.day,
                name="Console-check fair",
                failure="price",
                at=datetime.now(UTC),
            )
        plan_url = f"{base}/calendar/{plan.id}"

        for on in (False, True):
            size = "phone" if on else "desktop"
            await phone(browser, on)
            page = await shown(browser, f"{base}/calendar")
            _check(
                f"the page: heading, its line, This year's dates ({size})",
                "Marketing calendar" in page
                and "21 days before each one, your assistant writes a campaign plan" in page
                and "This year's dates" in page,
                failures,
            )
            _check(
                f"Coming up: a ready plan, one tonight, one later, one that failed ({size})",
                "Plan ready" in page
                and "See the plan" in page
                and "Plan tonight" in page
                and "Plan on " in page
                and "Plan could not be made" in page
                and "Make it again" in page
                and page.index("Console-check fair")
                < page.index("Console-check launch")
                < page.index("Console-check sale")
                < page.index("Console-check birthday"),
                failures,
            )
            _check(
                f"before the year is saved, only own dates count, and the page says so ({size})",
                "Add this year's special dates" in page
                and "only your own dates get a plan" in page
                and "Black Friday" not in page,
                failures,
            )
            _check(
                f"it never posts for you, and fits the screen ({size})",
                "We never post or send anything for you." in page and await fits(browser),
                failures,
            )
        await phone(browser, False)

        names = await menu(browser)
        _check(
            "the menu lists Marketing calendar, after Shoppers asked for",
            "Marketing calendar" in names
            and names.index("Marketing calendar") == names.index("Shoppers asked for") + 1,
            failures,
        )

        home = await shown(browser, base)
        _check(
            "Home: the ready plan's line and Add this year's special dates, each a calendar",
            "Console-check launch is in 12 days. Your plan is ready." in home
            and "Read it, fill in your offer, and post it yourself." in home
            and "Add this year's special dates" in home
            and bool(
                await browser.evaluate(
                    f"!!document.querySelector('a[href=\"/console/{tenant}/calendar/{plan.id}\"]')"
                    f" && !!document.querySelector('a[href=\"/console/{tenant}/calendar/dates\"]')"
                    " && document.querySelectorAll('[data-calendar-line]').length === 2"
                )
            ),
            failures,
        )

        for on in (False, True):
            size = "phone" if on else "desktop"
            await phone(browser, on)
            page = await shown(browser, plan_url)
            _check(
                f"a plan: its date, when it was made, the idea ({size})",
                "Console-check launch \u00b7 " in page
                and "Your plan, made today by your assistant from your shop's own data." in page
                and "A console-check tea week" in page,
                failures,
            )
            _check(
                f"Act on this first: the counts from the plan, links to both pages ({size})",
                "8 shoppers asked for \u201ctea gift box\u201d" in page
                and "3 shoppers asked about \u201ccaffeine\u201d for Console-check Breakfast Tea"
                in page
                and "See Shoppers asked for" in page
                and "See Missing from your pages" in page,
                failures,
            )
            _check(
                f"Products to show: names and prices from the catalogue, Open the page ({size})",
                "Console-check Breakfast Tea" in page
                and "LKR\u00a01,850.00" in page.replace("LKR 1,850.00", "LKR\u00a01,850.00")
                and bool(
                    await browser.evaluate(
                        '!!document.querySelector(\'[data-plan-product="cc-tea"] '
                        'a[href="https://shop.example/cc-tea"][target=_blank]\')'
                    )
                ),
                failures,
            )
            _check(
                f"When to post: five days, and five drafts with [your offer] marked ({size})",
                bool(
                    await browser.evaluate(
                        "document.querySelectorAll('[data-schedule] li').length === 5"
                        " && document.querySelectorAll('[data-draft]').length === 5"
                        " && document.querySelectorAll('[data-your-offer]').length >= 5"
                    )
                )
                and "Post the launch and send the email" in page
                and "Fill in [your offer] yourself." in page
                and "Check every word before you post it" in page,
                failures,
            )
            _check(
                f"a plan fits the screen, Edit and Copy under each draft ({size})",
                await fits(browser)
                and bool(
                    await browser.evaluate(
                        "(() => { const card = document.querySelector('[data-draft=\"teaser\"]');"
                        " const text = card.querySelector('[data-draft-shown]').getBoundingClientRect();"
                        " const copy = card.querySelector('[data-draft-copy]').getBoundingClientRect();"
                        " return copy.top >= text.bottom; })()"
                    )
                ),
                failures,
            )
        await phone(browser, False)

        await shown(browser, plan_url)
        # A person's click, on a page allowed the clipboard: a script's click() is
        # not one, and Chrome rightly refuses it the clipboard (the page then says
        # so). The clipboard is read back, so the check is about what was copied.
        await browser.call(
            "Browser.grantPermissions",
            permissions=["clipboardReadWrite", "clipboardSanitizedWrite"],
            origin=console,
        )
        await browser.call("Emulation.setFocusEmulationEnabled", enabled=True)
        where = await browser.evaluate(
            "(() => { const b = document.querySelector('[data-draft=\"banner\"] [data-draft-copy]');"
            " b.scrollIntoView({ block: 'center' }); const r = b.getBoundingClientRect();"
            " return [r.x + r.width / 2, r.y + r.height / 2]; })()"
        )
        for kind in ("mousePressed", "mouseReleased"):
            await browser.call(
                "Input.dispatchMouseEvent",
                type=kind,
                x=where[0],
                y=where[1],
                button="left",
                clickCount=1,
            )
        await asyncio.sleep(1)
        label = await browser.evaluate(
            "document.querySelector('[data-draft=\"banner\"] [data-draft-copy]').innerText"
        )
        pasted = (
            (
                await browser.call(
                    "Runtime.evaluate",
                    expression="navigator.clipboard.readText()",
                    awaitPromise=True,
                    returnByValue=True,
                )
            )
            .get("result", {})
            .get("value")
        )
        await browser.call("Emulation.setFocusEmulationEnabled", enabled=False)
        _check(
            "Copy: the banner is on the clipboard, word for word, and the button says Copied",
            "Copied" in str(label) and pasted == "Tea week: [your offer]",
            failures,
        )

        await click('[data-draft="teaser"] [data-draft-edit]', wait=1)
        await type_into(
            '[data-draft="teaser"] [data-draft-text]',
            "Our console-check words: 20% off.",
            "HTMLTextAreaElement",
        )
        await click('[data-draft="teaser"] [data-draft-save]', wait=3)
        again = await shown(browser, plan_url)
        _check(
            "Edit, then Save: the owner's words stay after a reload, unchecked",
            "Our console-check words: 20% off." in again,
            failures,
        )
        asked = await click("[data-make-again]", wait=1.5)
        _check(
            "Make it again, after an edit, asks first",
            "Your edits will be replaced. Make it again?" in asked,
            failures,
        )
        # Never confirmed: that would book GROW's job and call the AI.
        await browser.evaluate(
            "[...document.querySelectorAll('[data-make-again-area] button')]"
            ".find(b => b.innerText.trim() === 'Cancel').click(), true"
        )

        async with db.tenant_session(tenant) as session:
            await session.execute(
                calendar_plans.update()
                .where(calendar_plans.c.id == plan.id)
                .values(requested_at=datetime.now(UTC))
            )
        making = await shown(browser, plan_url)
        _check(
            "a plan asked for again says Making a new plan, and keeps the old one meanwhile",
            "Making a new plan" in making and "A console-check tea week" in making,
            failures,
        )
        async with db.tenant_session(tenant) as session:
            await CalendarRepository(session).forget_request(tenant, plan.id)

        broken = await shown(browser, f"{base}/calendar/{failed.id}")
        _check(
            "a plan that failed the checks twice says so, with Make it again",
            "Your plan could not be made" in broken
            and bool(await browser.evaluate("!!document.querySelector('[data-make-again]')")),
            failures,
        )

        for on in (False, True):
            size = "phone" if on else "desktop"
            await phone(browser, on)
            page = await shown(browser, f"{base}/calendar/dates")
            _check(
                f"This year's dates: the lists, ticked, and where the shop is ({size})",
                f"This year's dates \u00b7 {today.year}" in page
                and "Your shop is in" in page
                and "Festivals in Sri Lanka" in page
                and "Every month" in page
                and "Shopping days" in page
                and "Your own dates" in page
                and "The last working day of each month \u00b7 12 plans a year" in page
                and bool(
                    await browser.evaluate(
                        "[...document.querySelectorAll('[data-tick]')].every(b => b.checked)"
                    )
                ),
                failures,
            )
            _check(
                f"a moving date is not set, with Set the date; Save and the January line ({size})",
                "Date not set yet \u00b7 usually in April" in page
                and bool(
                    await browser.evaluate("!!document.querySelector('[data-set-date=\"vesak\"]')")
                )
                and "Save this year's dates" in page
                and "Moving dates are checked by FiveNeurals each January." in page
                and await fits(browser),
                failures,
            )
        await phone(browser, False)

        await shown(browser, f"{base}/calendar/dates")
        await click('[data-tick="black_friday"]', wait=0.5)
        unticked = str(
            await browser.evaluate(
                "document.querySelector('[data-date=\"black_friday\"]').innerText"
            )
        )
        _check(
            "untick: the date says No plan will be made",
            "No plan will be made" in unticked,
            failures,
        )
        await click('[data-set-date="vesak"]', wait=0.5)
        await type_into('[data-date-day="vesak"]', f"{today.year}-05-20")
        saved = await click("[data-save-dates]", wait=3)
        _check(
            "Save this year's dates: saved",
            "Saved. Your assistant writes a plan 21 days before each ticked date." in saved,
            failures,
        )
        await shown(browser, f"{base}/calendar/dates")
        _check(
            "after a reload: Black Friday unticked, Vesak on the day the owner set",
            bool(
                await browser.evaluate(
                    "document.querySelector('[data-date=\"black_friday\"]').dataset.kept === 'no'"
                    f" && document.querySelector('[data-date-day=\"vesak\"]').value === '{today.year}-05-20'"
                )
            ),
            failures,
        )
        elsewhere = await click('[data-country-choice="other"]', wait=0.5)
        _check(
            "Another country: the shopping days and own dates only",
            "Festivals in Sri Lanka" not in elsewhere
            and "Every month" not in elsewhere
            and "Shopping days" in elsewhere,
            failures,
        )
        await click('[data-country-choice="lk"]', wait=0.5)

        await type_into("[data-own-name]", "Console-check added")
        await type_into("[data-own-day]", (today + timedelta(days=30)).isoformat())
        added = await click("[data-add-own]", wait=3)
        _check("Add: an own date is listed at once", "Console-check added" in added, failures)
        added_id = await browser.evaluate(
            "[...document.querySelectorAll('[data-own-date]')]"
            ".find(li => li.innerText.includes('Console-check added'))?.dataset.ownDate ?? ''"
        )
        removed = await click(f'[data-remove-own="{added_id}"]', wait=3)
        _check("Remove: it goes at once", "Console-check added" not in removed, failures)

        page = await shown(browser, f"{base}/calendar")
        _check(
            "once saved, the suggested dates come up, a moving one not set yet",
            "Add this year's special dates" not in page
            and "Christmas" in page
            and "Black Friday" not in page,
            failures,
        )
        home = await shown(browser, base)
        _check(
            "Home: Add this year's special dates goes once saved and a date is near",
            "Add this year's special dates" not in home and "Your plan is ready." in home,
            failures,
        )

        async with db.tenant_session(tenant) as session:
            await SwitchRepository(session).set(tenant, "grow.calendar", on=False, by=user_id)
        paused = await shown(browser, f"{base}/calendar")
        _check(
            "Paused: the note, no plan promised, no Make it again; the plans stay",
            "Paused since" in paused
            and "FiveNeurals has paused the plans for this shop" in paused
            and "No plan while paused" in paused
            and "Plan ready" in paused
            and "Make it again" not in paused,
            failures,
        )
        paused_plan = await shown(browser, plan_url)
        _check(
            "Paused: the plan page says so and offers no Make it again",
            "FiveNeurals has paused the plans for this shop" in paused_plan
            and not await browser.evaluate("!!document.querySelector('[data-make-again]')"),
            failures,
        )

        links: dict[str, str] = {}
        for role in ("support", "developer"):
            person = ids.new_id(ids.USER)
            email = f"calendar-check-{role}-{person.lower()[-8:]}@example.com"
            async with db.identity_session() as session:
                await session.execute(users.insert().values(id=person, email=email))
            people.append(person)
            async with db.tenant_session(tenant) as session:
                await session.execute(
                    memberships.insert().values(
                        id=ids.new_id(ids.MEMBERSHIP), tenant_id=tenant, user_id=person, role=role
                    )
                )
            async with db.identity_session() as session:
                minted = await request_sign_in_link(session, email=email, console_base_url=console)
            links[role] = minted.url

        async with Chrome(find_chrome()) as support:
            await phone(support, False)
            await shown(support, links["support"], wait=4)
            page = await shown(support, f"{base}/calendar")
            names = await menu(support)
            _check(
                "Support: Marketing calendar in the menu, and the page opens",
                "Marketing calendar" in names and "Coming up" in page,
                failures,
            )
            page = await shown(support, plan_url)
            _check(
                "Support: a plan whole, without the link to the Owner's page (R99)",
                "8 shoppers asked for" in page
                and "See Shoppers asked for" not in page
                and "See Missing from your pages" in page,
                failures,
            )
        async with Chrome(find_chrome()) as developer:
            await phone(developer, False)
            await shown(developer, links["developer"], wait=4)
            page = await shown(developer, f"{base}/calendar")
            _check(
                "the Developer: no menu item, and You can't open this page",
                "Marketing calendar" not in await menu(developer)
                and "You can't open this page" in page.replace("\u2019", "'"),
                failures,
            )

        if seeded.get("tenant"):
            await shown(browser, f"{console}/console/{seeded['tenant']}")
            _check(
                "a shop without GROW does not list the Marketing calendar",
                "Marketing calendar" not in await menu(browser),
                failures,
            )
    finally:
        async with db.tenant_session(tenant) as session:
            await remove_tenant(session, tenant)
        if people:
            async with db.identity_session() as session:
                await session.execute(
                    delete(login_tokens).where(login_tokens.c.user_id.in_(people))
                )
                await session.execute(delete(users).where(users.c.id.in_(people)))


async def _check_links(
    browser: Chrome,
    console: str,
    api: str,
    db: Database,
    user_id: str,
    seeded: dict[str, str],
    failures: list[str],
) -> None:
    """Links that count clicks (ADR-0074, console.md §3.15, boards 80 to 83).

    In **a shop of its own** with NEURA-GROW, where this person is the Owner, so
    nothing real is touched: one plan with two products. Checked: a plan's posts,
    each with its product chooser and its link buttons (the email one, the
    banner none), on desktop and phone; a **real click** on *Copy Facebook
    link* with the clipboard read back (the link is made while the click waits,
    which is what Safari's rule is about); **a tap through ``/go/``** that is
    counted, and a link preview that is not; the plan showing the click and
    starting its chooser on the product last copied; *Make a link*; the Links
    page with both lists; *Remove* asking first; the menu; Support and the
    Developer each in a browser of their own. **No AI is called.** Everything
    made here is removed at the end.
    """
    from neura_agent_core.calendar import CalendarRepository, shop_today
    from neura_agent_core.calendar import Country as CalendarCountry
    from neura_agent_core.links import LinkRepository, link_clicks
    from neura_core.identity.schema import login_tokens, memberships, users
    from neura_core.tenancy import TenantRepository
    from neura_core.tenancy.removal import remove_tenant
    from neura_core.tenancy.switches import SwitchRepository

    tenant = ids.new_id(ids.TENANT)
    base = f"{console}/console/{tenant}"
    today = shop_today(CalendarCountry.SRI_LANKA, datetime.now(UTC))
    people: list[str] = []
    safari = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    answer = {
        "theme": "A console-check links week",
        "idea": "Two teas, a link for every post.",
        "products": ["cl-tea", "cl-cinnamon"],
        "act_on": [],
        "texts": {
            "teaser": "Something is coming. [your offer] soon.",
            "launch": "Here now: [your offer].",
            "last_chance": "Last 2 days for [your offer].",
            "email_subject": "Our links week",
            "email_body": "Hello,\n\nIt is here. [your offer].",
            "banner": "Links week: [your offer]",
        },
        "catalogue_cut": False,
    }

    async def phone(page: Chrome, on: bool) -> None:
        await page.call(
            "Emulation.setDeviceMetricsOverride",
            width=390 if on else 1280,
            height=844 if on else 900,
            deviceScaleFactor=1,
            mobile=on,
        )

    async def shown(page: Chrome, url: str, wait: float = 3.5) -> str:
        await page.goto(url)
        await asyncio.sleep(wait)
        return str(await page.evaluate("document.body.innerText"))

    async def fits(page: Chrome) -> bool:
        return bool(
            await page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        )

    async def click(selector: str, wait: float = 2.5) -> str:
        await browser.evaluate(f"document.querySelector('{selector}').click(), true")
        await asyncio.sleep(wait)
        return str(await browser.evaluate("document.body.innerText"))

    async def press(selector: str) -> None:
        """A person's click, the only kind Chrome lets write to the clipboard."""
        where = await browser.evaluate(
            f"(() => {{ const b = document.querySelector('{selector}');"
            " b.scrollIntoView({ block: 'center' }); const r = b.getBoundingClientRect();"
            " return [r.x + r.width / 2, r.y + r.height / 2]; })()"
        )
        for kind in ("mousePressed", "mouseReleased"):
            await browser.call(
                "Input.dispatchMouseEvent",
                type=kind,
                x=where[0],
                y=where[1],
                button="left",
                clickCount=1,
            )

    async def menu(page: Chrome) -> list[str]:
        return list(
            await page.evaluate(
                "[...document.querySelectorAll('nav[aria-label=Screens] a')]"
                ".map(a => a.innerText.trim().split('\\n')[0])"
            )
        )

    async def taps(code: str, agent: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=5) as client:
            return await client.get(
                f"{api}/go/{code}", headers={"User-Agent": agent}, follow_redirects=False
            )

    async def counted() -> int:
        async with db.tenant_session(tenant) as session:
            return int(
                await session.scalar(select(func.coalesce(func.sum(link_clicks.c.clicks), 0)))
            )

    try:
        async with db.tenant_session(tenant) as session:
            await TenantRepository(session).create(
                tenant_id=tenant,
                name=f"Links Check {tenant[-6:].lower()}",
                enabled_agents=["care", "grow"],
            )
            await session.execute(
                memberships.insert().values(
                    id=ids.new_id(ids.MEMBERSHIP), tenant_id=tenant, user_id=user_id, role="owner"
                )
            )
            for product_id, title, stocked in (
                ("cl-tea", "Console-check Links Tea", True),
                ("cl-cinnamon", "Console-check Links Cinnamon", True),
                ("cl-crackers", "Console-check Links Crackers", False),
            ):
                await session.execute(
                    synced_entities.insert().values(
                        tenant_id=tenant,
                        platform=SEEDED_PLATFORM,
                        entity_type="product",
                        external_id=product_id,
                        neura_id=f"nr_{product_id}",
                        fingerprint="c" * 32,
                        document={
                            "title": title,
                            "url": f"https://shop.example/{product_id}",
                            "variants": [{"external_id": f"{product_id}-v", "in_stock": stocked}],
                        },
                    )
                )
            repository = CalendarRepository(session)
            own = await repository.add_own(
                tenant,
                name="Console-check links sale",
                day=today + timedelta(days=12),
                every_year=False,
                by=user_id,
            )
            plan = await repository.store_plan(
                tenant,
                date_key=own.date_key,
                day=today + timedelta(days=12),
                name="Console-check links sale",
                answer=answer,
                prompt_revision="console-check",
                at=datetime.now(UTC),
            )
        plan_url = f"{base}/calendar/{plan.id}"

        for on in (False, True):
            size = "phone" if on else "desktop"
            await phone(browser, on)
            page = await shown(browser, plan_url)
            _check(
                f"a plan: Each post has its own links, the Instagram line ({size})",
                "Each post has its own links" in page
                and "put the Instagram link in your bio or a story" in page.replace("\u2019", "'"),
                failures,
            )
            _check(
                f"three link buttons under each post, one under the email, none on the banner ({size})",
                bool(
                    await browser.evaluate(
                        "['teaser','launch','last_chance'].every(p =>"
                        ' document.querySelectorAll(`[data-post-links="${p}"] [data-copy-link]`)'
                        ".length === 3)"
                        " && document.querySelectorAll('[data-post-links=\"email\"] [data-copy-link]')"
                        ".length === 1"
                        " && !document.querySelector('[data-draft=\"banner\"] [data-post-links]')"
                        " && !!document.querySelector('[data-banner-no-link]')"
                    )
                )
                and "Copy Facebook link" in page
                and "Copy the link" in page
                and "whoever sees your banner is already in your shop" in page,
                failures,
            )
            _check(
                f"no clicks yet, the dashboard made the links, and it fits ({size})",
                "No clicks yet." in page
                and "The links are made by your dashboard, not by AI" in page
                and await fits(browser),
                failures,
            )
        await phone(browser, False)

        await shown(browser, plan_url)
        # The teaser's link opens the second product: chosen first, then copied.
        await browser.evaluate(
            """(() => {
              const s = document.querySelector('[data-post-links="teaser"] [data-link-product]');
              const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
              set.call(s, 'cl-cinnamon');
              s.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            })()"""
        )
        await browser.call(
            "Browser.grantPermissions",
            permissions=["clipboardReadWrite", "clipboardSanitizedWrite"],
            origin=console,
        )
        await browser.call("Emulation.setFocusEmulationEnabled", enabled=True)
        await press('[data-post-links="teaser"] [data-copy-link="facebook"]')
        await asyncio.sleep(2)
        label = await browser.evaluate(
            'document.querySelector(\'[data-post-links="teaser"] [data-copy-link="facebook"]\')'
            ".innerText"
        )
        line = str(
            await browser.evaluate(
                "document.querySelector('[data-post-links=\"teaser\"] [data-link-copied]')"
                "?.innerText ?? ''"
            )
        )
        pasted = str(
            (
                await browser.call(
                    "Runtime.evaluate",
                    expression="navigator.clipboard.readText()",
                    awaitPromise=True,
                    returnByValue=True,
                )
            )
            .get("result", {})
            .get("value")
            or ""
        )
        await browser.call("Emulation.setFocusEmulationEnabled", enabled=False)
        code = pasted.rstrip("/").rsplit("/", 1)[-1]
        _check(
            "Copy Facebook link: a real click puts the link on the clipboard, Copied",
            "Copied" in str(label)
            and re.fullmatch(r"https?://\S+/[a-z2-9]{6}", pasted) is not None,
            failures,
        )
        _check(
            "the green line names the link and the product it opens",
            line.startswith("Copied ")
            and code in line
            and "It opens Console-check Links Cinnamon on your shop." in line,
            failures,
        )

        person = await taps(code, safari)
        preview = await taps(code, "facebookexternalhit/1.1")
        _check(
            "a tap goes to the product with the labels, 302, not stored",
            person.status_code == 302
            and person.headers.get("location", "").startswith(
                "https://shop.example/cl-cinnamon?utm_source=facebook&utm_medium=social"
            )
            and person.headers.get("cache-control") == "no-store"
            and "set-cookie" not in person.headers,
            failures,
        )
        _check(
            "a person's tap is counted, a link preview's is not",
            preview.status_code == 302 and await counted() == 1,
            failures,
        )
        gone = await taps("zzzzzz", safari)
        _check(
            "a code nobody made: This link is no longer active.",
            gone.status_code == 404 and "This link is no longer active." in gone.text,
            failures,
        )

        page = await shown(browser, plan_url)
        _check(
            "the plan shows the click, and the chooser starts on the product copied",
            "Clicks so far: Facebook 1"
            in str(
                await browser.evaluate(
                    "document.querySelector('[data-post-links=\"teaser\"] [data-link-clicks]')"
                    ".innerText"
                )
            )
            and await browser.evaluate(
                "document.querySelector('[data-post-links=\"teaser\"] [data-link-product]').value"
            )
            == "cl-cinnamon"
            and await browser.evaluate(
                "document.querySelector('[data-post-links=\"launch\"] [data-link-product]').value"
            )
            == "cl-tea",
            failures,
        )

        # D20 (R124 to R126): Change products, without asking the AI.
        _check(
            "a plan with nothing that fits says so, not that shoppers asked nothing (G125)",
            "Nothing your shoppers asked fits this date" in page,
            failures,
        )
        panel = await click("[data-change-products]", wait=3)
        _check(
            "Change products: the plan's two, and a sold-out one to add, said so",
            "Products for this plan" in panel
            and "Choose 1 to 3." in panel
            and bool(
                await browser.evaluate(
                    "document.querySelectorAll('[data-chosen-product]').length === 2"
                    " && [...document.querySelectorAll('[data-add-product-choice] option')]"
                    ".some(o => o.textContent.includes('Crackers (sold out now)'))"
                )
            ),
            failures,
        )
        await click("[data-add-product]", wait=1)
        full = str(await browser.evaluate("document.body.innerText"))
        _check(
            "added: three products, Sold out now on the new one, and no more can be added",
            bool(
                await browser.evaluate(
                    "document.querySelectorAll('[data-chosen-product]').length === 3"
                    ' && !!document.querySelector(\'[data-chosen-product="cl-crackers"]'
                    " [data-sold-out-now]')"
                    " && !document.querySelector('[data-add-product]')"
                )
            )
            and "A plan has at most 3 products." in full,
            failures,
        )
        await click("[data-remove-product]", wait=1)
        _check(
            "removed: two left",
            bool(
                await browser.evaluate(
                    "document.querySelectorAll('[data-chosen-product]').length === 2"
                )
            ),
            failures,
        )
        async with db.tenant_session(tenant) as session:
            await SwitchRepository(session).set(tenant, "grow.calendar", on=False, by=user_id)
        refused = await click("[data-write-again]", wait=3)
        async with db.tenant_session(tenant) as session:
            kept = await CalendarRepository(session).plan(tenant, plan.id)
            await SwitchRepository(session).set(tenant, "grow.calendar", on=True, by=user_id)
        _check(
            "Write the plan again while paused: refused, said, and nothing is kept",
            "FiveNeurals has paused the plans for this shop." in refused
            and kept is not None
            and kept.owner_products is None
            and kept.requested_at is None,
            failures,
        )
        page = await shown(browser, f"{base}/links/new", wait=4)
        _check(
            "Make a link: product, where you'll post it, name",
            "Make a link" in page
            and "Where you'll post it" in page.replace("\u2019", "'")
            and "Somewhere else" in page
            and "Shoppers don't see it." in page.replace("\u2019", "'")
            and "A link can only open your own shop's product pages."
            in page.replace("\u2019", "'"),
            failures,
        )
        await browser.evaluate(
            """(() => {
              const el = document.querySelector('[data-link-name]');
              const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
              set.call(el, 'Tuesday post');
              el.dispatchEvent(new Event('input', { bubbles: true }));
              return true;
            })()"""
        )
        await click('[data-link-place="whatsapp"]', wait=0.5)
        made = await click("[data-make-the-link]", wait=3)
        _check(
            "Make the link: Your link, its address and Copy",
            "Your link" in made
            and bool(re.search(r"/[a-z2-9]{6}\b", made))
            and "on your shop. Its clicks show on Links." in made,
            failures,
        )

        for on in (False, True):
            size = "phone" if on else "desktop"
            await phone(browser, on)
            page = await shown(browser, f"{base}/links")
            _check(
                f"Links: Your links, with its product, place and clicks ({size})",
                "Your links" in page
                and "Tuesday post" in page
                and "WhatsApp" in page
                and "0 clicks" in page
                and "Make a link" in page,
                failures,
            )
            _check(
                f"Links: the campaign, its post's click, See the plan ({size})",
                "From your campaigns" in page
                and f"Console-check links sale {plan.day.year}" in page
                and "Facebook 1" in page
                and bool(
                    await browser.evaluate(
                        f"!!document.querySelector('a[href=\"/console/{tenant}/calendar/{plan.id}\"]')"
                    )
                ),
                failures,
            )
            _check(
                f"Links: a click is a tap, never who clicked, and it fits ({size})",
                "We count clicks only, never who clicked." in page
                and "one person tapping twice counts twice" in page
                and await fits(browser),
                failures,
            )
        await phone(browser, False)

        names = await menu(browser)
        _check(
            "the menu lists Links, after Marketing calendar",
            "Links" in names and names.index("Links") == names.index("Marketing calendar") + 1,
            failures,
        )

        await shown(browser, f"{base}/links")
        asking = await click("[data-remove-link]", wait=1)
        _check(
            "Remove asks first: its clicks are deleted, the link keeps opening its product",
            "Remove this link? Its clicks are deleted. The link keeps opening its product."
            in asking,
            failures,
        )
        await click("[data-confirm-remove]", wait=3)
        page = await shown(browser, f"{base}/links")
        async with db.tenant_session(tenant) as session:
            left = [link.name for link in await LinkRepository(session).listed(tenant)]
        _check(
            "Removed: No links yet, and the campaign's link stays",
            "No links yet." in page and "Tuesday post" not in left and None in left,
            failures,
        )

        signs: dict[str, str] = {}
        for role in ("support", "developer"):
            person_id = ids.new_id(ids.USER)
            email = f"links-check-{role}-{person_id.lower()[-8:]}@example.com"
            async with db.identity_session() as session:
                await session.execute(users.insert().values(id=person_id, email=email))
            people.append(person_id)
            async with db.tenant_session(tenant) as session:
                await session.execute(
                    memberships.insert().values(
                        id=ids.new_id(ids.MEMBERSHIP),
                        tenant_id=tenant,
                        user_id=person_id,
                        role=role,
                    )
                )
            async with db.identity_session() as session:
                minted = await request_sign_in_link(session, email=email, console_base_url=console)
            signs[role] = minted.url

        async with Chrome(find_chrome()) as support:
            await phone(support, False)
            await shown(support, signs["support"], wait=4)
            page = await shown(support, f"{base}/links")
            plan_page = await shown(support, plan_url)
            _check(
                "Support: Links in the menu, the page and the plan's link buttons",
                "Links" in await menu(support)
                and "Your links" in page
                and "Copy Facebook link" in plan_page,
                failures,
            )
        async with Chrome(find_chrome()) as developer:
            await phone(developer, False)
            await shown(developer, signs["developer"], wait=4)
            page = await shown(developer, f"{base}/links")
            _check(
                "the Developer: no menu item, and You can't open this page",
                "Links" not in await menu(developer)
                and "You can't open this page" in page.replace("\u2019", "'"),
                failures,
            )

        if seeded.get("tenant"):
            await shown(browser, f"{console}/console/{seeded['tenant']}")
            _check(
                "a shop without GROW does not list Links",
                "Links" not in await menu(browser),
                failures,
            )
    finally:
        async with db.tenant_session(tenant) as session:
            await remove_tenant(session, tenant)
        if people:
            async with db.identity_session() as session:
                await session.execute(
                    delete(login_tokens).where(login_tokens.c.user_id.in_(people))
                )
                await session.execute(delete(users).where(users.c.id.in_(people)))


def _check(what: str, passed: bool, failures: list[str]) -> None:
    print(f"    {GREEN}✔{OFF} {what}" if passed else f"    {RED}✘{OFF} {what}")
    if not passed:
        failures.append(what)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
