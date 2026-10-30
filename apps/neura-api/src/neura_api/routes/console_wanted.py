"""What shoppers asked for that the shop does not sell — ADR-0068's page.

    GET  /v1/console/shops/{tenant_id}/wanted          the page's rows
    POST /v1/console/shops/{tenant_id}/wanted/hidden   *Hide*
    DELETE …/wanted/hidden/{label}                     *Show again* (ADR-0070)

**The console's own route, not GROW's** (as *Missing from your pages*, G88): the
rows live in the shared core (``neura_agent_core.wanted``), only GROW's night job
writes them, and ``neura-api`` may not learn an agent's name. A shop without
GROW has no rows, and its menu shows no item.

**What it says** (ADR-0068 §2, §3): the things at least 2 shoppers asked for in
30 days that the shop does not sell, most asked first. Counts only, never who
asked: no conversation id leaves this route (*See the chats* is Conversations'
``?wanted=`` filter, behind this same permission).

**The Owner only** (R61): what to sell is the owner's decision, as Sold out.

**Paused** (ADR-0065, ADR-0068 §8): the night check's switch pauses this page
too, read from the manifests as *Missing from your pages* reads it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from neura_agent_core.gaps import GAP_DAYS, MIN_SHOPPERS
from neura_agent_core.wanted import (
    MAX_LABEL_CHARS,
    WANTED_ITEMS,
    HiddenTopic,
    WantedRepository,
    WantedTopic,
    wanted_items,
)
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_api.routes.console_gaps import paused
from neura_core import NotFoundError, get_logger
from neura_core.identity.roles import WANTED_READ

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])


class Hidden(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=MAX_LABEL_CHARS)


@router.get("/wanted", summary="What shoppers asked for that the shop does not sell")
async def wanted(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(WANTED_READ))],
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=GAP_DAYS)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = WantedRepository(session)
        topics = await repository.topics(actor.tenant_id, since=since)
        hidden_topics = await repository.hidden(actor.tenant_id, since=since)
        paused_since = await paused(request, session, actor.tenant_id, WANTED_ITEMS)

    return envelope(
        {
            "days": GAP_DAYS,
            "min_shoppers": MIN_SHOPPERS,
            "paused_since": paused_since.isoformat() if paused_since else None,
            "total": len(topics),
            "items": [_topic(t) for t in topics],
            "hidden": [_hidden(t) for t in hidden_topics],
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/wanted/hidden", summary="Hide: the thing leaves the page until asked for again")
async def hidden(
    body: Hidden,
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(WANTED_READ))],
) -> dict[str, Any]:
    label = body.label.strip()
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        asked = await session.scalar(
            select(func.count())
            .select_from(wanted_items)
            .where(wanted_items.c.tenant_id == actor.tenant_id, wanted_items.c.label == label)
        )
        if not asked:
            raise NotFoundError("No such thing.", details={"label": label})
        await WantedRepository(session).hide(actor.tenant_id, label=label, by=actor.user_id)
    log.info("console_wanted_hidden", tenant_id=actor.tenant_id, by=actor.user_id)
    return envelope(
        {"hidden": True, "label": label},
        request_id=getattr(request.state, "request_id", None),
    )


@router.delete("/wanted/hidden/{label}", summary="Show again: forget the Hide")
async def show_again(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(WANTED_READ))],
    label: Annotated[str, Path(min_length=1, max_length=MAX_LABEL_CHARS)],
) -> dict[str, Any]:
    label = label.strip()
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        forgotten = await WantedRepository(session).show_again(actor.tenant_id, label=label)
    if not forgotten:
        raise NotFoundError("Not hidden.", details={"label": label})
    log.info("console_wanted_shown_again", tenant_id=actor.tenant_id, by=actor.user_id)
    return envelope(
        {"hidden": False, "label": label},
        request_id=getattr(request.state, "request_id", None),
    )


def _hidden(topic: HiddenTopic) -> dict[str, Any]:
    return {
        "label": topic.label,
        "question": topic.question,
        "shoppers": topic.shoppers,
        "last_asked": topic.last_asked.isoformat(),
        "hidden_at": topic.hidden_at.isoformat(),
    }


def _topic(topic: WantedTopic) -> dict[str, Any]:
    return {
        "label": topic.label,
        "question": topic.question,
        "shoppers": topic.shoppers,
        "last_asked": topic.last_asked.isoformat(),
    }


__all__ = ["router"]
