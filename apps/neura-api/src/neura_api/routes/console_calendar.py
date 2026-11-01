"""The Marketing calendar — ADR-0072's page, console.md §3.14.

    GET    /v1/console/shops/{tenant_id}/calendar                      the page: Coming up
    GET    /v1/console/shops/{tenant_id}/calendar/dates                This year's dates
    PUT    /v1/console/shops/{tenant_id}/calendar/dates                Save this year's dates
    POST   /v1/console/shops/{tenant_id}/calendar/dates/own            Add an own date
    DELETE /v1/console/shops/{tenant_id}/calendar/dates/own/{date_id}  Remove it
    GET    /v1/console/shops/{tenant_id}/calendar/plans/{plan_id}      a plan
    PUT    /v1/console/shops/{tenant_id}/calendar/plans/{plan_id}/texts   Save an edit
    POST   /v1/console/shops/{tenant_id}/calendar/plans/{plan_id}/again   Make it again

**The console's own route, not GROW's** (as the other GROW pages, G88): the dates
and plans live in the shared core (``neura_agent_core.calendar``), only GROW's
night run writes a plan, and ``neura-api`` may not learn an agent's name. A shop
without GROW is not shown the page (the console checks its assistants).

**The Owner and Support** (R86, ``shop:calendar:write``); never the Developer.

**What comes from where** (ADR-0072 §5): the dates and their days from code, the
products' names, photos, prices and links from the synced catalogue, the counts
from the stored plan, the schedule from :func:`post_days`; only the theme, the
idea and the drafts are the model's words, after the checks.

**Every write books the shop's daily jobs** (a no-op when they are booked), so
GROW's night run reaches a shop with no chats (ADR-0072 §8, R96). *Make it
again* books the job a manifest's ``on_demand`` names for this page, to run at
once (R95), and is refused while FiveNeurals has paused the plans.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from neura_agent_core.calendar import (
    CALENDAR_PLANS,
    COMING_UP_MONTHS,
    MAX_EDIT_CHARS,
    MAX_NAME_CHARS,
    PLAN_DAYS_BEFORE,
    QUIET_MONTHS,
    SUGGESTED_BY_KEY,
    TEXT_FIELDS,
    TIME_ZONES,
    CalendarRepository,
    Country,
    Group,
    Occurrence,
    Plan,
    PlanState,
    add_months,
    kept_occurrences,
    post_days,
    shop_today,
    suggested_for,
    this_years_list,
    year_saved,
)
from neura_agent_core.links import LinkRepository, Post, PostClicks
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_api.jobs.daily import book_daily_jobs
from neura_api.routes.console_gaps import paused
from neura_commerce.sync.schema import synced_entities
from neura_core import ConflictError, NotFoundError, ValidationError, get_logger
from neura_core.identity import role_may
from neura_core.identity.roles import CALENDAR_WRITE, GAPS_WRITE, LINKS_WRITE, WANTED_READ
from neura_core.jobs import JobQueue
from neura_core.tenancy import TenantRepository

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

Writer = Annotated[ConsoleActor, Depends(Permitted(CALENDAR_WRITE))]

#: The furthest ahead an own date may be added: the end of next year.
_AHEAD_YEARS = 1


class DateChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=32)
    kept: bool
    #: A moving date's day, set by the owner (AD12: *you can set one yourself*).
    day: date | None = None


class OwnChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    kept: bool


class SaveDates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country: Country = Country.SRI_LANKA
    dates: list[DateChoice] = Field(default_factory=list, max_length=50)
    own: list[OwnChoice] = Field(default_factory=list, max_length=200)


class NewOwnDate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    day: date
    every_year: bool = False


class Texts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    texts: dict[str, str] = Field(min_length=1, max_length=len(TEXT_FIELDS))


# ── The page: Coming up ──────────────────────────────────────────────────────


@router.get("/calendar", summary="The Marketing calendar: the kept dates coming up")
async def calendar(request: Request, actor: Writer) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = CalendarRepository(session)
        country = await repository.country(actor.tenant_id)
        today = shop_today(country, now)
        rows = await repository.rows(actor.tenant_id)
        plans = await repository.plans(actor.tenant_id, since=today)
        paused_since = await paused(request, session, actor.tenant_id, CALENDAR_PLANS)

    coming = kept_occurrences(rows, country, start=today, end=add_months(today, COMING_UP_MONTHS))
    by_date = {(plan.date_key, plan.day): plan for plan in plans}
    return envelope(
        {
            "today": today.isoformat(),
            "country": country.value,
            "time_zone": TIME_ZONES[country],
            "year": today.year,
            "saved": year_saved(rows, today.year),
            "plan_days_before": PLAN_DAYS_BEFORE,
            "paused_since": paused_since.isoformat() if paused_since else None,
            "coming_up": [
                _occurrence(o, by_date, today=today, paused=paused_since is not None)
                for o in coming
            ],
        },
        request_id=getattr(request.state, "request_id", None),
    )


def _occurrence(
    occurrence: Occurrence,
    plans: Mapping[tuple[str, date], Plan],
    *,
    today: date,
    paused: bool,
) -> dict[str, Any]:
    day = occurrence.day
    plan = plans.get((occurrence.date_key, day)) if day is not None else None
    if day is None:
        status = "not_set"
    elif plan is not None:
        status = plan.state.value
    elif occurrence.plan_day is not None and occurrence.plan_day <= today:
        # Due and not made yet: the night run makes it (R94), unless paused.
        status = "paused" if paused else "tonight"
    else:
        status = "planned"
    return {
        "date_key": occurrence.date_key,
        "key": occurrence.key,
        "name": occurrence.name,
        "line": occurrence.line,
        "own": occurrence.own_id is not None,
        "every_year": occurrence.every_year,
        "day": day.isoformat() if day else None,
        "usually": list(occurrence.usually),
        "days_left": (day - today).days if day else None,
        "plan_day": occurrence.plan_day.isoformat() if occurrence.plan_day else None,
        "status": status,
        "plan_id": plan.id if plan is not None else None,
    }


# ── This year's dates ────────────────────────────────────────────────────────


@router.get("/calendar/dates", summary="This year's dates: the suggested list and the shop's own")
async def dates(request: Request, actor: Writer) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = CalendarRepository(session)
        country = await repository.country(actor.tenant_id)
        rows = await repository.rows(actor.tenant_id)
    today = shop_today(country, now)
    year = today.year
    choices, own = this_years_list(rows, year)
    return envelope(
        {
            "year": year,
            "today": today.isoformat(),
            "country": country.value,
            "saved": year_saved(rows, year),
            # Every group, a shop elsewhere included: the page shows only
            # Shopping days when Another country is chosen (R85, G119).
            "groups": [
                {
                    "group": group.value,
                    "dates": [
                        {
                            "key": c.suggested.key,
                            "name": c.suggested.name,
                            "line": c.suggested.dates_line or c.suggested.line,
                            "kept": c.kept,
                            "day": c.day.isoformat() if c.day else None,
                            "moving": c.suggested.moving,
                            "usually": list(c.suggested.usually),
                            "set_by_owner": c.set_by_owner,
                            "sri_lanka": c.suggested.sri_lanka,
                        }
                        for c in choices
                        if c.suggested.group is group
                    ],
                }
                for group in Group
            ],
            "own": [
                {
                    "id": row.id,
                    "name": row.name,
                    "day": row.own_day(max(year, row.year)).isoformat(),
                    "every_year": row.every_year,
                    "kept": row.kept,
                }
                for row in own
            ],
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.put("/calendar/dates", summary="Save this year's dates")
async def save_dates(body: SaveDates, request: Request, actor: Writer) -> dict[str, Any]:
    now = datetime.now(UTC)
    year = shop_today(body.country, now).year
    allowed = {s.key for s in suggested_for(body.country)}
    chosen = {choice.key: choice for choice in body.dates}
    unknown = sorted(set(chosen) - set(SUGGESTED_BY_KEY))
    if unknown:
        raise ValidationError("No such date.", code="UNKNOWN_DATE", details={"keys": unknown})
    for choice in chosen.values():
        if choice.day is None:
            continue
        if not SUGGESTED_BY_KEY[choice.key].moving:
            raise ValidationError(
                "Only a date that moves can be set.",
                code="NOT_A_MOVING_DATE",
                details={"key": choice.key},
            )
        if choice.day.year != year:
            raise ValidationError(
                f"Choose a day in {year}.", code="NOT_THIS_YEAR", details={"key": choice.key}
            )
    # A date the page showed and the body left out is ticked, as the page shows
    # every date until it is unticked (R89).
    suggested = {
        key: (chosen[key].kept, chosen[key].day) if key in chosen else (True, None)
        for key in sorted(allowed)
    }
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = CalendarRepository(session)
        own_ids = {row.id for row in await repository.rows(actor.tenant_id) if row.own}
        await repository.set_country(actor.tenant_id, body.country, by=actor.user_id)
        await repository.save_year(
            actor.tenant_id,
            year,
            suggested=suggested,
            own={choice.id: choice.kept for choice in body.own if choice.id in own_ids},
            by=actor.user_id,
        )
        await book_daily_jobs(session, actor.tenant_id)
    log.info("console_calendar_saved", tenant_id=actor.tenant_id, by=actor.user_id, year=year)
    return envelope(
        {"saved": True, "year": year, "kept": sum(kept for kept, _ in suggested.values())},
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/calendar/dates/own", summary="Add an own date")
async def add_own_date(body: NewOwnDate, request: Request, actor: Writer) -> dict[str, Any]:
    name = " ".join(body.name.split())
    if not name or any(not ch.isprintable() for ch in name):
        raise ValidationError("Give the date a name.", code="NO_NAME")
    now = datetime.now(UTC)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = CalendarRepository(session)
        today = shop_today(await repository.country(actor.tenant_id), now)
        if body.day < today:
            raise ValidationError("Choose a day from today on.", code="DAY_PASSED")
        if body.day.year > today.year + _AHEAD_YEARS:
            raise ValidationError(
                f"Choose a day before {today.year + _AHEAD_YEARS + 1}.", code="TOO_FAR_AHEAD"
            )
        row = await repository.add_own(
            actor.tenant_id,
            name=name,
            day=body.day,
            every_year=body.every_year,
            by=actor.user_id,
        )
        await book_daily_jobs(session, actor.tenant_id)
    log.info("console_calendar_own_added", tenant_id=actor.tenant_id, by=actor.user_id)
    return envelope(
        {
            "id": row.id,
            "name": row.name,
            "day": body.day.isoformat(),
            "every_year": row.every_year,
            "kept": row.kept,
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.delete("/calendar/dates/own/{date_id}", summary="Remove an own date, and its plans")
async def remove_own_date(
    request: Request,
    actor: Writer,
    date_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> dict[str, Any]:
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        removed = await CalendarRepository(session).remove_own(actor.tenant_id, date_id)
    if not removed:
        raise NotFoundError("No such date.", details={"id": date_id})
    log.info("console_calendar_own_removed", tenant_id=actor.tenant_id, by=actor.user_id)
    return envelope(
        {"removed": True, "id": date_id},
        request_id=getattr(request.state, "request_id", None),
    )


# ── A plan ───────────────────────────────────────────────────────────────────


@router.get("/calendar/plans/{plan_id}", summary="One campaign plan")
async def plan(
    request: Request,
    actor: Writer,
    plan_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = CalendarRepository(session)
        found = await repository.plan(actor.tenant_id, plan_id)
        if found is None:
            raise NotFoundError("No such plan.", details={"id": plan_id})
        country = await repository.country(actor.tenant_id)
        answer = dict(found.answer or {})
        facts = list(answer.get("act_on") or [])
        ids = [str(i) for i in answer.get("products") or []]
        ids += [str(f["product_id"]) for f in facts if f.get("product_id")]
        catalogue = await _catalogue(session, actor.tenant_id, ids)
        paused_since = await paused(request, session, actor.tenant_id, CALENDAR_PLANS)
        # Each post's link chooser and clicks (ADR-0074 §6, board 80).
        post_links = (
            await LinkRepository(session).plan_posts(
                actor.tenant_id, date_key=found.date_key, day=found.day
            )
            if role_may(actor.role, LINKS_WRITE)
            else None
        )
    return envelope(
        _plan(
            found,
            answer=answer,
            catalogue=catalogue,
            country=country,
            now=now,
            paused_since=paused_since,
            links={
                "wanted": role_may(actor.role, WANTED_READ),
                "gaps": role_may(actor.role, GAPS_WRITE),
            },
            post_links=post_links,
        ),
        request_id=getattr(request.state, "request_id", None),
    )


def _plan(
    found: Plan,
    *,
    answer: Mapping[str, Any],
    catalogue: Mapping[str, Mapping[str, Any]],
    country: Country,
    now: datetime,
    paused_since: datetime | None,
    links: Mapping[str, bool],
    post_links: Mapping[Post, PostClicks] | None = None,
) -> dict[str, Any]:
    today = shop_today(country, now)
    zone = TIME_ZONES[country]
    made_on = found.made_at.astimezone(ZoneInfo(zone)).date() if found.made_at is not None else None
    posts = post_days(found.day)
    facts = list(answer.get("act_on") or [])
    edited = sorted(name for name in TEXT_FIELDS if found.edits.get(name))
    return {
        "id": found.id,
        "date_key": found.date_key,
        "own": found.date_key.startswith("o:"),
        "name": found.name,
        "day": found.day.isoformat(),
        "today": today.isoformat(),
        "days_left": (found.day - today).days,
        "state": found.state.value,
        "has_plan": found.answer is not None,
        "made_at": found.made_at.isoformat() if found.made_at else None,
        "made_on": made_on.isoformat() if made_on else None,
        "failed": found.failed_at is not None,
        "theme": answer.get("theme"),
        "idea": answer.get("idea"),
        "act_on": [
            {
                "kind": fact.get("kind"),
                "label": fact.get("label"),
                "shoppers": fact.get("shoppers"),
                "product_id": fact.get("product_id"),
                "product_title": (catalogue.get(str(fact.get("product_id"))) or {}).get("title"),
            }
            for fact in facts
        ],
        "products": [
            {"product_id": product_id, **(catalogue.get(product_id) or {"title": None})}
            for product_id in (str(i) for i in answer.get("products") or [])
        ],
        "catalogue_cut": bool(answer.get("catalogue_cut")),
        # When to post, worked out here and never by the model (ADR-0072 §5).
        "schedule": [
            {"step": "ready", "day": (made_on or found.day).isoformat()},
            {"step": "teaser", "day": posts["teaser"].isoformat()},
            {"step": "launch", "day": posts["launch"].isoformat()},
            {"step": "last_chance", "day": posts["last_chance"].isoformat()},
            {"step": "day", "day": found.day.isoformat()},
        ],
        "texts": found.texts() if found.answer is not None else {},
        "edited": edited,
        "paused_since": paused_since.isoformat() if paused_since else None,
        "can_make_again": paused_since is None
        and found.day >= today
        and found.state is not PlanState.MAKING,
        "links": dict(links),
        # ``null`` for a role without Links; else each post's chooser and clicks.
        "post_links": None
        if post_links is None
        else {
            post.value: {
                "product_id": found_post.product_id,
                "clicks": {place.value: count for place, count in found_post.clicks.items()},
            }
            for post, found_post in post_links.items()
        },
    }


@router.put("/calendar/plans/{plan_id}/texts", summary="Save the owner's words over a draft")
async def save_texts(
    body: Texts,
    request: Request,
    actor: Writer,
    plan_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> dict[str, Any]:
    unknown = sorted(set(body.texts) - set(TEXT_FIELDS))
    if unknown:
        raise ValidationError("No such text.", code="UNKNOWN_TEXT", details={"fields": unknown})
    texts = {name: text.strip() for name, text in body.texts.items()}
    if any(not text or len(text) > MAX_EDIT_CHARS for text in texts.values()):
        raise ValidationError(
            f"A text must have 1 to {MAX_EDIT_CHARS} characters.", code="TEXT_LENGTH"
        )
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = CalendarRepository(session)
        found = await repository.plan(actor.tenant_id, plan_id)
        if found is None:
            raise NotFoundError("No such plan.", details={"id": plan_id})
        if found.answer is None:
            raise ConflictError("This plan has no texts to edit.", code="NO_PLAN_YET")
        saved = await repository.save_texts(actor.tenant_id, plan_id, texts)
    log.info("console_calendar_texts_saved", tenant_id=actor.tenant_id, by=actor.user_id)
    return envelope(
        {
            "texts": saved.texts() if saved else {},
            "edited": sorted(n for n in TEXT_FIELDS if saved and saved.edits.get(n)),
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/calendar/plans/{plan_id}/again", summary="Make it again: a fresh plan, at once")
async def make_it_again(
    request: Request,
    actor: Writer,
    plan_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        repository = CalendarRepository(session)
        found = await repository.plan(actor.tenant_id, plan_id)
        if found is None:
            raise NotFoundError("No such plan.", details={"id": plan_id})
        if await paused(request, session, actor.tenant_id, CALENDAR_PLANS) is not None:
            raise ConflictError("FiveNeurals has paused the plans for this shop.", code="PAUSED")
        if found.day < shop_today(await repository.country(actor.tenant_id), now):
            raise ConflictError("This date has passed.", code="DATE_PASSED")
        await repository.ask_again(actor.tenant_id, plan_id, by=actor.user_id)
        booked = await _book_now(request, session, actor.tenant_id, now=now)
    log.info("console_calendar_again", tenant_id=actor.tenant_id, by=actor.user_id, booked=booked)
    return envelope(
        {"state": PlanState.MAKING.value, "booked": booked},
        request_id=getattr(request.state, "request_id", None),
    )


async def _book_now(request: Request, session: Any, tenant_id: str, *, now: datetime) -> bool:
    """Book, to run now, the job a manifest says makes this page's plans (R95)."""
    tenant = await TenantRepository(session).get(tenant_id)
    if tenant is None:
        return False
    booked = False
    for key, discovered in (getattr(request.app.state, "agents", {}) or {}).items():
        kind = (getattr(discovered.manifest, "on_demand", None) or {}).get(CALENDAR_PLANS)
        if not kind or not tenant.may_use(key):
            continue
        await JobQueue(session).enqueue(tenant_id, kind, dedupe_key=kind, run_after=now)
        booked = True
    return booked


