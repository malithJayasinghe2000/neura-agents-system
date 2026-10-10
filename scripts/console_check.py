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
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from sqlalchemy import delete, func, select
from widget_check import Chrome, find_chrome

from neura_agent_core.conversations import (
    ConversationRepository,
    ConversationState,
    conversation_messages,
    conversations,
)
from neura_agent_core.rag.schema import document_chunks
from neura_agent_core.shadow import ShadowRepository, ShadowTurn, shadow_turns
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
                else:
                    print(f"  {DIM}no shop with SELL — the Sold out checks are skipped{OFF}")

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
            sentence == "I can't help with this here. Please contact our store: "
            "hello@yourshop.example, +94 11 234 5678.",
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
        "its menu lists neither Suggestions nor Sold out",
        "Home" in menu and "Suggestions" not in menu and "Sold out" not in menu,
        failures,
    )
    home = await browser.evaluate("document.body.innerText")
    _check("its Home shows no Suggestions or Sold out card", "Open Sold out" not in home, failures)

    await browser.goto(f"{base}/sold-out")
    await asyncio.sleep(3)
    page = await browser.evaluate("document.body.innerText")
    _check(
        "opened by its address, Sold out says it is not part of this shop's plan",
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
    _check("its Help does not mention Sold out", "Sold out" not in help_page, failures)


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
        "so you know what to restock" in page,
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
        )
        for product, title in (
            (SEEDED_SOLD_OUT_ID, SEEDED_SOLD_OUT_TITLE),
            (SEEDED_IN_STOCK_ID, SEEDED_IN_STOCK_TITLE),
        ):
            await session.execute(
                synced_entities.insert().values(
                    tenant_id=tenant_id,
                    platform=SEEDED_PLATFORM,
                    entity_type="product",
                    external_id=product,
                    neura_id=ids.new_id(ids.NEURA_ENTITY),
                    fingerprint="console-check",
                    document={"title": title},
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
        threads = [seeded["conversation"], seeded["answered_conversation"]]
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


def _check(what: str, passed: bool, failures: list[str]) -> None:
    print(f"    {GREEN}✔{OFF} {what}" if passed else f"    {RED}✘{OFF} {what}")
    if not passed:
        failures.append(what)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
