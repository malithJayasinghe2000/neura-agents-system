"""Does the widget actually work in a browser?

Milestone 1.16 shipped `widget.js` with its render decision unit-tested under
`node --test` and its hosting asserted from Python — and **none of that runs the
browser half**. The Shadow DOM, the streaming bubble and the socket-to-REST
fallback existed only as text that parsed. This project has recorded the same
shape of failure five times now (`pii_leaked` scored by nothing, `guard.block`
read by nobody, usage written by nobody, an audit column nobody could overflow,
and a `reply` field no client had consumed): **a control nobody has run is not a
control that works, it is a control nobody has run** — and that includes a
client.

So this drives the real file in real Google Chrome, headless, over the Chrome
DevTools Protocol. No npm, no Playwright, no `package.json`: Chrome is already
on the machine and `websockets` already ships with `uvicorn[standard]`.

    make widget-check          # stub server — NO MODELS, no cost, no heat
    make widget-check LIVE=1 URL=http://localhost:8000 KEY=fn_pk_...

**Stub mode is the important one and it is free.** It serves the real
`widget.js` next to a scripted API, which is the only way to drive cases that are
awkward to produce on demand — a shadowed turn, an empty turn, a socket that
refuses to open. Live mode then proves the same file works against the real API.

Exits non-zero on the first failed scenario, and reports "not measured" as its
own outcome rather than as a pass: a scenario whose browser never answered has
not told us anything (open question E6, the general form).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import shutil
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import websockets
from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse

ROOT = Path(__file__).resolve().parents[1]
WIDGET_JS = ROOT / "apps/neura-api/src/neura_api/widget/widget.js"

CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
)

#: A page on the stub's own origin, so the widget's fetch and socket are
#: same-origin exactly as they are on a merchant's site.
HARNESS_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>widget harness</title></head>
<body><script src="/v1/widget/widget.js" data-neura-key="fn_pk_test_harness"
        data-neura-open="true"></script></body></html>
"""

# ── Reading the widget from outside ──────────────────────────────────────────

#: Everything the widget has drawn, read out of the Shadow root. Note this
#: reaches *through* `shadowRoot`, which is itself the check that the element
#: attached one — a widget that failed to upgrade returns `ready: false`.
READ_ROWS = """
(() => {
  const el = document.querySelector("neura-chat");
  if (!el || !el.shadowRoot) return JSON.stringify({ ready: false });
  const sr = el.shadowRoot;
  const rows = [...sr.querySelectorAll(".row")].map((r) => ({
    role: r.dataset.role,
    text: (r.querySelector(".bubble") || {}).textContent || "",
    note: (r.querySelector(".note") || {}).textContent || "",
    link: (r.querySelector("a.signin") || {}).href || "",
    linkText: (r.querySelector("a.signin") || {}).textContent || "",
  }));
  const status = sr.querySelector(".status");
  return JSON.stringify({
    ready: true,
    rows: rows,
    status: status ? status.textContent : "",
    busy: !!(sr.querySelector(".compose button") || {}).disabled,
    panelOpen: (sr.querySelector(".panel") || { dataset: {} }).dataset.open === "true",
  });
})()
"""

SEND_MESSAGE = """
(() => {
  const sr = document.querySelector("neura-chat").shadowRoot;
  sr.querySelector("input").value = %s;
  sr.querySelector("form").dispatchEvent(
    new Event("submit", { cancelable: true, bubbles: true })
  );
  return "sent";
})()
"""


@dataclass
class Scenario:
    """One thing a shopper can do, and what must appear on screen."""

    name: str
    message: str
    #: What the stub does with the turn. Ignored in live mode.
    script: str = "answer"
    #: Which transport must have served it. ADR-0019 §4 prefers the socket, so
    #: a turn REST answered when the socket was available is a regression even
    #: though the shopper sees the right thing.
    transport: str = "websocket"
    #: A second message on the SAME page, sent after the first turn finished.
    #: The only way to exercise what a socket does between turns.
    follow_up: str | None = None
    #: The page cannot reach NEURA at all: a shopper offline (G56).
    unreachable: bool = False
    #: A failure case: every message must get exactly this one error row (G56).
    expect_error: str | None = None
    #: ADR-0057: a signed-in shopper's pass and the shop's sign-in page, as the
    #: shop's server writes them into the line.
    customer_pass: str | None = None
    sign_in_url: str | None = None
    why: str = ""


@dataclass
class Result:
    scenario: str
    ok: bool
    detail: str
    rows: list[dict[str, Any]] = field(default_factory=list)


# ── The stub API ─────────────────────────────────────────────────────────────


