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

## Finding a conversation (2026-09-27)

A list of fifty-five states and timestamps is a list nobody can use, so each row
now carries **the shopper's first message** — one line, cut to
:data:`PREVIEW_CHARS` — and the list takes ``q`` (words the shopper wrote) and
``agent`` (which assistant held it). Its ``meta`` says how many match in all and
where this page sits among them, and carries a cursor for the page *before* this
one. Paging is still a keyset cursor (api-design.md §5): the position is
**counted** for the label, never used to fetch, so a conversation written between
two clicks can move the words by one but cannot skip or repeat a row.

## The held drafts, beside the history and never in it (2026-09-28)

A chat held in practice mode used to open on the shopper's question and nothing
else, with a sentence pointing at Review. The transcript now also returns
``held``: each draft from ``shadow_turns`` for this conversation, with the id of
the shopper message it answers and whether it is graded, so the screen can show
the draft under its question and link to that one reply in Review.

**They stay a separate field.** Merging a draft into ``messages`` is exactly the
mistake shadow.py's two tables exist to prevent — a draft is what the agent
*would* have said, and ``messages`` is what a shopper read. Grading stays in
Review, where the evidence sits beside the buttons (console.md §3.2).

**What a reply looked at, by name.** Each citation carries ``name``: the
product's, category's or policy's own title from the **synced** catalogue, as
Sold out reads it (never a call to the shop). ``null`` for a lookup, which has
no title, and for anything the synced catalogue does not hold.
## Who is waiting for the shop's answer (ADR-0062, 2026-10-11)

``?waiting=1`` narrows the list to chats whose handed-over shopper waits: an
address left in the chat box, or a signed-in customer, not yet answered. Each row
and transcript carries ``waiting`` (how the shop can reach them, since when, and
who answered), **never the address itself**: that needs ``shop:handovers:write``
and comes from ``console_handover.py``, so Conversations stays readable by
whoever reads chats without showing anyone's email.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from neura_agent_core.conversations import (
    Conversation,
    ConversationRepository,
    ConversationState,
    Message,
)
from neura_agent_core.review import no_draft_reason
from neura_agent_core.shadow import ShadowRepository, ShadowTurn
from neura_agent_core.waiting import WaitingAnswer, WaitingAnswerRepository
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import decode_cursor, encode_cursor, envelope, page
from neura_api.routes.console_people import who_made
from neura_commerce.sync.schema import synced_entities
from neura_core import NotFoundError, ValidationError, get_logger
from neura_core.identity.roles import CONVERSATIONS_READ

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

DEFAULT_LIMIT = 25
MAX_LIMIT = 100

#: How much of the shopper's first message a list row carries. A line to
#: recognise a thread by, not a transcript — a hundred rows must not ship a
#: hundred conversations.
PREVIEW_CHARS = 160

#: How many messages one transcript returns. A bound rather than a judgement:
#: an unbounded thread is an unbounded response, and a conversation long enough
#: to hit this is a conversation with a different problem.
MAX_MESSAGES = 200


