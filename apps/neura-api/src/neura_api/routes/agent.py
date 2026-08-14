"""The routes every agent gets, mounted once per installed agent.

``/v1/care/chat`` exists because CARE's manifest says ``route_prefix="/v1/care"``,
not because anything here knows the word "care". Adding agent #2 adds its routes,
its OpenAPI section and its entitlement check with no edit to this file — which is
the same discipline that keeps ``neura_agent_core`` and ``neura_evals`` ignorant of
agent names, applied to the deployable.

The four endpoints are api-design.md §7 and §8:

    POST /chat                          one turn
    WS   /stream                        the same turn, streamed (ADR-0016)
    GET  /conversations                 cursor-paginated, filterable by state
    GET  /conversations/{id}            one transcript

**Chat and stream share one code path** — both build a ``TurnInput`` and hand it
to ``TurnService``. api-design.md §8 requires it ("the transport is never allowed
to become a second code path"), and the practical reason is that the golden suite
measures one agent: if the socket ran a second assembly of the same graph, an
eval result would be evidence about REST only.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocket

from neura_agent_core.conversations import ConversationRepository, ConversationState
from neura_api import idempotency as idem
from neura_api.dependencies import agent_context, client_address
from neura_api.envelopes import decode_cursor, encode_cursor, envelope, page
from neura_api.ratelimit import enforce, subjects_for
from neura_api.stream import run_streamed_turn
from neura_api.turns import TurnInput, TurnResult
from neura_core import (
    ForbiddenError,
    NeuraError,
    NotFoundError,
    ValidationError,
    get_logger,
)
from neura_core.tenancy import ApiKeyKind, AuthenticatedCaller

log = get_logger(__name__)

#: EU AI Act Article 50 (blueprint-v2 §9). Present on **every** chat response,
#: not only the first: a client that renders one message at a time would
#: otherwise show it once and never again, and the obligation is that the person
#: knows they are talking to a machine — which is a property of the conversation,
#: not of its first frame.
AI_DISCLOSURE = "You are chatting with an AI assistant."

MAX_MESSAGE_CHARS = 4000


class CustomerRef(BaseModel):
    """What the merchant's own server has already authenticated.

    **Refused on a public key**, in the route. A browser cannot be trusted to
    name its own customer, and a session that accepted it would make every order
    in the shop readable by anyone who guessed an email address — the exact
    enumeration the ownership gate exists to stop.
    """

    model_config = ConfigDict(extra="forbid")

    external_id: str | None = None
    email: str | None = None


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    #: Omit to start a new conversation. Server-issued and unguessable; a
    #: client's own identifier goes in ``external_ref`` instead (open question
    #: P2, and this is the "leaning server-issued with an optional external_ref"
    #: it proposed).
    conversation_id: str | None = None
    external_ref: str | None = Field(default=None, max_length=128)
    customer: CustomerRef | None = None
    channel: str = Field(default="web", max_length=32)
    locale: str = Field(default="en", max_length=16)


class Citation(BaseModel):
    type: str
    id: str


class ChatData(BaseModel):
    conversation_id: str
    message_id: str
    reply: str
    state: ConversationState
    escalated: bool
    blocked: bool
    citations: list[Citation]
    ai_disclosure: str = AI_DISCLOSURE


def build_router(agent_key: str) -> APIRouter:
    """Every route one agent needs, bound to its key."""
    router = APIRouter(tags=[agent_key])

    @router.post(
        "/chat",
        summary="Send one message and get the agent's reply",
        response_model=None,
        responses={
            401: {"description": "Missing or invalid API key"},
            403: {"description": "Scope missing, or the tenant has not enabled this agent"},
            409: {"description": "Idempotency-Key reused with a different body"},
            429: {"description": "Rate limited"},
        },
    )
    async def chat(
        request: Request,
        body: ChatRequest,
        response: Response,
        idempotency_key: Annotated[str | None, Header(alias=idem.HEADER)] = None,
    ) -> dict[str, Any]:
        context = await agent_context(request, agent_key, scopes=(f"{agent_key}:chat:write",))
        verdict = await _rate_limit(request, context.caller, body.conversation_id)
        response.headers.update(verdict.headers())
        enforce(verdict)

        turn = _turn_input(request, context.caller, agent_key, body)

        idempotency = request.app.state.idempotency
        claim, replay = await idempotency.claim(
            context.tenant_id,
            key=idempotency_key,
            endpoint=f"POST {request.url.path}",
            # The **raw** body, byte for byte. Re-serialising the parsed model
            # changes key order and whitespace, so two identical retries would
            # fingerprint differently and the replay would become a 409 — the
            # least helpful outcome for a client that did everything right.
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
            # The key goes back: a failed turn has no response to replay, and
            # holding it would refuse the client's legitimate retry for a day.
            await idempotency.release(claim)
            raise
        except Exception:
            await idempotency.release(claim)
            raise

        await _note_webhooks(request, context.tenant_id)
        payload = _chat_payload(request, result)
        await idempotency.complete(claim, status=200, body=payload)
        return payload

    @router.websocket("/stream")
    async def stream(websocket: WebSocket, token: Annotated[str | None, Query()] = None) -> None:
        """One turn over a socket, with progress frames and a verified reply.

        The credential arrives as a query parameter because a browser's
        ``WebSocket`` constructor cannot set headers. That is the only difference
        between this and ``POST /chat``; everything after authentication is the
        same objects in the same order.

        **No model-generated text is sent before ``verify`` has passed**
        (ADR-0016). ``token`` frames carry slices of the *verified* reply.
        """
        await run_streamed_turn(websocket, agent_key=agent_key, token=token)

    @router.get("/conversations", summary="List conversations, newest first")
    async def list_conversations(
        request: Request,
        state: Annotated[ConversationState | None, Query()] = None,
        cursor: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        context = await agent_context(
            request, agent_key, scopes=(f"{agent_key}:conversations:read",)
        )
        position = decode_cursor(cursor)
        before = None
        if position is not None:
            from datetime import datetime

            before = (datetime.fromisoformat(str(position["u"])), str(position["i"]))

        db = request.app.state.database
        async with db.tenant_session(context.tenant_id) as session:
            # One extra row, discarded: that is how "is there a next page?" is
            # answered without a second COUNT query that can disagree with the
            # page it describes.
            rows = await ConversationRepository(session).list_for(
                context.tenant_id, state=state, before=before, limit=limit + 1
            )

        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            encode_cursor({"u": rows[-1].updated_at.isoformat(), "i": rows[-1].id})
            if has_more and rows and rows[-1].updated_at is not None
            else None
        )
        return page(
            [_conversation_payload(c) for c in rows],
            next_cursor=next_cursor,
            request_id=getattr(request.state, "request_id", None),
        )

    @router.get("/conversations/{conversation_id}", summary="One conversation and its transcript")
    async def get_conversation(request: Request, conversation_id: str) -> dict[str, Any]:
        context = await agent_context(
            request, agent_key, scopes=(f"{agent_key}:conversations:read",)
        )
        db = request.app.state.database
        async with db.tenant_session(context.tenant_id) as session:
            repository = ConversationRepository(session)
            conversation = await repository.get(context.tenant_id, conversation_id)
            if conversation is None:
                raise NotFoundError(
                    "No such conversation.", details={"conversation_id": conversation_id}
                )
            messages = await repository.messages(context.tenant_id, conversation_id)

        return envelope(
            {
                **_conversation_payload(conversation),
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role.value,
                        "content": m.content,
                        "intent": m.intent,
                        "state": m.state.value if m.state else None,
                        "citations": m.citations,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in messages
                ],
            },
            request_id=getattr(request.state, "request_id", None),
        )

    return router


# ── Shared with the socket transport ─────────────────────────────────────────


def _turn_input(
    request: Request | WebSocket,
    caller: AuthenticatedCaller,
    agent_key: str,
    body: ChatRequest,
) -> TurnInput:
    """Build the transport-neutral turn, and refuse the one thing a browser
    must not be allowed to assert."""
    customer_external_id = body.customer.external_id if body.customer else None

    if customer_external_id and caller.api_key.kind is ApiKeyKind.PUBLIC:
        raise ForbiddenError(
            "A public key may not assert a customer identity. Identify the "
            "shopper from your server with a secret key.",
            code="IDENTITY_NOT_PERMITTED",
        )

    if body.conversation_id and not body.conversation_id.startswith("cnv_"):
        raise ValidationError(
            "conversation_id must be a value this API issued.",
            details={"field": "conversation_id"},
        )

    return TurnInput(
        caller=caller,
        agent_key=agent_key,
        message=body.message,
        conversation_id=body.conversation_id,
        customer_external_id=customer_external_id,
        external_ref=body.external_ref,
        channel=body.channel,
        locale=body.locale,
        trace_id=str(getattr(getattr(request, "state", None), "request_id", "") or ""),
    )


async def _rate_limit(
    request: Request | WebSocket,
    caller: AuthenticatedCaller,
    conversation_id: str | None,
) -> Any:
    limiter = request.app.state.limiter
    return await limiter.check(
        subjects_for(caller, client=client_address(request), conversation_id=conversation_id)
    )


def _chat_payload(request: Request | WebSocket, result: TurnResult) -> dict[str, Any]:
    """What the caller is told.

    ``reply`` and ``state`` come from the :class:`TurnResult`, not from the
    outcome underneath it, and on a shadowed turn those differ: the reply is
    empty and the state is ``shadowed`` (agent-runtime.md §6). ``escalated`` and
    ``blocked`` still describe what the *agent* did, because a merchant reading
    their own shadow traffic wants to know that it would have escalated — the
    difference between "would have" and "did" is carried by ``state``, in one
    place, rather than by three fields that could disagree.
    """
    outcome = result.outcome
    return envelope(
        ChatData(
            conversation_id=result.conversation_id,
            message_id=result.message_id,
            reply=result.reply,
            state=result.state,
            escalated=outcome.escalated,
            blocked=outcome.blocked,
            citations=[Citation(type=c.type, id=c.id) for c in outcome.citations],
        ).model_dump(mode="json"),
        request_id=str(getattr(getattr(request, "state", None), "request_id", "") or ""),
    )


def _conversation_payload(conversation: Any) -> dict[str, Any]:
    """A conversation, as an integrator sees it.

    No message content: listing a hundred conversations must not ship a hundred
    transcripts, and a merchant's dashboard that wants one asks for it by id.
    """
    return {
        "id": conversation.id,
        "agent": conversation.agent_key,
        "state": conversation.state.value,
        "external_ref": conversation.external_ref,
        "channel": conversation.channel,
        "locale": conversation.locale,
        "turns": conversation.turns,
        "escalations": conversation.escalations,
        "started_at": conversation.started_at.isoformat() if conversation.started_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }


async def _note_webhooks(request: Request | WebSocket, tenant_id: str) -> None:
    """Tell the drainer this tenant has queued work.

    After the turn's transaction, never inside it: an index entry written for a
    transaction that then rolled back would send the drainer looking for rows
    that do not exist.
    """
    drainer = getattr(request.app.state, "drainer", None)
    if drainer is not None:
        await drainer.note(tenant_id)


__all__ = [
    "AI_DISCLOSURE",
    "MAX_MESSAGE_CHARS",
    "ChatRequest",
    "build_router",
]
