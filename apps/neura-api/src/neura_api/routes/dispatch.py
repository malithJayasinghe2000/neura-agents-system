"""``POST /v1/chat`` — the shopper does not choose the agent. [ADR-0031]

Every other chat route is mounted per agent, from that agent's own
``route_prefix``. This one is mounted once and names no agent at all: the
message arrives without a destination, the dispatcher reads the merchant's
enabled agents' *declarations*, and the turn runs on whichever one it picked.

**Why the per-agent routes stay.** They are an agent's own manifest-declared
prefix, they are what integrators and the eval harness address, and a
single-agent embed has nothing to dispatch. ADR-0031 adds a door; it closes
none.

**Everything after the choice is the existing code path**, deliberately.
``agent_context`` does the scope check and the entitlement check, ``_turn_input``
builds the turn, ``TurnService`` runs it, ``_chat_payload`` renders it. A second
assembly of the same turn is exactly what api-design.md §8 forbids for the
socket, and the reason holds here too: an eval result would otherwise be
evidence about one door only.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response
from starlette.websockets import WebSocket

from neura_api import idempotency as idem
from neura_api.dependencies import agent_context, authenticate_request
from neura_api.ratelimit import enforce
from neura_api.routes.agent import ChatRequest, _chat_payload, _rate_limit, _turn_input
from neura_api.stream import run_streamed_turn
from neura_core import get_logger
from neura_core.errors import ForbiddenError, NeuraError
from neura_dispatch.candidates import enabled_candidates
from neura_dispatch.chooser import NoCandidatesError, choose

log = get_logger(__name__)

router = APIRouter(tags=["dispatch"])


class NoAgentsEnabledError(ForbiddenError):
    """The tenant has no installed agent enabled, so nothing can answer.

    A provisioning fault, and reported as one. It is deliberately not the same
    error as "the agent you named is not enabled" (``AGENT_NOT_ENABLED``): that
    one tells a caller their URL was wrong, and this one tells an operator the
    account was never finished.
    """

    code = "NO_AGENTS_ENABLED"


@router.post(
    "/chat",
    summary="Send one message; the server chooses which agent answers",
    response_model=None,
    responses={
        401: {"description": "Missing or invalid API key"},
        403: {"description": "No enabled agent, or the key lacks the chosen agent's scope"},
        409: {"description": "Idempotency-Key reused with a different body"},
        429: {"description": "Rate limited"},
    },
)
async def dispatch_chat(
    request: Request,
    body: ChatRequest,
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias=idem.HEADER)] = None,
) -> dict[str, Any]:
    """Choose an agent for this message, then run it.

    Authentication happens **before** the choice and the agent's own scope check
    happens **after** it, which is the one ordering difference from the per-agent
    route. It cannot be otherwise: the scope to require is named after the agent,
    and the agent is not known until the message has been read.
    """
    caller = await authenticate_request(request)

    # Only agents the merchant actually pays for are candidates. ADR-0031 §3
    # promises a single-agent shop costs nothing new, and that promise lives
    # here: with one candidate `choose` returns without calling a model.
    #
    # §4's "a question for an agent they have not bought" is then answered by
    # the agent that *is* enabled — SELL classifies an order question
    # `needs_person` and hands it over — rather than by this route silently
    # running an agent the shop never bought.
    candidates = enabled_candidates(caller.tenant.enabled_agents)
    if not candidates:
        raise NoAgentsEnabledError(
            "This account has no agent enabled, so no message can be answered.",
            details={"tenant": caller.tenant_id},
        )

    try:
        decision = await choose(
            request.app.state.llm,
            body.message,
            candidates,
            history=None,
        )
    except NoCandidatesError as exc:  # pragma: no cover - guarded directly above
        raise NoAgentsEnabledError(str(exc)) from exc

    if decision.agent is None:
        # The model would not name a candidate. Not a guess, and not a silent
        # fallback to whichever agent happens to sort first — either would send
        # a shopper somewhere nobody chose. The first candidate *is* used, and
        # it is used loudly: logged, and the agent's own router still decides
        # whether it can answer or must hand over.
        log.warning(
            "dispatch_undecided",
            tenant_id=caller.tenant_id,
            candidates=[c.key for c in candidates],
            reason=decision.reason,
        )
        chosen = candidates[0].key
    else:
        chosen = decision.agent

    log.info(
        "dispatch_route",
        tenant_id=caller.tenant_id,
        agent=chosen,
        confidence=decision.confidence,
        trivial=decision.trivial,
        candidates=[c.key for c in candidates],
    )

    # From here it is the per-agent route's own path, including its scope and
    # entitlement checks. A key that may not write to the chosen agent's chat is
    # a provisioning fault and is reported as one rather than quietly rerouted:
    # rerouting would make a misconfigured key look like a working one.
    context = await agent_context(request, chosen, scopes=(f"{chosen}:chat:write",))

    verdict = await _rate_limit(request, context.caller, body.conversation_id)
    response.headers.update(verdict.headers())
    enforce(verdict)

    turn = _turn_input(request, context.caller, chosen, body)

    idempotency = request.app.state.idempotency
    claim, replay = await idempotency.claim(
        context.tenant_id,
        key=idempotency_key,
        endpoint=f"POST {request.url.path}",
        body=await request.body(),
        request_id=getattr(request.state, "request_id", ""),
    )
    if replay is not None:
        response.status_code = replay.status
        response.headers[idem.REPLAYED_HEADER] = "true"
        replayed: dict[str, Any] = replay.body
        return replayed

    try:
        result = await request.app.state.turns.run(context.runner, turn)
    except NeuraError:
        await idempotency.release(claim)
        raise
    except Exception:
        await idempotency.release(claim)
        raise

    payload = _chat_payload(request, result)
    # Which agent answered. The client does not need it to render the reply, and
    # the merchant's console does need it — a conversation that moved between
    # services is one thread with each message marked (ADR-0031 §5).
    payload.setdefault("data", {})
    if isinstance(payload.get("data"), dict):
        payload["data"]["agent"] = chosen

    await idempotency.complete(claim, status=200, body=payload)
    return payload


@router.websocket("/stream")
async def dispatch_stream(
    websocket: WebSocket, token: Annotated[str | None, Query()] = None
) -> None:
    """The dispatched turn over a socket, with progress frames.

    ``agent_key=None`` is what makes it dispatched: an agent is chosen **per
    message**, so a conversation that changes subject changes service with it
    ([ADR-0031] §5). Everything else — the frames, their order, and ADR-0016's
    rule that no model-generated text is sent before ``verify`` has passed — is
    the named socket's own code, unchanged.
    """
    await run_streamed_turn(websocket, agent_key=None, token=token)


__all__ = ["NoAgentsEnabledError", "router"]
