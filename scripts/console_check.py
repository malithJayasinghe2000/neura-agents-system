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
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from sqlalchemy import delete
from widget_check import Chrome, find_chrome

from neura_agent_core.conversations import (
    ConversationRepository,
    conversation_messages,
    conversations,
)
from neura_agent_core.rag.schema import document_chunks
from neura_agent_core.shadow import ShadowRepository, ShadowTurn, shadow_turns
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, memberships_for, request_sign_in_link

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

        if held:
            seeded = await _seed_review(db, held[0].tenant_id)
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
            _check("the console greets the signed-in person", "Welcome back" in body, failures)

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
                print(f"\n  {BOLD}review — grading what the agent would have said{OFF}")
                await _check_review(browser, console, seeded, failures)

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
            await _unseed_review(db, seeded)
        await db.dispose()

    print()
    if failures:
        print(f"  {RED}{len(failures)} check(s) failed.{OFF}\n")
        return 1
    print(f"  {GREEN}Sign-in and review work in a real browser.{OFF}")
    print(f"  {DIM}Evidence about THIS build and THIS browser, and nothing more.{OFF}\n")
    return 0


#: What the seeded shopper asks. Distinctive enough that finding it on the page
#: cannot be a coincidence, and about a policy so that the cited evidence is a
#: document rather than a tool.
SEEDED_QUESTION = "can I return these boots after 20 days?"

#: The merchant's own words, which is what "show the evidence" means. The check
#: below fails unless this exact sentence is rendered on the review screen.
SEEDED_POLICY = "Returns are accepted within 30 days of delivery, unworn."


async def _check_review(
    browser: Chrome, console: str, seeded: dict[str, str], failures: list[str]
) -> None:
    """The three rules of `console.md §3.2`, asserted against a rendered page.

    Every one of them is a claim about what a *grader sees*. The API returning
    the right JSON is necessary and is not the claim — a screen that fetched the
    evidence and never rendered it would satisfy every pytest assertion in
    `tests/integration/test_console_review.py` and still be the wrong screen.
    """
    await browser.goto(f"{console}/console/{seeded['tenant']}/review")
    await asyncio.sleep(3)

    page = await browser.evaluate("document.body.innerText")

    _check("the queue lists what the agent drafted", SEEDED_QUESTION in page, failures)

    # Rule 1. A grader who cannot see what the agent worked from is grading
    # fluency (open question E7).
    _check("the evidence is on the page, not behind a click", SEEDED_POLICY in page, failures)

    # Rule 2, half one: every row says the shopper never saw it.
    _check("a withheld turn says so", "Withheld" in page, failures)

    # Rule 2, half two, and the one a hurried build breaks: the turn the agent
    # *declined* is in the queue and explains itself instead of rendering an
    # empty card (ADR-0020).
    _check(
        "the turn the agent declined is in the queue and explains itself",
        "handed this to a person" in page,
        failures,
    )

    # Rule 4. Cost is zero for a local model *and* for an unpriced cloud model,
    # so "$0.00" on this screen would be a measurement in one case and a gap in
    # the other (CLAUDE.md §4).
    _check("no unmeasured cost is printed as a figure", "$0" not in page, failures)

    # Rule 4 again, on the scorecard: an unreviewed queue is not a queue that
    # failed review, so there is no percentage until somebody has graded.
    _check(
        "an ungraded queue reports no agreement figure",
        "%" not in page and "graded yet" in page,
        failures,
    )

    _check("no API key reached the review screen", "fn_sk_" not in page, failures)

    # And the write path, through the real button rather than through fetch:
    # a screen whose grade does not persist is a screen that produces no
    # graded turns, which is the entire reason this one was built first (E1).
    clicked = await browser.evaluate(_CLICK_VERDICT)
    _check("the queue offers a verdict to click", bool(clicked), failures)

    if clicked:
        await asyncio.sleep(3)
        await browser.goto(f"{console}/console/{seeded['tenant']}/review?show=graded")
        await asyncio.sleep(3)
        after = await browser.evaluate("document.body.innerText")
        _check(
            "a verdict given in the browser is still there after a reload",
            "Graded" in after and SEEDED_QUESTION in after,
            failures,
        )


#: Click the first "I'd have sent this" button on the page.
#:
#: By its text, because that text is what a merchant reads — a `data-testid`
#: would let the label change to something wrong while this stayed green. The
#: apostrophe is matched loosely for the reason the sign-in check gives: React
#: may emit either form.
_CLICK_VERDICT = """
(() => {
  const button = [...document.querySelectorAll('button')]
    .find((b) => /have sent this/i.test(b.textContent || ''));
  if (!button) return false;
  button.click();
  return true;
})()
"""


async def _seed_review(db: Database, tenant_id: str) -> dict[str, str]:
    """Two shadowed turns and one policy for them to cite.

    Two, because one would not exercise the rule that matters: an **answered**
    turn proves the evidence is rendered, and a **declined** one proves the queue
    does not quietly omit the turns the agent refused. Written through the same
    repositories the turn service uses, so this is the shape a real turn records
    and not an approximation of it.
    """
    made = {
        "tenant": tenant_id,
        "conversation": ids.new_id(ids.CONVERSATION),
        "chunk": ids.new_id(ids.CHUNK),
    }

    async with db.tenant_session(tenant_id) as session:
        conversations = ConversationRepository(session)
        await conversations.start(tenant_id, conversation_id=made["conversation"], agent_key="care")
        message_id = await conversations.append_shopper_message(
            tenant_id, made["conversation"], shopper=SEEDED_QUESTION
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
                draft="Yes — unworn boots can be returned within 30 days of delivery.",
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


async def _unseed_review(db: Database, seeded: dict[str, str]) -> None:
    """Remove exactly the rows above, by id.

    By id and never by tenant: this runs against a developer's own database,
    where the tenant it just wrote to may be a real shop with real traffic in it.
    A cleanup that deleted "this tenant's shadow turns" would be a data-loss bug
    living inside a test.
    """
    async with db.tenant_session(seeded["tenant"]) as session:
        await session.execute(
            delete(shadow_turns).where(
                shadow_turns.c.id.in_([seeded["answered"], seeded["declined"]])
            )
        )
        await session.execute(
            delete(document_chunks).where(document_chunks.c.id == seeded["chunk"])
        )
        await session.execute(
            delete(conversation_messages).where(
                conversation_messages.c.conversation_id == seeded["conversation"]
            )
        )
        await session.execute(
            delete(conversations).where(conversations.c.id == seeded["conversation"])
        )


def _check(what: str, passed: bool, failures: list[str]) -> None:
    print(f"    {GREEN}✔{OFF} {what}" if passed else f"    {RED}✘{OFF} {what}")
    if not passed:
        failures.append(what)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
