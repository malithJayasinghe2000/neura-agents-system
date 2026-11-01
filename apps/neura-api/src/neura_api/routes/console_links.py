"""Links that count their clicks: ADR-0074's pages, console.md §3.15.

    GET    /v1/console/shops/{tenant_id}/links                          the Links page
    GET    /v1/console/shops/{tenant_id}/links/products                 Make a link's product chooser
    POST   /v1/console/shops/{tenant_id}/links                          Make a link
    DELETE /v1/console/shops/{tenant_id}/links/{link_id}                Remove
    POST   /v1/console/shops/{tenant_id}/calendar/plans/{plan_id}/links a plan's post link (Copy)

A plan's page shows each post's clicks from ``GET …/calendar/plans/{plan_id}``
(``post_links``), so this file holds only what the links do.

**The console's own route, not GROW's** (as the other GROW pages, G88): the
links live in the shared core (``neura_agent_core.links``) and ``neura-api``
may not learn an agent's name. A shop without GROW is not shown the pages (the
console checks its assistants).

**The Owner and Support** (R115, ``shop:links:write``); never the Developer.

**Where a link goes comes from the synced catalogue, never from the request**
(ADR-0074 §3): a body names a product by its id, and a product with no web page
of its own gets no link. A plan's post link is for one of **the plan's own
products** (R110); an own link, for any product the shop sells.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select

from neura_agent_core.calendar import CalendarRepository, calendar_plans
from neura_agent_core.links import (
    MAX_NAME_CHARS,
    POST_PLACES,
    Link,
    LinkRepository,
    Place,
    Post,
    short_link,
)
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_commerce.sync.schema import synced_entities
from neura_core import NotFoundError, ValidationError, get_logger, get_settings
from neura_core.identity.roles import LINKS_WRITE

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

Writer = Annotated[ConsoleActor, Depends(Permitted(LINKS_WRITE))]

#: The product chooser shows at most this many at a time; typing narrows it.
CHOOSER_LIMIT = 20
#: The order a campaign's posts are listed in: the order they are posted.
_POST_ORDER = (Post.TEASER, Post.LAUNCH, Post.EMAIL, Post.LAST_CHANCE)


class NewLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=255)
    place: Place
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)

    @field_validator("name")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("A name is needed.")
        return value


class PostLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post: Post
    place: Place
    product_id: str = Field(min_length=1, max_length=255)


# ── The Links page ───────────────────────────────────────────────────────────


@router.get("/links", summary="Links: the shop's own links, and its campaigns' links")
async def listed(request: Request, actor: Writer) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        found = await LinkRepository(session).listed(actor.tenant_id)
        catalogue = await _catalogue(session, actor.tenant_id, [link.product_id for link in found])
        plans = await _plans(session, actor.tenant_id, found)
    base = get_settings().links_base_url
    own = [link for link in found if link.post is None]
    return envelope(
        {
            "own": [_own(link, base, catalogue) for link in own],
            "campaigns": _campaigns([link for link in found if link.post], plans),
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/links/products", summary="Make a link: the products a link may open")
async def products(
    request: Request,
    actor: Writer,
    q: Annotated[str, Query(max_length=100)] = "",
) -> dict[str, Any]:
    title = synced_entities.c.document["title"].astext
    address = synced_entities.c.document["url"].astext
    status = synced_entities.c.document["status"].astext
    statement = (
        select(synced_entities.c.external_id, title.label("title"))
        .where(
            synced_entities.c.tenant_id == actor.tenant_id,
            synced_entities.c.entity_type == "product",
            address.op("~*")("^https?://"),
            or_(status.is_(None), status == "active"),
        )
        .order_by(func.lower(title), synced_entities.c.external_id)
        .limit(CHOOSER_LIMIT + 1)
    )
    if q.strip():
        statement = statement.where(title.ilike(f"%{_like(q.strip())}%", escape="\\"))
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        rows = (await session.execute(statement)).all()
    return envelope(
        {
            "products": [
                {"product_id": str(row.external_id), "title": row.title}
                for row in rows[:CHOOSER_LIMIT]
            ],
            "more": len(rows) > CHOOSER_LIMIT,
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/links", summary="Make a link for any product")
async def make(body: NewLink, request: Request, actor: Writer) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        catalogue = await _catalogue(session, actor.tenant_id, [body.product_id])
        product = _with_page(catalogue, body.product_id)
        made = await LinkRepository(session).make_own(
            actor.tenant_id,
            name=body.name,
            place=body.place,
            product_id=body.product_id,
            url=product["url"],
            by=actor.user_id,
        )
    log.info("console_link_made", tenant_id=actor.tenant_id, by=actor.user_id, place=made.place)
    return envelope(
        _own(made, get_settings().links_base_url, catalogue),
        request_id=getattr(request.state, "request_id", None),
    )


@router.delete("/links/{link_id}", summary="Remove a link: its clicks go, it keeps forwarding")
async def remove(
    request: Request,
    actor: Writer,
    link_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        removed = await LinkRepository(session).remove(
            actor.tenant_id, link_id, at=datetime.now(UTC)
        )
    if not removed:
        raise NotFoundError("No such link.", details={"id": link_id})
    log.info("console_link_removed", tenant_id=actor.tenant_id, by=actor.user_id)
    return envelope(
        {"removed": True, "id": link_id}, request_id=getattr(request.state, "request_id", None)
    )


# ── A plan's post link ───────────────────────────────────────────────────────


@router.post(
    "/calendar/plans/{plan_id}/links", summary="A plan's post link: made on the first Copy"
)
async def post_link(
    body: PostLink,
    request: Request,
    actor: Writer,
    plan_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> dict[str, Any]:
    if body.place not in POST_PLACES[body.post]:
        raise ValidationError(
            "This post has no link for that place.",
            code="NO_SUCH_PLACE",
            details={"post": body.post.value, "place": body.place.value},
        )
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        plan = await CalendarRepository(session).plan(actor.tenant_id, plan_id)
        if plan is None or plan.answer is None:
            raise NotFoundError("No such plan.", details={"id": plan_id})
        if body.product_id not in {str(i) for i in plan.answer.get("products") or []}:
            raise ValidationError(
                "A post's link opens one of the plan's products.",
                code="NOT_IN_PLAN",
                details={"product_id": body.product_id},
            )
        catalogue = await _catalogue(session, actor.tenant_id, [body.product_id])
        product = _with_page(catalogue, body.product_id)
        link = await LinkRepository(session).for_post(
            actor.tenant_id,
            date_key=plan.date_key,
            day=plan.day,
            campaign=plan.name,
            post=body.post,
            place=body.place,
            product_id=body.product_id,
            url=product["url"],
            by=actor.user_id,
        )
    return envelope(
        {
            "id": link.id,
            "link": short_link(get_settings().links_base_url, link.code),
            "post": link.post.value if link.post else None,
            "place": link.place.value,
            "product_id": link.product_id,
            "product_title": product.get("title"),
        },
        request_id=getattr(request.state, "request_id", None),
    )


# ── Shapes ───────────────────────────────────────────────────────────────────


def _own(link: Link, base: str, catalogue: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "id": link.id,
        "link": short_link(base, link.code),
        "name": link.name,
        "place": link.place.value,
        "product_id": link.product_id,
        "product_title": (catalogue.get(link.product_id) or {}).get("title"),
        "clicks": link.clicks,
        "made_at": link.created_at.isoformat(),
    }


def _campaigns(found: Sequence[Link], plans: Mapping[tuple[str, str], str]) -> list[dict[str, Any]]:
    """One entry per campaign (a date and its day), the latest day first (board 81)."""
    grouped: dict[tuple[str, str], list[Link]] = {}
    for link in found:
        if link.date_key is None or link.day is None:
            continue
        grouped.setdefault((link.date_key, link.day.isoformat()), []).append(link)
    campaigns = []
    for (date_key, day), members in grouped.items():
        posts: list[dict[str, Any]] = []
        total = 0
        for post in _POST_ORDER:
            mine = [link for link in members if link.post is post]
            if not mine:
                continue
            places = {place.value: 0 for place in POST_PLACES[post]}
            for link in mine:
                places[link.place.value] += link.clicks
            posts.append({"post": post.value, "places": places, "clicks": sum(places.values())})
            total += sum(places.values())
        campaigns.append(
            {
                "date_key": date_key,
                "day": day,
                # `listed` is newest first: the name the date had when last used.
                "name": members[0].campaign,
                "plan_id": plans.get((date_key, day)),
                "posts": posts,
                "clicks": total,
            }
        )
    return sorted(campaigns, key=lambda c: (c["day"], c["date_key"]), reverse=True)


# ── Reads ────────────────────────────────────────────────────────────────────


async def _plans(session: Any, tenant_id: str, found: Sequence[Link]) -> dict[tuple[str, str], str]:
    """The plans still kept for the campaigns listed: *See the plan* (R116)."""
    days = {link.day for link in found if link.day is not None}
    if not days:
        return {}
    rows = (
        await session.execute(
            select(calendar_plans.c.id, calendar_plans.c.date_key, calendar_plans.c.day).where(
                calendar_plans.c.tenant_id == tenant_id,
                calendar_plans.c.day.in_(sorted(days)),
                calendar_plans.c.answer.is_not(None),
            )
        )
    ).all()
    return {(row.date_key, row.day.isoformat()): row.id for row in rows}


async def _catalogue(session: Any, tenant_id: str, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Each product's name and page, from the synced catalogue."""
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(synced_entities.c.external_id, synced_entities.c.document).where(
                synced_entities.c.tenant_id == tenant_id,
                synced_entities.c.entity_type == "product",
                synced_entities.c.external_id.in_(sorted(set(ids))),
            )
        )
    ).all()
    found: dict[str, dict[str, Any]] = {}
    for row in rows:
        document = dict(row.document or {})
        url = document.get("url")
        found[str(row.external_id)] = {
            "title": document.get("title"),
            "url": url
            if isinstance(url, str) and url.lower().startswith(("http://", "https://"))
            else None,
        }
    return found


def _with_page(catalogue: Mapping[str, Mapping[str, Any]], product_id: str) -> Mapping[str, Any]:
    """The product, or a refusal: no link for a product we cannot open (§3)."""
    product = catalogue.get(product_id)
    if product is None:
        raise ValidationError(
            "No such product in your shop.",
            code="PRODUCT_NOT_FOUND",
            details={"product_id": product_id},
        )
    if not product.get("url"):
        raise ValidationError(
            "This product has no page in your shop to open.",
            code="NO_PRODUCT_PAGE",
            details={"product_id": product_id},
        )
    return product


def _like(value: str) -> str:
    """``value`` with ``LIKE``'s wildcards taken literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = ["router"]
