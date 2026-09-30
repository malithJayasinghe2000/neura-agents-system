#!/usr/bin/env python3
"""The public website, built and opened in a real browser. ADR-0051.

    make web-check

Free — no models, no API, no database. Builds ``apps/neura-web`` to static
files, serves them on a local port, and checks the rules the owner set for the
public pages — each one a claim about what a *built page* contains, which is why
this reads the HTML the build wrote and the page Chrome drew, not the source:

* **no test-shop data** — made-up examples only (the owner's rule);
* **no secret** — a key on a public page is a published key;
* **no commerce platform name** (AGENTS.md Rule 1);
* **no request to anywhere else** — no analytics, no font CDN (ADR-0051 §3);
* **every page draws, and nothing scrolls sideways on a phone.**

It ends by **listing every placeholder still on the pages** (``[CONTACT
ADDRESS]`` …). That is not a failure — they are undecided on purpose — but a
deployment must not happen while the list is non-empty, and a list printed
every run cannot be forgotten.

``--shots DIR`` also saves a screenshot of every page, desktop and phone.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import functools
import http.server
import re
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from widget_check import Chrome, find_chrome

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "apps" / "neura-web"
OUT = APP / "out"

PAGES = ("/", "/sell/", "/docs/", "/docs/owners/", "/docs/developers/")

GREEN, RED, DIM, BOLD, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"

PLATFORMS = ("bagisto", "shopify", "woocommerce", "magento")

#: Strings that only the test shop could have put on a page. The owner found
#: "order 86" and "Cashmere jumper" on early mockups; the seeder's own product
#: names are added below when the test shop is on this machine.
TEST_SHOP = ("dispatch test shop", "tn_01", "bagisto.test", "order 86", "cashmere")
SEEDER = Path.home() / "Developer" / "bagisto" / "database" / "seeders" / "NeuraDemoDataSeeder.php"

#: A real key has a body after its prefix; the pages show `fn_pk_…` and `fn_sk_…` only.
SECRET = re.compile(r"fn_(?:sk|pk)_(?:live_|test_)?[A-Za-z0-9]{8,}")
EXTERNAL = re.compile(r"""<(?:script|link|img|iframe)\b[^>]*\b(?:src|href)=["']https?://""", re.I)
PLACEHOLDER = re.compile(r"\[[A-Z][A-Z ]{3,}\]")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    """Serves `out/` without printing a line per request."""

    def log_message(self, format: str, *args: object) -> None:
        pass


def _check(label: str, ok: bool, failures: list[str], detail: str = "") -> None:
    print(f"    {GREEN}✔{OFF} {label}" if ok else f"    {RED}✘{OFF} {label}")
    if not ok:
        failures.append(label)
        if detail:
            print(f"      {DIM}{detail}{OFF}")


def _seeded_names() -> tuple[str, ...]:
    if not SEEDER.exists():
        return ()
    return tuple(
        name.lower() for name in re.findall(r"'name'\s*=>\s*'([^']{6,})'", SEEDER.read_text())
    )


def _build() -> None:
    print(f"\n  {BOLD}building apps/neura-web{OFF}")
    for command in (["npm", "run", "lint"], ["npx", "tsc", "--noEmit"], ["npm", "run", "build"]):
        # Fixed argv, no shell, nothing from outside this file.
        result = subprocess.run(command, cwd=APP, capture_output=True, text=True)  # noqa: S603
        if result.returncode != 0:
            print(result.stdout[-3000:], result.stderr[-3000:])
            raise SystemExit(f"  {RED}✘ {' '.join(command)} failed{OFF}")
        print(f"    {GREEN}✔{OFF} {' '.join(command)}")


def _html_of(page: str) -> str:
    path = OUT / page.strip("/") / "index.html" if page != "/" else OUT / "index.html"
    return path.read_text()


def _static_checks(failures: list[str]) -> None:
    print(f"\n  {BOLD}what the built pages contain{OFF}")
    names = _seeded_names()
    for page in PAGES:
        html = _html_of(page)
        text = re.sub(r"<[^>]+>", " ", html).lower()
        leaked = [s for s in TEST_SHOP + names if s in text]
        _check(f"{page}: no test-shop data", not leaked, failures, ", ".join(leaked[:5]))
        _check(f"{page}: no platform named", not any(p in text for p in PLATFORMS), failures)
        _check(f"{page}: no secret key", not SECRET.search(html), failures)
        _check(f"{page}: no request to another site", not EXTERNAL.search(html), failures)
    spec = (OUT / "spec" / "openapi.json").read_text().lower()
    _check(
        "the OpenAPI file is published, and names no platform",
        not any(p in spec for p in PLATFORMS),
        failures,
    )


async def _browser_checks(base: str, shots: Path | None, failures: list[str]) -> None:
    print(f"\n  {BOLD}the pages in a real browser{OFF}")
    async with Chrome(find_chrome()) as browser:
        for name, width, height, mobile in (
            ("desktop", 1440, 900, False),
            ("phone", 390, 844, True),
        ):
            await browser.call(
                "Emulation.setDeviceMetricsOverride",
                width=width,
                height=height,
                deviceScaleFactor=1,
                mobile=mobile,
            )
            for page in PAGES:
                await browser.goto(base + page)
                await asyncio.sleep(1.5)
                heading = await browser.evaluate("(document.querySelector('h1')||{}).innerText||''")
                _check(f"{name} {page}: draws its heading", bool(heading.strip()), failures)
                if mobile:
                    wide = await browser.evaluate(
                        "document.documentElement.scrollWidth > window.innerWidth + 1"
                    )
                    _check(f"{name} {page}: nothing scrolls sideways", not wide, failures)
                if shots:
                    full = await browser.evaluate("document.documentElement.scrollHeight")
                    await browser.call(
                        "Emulation.setDeviceMetricsOverride",
                        width=width,
                        height=int(full),
                        deviceScaleFactor=1,
                        mobile=mobile,
                    )
                    await asyncio.sleep(0.5)
                    shot = await browser.call("Page.captureScreenshot", format="png")
                    data = shot.get("data") or shot.get("result", {}).get("data")
                    slug = page.strip("/").replace("/", "-") or "care"
                    (shots / f"{name}-{slug}.png").write_bytes(base64.b64decode(data))
                    await browser.call(
                        "Emulation.setDeviceMetricsOverride",
                        width=width,
                        height=height,
                        deviceScaleFactor=1,
                        mobile=mobile,
                    )


def _placeholders() -> None:
    found: set[str] = set()
    for page in PAGES:
        found.update(PLACEHOLDER.findall(re.sub(r"<[^>]+>", " ", _html_of(page))))
    print(f"\n  {BOLD}still undecided on the pages{OFF} {DIM}(lib/site.ts — not a failure){OFF}")
    for item in sorted(found) or ["none"]:
        print(f"    · {item}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", type=Path, help="save a screenshot of every page here")
    args = parser.parse_args()
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)

    _build()
    failures: list[str] = []
    _static_checks(failures)

    handler = functools.partial(_Quiet, directory=str(OUT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        asyncio.run(_browser_checks(f"http://127.0.0.1:{server.server_port}", args.shots, failures))
    finally:
        server.shutdown()

    _placeholders()
    if failures:
        print(f"\n  {RED}{len(failures)} failed.{OFF}\n")
        return 1
    print(f"\n  {GREEN}The public website builds and keeps its rules.{OFF}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