@router.get("/conversations", summary="This shop's conversations, newest first")
async def list_conversations(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(CONVERSATIONS_READ))],
    state: Annotated[str | None, Query()] = None,
    agent: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    waiting: Annotated[bool, Query()] = False,
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    # One set of filters for the page, its count and its *Newer* cursor, so the
    # three can never describe different rows.
    matching: dict[str, Any] = {
        "state": _state(state),
        # An agent key is data here, never a branch: `neura-api` does not know
        # any agent's name, so an unknown key is not refused — it matches
        # nothing, which is what an honest filter on it would show.
        "agent": (agent or "").strip() or None,
        "search": (q or "").strip() or None,
        # Only the chats whose shopper waits for the shop's answer (ADR-0062).
        "waiting": waiting,
    }
    before = _position(decode_cursor(cursor))

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        repository = ConversationRepository(session)
        rows = await repository.list_for(
            actor.tenant_id, before=before, limit=limit + 1, **matching
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        questions = await repository.first_questions(actor.tenant_id, [row.id for row in rows])
        waits = await WaitingAnswerRepository(session).for_conversations(
            actor.tenant_id, [row.id for row in rows]
        )
        total = await repository.count_for(actor.tenant_id, **matching)
        offset = (
            await repository.count_for(actor.tenant_id, through=before, **matching)
            if before is not None
            else 0
        )
        previous = (
            await repository.cursor_for_page_before(
                actor.tenant_id, page_after=before, size=limit, **matching
            )
            if before is not None
            else None
        )

    last = rows[-1] if rows else None
    next_cursor = (
        _cursor((last.updated_at, last.id))
        if has_more and last is not None and last.updated_at is not None
        else None
    )

    return page(
        [
            {
                **_conversation_payload(row),
                "first_question": _preview(questions.get(row.id)),
                # Only while it waits: a row's badge, never the address.
                "waiting": _waiting_row(waits.get(row.id)),
            }
            for row in rows
        ],
        next_cursor=next_cursor,
        request_id=getattr(request.state, "request_id", None),
        # Counts for the words "26-50 of 55". `offset` is how many matching
        # conversations come before this page, not a way to fetch one.
        total=total,
        offset=offset,
        has_previous=offset > 0,
        # `null` with `has_previous` true means the page before is the first.
        previous_cursor=_cursor(previous) if previous is not None else None,
    )


@router.get("/conversations/{conversation_id}", summary="One transcript")
async def read_conversation(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(CONVERSATIONS_READ))],
    conversation_id: str,
) -> dict[str, Any]:
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
        held = await ShadowRepository(session).for_conversation(
            actor.tenant_id, conversation_id, limit=MAX_MESSAGES
        )
        names = await _names(session, actor.tenant_id, messages)
        waiting = await _waiting_transcript(
            session,
            actor.tenant_id,
            await WaitingAnswerRepository(session).get(actor.tenant_id, conversation_id),
        )

    return envelope(
        {
            **_conversation_payload(conversation),
            "messages": [_message_payload(message, names) for message in messages],
            # What the agent *would* have said, never merged into `messages`
            # (this module's docstring). Oldest first.
            "held": [_held_payload(turn) for turn in held],
            # How the shop can reach a handed-over shopper, and who answered
            # (ADR-0062). Never the address: that is `…/waiting`'s, behind
            # `shop:handovers:write`.
            "waiting": waiting,
            # Stated rather than left for the client to count. A thread cut at
            # the bound must not look like a thread that ended.
            "truncated": len(messages) >= MAX_MESSAGES,
        },
        request_id=getattr(request.state, "request_id", None),
    )


async def _names(
    session: AsyncSession, tenant_id: str, messages: Sequence[Message]
) -> dict[tuple[str, str], str]:
    """The synced catalogue's title for everything a reply cited, in one query.

    Keyed by ``(type, id)``: a citation's type is the synced entity's type
    (``product``, ``category``, ``policy``), and a tuple ``IN`` rather than two
    independent ``IN``s, because a product and a category can share an id.
    """
    wanted = {
        (str(citation.get("type", "")), str(citation.get("id", "")))
        for message in messages
        for citation in message.citations
        if citation.get("type") not in (None, "", "tool") and citation.get("id")
    }
    if not wanted:
        return {}

    entities = synced_entities.c
    rows = (
        await session.execute(
            select(entities.entity_type, entities.external_id, entities.document)
            .where(entities.tenant_id == tenant_id)
            .where(tuple_(entities.entity_type, entities.external_id).in_(sorted(wanted)))
        )
    ).all()
    names: dict[tuple[str, str], str] = {}
    for row in rows:
        # A product and a policy have a title; a category has a name.
        name = row.document.get("title") or row.document.get("name")
        if name:
            names[(str(row.entity_type), str(row.external_id))] = str(name)
    return names


def _waiting_row(wait: WaitingAnswer | None) -> dict[str, Any] | None:
    """A list row's *Waiting for an answer*: how, and since when. ``None`` once
    answered, or for a chat nobody waits on."""
    if wait is None or not wait.waiting:
        return None
    return {"reach": wait.reach.value, "since": wait.created_at.isoformat()}