def build_stub() -> Any:
    """An API-shaped server with no agent behind it.

    It speaks the frames `stream.py` sends and the payload `routes/agent.py`
    returns — nothing more. The point is not to simulate the agent (the golden
    suite does that); it is to hand the browser each *shape* of turn, including
    the two that are hard to produce on demand.
    """
    # NB: these must be imported at module scope, not here. This file uses
    # postponed annotations, and FastAPI resolves a handler's annotations
    # against the *module* namespace — a function-local `Request` or
    # `WebSocket` silently becomes a required query parameter, which shows up
    # as a 422 on the POST and a bare 403 on the socket handshake.
    app = FastAPI()
    disclosure = "You are chatting with an AI assistant."

    #: Which transport actually served the last turn.
    #:
    #: This exists because of a real near-miss while writing this script: the
    #: socket was rejecting every handshake, REST was quietly covering for it,
    #: and the scenario reported a clean pass. A check that cannot tell which
    #: path answered cannot tell you the preferred path is broken — so it was
    #: measuring the fallback and calling it the feature.
    served: dict[str, str] = {"transport": "none"}

    payloads: dict[str, dict[str, Any]] = {
        "answer": {
            "reply": "Your order #1001 shipped on 22 July.",
            "state": "resolved",
            "fallback_message": "",
        },
        # 1.15 withholds the reply. Without ADR-0020 this renders nothing at all,
        # which is the whole reason this scenario is here.
        "shadow": {
            "reply": "",
            "state": "shadowed",
            "fallback_message": "Thanks — your message has been received.",
        },
        # Must never happen in production, and must be visible when it does.
        "empty": {"reply": "", "state": "shadowed", "fallback_message": ""},
        # ADR-0057 §7: an order question from someone not signed in.
        "sign_in": {
            "reply": SIGN_IN_SENTENCE,
            "state": "resolved",
            "fallback_message": "",
            "sign_in": True,
        },
    }
    payloads["sign_in_refuse"] = payloads["sign_in"]

    #: The customer pass the last message carried, on either transport, so a
    #: scenario can prove the chat box sent it (and in the message, not the
    #: address).
    received: dict[str, str] = {"customer_pass": "", "address": ""}

    def _done(script: str) -> dict[str, Any]:
        body = payloads.get(script, payloads["answer"])
        return {
            "type": "done",
            "conversation_id": "cnv_stub",
            "message_id": "msg_stub",
            "escalated": False,
            "blocked": False,
            "citations": [],
            "ai_disclosure": disclosure,
            **body,
        }

    @app.get("/v1/widget/widget.js")
    async def asset() -> Response:
        return Response(
            WIDGET_JS.read_text(encoding="utf-8"),
            media_type="application/javascript; charset=utf-8",
        )

    @app.get("/harness")
    async def harness() -> HTMLResponse:
        served["transport"] = "none"
        return HTMLResponse(HARNESS_HTML)

    @app.get("/served")
    async def which() -> dict[str, str]:
        return {**served, **received}

    def _script_from(token: str) -> str:
        """Which turn shape to play, carried on the credential.

        The widget sends its key and nothing else — no test hook — so the
        scenario rides inside the token rather than in a query parameter the
        widget would have to know to append. That keeps the file under test
        free of anything that exists only for this script.
        """
        _, _, script = token.partition(":")
        return script or "answer"

    # **Both doors, and the undecorated one is the one that matters.** ADR-0031
    # made the widget stop naming an agent (`AGENT_DEFAULT = ""`), so it now
    # addresses `/v1/stream` and `/v1/chat` and the server dispatches per
    # message. This stub served only the `care`-prefixed pair, so from the day
    # that shipped every scenario here failed the socket, fell back to REST,
    # 404ed, and drew "We could not reach the assistant" — and nobody ran it.
    # The prefixed routes stay because a single-agent embed still uses them.
    @app.websocket("/v1/stream")
    @app.websocket("/v1/care/stream")
    async def stream(websocket: WebSocket) -> None:
        script = _script_from(websocket.query_params.get("token", ""))
        # "refuse" never accepts the handshake, so the widget must notice the
        # socket is unusable and fall back to REST on its own.
        if script in REFUSING:
            await websocket.close(code=1011)
            return
        await websocket.accept()
        served["transport"] = "websocket"
        received["address"] = str(websocket.url)
        while True:
            try:
                frame = await websocket.receive_json()
            except Exception:
                return
            received["customer_pass"] = str(frame.get("customer_pass") or "")
            await websocket.send_json({"type": "accepted", "conversation_id": "cnv_stub"})
            for node in ("guard", "route", "retrieve", "compose", "verify"):
                await websocket.send_json({"type": "step", "name": node})
                await asyncio.sleep(0.02)
            done = _done(script)
            # ADR-0016: token frames carry the already-verified reply, and a
            # withheld turn emits none at all.
            if done["reply"]:
                for i in range(0, len(done["reply"]), 12):
                    await websocket.send_json(
                        {"type": "token", "content": done["reply"][i : i + 12]}
                    )
                    await asyncio.sleep(0.02)
            await websocket.send_json(done)
            if script == "die":
                # What the real server does after `IDLE_TIMEOUT_S`, and what
                # `--reload` does to every open socket on any source edit. The
                # turn succeeded; the socket is gone. Whatever the widget holds
                # now, the shopper's NEXT message must still reach a server.
                await websocket.close(code=1000, reason="idle")
                return

    @app.post("/v1/chat")
    @app.post("/v1/care/chat")
    async def chat(request: Request) -> Any:
        served["transport"] = "rest"
        received["address"] = str(request.url)
        with contextlib.suppress(Exception):
            received["customer_pass"] = str((await request.json()).get("customer_pass") or "")
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        script = _script_from(bearer)
        if script == "refused_key":
            # NEURA's own refusal, readable by the page (G55): its words are shown.
            return JSONResponse(
                {"error": {"code": "SECRET_KEY_IN_PAGE", "message": REFUSAL_SENTENCE}},
                status_code=401,
            )
        if script == "html_error":
            # A proxy's error page: not JSON, so nothing in it is for a shopper.
            return Response(
                "<html><body>502 Bad Gateway</body></html>", status_code=502, media_type="text/html"
            )
        done = _done(script)
        done.pop("type")
        return {"data": done, "meta": {}}

    return app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# ── Chrome, over the DevTools Protocol ───────────────────────────────────────