def _http(url: Any) -> str | None:
    """An address the browser may open: http or https only."""
    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
        return url
    return None


async def _catalogue(session: Any, tenant_id: str, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Each product's name, page, first photo and price, from the synced catalogue."""
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
        price = document.get("price_range_min") or {}
        found[str(row.external_id)] = {
            "title": document.get("title"),
            "url": _http(document.get("url")),
            "image": _http(next(iter(document.get("image_urls") or []), None)),
            "price": (
                {"amount": str(price["amount"]), "currency": str(price.get("currency") or "")}
                if isinstance(price, dict) and price.get("amount")
                else None
            ),
        }
    return found


# ── Home's lines ─────────────────────────────────────────────────────────────


async def home_lines(session: Any, tenant_id: str, *, now: datetime) -> dict[str, Any]:
    """Home's calendar lines (ADR-0072 §7): *Add this year's special dates*, and
    one *[Name] is in [n] days. Your plan is ready.* per ready plan."""
    repository = CalendarRepository(session)
    country = await repository.country(tenant_id)
    today = shop_today(country, now)
    rows = await repository.rows(tenant_id)
    plans = {(p.date_key, p.day): p for p in await repository.plans(tenant_id, since=today)}
    soon = kept_occurrences(rows, country, start=today, end=add_months(today, QUIET_MONTHS))
    ahead = kept_occurrences(
        rows, country, start=today, end=today + timedelta(days=PLAN_DAYS_BEFORE + 1)
    )
    ready = []
    for occurrence in ahead:
        found = plans.get((occurrence.date_key, occurrence.day)) if occurrence.day else None
        if found is None or found.answer is None or occurrence.day is None:
            continue
        ready.append(
            {
                "plan_id": found.id,
                "name": occurrence.name,
                "day": occurrence.day.isoformat(),
                "days_left": (occurrence.day - today).days,
            }
        )
    return {
        "add_dates": not year_saved(rows, today.year) or not any(o.day for o in soon),
        "ready": ready,
    }


__all__ = ["home_lines", "router"]
