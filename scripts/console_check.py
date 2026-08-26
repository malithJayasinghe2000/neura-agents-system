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

This is the console's half of the deterministic bar in `console.md §6`, and it
follows `make widget-check` deliberately: the same hand-rolled CDP driver, the
same argument. *A control nothing runs is not a control that works.*
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from widget_check import Chrome, find_chrome

from neura_core import Database, get_settings, load_env
from neura_core.identity import COOKIE_NAME, request_sign_in_link

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
    try:
        async with db.identity_session() as session:
            minted = await request_sign_in_link(session, email=email, console_base_url=console)
        if not minted.minted:
            print(f"  {RED}✘ no account for {email}{OFF}")
            print(f"  {DIM}Create one: make user-new EMAIL={email} TENANT=tn_...{OFF}\n")
            return 1
    finally:
        await db.dispose()

    failures: list[str] = []
    chrome = find_chrome()

    async with Chrome(chrome) as browser:
        # 1. The signed-out screen.
        await browser.goto(console)
        await asyncio.sleep(2)
        heading = await browser.evaluate("document.body.innerText")
        _check("the sign-in screen offers a link, not a password", "Sign in" in heading, failures)
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

        # 5. The link is single use. Reloading it must not sign anyone in again.
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

    print()
    if failures:
        print(f"  {RED}{len(failures)} check(s) failed.{OFF}\n")
        return 1
    print(f"  {GREEN}Sign-in works in a real browser.{OFF}")
    print(f"  {DIM}Evidence about THIS build and THIS browser, and nothing more.{OFF}\n")
    return 0


def _check(what: str, passed: bool, failures: list[str]) -> None:
    print(f"    {GREEN}✔{OFF} {what}" if passed else f"    {RED}✘{OFF} {what}")
    if not passed:
        failures.append(what)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
