"""Grading what the agent would have said — the console's half. ADR-0026.

`routes/agent.py` already serves this queue at ``GET /v1/{agent}/shadow``, and
these endpoints are **not** a duplicate of it. They differ in the only way that
matters: who is allowed to call them.

    /v1/care/shadow           a bearer key held by a program, scope-checked
    /v1/console/shops/…/review  a session cookie held by a person, membership-checked

The agent routes cannot serve the console, and the shortcut that would let them
is the one [ADR-0026 §3](../../../../docs/architecture/adr/0026-the-merchant-console-and-the-first-human-in-the-system.md)
exists to refuse: mint a tenant API key at sign-in and let the browser use it.
That key carries the tenant's full machine authority into every extension, crash
report and screenshot the merchant ever takes. So the console gets its own door,
and behind it the *same* repository, the same table and the same RLS.

## What these add over the machine endpoints

The evidence. `routes/agent.py` returns the row as recorded — citations as
``type:id``, because that is what an integrator was promised (api-design.md §7).
A **human** grading a draft needs what those references point at, or they are
grading fluency ([console.md §3.2](../../../../docs/console.md), open question
**E7**). `neura_agent_core.review` assembles it; this module is transport.

## Three things not to add

**Sampling.** Every recorded turn is listed. **A4** is unanswered and shadow.py
already declines to invent a rate for it.

**A state filter that hides declines.** A turn the agent refused or escalated is
the interesting one. ADR-0020 made a withheld reply say so to the *shopper*; the
merchant-facing version of that mistake is a queue that quietly omits them.

**A number nobody measured.** ``cost_usd`` is zero both for a local model and
for a cloud model whose price is not configured (`neura_llm.pricing`), so it is
returned with a flag saying which — see :func:`_scorecard_payload`. Rendering
"$0.00" as a measurement would be CLAUDE.md §4 failing in the one place a
merchant reads numbers.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from neura_agent_core.conversations import ConversationState
from neura_agent_core.review import ReviewItem, ReviewQueue, evidence_payload, no_draft_reason
from neura_agent_core.shadow import ShadowRepository, ShadowVerdict
from neura_api.dependencies import acting_for
from neura_api.envelopes import decode_cursor, encode_cursor, envelope, page
from neura_core import NotFoundError, ValidationError, get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: A page of the queue. Smaller than the machine endpoint's 50 because every row
#: here carries its evidence, and a reviewer reads rows rather than streaming
#: them. Not a sampling rate: the cursor reaches every recorded turn.
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


class Grade(BaseModel):
    """One person's verdict on one withheld reply.

    No ``reviewed_by``. The machine endpoint takes it as a free string because
    it has no way to know who is calling; here the person is *the thing that was
    authenticated*, and accepting a name from the browser would let a reviewer
    sign somebody else's opinion.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: ShadowVerdict
    note: str = Field(default="", max_length=2000)


@router.get("/review/scorecard", summary="What this shop's shadow queue says so far")
async def scorecard(request: Request, tenant_id: str) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        # No `agent_key` filter: the console asks about the shop, and a merchant
        # running two agents has one queue to work through. Every count below is
        # a count, so summing across agents does not average anything away.
        card = await ShadowRepository(session).scorecard(actor.tenant_id)

    return envelope(
        _scorecard_payload(card),
        request_id=getattr(request.state, "request_id", None),
    )


#: The filters a reader narrows the queue by — shared by the page and its counts.
#: ``since``/``until`` are calendar days **in the reader's time zone** (``tz``),
#: because "today" in Colombo is not "today" in UTC for five and a half hours of
#: every day, and a date filter that disagreed with the dates on the screen would
#: be a wrong number wearing a right label.
Agent = Annotated[str | None, Query(max_length=64)]
Since = Annotated[date | None, Query()]
Until = Annotated[date | None, Query()]
Tz = Annotated[str, Query(max_length=64)]