async def _waiting_transcript(
    session: AsyncSession, tenant_id: str, wait: WaitingAnswer | None
) -> dict[str, Any] | None:
    """A transcript's waiting state: how the shop can reach the shopper, since
    when, and, once answered, when and by whom. Never the address."""
    if wait is None:
        return None
    return {
        "reach": wait.reach.value,
        "since": wait.created_at.isoformat(),
        "answered_at": wait.answered_at.isoformat() if wait.answered_at else None,
        "answered_by": await who_made(session, tenant_id, wait.answered_by)
        if wait.answered_by
        else None,
    }


def _position(decoded: dict[str, Any] | None) -> tuple[datetime, str] | None:
    if decoded is None:
        return None
    return datetime.fromisoformat(str(decoded["c"])), str(decoded["i"])


def _cursor(position: tuple[datetime, str]) -> str:
    moment, row_id = position
    return encode_cursor({"c": moment.isoformat(), "i": row_id})


def _preview(text: str | None) -> str | None:
    """One line of the shopper's first message, as stored — tokens included.

    ``None`` when the shopper never wrote, which the screen says in words
    rather than showing an empty line.
    """
    if text is None:
        return None
    line = " ".join(text.split())
    return line if len(line) <= PREVIEW_CHARS else line[: PREVIEW_CHARS - 1].rstrip() + "…"


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
    """One conversation, without its messages — listing a hundred conversations
    must not ship a hundred transcripts. The list adds one line of the first
    question on top of this (``first_question``); the transcript adds the rest."""
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


def _message_payload(
    message: Message, names: dict[tuple[str, str], str] | None = None
) -> dict[str, Any]:
    """One message, **as it is stored**.

    Tokenised — see this module's docstring. Nothing here redacts and nothing
    here rehydrates; the second is not possible (the vault is per-turn and never
    persisted) and the first would be a silent second opinion about a decision
    the guard already made.
    """
    names = names or {}
    return {
        "id": message.id,
        "role": message.role.value,
        "content": message.content,
        "sequence": message.sequence,
        "intent": message.intent,
        # Present on the agent's message and `null` on the shopper's — the
        # per-turn outcome belongs to the reply, not to the question.
        "state": message.state.value if message.state else None,
        # Each citation as stored, plus its catalogue title where one exists.
        "citations": [
            {
                **citation,
                "name": names.get((str(citation.get("type", "")), str(citation.get("id", "")))),
            }
            for citation in message.citations
        ],
        # Which service wrote this ([ADR-0031] §5). `null` on the shopper's own
        # message, and on anything stored before a message could say — the
        # console renders it only where it exists rather than filling the gap
        # from the conversation, which would be a guess dressed as a record.
        "agent": message.agent_key,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _held_payload(turn: ShadowTurn) -> dict[str, Any]:
    """One held draft, as much of it as the transcript shows.

    Only what reading the chat needs: the draft, which shopper message it
    answers, what it would have done, and whether it is graded. The evidence,
    the fact check and the cost stay in Review, where the grade is given.
    """
    return {
        "id": turn.id,
        # The shopper message this draft answers — `conversation_messages.id`.
        "message_id": turn.message_id,
        "agent": turn.agent_key,
        # What it *would* have done: the same values as a reply's `state`.
        "state": turn.state,
        "draft": turn.draft,
        # Never empty when the draft is (ADR-0020): an empty bubble reads as a bug.
        "no_draft_reason": "" if turn.draft.strip() else no_draft_reason(turn),
        "verdict": turn.verdict.value if turn.verdict else None,
        # A user id, compared by the screen with the reader's own.
        "reviewed_by": turn.reviewed_by,
        "reviewed_at": turn.reviewed_at.isoformat() if turn.reviewed_at else None,
        "created_at": turn.created_at.isoformat() if turn.created_at else None,
    }


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "MAX_MESSAGES", "PREVIEW_CHARS", "router"]
