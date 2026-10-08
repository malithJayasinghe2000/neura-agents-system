"""Does the paired-suggestion block actually work in a browser?

`pairs.js` shipped with its pure half unit-tested under `node --test` and its
hosting asserted from Python — and **none of that runs the browser half**. The
Shadow DOM, the fetch, the `textContent` rule that makes an arbitrary merchant's
product title safe to display: all of it existed only as text that parsed. This
is `widget_check.py`'s argument applied to ADR-0040's surface, and it is the same
argument every time — **a control nobody has run is not a control that works, it
is a control nobody has run.**

Real Google Chrome, headless, over the DevTools Protocol. No npm, no Playwright:
the driver is imported from `widget_check.py` rather than written twice.

    make pairs-check            # stub server — NO MODELS, no shop, no cost
    make pairs-check LIVE=1 URL=http://localhost:8010 \\
         SHOP=http://bagisto.test/neura/v1 TOKEN=... PRODUCTS=1315

**Stub mode is the important one and it is free.** It serves the real `pairs.js`
next to a scripted endpoint, which is the only way to drive the cases that matter
and are awkward to produce on demand — an empty response, a hostile product
title, a `javascript:` URL in a product link.

**Live mode proves something stub mode structurally cannot: the page is on a
different origin from the API.** A merchant's cart page always is. So the
harness is served from its own port, the key is origin-locked to it, and the
block's fetch crosses origins for real — exercising the per-key CORS decision
(`middleware/cors.py`) and the key's own origin lock together.

Exits non-zero on the first failed scenario. A scenario whose browser never
answered is reported as **not measured**, never as a pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

sys.path.insert(0, str(Path(__file__).resolve().parent))

from widget_check import Chrome, find_chrome, free_port

#: The stub routes on the key because that is the one value the element sends
#: which this file chooses. Split on the whole prefix — see `suggestions`.
KEY_PREFIX = "fn_pk_stub_"

ROOT = Path(__file__).resolve().parents[1]
PAIRS_JS = ROOT / "apps/neura-api/src/neura_api/widget/pairs.js"

#: What the block rendered, read out of the Shadow root.
#:
#: `img` and `a` are counted rather than inspected for content, because the two
#: things worth proving are *how many elements exist* — a title that became
#: markup would create one — and *what a browser was handed to resolve*.
READ = """
(() => {
  const el = document.querySelector('neura-pairs');
  const root = el && el.shadowRoot;
  if (!root) return JSON.stringify({ ready: false });
  const section = root.querySelector('.neura-pairs');
  const heading = section && section.querySelector('h2');
  return JSON.stringify({
    ready: true,
    rendered: !!section,
    heading: heading ? heading.textContent : '',
    titles: Array.from(root.querySelectorAll('.t')).map(n => n.textContent),
    prices: Array.from(root.querySelectorAll('.p')).map(n => n.textContent),
    hrefs: Array.from(root.querySelectorAll('a')).map(a => a.getAttribute('href')),
    images: root.querySelectorAll('img').length,
    scripts: root.querySelectorAll('script').length,
  });
})()
"""

HARNESS = """<!doctype html>
<html><head><meta charset="utf-8"><title>pairs harness</title></head>
<body>
<script src="{base}/v1/widget/pairs.js"></script>
<neura-pairs data-neura-key="{key}" data-products="{products}"></neura-pairs>
</body></html>
"""


@dataclass(frozen=True, slots=True)
class Result:
    scenario: str
    ok: bool
    detail: str
    measured: bool = True


#: Each scripted reply, and what it is there to prove. The hostile strings are
#: the point of the file: they are what a merchant's own catalogue could contain
#: — `guard/injection.py` records the shape as live in the wild — and the claim
#: being tested is that no string in a product can become code.
SCRIPTS: dict[str, dict[str, Any]] = {
    "ordinary": {
        "heading": "Goes well with your Lightweight Rain Shell",
        "paired_with": {"id": "1315", "title": "Lightweight Rain Shell"},
        "suggestions": [
            {
                "id": "1332",
                "title": "Waterproof Hiking Shoe",
                "price": "132.00",
                "currency": "USD",
                "in_stock": "true",
                "url": "https://shop.example.com/p/1332",
            },
            {
                "id": "1305",
                "title": "Linen Drawstring Trousers",
                "price": "44.00",
                "currency": "USD",
                "in_stock": "true",
            },
        ],
    },
    "empty": {"heading": "", "paired_with": None, "suggestions": []},
    "hostile_title": {
        "heading": "Goes well with your Rain Shell",
        "paired_with": {"id": "1315", "title": "Rain Shell"},
        "suggestions": [
            {
                "id": "x1",
                "title": "<img src=x onerror=\"document.title='pwned'\">",
                "in_stock": "true",
            },
            {
                "id": "x2",
                "title": "<script>document.title='pwned'</script>",
                "in_stock": "true",
            },
        ],
    },
    "hostile_url": {
        "heading": "Goes well with your Rain Shell",
        "paired_with": {"id": "1315", "title": "Rain Shell"},
        "suggestions": [
            {
                "id": "x3",
                "title": "A product with a hostile link",
                "in_stock": "true",
                "url": "javascript:document.title='pwned'",
                "image": "data:text/html,<script>document.title='pwned'</script>",
            }
        ],
    },
    "no_heading": {
        # A server that sent products and no heading. §3 says the block must not
        # render, because an unattributed "goes well with" names nothing.
        "heading": "",
        "paired_with": None,
        "suggestions": [{"id": "x4", "title": "An unattributed product", "in_stock": "true"}],
    },
}


def build_stub() -> FastAPI:
    """The real `pairs.js`, next to a scripted endpoint. No database, no shop."""
    app = FastAPI()

    @app.get("/v1/widget/pairs.js")
    async def asset() -> Response:
        return Response(
            content=PAIRS_JS.read_text(encoding="utf-8"),
            media_type="application/javascript; charset=utf-8",
        )

    @app.get("/harness")
    async def harness(script: str = "ordinary") -> HTMLResponse:
        return HTMLResponse(HARNESS.format(base="", key=f"{KEY_PREFIX}{script}", products="1315"))

    @app.post("/v1/sell/suggestions")
    async def suggestions(request: Request) -> JSONResponse:
        # The script is carried on the key, because the key is the one thing the
        # element sends that this stub chooses. Split on the whole prefix, not on
        # the last underscore: script names contain underscores, and splitting on
        # one silently served `ordinary` to every hostile scenario — which read
        # as three passing safety checks that had never run.
        key = request.headers.get("authorization", "")
        name = key.split(KEY_PREFIX, 1)[-1].strip() if KEY_PREFIX in key else "ordinary"
        return JSONResponse(SCRIPTS.get(name, SCRIPTS["ordinary"]))

    return app


async def serve(app: FastAPI, port: int) -> Any:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # uvicorn exposes `started` as a plain flag rather than an event, so this
    # polls it. Bounded, because a server that never starts must fail the run
    # rather than hang it.
    for _ in range(200):
        if server.started:
            return server, task
        await asyncio.sleep(0.05)
    raise SystemExit("the harness server did not start")


async def read_block(chrome: Chrome, url: str) -> dict[str, Any]:
    await chrome.goto(url)
    # The block fetches on connect; give the round trip room on a cold profile.
    for _ in range(20):
        state = dict(json.loads(await chrome.evaluate(READ)))
        if state.get("ready") and (state.get("rendered") or state.get("titles")):
            return state
        await asyncio.sleep(0.25)
    return dict(json.loads(await chrome.evaluate(READ)))


async def title_of(chrome: Chrome) -> str:
    return str(await chrome.evaluate("document.title"))


async def run_stub(chrome_binary: str) -> list[Result]:
    port = free_port()
    server, task = await serve(build_stub(), port)
    base = f"http://127.0.0.1:{port}"
    results: list[Result] = []

    try:
        async with Chrome(chrome_binary) as chrome:
            state = await read_block(chrome, f"{base}/harness?script=ordinary")
            if not state.get("ready"):
                return [
                    Result(
                        "the element upgrades and attaches a Shadow root",
                        False,
                        "<neura-pairs> never got a shadowRoot — the custom element did not define",
                        measured=False,
                    )
                ]

            results.append(
                Result(
                    "a block renders in a real Shadow root",
                    bool(state["rendered"]) and len(state["titles"]) == 2,
                    f"heading {state['heading']!r}, {len(state['titles'])} cards: {state['titles']}",
                )
            )
            results.append(
                Result(
                    "the heading is the server's words, verbatim",
                    state["heading"] == SCRIPTS["ordinary"]["heading"],
                    f"rendered {state['heading']!r}",
                )
            )
            results.append(
                Result(
                    "a product link becomes an href; a card without one does not",
                    state["hrefs"] == ["https://shop.example.com/p/1332"],
                    f"hrefs {state['hrefs']}",
                )
            )
            results.append(
                Result(
                    "a price renders with its currency",
                    any("132" in price for price in state["prices"]),
                    f"prices {state['prices']}",
                )
            )

            state = await read_block(chrome, f"{base}/harness?script=empty")
            results.append(
                Result(
                    "no suggestions renders nothing at all — not an empty box",
                    not state.get("rendered") and not state.get("titles"),
                    f"rendered={state.get('rendered')}, titles={state.get('titles')}",
                )
            )

            state = await read_block(chrome, f"{base}/harness?script=no_heading")
            results.append(
                Result(
                    "products with no heading render nothing (ADR-0040 §3)",
                    not state.get("rendered"),
                    "an unattributed 'goes well with' names nothing a shopper can reject",
                )
            )

            state = await read_block(chrome, f"{base}/harness?script=hostile_title")
            title = await title_of(chrome)
            rendered_as_text = state["titles"] and all("<" in text for text in state["titles"])
            results.append(
                Result(
                    "a product title that is markup renders as TEXT",
                    bool(rendered_as_text)
                    and state["images"] == 0
                    and state["scripts"] == 0
                    and title != "pwned",
                    f"titles={state['titles']}, img={state['images']}, "
                    f"script={state['scripts']}, document.title={title!r}",
                )
            )

            state = await read_block(chrome, f"{base}/harness?script=hostile_url")
            title = await title_of(chrome)
            results.append(
                Result(
                    "a javascript: link and a data: image never reach an attribute",
                    state["hrefs"] == [] and state["images"] == 0 and title != "pwned",
                    f"hrefs={state['hrefs']}, img={state['images']}, document.title={title!r}",
                )
            )
    finally:
        server.should_exit = True
        await task

    return results


async def run_live(
    chrome_binary: str, api: str, shop_url: str, shop_token: str, products: str
) -> list[Result]:
    """The real file, the real API, the real shop — and a real cross-origin page.

    The harness is served from its own port and the key is locked to it, so the
    fetch crosses origins exactly as a merchant's cart page does. That is the
    half stub mode cannot reach: per-key CORS and the key's origin lock, both
    decided by the same credential.
    """
    from provision_pairs import deprovision, provision

    port = free_port()
    origin = f"http://127.0.0.1:{port}"

    app = FastAPI()

    @app.get("/harness")
    async def harness(key: str, ids: str) -> HTMLResponse:
        return HTMLResponse(HARNESS.format(base=api.rstrip("/"), key=key, products=ids))

    server, task = await serve(app, port)
    tenant_id, key = await provision(shop_url, shop_token, origin)

    try:
        async with Chrome(chrome_binary) as chrome:
            state = await read_block(chrome, f"{origin}/harness?key={key}&ids={products}")
            if not state.get("ready"):
                return [
                    Result(
                        "the real block, cross-origin, against the real shop",
                        False,
                        "the element never attached a Shadow root",
                        measured=False,
                    )
                ]
            return [
                Result(
                    "the real block renders real products, cross-origin",
                    bool(state.get("rendered")) and bool(state.get("titles")),
                    f"heading {state.get('heading')!r}, cards {state.get('titles')}",
                )
            ]
    finally:
        server.should_exit = True
        await task
        await deprovision(tenant_id)


def report(results: list[Result], *, mode: str) -> int:
    print()
    print(f"  Paired-suggestion check — {mode}")
    print("  " + "─" * 68)
    for result in results:
        mark = "?" if not result.measured else ("✔" if result.ok else "✘")
        print(f"  {mark} {result.scenario}")
        print(f"      {result.detail}")
    unmeasured = [r for r in results if not r.measured]
    failed = [r for r in results if r.measured and not r.ok]
    print()
    if unmeasured:
        print(f"  {len(unmeasured)} scenario(s) NOT MEASURED — the browser never answered.")
        return 1
    if failed:
        print(f"  {len(failed)} of {len(results)} scenarios FAILED.")
        return 1
    print(f"  All {len(results)} scenarios passed — in a real browser.")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--url", default="http://localhost:8010")
    parser.add_argument("--shop-url", default="")
    parser.add_argument("--shop-token", default="")
    parser.add_argument("--products", default="1315")
    args = parser.parse_args()

    chrome_binary = find_chrome()

    if args.live:
        if not (args.shop_url and args.shop_token):
            raise SystemExit("live mode needs --shop-url and --shop-token")
        results = await run_live(
            chrome_binary, args.url, args.shop_url, args.shop_token, args.products
        )
        return report(results, mode=f"live, cross-origin, against {args.url}")

    return report(await run_stub(chrome_binary), mode="stub server — no models were run")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