@router.get("/review", summary="Turns awaiting a human verdict, with their evidence")
async def review_queue(
    request: Request,
    tenant_id: str,
    graded: Annotated[bool | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    verdict: Annotated[str | None, Query()] = None,
    agent: Agent = None,
    since: Since = None,
    until: Until = None,
    tz: Tz = "UTC",
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)
    start, end = _window(since, until, tz)
    filters = {
        "state": _state(state),
        "verdict": _verdict(verdict),
        # A key the API matches as data. It knows no agent's name, so an
        # unknown one is not refused — it matches nothing.
        "agent_key": (agent or "").strip() or None,
        "since": start,
        "until": end,
    }

    position = decode_cursor(cursor)
    before = (
        (datetime.fromisoformat(str(position["c"])), str(position["i"]))
        if position is not None
        else None
    )

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        # One extra row, to learn whether there is a next page without counting
        # the table. The extra row is dropped below and never rendered.
        items = await ReviewQueue(session).page(
            actor.tenant_id, graded=graded, before=before, limit=limit + 1, **filters
        )

    has_more = len(items) > limit
    items = items[:limit]
    last = items[-1].turn if items else None
    next_cursor = (
        encode_cursor({"c": last.created_at.isoformat(), "i": last.id})
        if has_more and last is not None and last.created_at is not None
        else None
    )

    return page(
        [_item_payload(item) for item in items],
        next_cursor=next_cursor,
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/review/counts", summary="How many turns match, by outcome and by verdict")
async def review_counts(
    request: Request,
    tenant_id: str,
    graded: Annotated[bool | None, Query()] = None,
    agent: Agent = None,
    since: Since = None,
    until: Until = None,
    tz: Tz = "UTC",
) -> dict[str, Any]:
    """The numbers beside the screen's filter buttons. Counts, never a rate."""
    actor = await acting_for(request, tenant_id)
    start, end = _window(since, until, tz)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        counts = await ShadowRepository(session).counts(
            actor.tenant_id,
            graded=graded,
            agent_key=(agent or "").strip() or None,
            since=start,
            until=end,
        )

    return envelope(
        {"total": counts.total, "by_state": counts.by_state, "by_verdict": counts.by_verdict},
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/review/{shadow_id}", summary="One turn, with its evidence")
async def review_item(request: Request, tenant_id: str, shadow_id: str) -> dict[str, Any]:
    """One turn by id — so a reply can be opened by a link, graded or not.

    404 for another tenant's turn and for one that does not exist, which under
    RLS are the same fact.
    """
    actor = await acting_for(request, tenant_id)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        item = await ReviewQueue(session).one(actor.tenant_id, shadow_id)
    if item is None:
        raise NotFoundError("No such turn.", details={"id": shadow_id})

    return envelope(
        _item_payload(item),
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/review/{shadow_id}/grade", summary="Record this person's verdict on one turn")
async def grade(request: Request, tenant_id: str, shadow_id: str, body: Grade) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        repository = ShadowRepository(session)
        recorded = await repository.grade(
            actor.tenant_id,
            shadow_id,
            verdict=body.verdict,
            note=body.note,
            # The **authenticated** person, not a name the browser supplied.
            # This is the first grade in this system that can answer "who
            # approved this?" with something that cannot be typed in.
            reviewed_by=actor.user_id,
        )
        if not recorded:
            raise NotFoundError("No such turn.", details={"id": shadow_id})
        item = await ReviewQueue(session).one(actor.tenant_id, shadow_id)

    log.info(
        "console_shadow_graded",
        tenant_id=actor.tenant_id,
        user_id=actor.user_id,
        shadow_id=shadow_id,
        verdict=body.verdict.value,
    )
    return envelope(
        _item_payload(item) if item else {},
        request_id=getattr(request.state, "request_id", None),
    )


def _item_payload(item: ReviewItem) -> dict[str, Any]:
    """One turn as a grader receives it.

    ``withheld`` is on every row and is always true — a ``shadow_turns`` row is
    by definition a reply no shopper saw. It is a field rather than something
    the screen infers, because ADR-0020's lesson was precisely that a client
    left to infer "there is nothing to show here" renders nothing at all.

    ``draft`` may legitimately be empty, on a turn the agent escalated or
    refused. ``no_draft_reason`` is what the screen says instead, and it is
    never empty when the draft is: an empty reply with no explanation is the
    error path ADR-0020 §4 forbids, and the merchant-facing version of it is
    a card that looks like a rendering bug.
    """
    turn = item.turn
    return {
        "id": turn.id,
        "conversation_id": turn.conversation_id,
        "agent": turn.agent_key,
        "created_at": turn.created_at.isoformat() if turn.created_at else None,
        "withheld": True,
        "mode": turn.mode,
        "question": {
            "text": item.question,
            # Both flags exist so the screen can tell "the shopper said nothing"
            # apart from "the transcript no longer holds what they said".
            "recorded": item.question_recorded,
            "asked_at": item.asked_at.isoformat() if item.asked_at else None,
        },
        "draft": turn.draft,
        "no_draft_reason": "" if item.has_draft else no_draft_reason(item.turn),
        "intent": turn.intent,
        "state": turn.state,
        "escalated": turn.escalated,
        "verify": {
            # `null` is a real value here — `verify` did not run, which is not
            # the same as it having failed.
            "grounded": turn.grounded,
            "reason": turn.verify_reason,
        },
        "evidence": [evidence_payload(piece) for piece in item.evidence],
        "tools": turn.tools,
        "cost": _cost_payload(turn.cost_usd),
        "latency_ms": turn.latency_ms,
        "llm_calls": turn.llm_calls,
        "tool_calls": turn.tool_calls,
        "prompt_revision": turn.prompt_revision,
        "verdict": turn.verdict.value if turn.verdict else None,
        "note": turn.note,
        "reviewed_by": turn.reviewed_by,
        "reviewed_at": turn.reviewed_at.isoformat() if turn.reviewed_at else None,
    }


def _window(
    since: date | None, until: date | None, tz: str
) -> tuple[datetime | None, datetime | None]:
    """Calendar days in ``tz`` → the instants that bound them: ``since`` from its
    first moment, ``until`` through its last. Refused rather than guessed: an
    unknown zone or a window that ends before it starts is a 400, because a
    silently corrected window is a different set of rows under the same label.
    """
    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError("Unknown time zone.", details={"tz": tz}) from None

    start = datetime.combine(since, time.min, zone) if since else None
    end = datetime.combine(until + timedelta(days=1), time.min, zone) if until else None
    if start is not None and end is not None and start >= end:
        raise ValidationError(
            "The first day is after the last day.",
            details={"since": str(since), "until": str(until)},
        )
    return start, end


def _state(value: str | None) -> str | None:
    """What the turn would have done — the conversation vocabulary, or a 400."""
    if value in (None, ""):
        return None
    try:
        return ConversationState(value).value
    except ValueError:
        raise ValidationError(
            "Unknown state.",
            details={"state": value, "expected": [s.value for s in ConversationState]},
        ) from None


def _verdict(value: str | None) -> ShadowVerdict | None:
    if value in (None, ""):
        return None
    try:
        return ShadowVerdict(value)
    except ValueError:
        raise ValidationError(
            "Unknown verdict.",
            details={"verdict": value, "expected": [v.value for v in ShadowVerdict]},
        ) from None


def _cost_payload(cost: Any) -> dict[str, Any]:
    """What this turn cost, and whether that figure means anything.

    ``PriceTable.cost`` returns zero for a **local** model and zero for a cloud
    model with no configured price, and those are entirely different facts
    (`neura_llm.pricing`). A screen that printed "$0.00" for both would be
    reporting a measurement in one case and a gap in the other, which is the
    exact failure CLAUDE.md §4 is about. The API cannot tell them apart from
    here either — so it reports the zero and says it is unattributed, and the
    screen declines to call it a cost.
    """
    return {"usd": str(cost), "measured": cost > 0}


def _scorecard_payload(card: Any) -> dict[str, Any]:
    """Counts first, and no rate without its denominator.

    Copied in shape from ``routes/agent.py`` deliberately rather than shared:
    the two are the same numbers today and are read by an integrator and a
    merchant respectively, and the first divergence should be a visible edit
    rather than a surprise in a helper both call.
    """
    return {
        "recorded": card.total,
        "graded": card.graded,
        "ungraded": card.ungraded,
        "verdicts": {
            "agree": card.agree,
            "disagree": card.disagree,
            "would_have_harmed": card.would_have_harmed,
        },
        # `null` until a human has graded something — not 0.0. An unreviewed
        # queue is not a queue that failed review, and dividing by `recorded`
        # would make this figure improve every time the agent ran.
        "agreement_rate": card.agreement_rate,
        # A boolean. There is no acceptable percentage of harmful answers about
        # a shopper's money, so the go-live question is "any?" (shadow.py).
        "harm_free": card.harm_free,
        "escalated": card.escalated,
        "cost": _cost_payload(card.cost_usd),
        "total_latency_ms": card.total_latency_ms,
    }


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "Grade", "router"]
