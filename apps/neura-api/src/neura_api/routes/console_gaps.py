"""What shoppers asked that the shop's pages do not say — ADR-0064's page.

    GET  /v1/console/shops/{tenant_id}/gaps          the page's rows
    POST /v1/console/shops/{tenant_id}/gaps/added    *I added it*

**The console's own route, not GROW's** (Sold out's pattern, G88): the rows live
in the shared core (``neura_agent_core.gaps``), only GROW's night job writes
them, and ``neura-api`` may not learn an agent's name. A shop without GROW has
no rows, and its menu shows no item.

**What it says** (console.md §3.11): the questions at least 2 shoppers asked in
30 days that the shop's data could not answer, grouped by product, with *About
your shop* apart; most asked first. Counts only, never who asked: no
conversation id leaves this route (*See the chats* is Conversations' ``?gap=``
filter, behind its own permission).

**A product's page address is shown only when it is http or https**: it comes
from the shop's synced catalogue, and the console opens it in a new tab.

**Paused** (ADR-0065): read from the switch a manifest says pauses this page
(``pauses``), so the route never names the assistant that owns it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from neura_agent_core.gaps import (
    GAP_DAYS,
    MAX_FACT_CHARS,
    MAX_PRODUCT_ID_CHARS,
    MIN_SHOPPERS,
    PAGE_GAPS,
    GapTopic,
    PageGapRepository,
    page_gaps,
)
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_commerce.sync.schema import synced_entities
from neura_core import NotFoundError, get_logger
from neura_core.identity.roles import GAPS_WRITE
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.switches import SwitchRepository

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])


class Added(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ``None`` for a question about the shop (*About your shop*).
    product_id: str | None = Field(default=None, max_length=MAX_PRODUCT_ID_CHARS)
    fact: str = Field(min_length=1, max_length=MAX_FACT_CHARS)


@router.get("/gaps", summary="What shoppers asked that the shop's pages do not say")
async def gaps(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(GAPS_WRITE))],
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=GAP_DAYS)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        topics = await PageGapRepository(session).topics(actor.tenant_id, since=since)
        ids = sorted({t.product_id for t in topics if t.product_id is not None})
        catalogue = await _catalogue(session, actor.tenant_id, ids)
        paused_since = await paused(request, session, actor.tenant_id)

    groups: dict[str, list[GapTopic]] = {}
    shop: list[GapTopic] = []
    for topic in topics:  # most asked first, so each group is too
        if topic.product_id is None:
            shop.append(topic)
        else:
            groups.setdefault(topic.product_id, []).append(topic)

    return envelope(
        {
            "days": GAP_DAYS,
            "min_shoppers": MIN_SHOPPERS,
            "paused_since": paused_since.isoformat() if paused_since else None,
            "total": len(topics),
            "groups": len(groups) + (1 if shop else 0),
            # In the order of each product's most asked question.
            "products": [
                {
                    "product_id": product_id,
                    "title": catalogue.get(product_id, {}).get("title"),
                    "url": _link(catalogue.get(product_id, {}).get("url")),
                    "topics": [_topic(t) for t in rows],
                }
                for product_id, rows in groups.items()
            ],
            "shop": [_topic(t) for t in shop],
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/gaps/added", summary="I added it: the question leaves the page")
async def added(
    body: Added,
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(GAPS_WRITE))],
) -> dict[str, Any]:
    fact = body.fact.strip()
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        asked = await session.scalar(
            select(func.count())
            .select_from(page_gaps)
            .where(
                page_gaps.c.tenant_id == actor.tenant_id,
                func.coalesce(page_gaps.c.product_id, "") == (body.product_id or ""),
                page_gaps.c.fact == fact,
            )
        )
        if not asked:
            raise NotFoundError("No such question.", details={"fact": fact})
        await PageGapRepository(session).mark_fixed(
            actor.tenant_id, product_id=body.product_id, fact=fact, by=actor.user_id
        )
    log.info("console_gap_added", tenant_id=actor.tenant_id, by=actor.user_id)
    return envelope(
        {"added": True, "product_id": body.product_id, "fact": fact},
        request_id=getattr(request.state, "request_id", None),
    )


async def paused(
    request: Request, session: Any, tenant_id: str, page: str = PAGE_GAPS
) -> datetime | None:
    """Since when ``page``'s finder is switched off for the shop, or ``None``.

    Only a switch of an assistant the shop has, which a manifest says pauses
    that page (ADR-0065 §4). *Shoppers asked for* reads it too (ADR-0068 §8).
    """
    tenant = await TenantRepository(session).get(tenant_id)
    if tenant is None:
        return None
    switches = SwitchRepository(session)
    for agent_key, discovered in (getattr(request.app.state, "agents", {}) or {}).items():
        if agent_key not in tenant.enabled_agents:
            continue
        for key, pages in (getattr(discovered.manifest, "pauses", None) or {}).items():
            if page not in pages or not key.startswith(f"{agent_key}."):
                continue
            switch = await switches.get(tenant_id, key)
            if switch is not None and not switch.on:
                return switch.changed_at
    return None


def _topic(topic: GapTopic) -> dict[str, Any]:
    return {
        "fact": topic.fact,
        "question": topic.question,
        "shoppers": topic.shoppers,
        "last_asked": topic.last_asked.isoformat(),
    }


def _link(url: Any) -> str | None:
    """The shop's own page address, only when the browser may open it as a link."""
    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
        return url
    return None


async def _catalogue(session: Any, tenant_id: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(synced_entities.c.external_id, synced_entities.c.document).where(
                synced_entities.c.tenant_id == tenant_id,
                synced_entities.c.entity_type == "product",
                synced_entities.c.external_id.in_(ids),
            )
        )
    ).all()
    return {row.external_id: dict(row.document or {}) for row in rows}


__all__ = ["paused", "router"]
