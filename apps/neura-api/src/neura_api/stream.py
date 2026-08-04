"""The WebSocket transport — ADR-0016 made concrete.

The rule the whole file is arranged around: **no model-generated text reaches a
client before ``verify`` has passed.** `verify` runs after `compose`, so a streamed
draft could need retracting mid-sentence — and CARE's argument for answering at
all, rather than escalating, is that a draft was checked against its evidence
first. A retraction does not un-read the two sentences that preceded it.

So this streams the *turn*, not the draft:

    accepted   → conversation_id                (before any work starts)
    step       → a node name                    (as each node finishes)
    tool_call  → a tool name                    (when one has run)
    token      → a slice of the VERIFIED reply  (after verify passed)
    done       → message_id, state, citations, disclosure
    error      → the same error object REST returns

The perceived behaviour is unchanged — text appears progressively — and every
character in it is text ``verify`` accepted. The honest cost is time to first
token, and ``step`` and ``tool_call`` frames are the answer to it: "checking your
order…" is exactly as informative as the first eight words of a draft and cannot
be wrong in a way that matters.

**The stream is a simulation, and that is documented rather than implied.**
``token`` frames are slices of a finished string, not provider deltas. A client
must not assume backpressure semantics or partial-word boundaries from them.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from neura_agent_core.serving import Progress, ProgressSink
from neura_core import NeuraError, ValidationError, get_logger, new_id
from neura_core.ids import CONVERSATION, REQUEST

log = get_logger(__name__)

#: How much verified reply goes in one frame. A rendering detail, not a
#: protocol one: a client that buffers everything until `done` is correct too.
TOKEN_CHUNK_CHARS = 24

#: Pause between `token` frames, so a fast local model does not deliver the
#: whole reply in one event-loop tick and defeat the point of streaming it.
TOKEN_DELAY_S = 0.02

#: A socket that has said nothing for this long is closed. An idle socket costs
#: a connection and, behind a proxy, an entry in someone's table.
IDLE_TIMEOUT_S = 300.0

#: Close codes. 4401 and 4403 mirror the HTTP statuses deliberately: an
#: integrator debugging a socket should not have to learn a second vocabulary
#: for the same two failures.
CLOSE_UNAUTHENTICATED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_RATE_LIMITED = 4429


async def run_streamed_turn(
    websocket: WebSocket,
    *,
    agent_key: str,
    token: str | None,
) -> None:
    """Accept a socket, authenticate it, and serve turns until it closes."""
    from neura_api.dependencies import agent_context_for_socket
    from neura_api.routes.agent import AI_DISCLOSURE, ChatRequest, _rate_limit, _turn_input

    request_id = new_id(REQUEST)

    try:
        context = await agent_context_for_socket(
            websocket, agent_key, token=token, scopes=(f"{agent_key}:chat:write",)
        )
    except NeuraError as exc:
        # Refused during the handshake: the socket is never accepted, so an
        # unauthenticated caller cannot hold a connection open at all.
        await websocket.close(code=_close_code(exc), reason=exc.code)
        log.info("stream_rejected", agent=agent_key, code=exc.code)
        return

    await websocket.accept()

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_json(), timeout=IDLE_TIMEOUT_S)
            except TimeoutError:
                await websocket.close(code=1000, reason="idle")
                return

            if not isinstance(raw, dict) or raw.get("type") != "message":
                await _send_error(
                    websocket,
                    ValidationError(
                        'Expected {"type": "message", "content": "..."}.',
                        details={"field": "type"},
                    ),
                    request_id,
                )
                continue

            try:
                body = ChatRequest(
                    message=str(raw.get("content", "")),
                    conversation_id=raw.get("conversation_id"),
                    external_ref=raw.get("external_ref"),
                    channel=str(raw.get("channel", "web")),
                    locale=str(raw.get("locale", "en")),
                )
            except PydanticValidationError as exc:
                await _send_error(
                    websocket,
                    ValidationError("Invalid message.", details={"errors": exc.errors()}),
                    request_id,
                )
                continue

            # Minted here rather than inside the turn, so `accepted` can carry
            # it before any work starts. `TurnService` uses whatever it is
            # given, so this is the same path a REST request takes with a
            # conversation_id already in hand.
            conversation_id = body.conversation_id or new_id(CONVERSATION)

            try:
                verdict = await _rate_limit(websocket, context.caller, conversation_id)
                if not verdict.allowed:
                    await _send_error(
                        websocket,
                        NeuraError("Too many requests.", code="RATE_LIMITED"),
                        request_id,
                        extra={"retry_after": verdict.retry_after},
                    )
                    continue

                turn = _turn_input(
                    websocket,
                    context.caller,
                    agent_key,
                    body.model_copy(update={"conversation_id": conversation_id}),
                )
                await _send(websocket, {"type": "accepted", "conversation_id": conversation_id})
                result = await websocket.app.state.turns.run(
                    context.runner, turn, on_progress=_progress_sink(websocket)
                )
            except NeuraError as exc:
                await _send_error(websocket, exc, request_id)
                continue

            outcome = result.outcome
            # Only an answered turn is streamed. A block or a handover is fixed
            # text, delivered whole — typing out a refusal a character at a time
            # is theatre, and ADR-0016 says a blocked turn emits no `token`
            # frame at all.
            if outcome.is_answer:
                for start in range(0, len(outcome.reply), TOKEN_CHUNK_CHARS):
                    await _send(
                        websocket,
                        {
                            "type": "token",
                            "content": outcome.reply[start : start + TOKEN_CHUNK_CHARS],
                        },
                    )
                    await asyncio.sleep(TOKEN_DELAY_S)

            await _send(
                websocket,
                {
                    "type": "done",
                    "conversation_id": result.conversation_id,
                    "message_id": result.message_id,
                    "reply": outcome.reply,
                    "state": outcome.state.value,
                    "escalated": outcome.escalated,
                    "blocked": outcome.blocked,
                    "citations": [c.as_dict() for c in outcome.citations],
                    "ai_disclosure": AI_DISCLOSURE,
                },
            )

            drainer = getattr(websocket.app.state, "drainer", None)
            if drainer is not None:
                await drainer.note(context.tenant_id)

    except WebSocketDisconnect:
        log.info("stream_closed", agent=agent_key)
    except Exception as exc:  # a socket must not take the app down
        log.exception("stream_failed", agent=agent_key, error=str(exc))
        with_suppressed_close(websocket)


def _progress_sink(websocket: WebSocket) -> ProgressSink:
    """Forward the graph's progress events to the socket.

    Node names and tool names only — whatever the runner chose to report. This
    function deliberately adds nothing to what it is given: a transport that
    enriched a progress frame from the turn's state is a transport that decides
    what a shopper's browser may see, and that decision belongs where the data
    is, not where the socket is.
    """

    async def _emit(progress: Progress) -> None:
        await _send(websocket, {"type": progress.kind.value, "name": progress.name})

    return _emit


def with_suppressed_close(websocket: WebSocket) -> None:
    """Best-effort close. A socket already gone raises, and that is fine."""
    task = asyncio.get_running_loop().create_task(_close_quietly(websocket))
    task.add_done_callback(lambda _: None)


async def _close_quietly(websocket: WebSocket) -> None:
    # The peer may already be gone, which is not a failure worth reporting.
    with contextlib.suppress(Exception):
        await websocket.close(code=1011)


async def _send(websocket: WebSocket, frame: dict[str, Any]) -> None:
    await websocket.send_json(frame)


async def _send_error(
    websocket: WebSocket,
    exc: NeuraError,
    request_id: str,
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """Errors on the socket use the **same** envelope as REST.

    api-design.md §3 promises one error shape for every failure. A socket that
    invented a second one would make an integrator write two error handlers for
    one API, and the second would be the one that is never tested.
    """
    payload = exc.to_dict(request_id)
    if extra:
        payload["error"].update(extra)
    await _send(websocket, {"type": "error", **payload})


def _close_code(exc: NeuraError) -> int:
    return {
        401: CLOSE_UNAUTHENTICATED,
        403: CLOSE_FORBIDDEN,
        429: CLOSE_RATE_LIMITED,
    }.get(exc.http_status, 1008)


__all__ = [
    "CLOSE_FORBIDDEN",
    "CLOSE_RATE_LIMITED",
    "CLOSE_UNAUTHENTICATED",
    "IDLE_TIMEOUT_S",
    "TOKEN_CHUNK_CHARS",
    "run_streamed_turn",
]