class Chrome:
    """Headless Chrome, driven directly. No automation library."""

    def __init__(self, binary: str) -> None:
        self.binary = binary
        self.profile = tempfile.mkdtemp(prefix="neura-widget-")
        self.port = free_port()
        self.process: subprocess.Popen[bytes] | None = None
        self.socket: Any = None
        self._id = 0

    async def __aenter__(self) -> Chrome:
        self.process = subprocess.Popen(
            [
                self.binary,
                "--headless=new",
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={self.profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        target = await self._wait_for_target()
        self.socket = await websockets.connect(target, max_size=None)
        await self.call("Page.enable")
        await self.call("Runtime.enable")
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self.socket is not None:
            with contextlib.suppress(Exception):
                await self.socket.close()
        if self.process is not None:
            self.process.terminate()
            with contextlib.suppress(Exception):
                self.process.wait(timeout=10)
        shutil.rmtree(self.profile, ignore_errors=True)

    async def _wait_for_target(self, timeout: float = 20.0) -> str:
        """Chrome needs a moment to open its debugging port."""
        deadline = asyncio.get_running_loop().time() + timeout
        async with httpx.AsyncClient() as http:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    response = await http.get(f"http://127.0.0.1:{self.port}/json/list")
                    for entry in response.json():
                        if entry.get("type") == "page" and entry.get("webSocketDebuggerUrl"):
                            return str(entry["webSocketDebuggerUrl"])
                except Exception:
                    pass
                await asyncio.sleep(0.25)
        raise RuntimeError("Chrome never opened its debugging port")

    async def call(self, method: str, **params: Any) -> dict[str, Any]:
        self._id += 1
        message_id = self._id
        await self.socket.send(json.dumps({"id": message_id, "method": method, "params": params}))
        while True:
            raw = json.loads(await self.socket.recv())
            if raw.get("id") == message_id:
                if "error" in raw:
                    raise RuntimeError(f"{method}: {raw['error']}")
                return dict(raw.get("result", {}))

    async def goto(self, url: str) -> None:
        await self.call("Page.navigate", url=url)
        await asyncio.sleep(1.2)

    async def evaluate(self, expression: str) -> Any:
        result = await self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        payload = result.get("result", {})
        if "value" not in payload:
            raise RuntimeError(f"no value from the page: {result}")
        return payload["value"]

    async def read(self) -> dict[str, Any]:
        return dict(json.loads(await self.evaluate(READ_ROWS)))

    async def send_message(self, message: str) -> None:
        await self.evaluate(SEND_MESSAGE % json.dumps(message))

    async def wait_until_idle(self, timeout: float = 90.0) -> dict[str, Any]:
        """Wait for the turn to finish — the widget re-enables its own input.

        A timeout is reported as **not measured**, never as a failed assertion:
        a scenario whose browser never answered has told us nothing about the
        widget, and scoring it as a defect is how a dead dependency becomes a
        fabricated result.
        """
        deadline = asyncio.get_running_loop().time() + timeout
        state: dict[str, Any] = {}
        while asyncio.get_running_loop().time() < deadline:
            state = await self.read()
            if state.get("ready") and not state.get("busy") and state.get("rows"):
                return state
            await asyncio.sleep(0.3)
        state["timed_out"] = True
        return state


# ── The scenarios ────────────────────────────────────────────────────────────

#: The widget's own words when a message could not be answered.
TRANSPORT_ERROR = "We could not reach the assistant. Please check your connection and try again."
#: ADR-0057 §7, the owner's words, as the server sends them.
SIGN_IN_SENTENCE = "Please sign in to your account so I can help with your orders."
#: A pass's shape only; the stub checks nothing about it.
STUB_PASS = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIzODUifQ.c2lnbmF0dXJl"  # noqa: S105 - made up, signed by nothing
STUB_SIGN_IN_URL = "https://shop.example/account/login"

#: The API's sentence for a secret key used from a page (G55).
REFUSAL_SENTENCE = (
    "A secret key may not be used from a web page, where anyone can read it. Use the "
    "shop's public key (fn_pk_…) in the page, and keep secret keys on your server."
)
#: Scripts whose socket is refused at the handshake, so REST is tried.
REFUSING = frozenset({"refuse", "refused_key", "html_error", "sign_in_refuse"})
#: A browser's or a parser's own words, which must never reach a shopper (G56).
RAW_WORDS = ("Failed to fetch", "Load failed", "NetworkError", "Unexpected token", "request_failed")

STUB_SCENARIOS = (
    Scenario(
        name="a signed-in shopper's pass goes with the message, and Sign in is a link",
        message="where is my order?",
        script="sign_in",
        customer_pass=STUB_PASS,
        sign_in_url=STUB_SIGN_IN_URL,
        why="ADR-0057: the pass in the message, never the address; the link the server asks for",
    ),
    Scenario(
        name="over the plain-request fallback too",
        message="where is my order?",
        script="sign_in_refuse",
        transport="rest",
        customer_pass=STUB_PASS,
        sign_in_url=STUB_SIGN_IN_URL,
        why="ADR-0057 §4: both transports carry the pass the same way",
    ),
    Scenario(
        name="an answered turn draws the reply",
        message="where is my order 1001?",
        script="answer",
        why="the ordinary path — and the first time the Shadow DOM has ever been built",
    ),
    Scenario(
        name="a SHADOWED turn draws the server's words, not silence",
        message="what is your returns policy?",
        script="shadow",
        why="ADR-0020. 1.15 makes `reply` empty by design; without this the panel shows nothing",
    ),
    Scenario(
        name="an empty turn is visibly an error, never silence",
        message="hello?",
        script="empty",
        why="the invariant, in a real browser rather than in a unit test",
    ),
    Scenario(
        name="a socket that died between turns loses no message",
        message="where is my order 1001?",
        follow_up="and what is your returns policy?",
        script="die",
        why="Finding 21 — the second message must reach a server, not a dead socket",
    ),
    Scenario(
        name="a refused socket falls back to REST and still answers",
        message="where is my order 1001?",
        script="refuse",
        transport="rest",
        why="the fallback ADR-0019 §4 accepts the cost of, and the path most likely to rot",
    ),
    Scenario(
        name="an offline shopper gets one plain error per message, never the browser's words",
        message="hello?",
        follow_up="are you there?",
        unreachable=True,
        transport="none",
        expect_error=TRANSPORT_ERROR,
        why="G56: it showed our sentence AND the browser's 'Failed to fetch'",
    ),
    Scenario(
        name="NEURA's readable refusal is shown once per message, in its own words",
        message="hello?",
        follow_up="hello again?",
        script="refused_key",
        transport="rest",
        expect_error=REFUSAL_SENTENCE,
        why="G55/G56: one sentence that says why, not a second error before it",
    ),
    Scenario(
        name="an error page that is not JSON is one plain error",
        message="hello?",
        script="html_error",
        transport="rest",
        expect_error=TRANSPORT_ERROR,
        why="G56: a parser's 'Unexpected token' is not for a shopper",
    ),
)


def check(
    scenario: Scenario,
    state: dict[str, Any],
    transport: str | None = None,
    received: dict[str, str] | None = None,
) -> Result:
    """What must be true on screen. Written as prose, because a failure here is
    read by somebody who has not got the widget open in front of them."""
    if state.get("timed_out"):
        return Result(scenario.name, False, "NOT MEASURED — the turn never finished")
    if not state.get("ready"):
        return Result(scenario.name, False, "the element never upgraded — no shadow root")

    rows = state.get("rows", [])
    if not rows:
        return Result(scenario.name, False, "nothing was drawn at all", rows)

    shopper = [r for r in rows if r["role"] == "shopper"]
    answers = [r for r in rows if r["role"] != "shopper"]
    if not shopper:
        return Result(scenario.name, False, "the shopper's own message was not echoed", rows)
    if not answers:
        return Result(scenario.name, False, "the shopper spoke and nothing came back", rows)

    # A two-turn scenario must have drawn two turns. Asserted before the reply
    # is read, because the failure it catches — the second message silently not
    # happening — leaves the FIRST turn's perfectly good reply sitting on screen
    # as `answers[-1]`, and everything below would pass on it.
    if scenario.follow_up:
        if len(shopper) < 2:
            return Result(scenario.name, False, "the second message was never echoed", rows)
        if len(answers) < 2:
            return Result(scenario.name, False, "the second message got no reply at all", rows)

    if scenario.expect_error is not None:
        return _check_failure(scenario, rows, shopper, answers)

    reply = answers[-1]
    # The invariant, stated once: whatever the outcome, the bubble has words in
    # it. An empty bubble is the bug 1.16 exists to make impossible.
    if not reply["text"].strip():
        return Result(scenario.name, False, "AN EMPTY BUBBLE WAS DRAWN", rows)

    expected_role = {
        "answer": "assistant",
        "shadow": "system",
        "empty": "error",
        "refuse": "assistant",
        "die": "assistant",
        "sign_in": "assistant",
        "sign_in_refuse": "assistant",
    }
    wanted = expected_role[scenario.script]
    if reply["role"] != wanted:
        return Result(
            scenario.name, False, f"drawn as `{reply['role']}`, expected `{wanted}`", rows
        )

    if wanted in {"assistant", "system"} and "AI assistant" not in reply["note"]:
        # EU AI Act Art. 50 — on every message, not only the first.
        return Result(scenario.name, False, "no AI disclosure on the message", rows)

    if transport is not None and transport != scenario.transport:
        return Result(
            scenario.name,
            False,
            f"served over `{transport}`, expected `{scenario.transport}` — "
            "the shopper saw the right thing over the wrong path",
            rows,
        )

    if scenario.customer_pass:
        sent = (received or {}).get("customer_pass", "")
        if sent != scenario.customer_pass:
            return Result(
                scenario.name, False, "the customer pass was not sent with the message", rows
            )
        if scenario.customer_pass in (received or {}).get("address", ""):
            return Result(scenario.name, False, "THE PASS WAS PUT IN THE ADDRESS", rows)
        if reply.get("link") != scenario.sign_in_url or reply.get("linkText") != "Sign in":
            return Result(
                scenario.name,
                False,
                f"no Sign in link under the reply ({reply.get('link')!r})",
                rows,
            )

    served = f" (over {transport})" if transport else ""
    link = " + Sign in link" if reply.get("link") else ""
    return Result(
        scenario.name, True, f"`{reply['role']}`: {reply['text'][:60]}{link}{served}", rows
    )


def _check_failure(
    scenario: Scenario,
    rows: list[dict[str, Any]],
    shopper: list[dict[str, Any]],
    answers: list[dict[str, Any]],
) -> Result:
    """A message that could not be answered: one error row per message, in words a
    shopper can read (G56)."""
    raw = [r["text"] for r in rows if any(words in r["text"] for words in RAW_WORDS)]
    if raw:
        return Result(scenario.name, False, f"the shopper read {raw[0]!r}", rows)
    errors = [r["text"] for r in answers if r["role"] == "error"]
    if len(answers) != len(errors) or errors != [scenario.expect_error] * len(shopper):
        return Result(
            scenario.name,
            False,
            f"{len(shopper)} message(s) drew {len(errors)} error(s): {errors}",
            rows,
        )
    return Result(scenario.name, True, f"one error per message: {errors[0][:70]}", rows)


# ── Runs ─────────────────────────────────────────────────────────────────────


async def run_stub(chrome_binary: str) -> list[Result]:
    import uvicorn

    port = free_port()
    config = uvicorn.Config(build_stub(), host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.1)

    results: list[Result] = []
    try:
        async with Chrome(chrome_binary) as chrome:
            for scenario in STUB_SCENARIOS:
                # A fresh page per scenario, so no element carries state over.
                # The scenario travels inside the key, which is the one value
                # the widget already sends on both transports.
                await chrome.goto(f"http://127.0.0.1:{port}/harness")
                # An offline shopper: NEURA's address on a port nobody listens on.
                base = (
                    f" e.config.base = 'http://127.0.0.1:{free_port()}';"
                    if scenario.unreachable
                    else ""
                )
                signed_in = (
                    f" e.config.customerPass = '{scenario.customer_pass}';"
                    f" e.config.signInUrl = '{scenario.sign_in_url}';"
                    if scenario.customer_pass
                    else ""
                )
                await chrome.evaluate(
                    "(() => { const e = document.querySelector('neura-chat');"
                    f" e.config.key = 'fn_pk_test_harness:{scenario.script}';{base}{signed_in}"
                    " return 'ok'; })()"
                )
                await chrome.send_message(scenario.message)
                state = await chrome.wait_until_idle(timeout=30)
                if scenario.follow_up and not state.get("timed_out"):
                    await chrome.send_message(scenario.follow_up)
                    state = await chrome.wait_until_idle(timeout=30)
                async with httpx.AsyncClient() as http:
                    served = (await http.get(f"http://127.0.0.1:{port}/served")).json()
                results.append(check(scenario, state, served["transport"], served))
    finally:
        server.should_exit = True
        with contextlib.suppress(Exception):
            await task
    return results


async def provision(
    base: str, shop_url: str, shop_token: str, *, shadow: bool = False, agent: str = "care"
) -> tuple[str, str]:
    """A tenant, a store, and a **public** key origin-locked to ``base``.

    Public rather than secret, deliberately: a widget key is what a shopper's
    browser actually holds, so a live check issued a secret key would be
    exercising a credential no widget ever has — and would skip the origin lock
    entirely, which is half of what there is to prove here (ADR-0014 §3).
    """
    from neura_core import Database, get_database, get_settings
    from neura_core.ids import TENANT, new_id
    from neura_core.tenancy import (
        ApiKeyKind,
        ApiKeyRepository,
        StoreConnectionRepository,
        TenantConfig,
        TenantRepository,
    )

    get_settings.cache_clear()
    get_database.cache_clear()
    db = Database.from_settings()
    tenant_id = new_id(TENANT)
    async with db.tenant_session(tenant_id) as session:
        await TenantRepository(session).create(
            tenant_id=tenant_id,
            name="widget check",
            enabled_agents=_agent_keys(agent),
            # `--shadow` runs the real thing: a full turn whose reply is
            # withheld, so what the browser renders is `fallback_message` and
            # nothing else. It is the one case that cannot be produced by
            # asking a different question.
            config=TenantConfig(mode="shadow") if shadow else TenantConfig(),
        )
        _, issued = await ApiKeyRepository(session).issue(
            tenant_id,
            scopes=_scopes_for(agent),
            name="widget-check",
            kind=ApiKeyKind.PUBLIC,
            allowed_origins=[base.rstrip("/")],
        )
        await StoreConnectionRepository(session).connect(
            tenant_id, platform="generic", base_url=shop_url, credentials={"token": shop_token}
        )
    await db.dispose()
    return tenant_id, issued.token


#: What a public widget key may do, per agent. Kept here rather than derived
#: from the manifest because a demo that silently grants whatever an agent
#: declares would stop being a check on what a *public* key is allowed to hold.
#: No ``conversations:read`` (G80): the chat box never reads a transcript, and a
#: public key that could would hand every shopper's chat to anyone.
_SCOPES = {
    "care": (
        "care:chat:write",
        "care:order:read",
        "care:catalogue:read",
        "care:policies:read",
        "care:escalate",
    ),
    "sell": (
        "sell:chat:write",
        "sell:catalogue:read",
        "sell:escalate",
    ),
}


def _agent_keys(agent: str) -> list[str]:
    """Split `--agent` into keys, preserving the order they were written in."""
    keys = [part.strip() for part in agent.split(",") if part.strip()]
    unknown = [k for k in keys if k not in _SCOPES]
    if not keys or unknown:
        raise SystemExit(
            f"unknown agent {', '.join(unknown) or '(none given)'} — "
            f"expected one or more of {', '.join(_SCOPES)}"
        )
    return keys


def _scopes_for(agent: str) -> list[str]:
    """Every scope the named agents need, as one set.

    A tenant running two agents needs a key holding both agents' scopes, or
    ``POST /v1/chat`` dispatches correctly and is then refused at the scope
    check — which reads as a broken dispatcher and is a provisioning fault
    ([ADR-0031] §1).
    """
    scopes: set[str] = set()
    for key in _agent_keys(agent):
        scopes.update(_SCOPES[key])
    return sorted(scopes)


async def deprovision(tenant_id: str) -> None:
    """Remove every row this tenant owns — *every* table, not the obvious seven.

    Found on 2026-08-27, in Stage 7 of the testing log. The earlier list deleted
    the transcript, the usage and the tenant row, and left twelve tenant-scoped
    tables standing. Three shadow turns, 147 embedded chunks and 46 synced
    entities had outlived the tenants that owned them — the shadow rows pointing
    at a conversation, a message and a tenant that no longer existed.

    That is litter in a test harness. What makes it worth a docstring is that
    this function is the **only** code in the repository that deletes a tenant,
    so it is also the closest thing here to an answer to "delete my data" — and
    the rows it was leaving behind are the merchant's catalogue and the drafts
    of replies. The product-level question is open as **S10**; this only stops
    the harness from being the thing that proves the gap.

    The session is tenant-scoped and RLS is forced, so an unqualified DELETE
    removes this tenant's rows and can reach nobody else's. `tenants` goes last
    so an interrupted run leaves a tenant that can be dropped again rather than
    orphans with no name to drop them by.

    **`audit_log` is deliberately absent, and finding out why is the useful part.**
    The first version of this list included it and the delete was refused:
    `neura_app` is granted only INSERT and SELECT on that table. Append-only is
    a *privilege*, not a convention someone remembered to honour — so the guard
    events behind ADR-0012 and S5 cannot be erased by the code path that erases
    everything else, which is the entire point of keeping them. It also means a
    tenant's rows do not all go away when the tenant does, and no wording of
    "we deleted your data" can be true of this table without saying so. That is
    **S10**, and it is a decision for a person and not for a cleanup helper.
    """
    from sqlalchemy import delete

    from neura_core import Database

    db = Database.from_settings()
    async with db.tenant_session(tenant_id) as session:
        for table in tenant_tables():
            await session.execute(delete(table))
    await db.dispose()


def tenant_tables() -> list[Any]:
    """Every table that holds a tenant's rows, in an order they can be deleted in.

    **`audit_log` is absent on purpose** (see `deprovision`). A test compares
    this list with the database's own (`tests/integration/test_tenant_drop_postgres.py`),
    because the list fell behind once already: the shop token, the full check,
    the pairings, the owner's choices and practice-mode evidence were all added
    after it, and their rows outlived every dropped tenant (G76).
    """
    from neura_agent_core.conversations import conversation_messages, conversations
    from neura_agent_core.graph.schema import agent_checkpoint_writes, agent_checkpoints
    from neura_agent_core.rag.schema import document_chunks
    from neura_agent_core.shadow import shadow_turns
    from neura_agent_core.shadow_evidence import shadow_evidence
    from neura_agent_sell.feed.schema import sell_feeds
    from neura_agent_sell.pairing.schema import sell_pairing_choices, sell_pairings
    from neura_commerce.sync.schema import sync_checkpoints, synced_entities
    from neura_core.idempotency import idempotency_keys
    from neura_core.identity.schema import memberships
    from neura_core.jobs.schema import job_queue
    from neura_core.observation.schema import observed_events
    from neura_core.tenancy.schema import (
        api_keys,
        customer_secrets,
        shop_checks,
        shop_tokens,
        tenant_stores,
        tenant_usage,
        tenants,
    )
    from neura_core.webhooks.schema import webhook_deliveries, webhook_endpoints

    return [
        # A shopper's events first: a dropped tenant must not leave the one
        # table that holds observed personal data behind (ADR-0044 §7).
        observed_events,
        # Before the turns it points at: the one foreign key among these tables.
        shadow_evidence,
        shadow_turns,
        sell_feeds,
        sell_pairing_choices,
        sell_pairings,
        conversation_messages,
        conversations,
        agent_checkpoint_writes,
        agent_checkpoints,
        document_chunks,
        synced_entities,
        sync_checkpoints,
        job_queue,
        webhook_deliveries,
        webhook_endpoints,
        memberships,
        idempotency_keys,
        tenant_usage,
        shop_checks,
        # The shop token, sealed: no shop should leave one behind.
        shop_tokens,
        # The customer sign-in secret, sealed, likewise (ADR-0057).
        customer_secrets,
        tenant_stores,
        api_keys,
        tenants,
    ]


async def run_live(
    chrome_binary: str, base: str, key: str, message: str, *, shadow: bool = False
) -> list[Result]:
    """The same file, against the real API — real key, real origin lock, real turn."""
    scenario = Scenario(
        name=(
            "a real SHADOWED turn, in a real browser"
            if shadow
            else "the real API, in a real browser"
        ),
        message=message,
        script="shadow" if shadow else "answer",
        # Live mode cannot read the stub's counter, so the transport is not
        # asserted here. The stub run is what pins that.
        transport="",
        why="everything the stub cannot prove: authentication, the origin lock, the real graph",
    )
    async with Chrome(chrome_binary) as chrome:
        await chrome.goto(f"{base.rstrip('/')}/v1/widget/demo?key={key}")
        state = await chrome.read()
        if not state.get("ready"):
            return [Result(scenario.name, False, "the widget never loaded on the demo page")]
        await chrome.send_message(message)
        # A real turn on a real model. p50 has been measured at 41.8-50.9s.
        return [check(scenario, await chrome.wait_until_idle(timeout=180))]


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    raise SystemExit("No Chrome or Chromium found — this check needs one installed.")


def report(results: list[Result], *, mode: str) -> int:
    print()
    print(f"  Widget check — {mode}")
    print("  " + "─" * 68)
    for result in results:
        mark = "✔" if result.ok else "✘"
        print(f"  {mark} {result.scenario}")
        print(f"      {result.detail}")
        if not result.ok and result.rows:
            for row in result.rows:
                print(f"        [{row['role']}] {row['text'][:70]!r}")
    failed = [r for r in results if not r.ok]
    print()
    if failed:
        print(f"  {len(failed)} of {len(results)} scenarios FAILED.")
        return 1
    print(f"  All {len(results)} scenarios passed — in a real browser.")
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="drive the real API instead of a stub")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--key", default="", help="an fn_pk_ key origin-locked to --url")
    parser.add_argument("--shop-url", default="", help="a real shop, to provision a tenant against")
    parser.add_argument("--shop-token", default="")
    parser.add_argument(
        "--shadow", action="store_true", help="provision the tenant in SHADOW mode (ADR-0020)"
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="provision and print a URL to open by hand, instead of driving Chrome",
    )
    parser.add_argument("--message", default="what is your returns policy?")
    parser.add_argument(
        "--agent",
        default="care",
        help=(
            "which agent(s) the provisioned tenant runs — comma-separated. "
            "`care` (default), `sell`, or `care,sell` for a tenant that dispatches"
        ),
    )
    args = parser.parse_args()

    chrome_binary = find_chrome()
    if args.live:
        tenant_id = ""
        key = args.key
        if not key:
            if not (args.shop_url and args.shop_token):
                raise SystemExit("--live needs either --key, or --shop-url and --shop-token")
            tenant_id, key = await provision(
                args.url, args.shop_url, args.shop_token, shadow=args.shadow, agent=args.agent
            )
            print(f"  provisioned {tenant_id} with a public key locked to {args.url}")
        if args.setup_only:
            # Left running on purpose. A headless pass proves the widget works;
            # it does not show anybody what it looks like, and the first person
            # to look at it is the one who notices what no assertion can.
            print()
            print("  Open this in your own browser:")
            print()
            # `&agent=` is a *pin*. A tenant running one agent gets pinned to
            # it, which is what it would do anyway and makes the URL explicit.
            # A tenant running two must NOT be pinned, or the demo page hands
            # the widget one agent and dispatch never runs — which is exactly
            # the defect this parameter caused on 2026-09-01 ([ADR-0031] §1).
            keys = _agent_keys(args.agent)
            pin = f"&agent={keys[0]}" if len(keys) == 1 else ""
            print(f"    {args.url.rstrip('/')}/v1/widget/demo?key={key}{pin}")
            if len(keys) > 1:
                print()
                print(f"    This tenant runs {', '.join(keys)} — the server picks per message.")
            print()
            print(f"  Mode: {'SHADOW — the reply is withheld' if args.shadow else 'LIVE'}")
            print(f"  When you are done:  make tenant-drop TENANT={tenant_id}")
            print()
            return 0

        try:
            results = await run_live(chrome_binary, args.url, key, args.message, shadow=args.shadow)
        finally:
            if tenant_id:
                await deprovision(tenant_id)
        return report(results, mode=f"live, against {args.url}")

    results = await run_stub(chrome_binary)
    return report(results, mode="stub server — no models were run")


if __name__ == "__main__":
    # `--drop` cleans up after `--setup-only`, which deliberately leaves its
    # tenant, key and store connection in place so a person can keep clicking.
    if len(sys.argv) > 2 and sys.argv[1] == "--drop":
        asyncio.run(deprovision(sys.argv[2]))
        print(f"  removed {sys.argv[2]}")
        raise SystemExit(0)
    sys.exit(asyncio.run(main()))
