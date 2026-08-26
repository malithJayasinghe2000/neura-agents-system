"""What the agent actually said — the console's transcript screen. ADR-0026.

The read-only twin of `console_review.py`, and the distinction between the two
is the whole reason both exist:

    Review          what the agent **would** have said, and nobody saw
    Conversations   what the agent **did** say, and a shopper read

`shadow.py` keeps those in separate tables on purpose — a withheld draft written
into ``conversation_messages`` would become history, and the next turn would
answer as though the shopper had read it. This module reads the half that is
history.

## Two things this screen shows that a shadow row cannot

**The whole thread.** Grading judges one turn; a complaint is about a
conversation. A merchant reading "why did it say that?" needs the question
before the question.

**What the shopper experienced**, which is ``ConversationState`` and not the
agent's own outcome. Five values, and none of them collapses into another:
``blocked`` and ``escalated`` are both refusals and cost wildly different things
([ADR-0012](../../../../docs/architecture/adr/0012-blocking-is-about-cost.md)),
and ``shadowed`` is neither — nothing was resolved and no person was reached.

## The tokens, which are the thing to know before reading the code

Messages come back **as the guard left them**: ``[EMAIL_1]``, not an address.
``append_turn`` stores the shopper's words tokenised so that a transcript kept
under a merchant's retention policy does not become a long-term store of card
numbers (security-model.md §6.2), and the rehydrated text existed only in the
reply the shopper saw — it was never persisted anywhere, by anything.

**This contradicts [console.md §3.3](../../../../docs/console.md), which promises
the merchant unredacted PII, and the contradiction is recorded rather than
resolved here.** Deciding it means either rewriting that paragraph or reopening
security-model.md §6.2, and neither is a decision to make inside a route module.
Nothing in this file redacts anything; it returns what is stored, and the screen
says what the tokens are.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from neura_agent_core.conversations import (
    Conversation,
    ConversationRepository,
    ConversationState,
    Message,
)
from neura_api.dependencies import acting_for
from neura_api.envelopes import decode_cursor, encode_cursor, envelope, page
from neura_core import NotFoundError, ValidationError, get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

DEFAULT_LIMIT = 25
MAX_LIMIT = 100

#: How many messages one transcript returns. A bound rather than a judgement:
#: an unbounded thread is an unbounded response, and a conversation long enough
#: to hit this is a conversation with a different problem.
MAX_MESSAGES = 200


@router.get("/conversations", summary="This shop's conversations, newest first")
async def list_conversations(
    request: Request,
    tenant_id: str,
    state: Annotated[str | None, Query()] = None,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)
    wanted = _state(state)

    position = decode_cursor(cursor)
    before = (
        (datetime.fromisoformat(str(position["c"])), str(position["i"]))
        if position is not None
        else None
    )

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        rows = await ConversationRepository(session).list_for(
            actor.tenant_id, state=wanted, before=before, limit=limit + 1
        )

    has_more = len(rows) > limit
    rows = rows[:limit]
    last = rows[-1] if rows else None
    next_cursor = (
        encode_cursor({"c": last.updated_at.isoformat(), "i": last.id})
        if has_more and last is not None and last.updated_at is not None
        else None
    )

    return page(
        [_conversation_payload(row) for row in rows],
        next_cursor=next_cursor,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/conversations/{conversation_id}", summary="One transcript")
async def read_conversation(
    request: Request, tenant_id: str, conversation_id: str
) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        repository = ConversationRepository(session)
        conversation = await repository.get(actor.tenant_id, conversation_id)
        if conversation is None:
            # 404 for another tenant's conversation and for one that does not
            # exist, which under RLS are the same fact: the row is not visible,
            # not merely forbidden. Distinguishing them would make this endpoint
            # a way of asking whether an id exists somewhere else.
            raise NotFoundError("No such conversation.", details={"id": conversation_id})
        messages = await repository.messages(actor.tenant_id, conversation_id, limit=MAX_MESSAGES)

    return envelope(
        {
            **_conversation_payload(conversation),
            "messages": [_message_payload(message) for message in messages],
            # Stated rather than left for the client to count. A thread cut at
            # the bound must not look like a thread that ended.
            "truncated": len(messages) >= MAX_MESSAGES,
        },
        request_id=getattr(request.state, "request_id", None),
    )


def _state(value: str | None) -> ConversationState | None:
    """Parse the filter, or refuse it.

    An unrecognised state is a **400**, not a silently ignored parameter. Quietly
    dropping it returns every conversation while looking like a filtered list,
    which is the failure mode where a merchant concludes they have no escalations.
    """
    if value in (None, ""):
        return None
    try:
        return ConversationState(value)
    except ValueError:
        raise ValidationError(
            "Unknown conversation state.",
            details={"state": value, "expected": [s.value for s in ConversationState]},
        ) from None


def _conversation_payload(conversation: Conversation) -> dict[str, Any]:
    """One row in the list. **No message content** — listing a hundred
    conversations must not ship a hundred transcripts."""
    return {
        "id": conversation.id,
        "agent": conversation.agent_key,
        # What the *shopper* experienced. Five values and no collapsing:
        # `blocked` and `escalated` are both refusals costing different things,
        # and `shadowed` is neither.
        "state": conversation.state.value,
        "external_ref": conversation.external_ref,
        "channel": conversation.channel,
        "locale": conversation.locale,
        "turns": conversation.turns,
        "escalations": conversation.escalations,
        "started_at": conversation.started_at.isoformat() if conversation.started_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }


def _message_payload(message: Message) -> dict[str, Any]:
    """One message, **as it is stored**.

    Tokenised — see this module's docstring. Nothing here redacts and nothing
    here rehydrates; the second is not possible (the vault is per-turn and never
    persisted) and the first would be a silent second opinion about a decision
    the guard already made.
    """
    return {
        "id": message.id,
        "role": message.role.value,
        "content": message.content,
        "sequence": message.sequence,
        "intent": message.intent,
        # Present on the agent's message and `null` on the shopper's — the
        # per-turn outcome belongs to the reply, not to the question.
        "state": message.state.value if message.state else None,
        "citations": message.citations,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "MAX_MESSAGES", "router"]
