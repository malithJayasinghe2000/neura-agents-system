"""The shop's Marketing calendar: its dates, and GROW's plans. ADR-0072's data.

A shop with NEURA-GROW keeps a list of special dates for each year: **a
suggested list in code** (§2, R85: Sri Lanka's festivals and payday, and the
worldwide shopping days), which the owner trims once a year, **and their own**
(R82: the shop's birthday, a sale). 21 days before each kept date, GROW's night
run writes a campaign plan (R87); the console shows the dates, the plans, and
Home's lines.

**Here, in the shared core, beside** :mod:`neura_agent_core.wanted`, for the
reason the other GROW pages' data is: the page is the console's own, and the
console may not learn an agent's name (AGENTS.md, G88). Only GROW's night run
writes a plan.

**What is kept, exactly** (ADR-0073):

* a **suggested date** is kept in a year once that year's list was saved
  (*Save this year's dates*, ADR-0072 §3: *"Save keeps the list"*) and its box
  was ticked. Before the save nothing suggested is kept, so no plan is made and
  nothing is spent for a shop whose owner never chose;
* an **own date** is kept from the moment it is added, while ticked; *every
  year* repeats it on the same day each year from the year it was added.

**The moving dates are never written from memory** (AD12): :data:`MOVING_DAYS`
is filled in by hand every January from the government's public holiday list.
A moving date with no day there shows *Date not set yet*, and the owner may set
it for their shop.

**No shopper's data** (ADR-0072 §8): a plan holds the model's checked answer,
the owner's edits, and the labels and counts it was made from; never a
shopper's question and never a conversation id. A plan is deleted 30 days after
its date by the retention sweep; shop removal knows all three tables (G76).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any, cast
from zoneinfo import ZoneInfo

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    delete,
    exists,
    func,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import metadata, new_id
from neura_core.ids import CALENDAR_DATE, CALENDAR_PLAN

CALENDAR_SETTINGS = "calendar_settings"
CALENDAR_DATES = "calendar_dates"
#: The page the switch *The calendar's AI plans* pauses (ADR-0065, ADR-0072 §5),
#: by this name, so the console can say *Paused* without naming an agent.
CALENDAR_PLANS = "calendar_plans"

#: A plan is written this many days before its date (R87).
PLAN_DAYS_BEFORE = 21
#: A plan is deleted this many days after its date (ADR-0072 §8).
PLANS_KEPT_DAYS = 30
#: *Coming up* lists the kept dates in the next 12 months (console.md §3.14).
COMING_UP_MONTHS = 12
#: Home says *Add this year's special dates* again when no kept date falls in
#: the next 2 months (ADR-0072 §7).
QUIET_MONTHS = 2
#: When to post, in days before the date (ADR-0072 §5, the owner's example).
TEASER_DAYS = 14
LAUNCH_DAYS = 7
LAST_CHANCE_DAYS = 2

MAX_NAME_CHARS = 60
#: The longest text the owner may save over a draft. The owner's own words are
#: not checked as the model's are: filling in *[your offer]* is their job.
MAX_EDIT_CHARS = 3000
#: The draft texts of a plan, in the order the page shows them.
TEXT_FIELDS = ("teaser", "launch", "last_chance", "email_subject", "email_body", "banner")


class Country(StrEnum):
    """Where the shop is (G119): which suggested dates it gets, and its day."""

    SRI_LANKA = "lk"
    #: Any other country: the worldwide shopping days only (R85).
    OTHER = "other"


#: Days are counted in the shop's time: Sri Lanka's, or UTC for another (G119).
TIME_ZONES: Mapping[Country, str] = {Country.SRI_LANKA: "Asia/Colombo", Country.OTHER: "UTC"}


def shop_today(country: Country, now: datetime) -> date:
    """Today, in the shop's own time zone."""
    return now.astimezone(ZoneInfo(TIME_ZONES[country])).date()


class Group(StrEnum):
    """The three lists on *This year's dates* (board 77)."""

    FESTIVALS = "festivals"
    MONTHLY = "monthly"
    SHOPPING = "shopping"


def _last_day(year: int, month: int) -> date:
    return date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)


def last_working_day(year: int, month: int) -> date:
    """The month's last Monday to Friday. Public holidays are not known (AD12)."""
    day = _last_day(year, month)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``th ``weekday`` (Monday 0) of a month."""
    first = date(year, month, 1)
    return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))


def black_friday(year: int) -> date:
    """The day after the fourth Thursday of November."""
    return nth_weekday(year, 11, 3, 4) + timedelta(days=1)


def _fixed(month: int, day: int) -> Callable[[int], tuple[date, ...]]:
    return lambda year: (date(year, month, day),)


def _paydays(year: int) -> tuple[date, ...]:
    return tuple(last_working_day(year, month) for month in range(1, 13))


def _mothers_day(year: int) -> tuple[date, ...]:
    return (nth_weekday(year, 5, 6, 2),)


def _black_friday(year: int) -> tuple[date, ...]:
    return (black_friday(year),)


def _cyber_monday(year: int) -> tuple[date, ...]:
    return (black_friday(year) + timedelta(days=3),)


#: The moving dates' days, by year, then by key. **Written in by hand every
#: January** from the government's public holiday list, and checked (AD12).
#: **Empty on purpose, and never filled from memory**: one wrong day here makes
#: every Sri Lankan shop's plan early or late at once (ADR-0072, Consequences).
#: A year missing here shows *Date not set yet*, and the owner may set it.
MOVING_DAYS: Mapping[int, Mapping[str, date]] = {}


@dataclass(frozen=True, slots=True)
class Suggested:
    """One date on the suggested list (ADR-0072 §2)."""

    key: str
    name: str
    group: Group
    #: The line under the name, where there is one (*Sinhala and Tamil New Year*).
    line: str | None = None
    #: *This year's dates* says more than *Coming up* for payday (board 77).
    dates_line: str | None = None
    #: A moving date's usual months, for *usually in …* and for its place in
    #: *Coming up* before its day is known. Empty: it moves through the year.
    usually: tuple[int, ...] = ()
    #: How a fixed or rule date falls in a year. ``None``: a moving date (AD12).
    rule: Callable[[int], tuple[date, ...]] | None = None
    #: Only for a shop in Sri Lanka (R85: the festivals and payday are its own).
    sri_lanka: bool = False

    @property
    def moving(self) -> bool:
        return self.rule is None

    def days(self, year: int) -> tuple[date, ...]:
        """Its days in ``year``; empty for a moving date nobody has written in."""
        if self.rule is not None:
            return self.rule(year)
        day = MOVING_DAYS.get(year, {}).get(self.key)
        return (day,) if day else ()


SUGGESTED: tuple[Suggested, ...] = (
    Suggested(
        "avurudu",
        "Avurudu",
        Group.FESTIVALS,
        line="Sinhala and Tamil New Year",
        usually=(4,),
        sri_lanka=True,
    ),
    Suggested("vesak", "Vesak", Group.FESTIVALS, usually=(5,), sri_lanka=True),
    Suggested("poson", "Poson", Group.FESTIVALS, usually=(6,), sri_lanka=True),
    Suggested("deepavali", "Deepavali", Group.FESTIVALS, usually=(10, 11), sri_lanka=True),
    # Its day is Eid al-Fitr's, the end of Ramadan; it moves through the year.
    Suggested("eid_al_fitr", "Ramadan and Eid al-Fitr", Group.FESTIVALS, sri_lanka=True),
    Suggested("christmas", "Christmas", Group.FESTIVALS, rule=_fixed(12, 25), sri_lanka=True),
    Suggested(
        "payday",
        "Payday",
        Group.MONTHLY,
        line="Last working day of the month",
        dates_line="The last working day of each month · 12 plans a year",
        rule=_paydays,
        sri_lanka=True,
    ),
    Suggested("valentines_day", "Valentine's Day", Group.SHOPPING, rule=_fixed(2, 14)),
    Suggested(
        "mothers_day",
        "Mother's Day",
        Group.SHOPPING,
        line="Second Sunday of May",
        rule=_mothers_day,
    ),
    Suggested("eleven_eleven", "11.11", Group.SHOPPING, rule=_fixed(11, 11)),
    Suggested("black_friday", "Black Friday", Group.SHOPPING, rule=_black_friday),
    Suggested("cyber_monday", "Cyber Monday", Group.SHOPPING, rule=_cyber_monday),
)
SUGGESTED_BY_KEY: Mapping[str, Suggested] = {s.key: s for s in SUGGESTED}


def suggested_for(country: Country) -> tuple[Suggested, ...]:
    """The suggested dates a shop in ``country`` gets (R85)."""
    return tuple(s for s in SUGGESTED if country is Country.SRI_LANKA or not s.sri_lanka)


#: Where the shop is, and who last said so. No row: Sri Lanka (G119).
calendar_settings = Table(
    CALENDAR_SETTINGS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("country", String(16), nullable=False),
    Column("changed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("changed_by", String(64), nullable=False),
    CheckConstraint("country IN ('lk', 'other')", name="country"),
)

#: A shop's dates. A suggested date has a row per year once that year's list is
#: saved (its key, ticked or not, and a moving date's day if the owner set it);
#: an own date has one row (its name and day, the year it was added, and
#: whether it repeats every year).
calendar_dates = Table(
    CALENDAR_DATES,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("id", String(64), primary_key=True),
    Column("year", Integer, nullable=False),
    Column("key", String(32), nullable=True),
    Column("name", String(MAX_NAME_CHARS), nullable=True),
    Column("day", Date, nullable=True),
    Column("kept", Boolean, nullable=False),
    Column("every_year", Boolean, nullable=False, server_default="false"),
    Column("changed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    #: The member of the shop's team who saved it.
    Column("changed_by", String(64), nullable=False),
    CheckConstraint("(key IS NULL) <> (name IS NULL)", name="key_or_name"),
    CheckConstraint("name IS NULL OR day IS NOT NULL", name="own_has_day"),
    Index(
        "uq_calendar_dates_suggested",
        "tenant_id",
        "year",
        "key",
        unique=True,
        postgresql_where=text("key IS NOT NULL"),
    ),
)

#: One plan per kept date and day (a payday has twelve days a year).
calendar_plans = Table(
    CALENDAR_PLANS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("id", String(64), primary_key=True),
    #: ``s:<key>`` for a suggested date, ``o:<id>`` for an own date.
    Column("date_key", String(80), nullable=False),
    Column("day", Date, nullable=False),
    #: The date's name when the plan was made.
    Column("name", String(MAX_NAME_CHARS), nullable=False),
    #: The model's answer after the checks (ADR-0072 §6), with the products and
    #: facts resolved to what the plan was made from. ``NULL``: never made.
    Column("answer", JSONB, nullable=True),
    #: The owner's own words over the drafts, by field (``TEXT_FIELDS``).
    Column("edits", JSONB, nullable=False, server_default="{}"),
    Column("made_at", DateTime(timezone=True), nullable=True),
    Column("prompt_revision", String(64), nullable=True),
    #: The last try failed the checks twice (ADR-0072 §5). An earlier answer stays.
    Column("failed_at", DateTime(timezone=True), nullable=True),
    Column("failure", String(64), nullable=True),
    #: *Make it again*, pressed and not yet answered.
    Column("requested_at", DateTime(timezone=True), nullable=True),
    Column("requested_by", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Index("uq_calendar_plans_date", "tenant_id", "date_key", "day", unique=True),
    Index("ix_calendar_plans_day", "tenant_id", "day"),
)


@dataclass(frozen=True, slots=True)
class DateRow:
    """One row of ``calendar_dates``."""

    id: str
    year: int
    key: str | None
    name: str | None
    day: date | None
    kept: bool
    every_year: bool = False

    @property
    def own(self) -> bool:
        return self.name is not None

    @property
    def date_key(self) -> str:
        return f"s:{self.key}" if self.key else f"o:{self.id}"

    def applies(self, year: int) -> bool:
        """Whether an own date is on ``year``'s list."""
        return self.year == year or (self.every_year and self.year <= year)

    def own_day(self, year: int) -> date:
        """An own date's day in ``year``; 29 February is the 28th in other years."""
        if self.day is None:
            raise ValueError("only an own date has a day of its own")
        try:
            return self.day.replace(year=year)
        except ValueError:
            return date(year, 2, 28)


def year_saved(rows: Iterable[DateRow], year: int) -> bool:
    """Whether ``year``'s list was saved: a suggested date has a row for it."""
    return any(row.key is not None and row.year == year for row in rows)


@dataclass(frozen=True, slots=True)
class Occurrence:
    """One kept date on one day (or a moving date whose day is not set)."""

    date_key: str
    name: str
    year: int
    #: ``None``: a moving date not set yet.
    day: date | None
    key: str | None = None
    own_id: str | None = None
    line: str | None = None
    usually: tuple[int, ...] = ()
    every_year: bool = False

    @property
    def plan_day(self) -> date | None:
        return None if self.day is None else self.day - timedelta(days=PLAN_DAYS_BEFORE)

    def sort_key(self) -> tuple[date, str]:
        if self.day is not None:
            return (self.day, self.name)
        # Not set: at the end of its usual months, as board 75 places Vesak.
        month = max(self.usually) if self.usually else 12
        return (_last_day(self.year, month), self.name)


def add_months(day: date, months: int) -> date:
    """``day`` moved by whole months, on the month's last day when it is shorter."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, _last_day(year, month).day))


def _may_fall(suggested: Suggested, year: int, start: date, end: date) -> bool:
    """Whether a moving date not set yet may fall in ``[start, end)``."""
    if not suggested.usually:
        return True
    first = date(year, min(suggested.usually), 1)
    return first < end and _last_day(year, max(suggested.usually)) >= start


def moving_day(suggested: Suggested, row: DateRow | None, year: int) -> date | None:
    """A moving date's day: the owner's, or the hand-checked list's (AD12)."""
    if row is not None and row.day is not None:
        return row.day
    days = suggested.days(year)
    return days[0] if days else None


def kept_occurrences(
    rows: Sequence[DateRow], country: Country, *, start: date, end: date
) -> list[Occurrence]:
    """Every kept date falling in ``[start, end)``, soonest first.

    A moving date not set yet is listed when its usual months reach the window,
    so the owner sees it and may set it.
    """
    found: list[Occurrence] = []
    for year in range(start.year, end.year + 1):
        if year_saved(rows, year):
            by_key = {row.key: row for row in rows if row.key and row.year == year}
            for suggested in suggested_for(country):
                row = by_key.get(suggested.key)
                if row is None or not row.kept:
                    continue
                if suggested.moving:
                    day = moving_day(suggested, row, year)
                    days: tuple[date | None, ...] = (day,) if day else ()
                    if not days and _may_fall(suggested, year, start, end):
                        days = (None,)
                else:
                    days = suggested.days(year)
                for day in days:
                    if day is None or start <= day < end:
                        found.append(
                            Occurrence(
                                date_key=row.date_key,
                                name=suggested.name,
                                year=year,
                                day=day,
                                key=suggested.key,
                                line=suggested.line,
                                usually=suggested.usually,
                            )
                        )
        for row in rows:
            if not row.own or not row.kept or not row.applies(year):
                continue
            day = row.own_day(year)
            if start <= day < end:
                found.append(
                    Occurrence(
                        date_key=row.date_key,
                        name=row.name or "",
                        year=year,
                        day=day,
                        own_id=row.id,
                        every_year=row.every_year,
                    )
                )
    return sorted(found, key=Occurrence.sort_key)


@dataclass(frozen=True, slots=True)
class Choice:
    """One suggested date on *This year's dates*: ticked or not, and its day."""

    suggested: Suggested
    kept: bool
    #: Its day this year, or ``None`` (payday has twelve; a moving date not set).
    day: date | None
    #: The owner set this moving date's day themselves.
    set_by_owner: bool = False


def this_years_list(rows: Sequence[DateRow], year: int) -> tuple[list[Choice], list[DateRow]]:
    """Every suggested date with its tick and day, and the own dates on the list.

    Every suggested date is ticked until the owner unticks it and saves (R89),
    so a year never saved shows them all ticked. Own dates shown are this
    year's, the ones repeating every year, and the ones added for a later year.
    """
    by_key = {row.key: row for row in rows if row.key and row.year == year}
    choices: list[Choice] = []
    for suggested in SUGGESTED:
        row = by_key.get(suggested.key)
        if suggested.moving:
            day = moving_day(suggested, row, year)
        else:
            days = suggested.days(year)
            day = days[0] if len(days) == 1 else None
        choices.append(
            Choice(
                suggested=suggested,
                kept=row.kept if row is not None else True,
                day=day,
                set_by_owner=bool(row is not None and row.day is not None),
            )
        )
    own = [row for row in rows if row.own and (row.applies(year) or row.year > year)]
    return choices, sorted(own, key=lambda row: (row.own_day(max(year, row.year)), row.id))


def post_days(day: date) -> dict[str, date]:
    """When to post, worked out in code, never by the model (ADR-0072 §5)."""
    return {
        "teaser": day - timedelta(days=TEASER_DAYS),
        "launch": day - timedelta(days=LAUNCH_DAYS),
        "last_chance": day - timedelta(days=LAST_CHANCE_DAYS),
    }


class PlanState(StrEnum):
    """What *Coming up* says about a plan."""

    READY = "ready"
    #: *Make it again* was pressed, and the new plan is not made yet.
    MAKING = "making"
    #: It failed the checks twice, and there is no earlier plan (ADR-0072 §5).
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Plan:
    """One row of ``calendar_plans``."""

    id: str
    date_key: str
    day: date
    name: str
    answer: Mapping[str, Any] | None
    edits: Mapping[str, str] = field(default_factory=dict)
    made_at: datetime | None = None
    prompt_revision: str | None = None
    failed_at: datetime | None = None
    failure: str | None = None
    requested_at: datetime | None = None

    @property
    def state(self) -> PlanState:
        if self.requested_at is not None:
            return PlanState.MAKING
        return PlanState.READY if self.answer is not None else PlanState.FAILED

    def texts(self) -> dict[str, str]:
        """The drafts as the page shows them: the owner's words where they edited."""
        written = dict((self.answer or {}).get("texts") or {})
        return {name: self.edits.get(name) or str(written.get(name) or "") for name in TEXT_FIELDS}


def _row(row: Any) -> DateRow:
    return DateRow(
        id=row.id,
        year=int(row.year),
        key=row.key,
        name=row.name,
        day=row.day,
        kept=bool(row.kept),
        every_year=bool(row.every_year),
    )


def _plan(row: Any) -> Plan:
    return Plan(
        id=row.id,
        date_key=row.date_key,
        day=row.day,
        name=row.name,
        answer=row.answer,
        edits=dict(row.edits or {}),
        made_at=row.made_at,
        prompt_revision=row.prompt_revision,
        failed_at=row.failed_at,
        failure=row.failure,
        requested_at=row.requested_at,
    )


class CalendarRepository:
    """Every read and write of the three tables, under the shop's own RLS."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Where the shop is ────────────────────────────────────────────────────

    async def country(self, tenant_id: str) -> Country:
        value = await self._session.scalar(
            select(calendar_settings.c.country).where(calendar_settings.c.tenant_id == tenant_id)
        )
        return Country(value) if value else Country.SRI_LANKA

    async def set_country(self, tenant_id: str, country: Country, *, by: str) -> None:
        statement = pg_insert(calendar_settings).values(
            tenant_id=tenant_id, country=country.value, changed_by=by
        )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[calendar_settings.c.tenant_id],
                set_={"country": country.value, "changed_at": func.now(), "changed_by": by},
            )
        )

    # ── The dates ────────────────────────────────────────────────────────────

    async def rows(self, tenant_id: str) -> list[DateRow]:
        """Every date row the shop has (a few dozen a year at most)."""
        result = await self._session.execute(
            select(calendar_dates)
            .where(calendar_dates.c.tenant_id == tenant_id)
            .order_by(calendar_dates.c.year, calendar_dates.c.id)
        )
        return [_row(row) for row in result.all()]

    async def save_year(
        self,
        tenant_id: str,
        year: int,
        *,
        suggested: Mapping[str, tuple[bool, date | None]],
        own: Mapping[str, bool],
        by: str,
    ) -> None:
        """*Save this year's dates*: each suggested date's tick (and a moving
        date's day the owner set), and each own date's tick."""
        for key, (kept, day) in suggested.items():
            statement = pg_insert(calendar_dates).values(
                tenant_id=tenant_id,
                id=new_id(CALENDAR_DATE),
                year=year,
                key=key,
                day=day,
                kept=kept,
                changed_by=by,
            )
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        calendar_dates.c.tenant_id,
                        calendar_dates.c.year,
                        calendar_dates.c.key,
                    ],
                    index_where=text("key IS NOT NULL"),
                    set_={"kept": kept, "day": day, "changed_at": func.now(), "changed_by": by},
                )
            )
        for date_id, kept in own.items():
            await self._session.execute(
                update(calendar_dates)
                .where(
                    calendar_dates.c.tenant_id == tenant_id,
                    calendar_dates.c.id == date_id,
                    calendar_dates.c.name.is_not(None),
                )
                .values(kept=kept, changed_at=func.now(), changed_by=by)
            )

    async def add_own(
        self, tenant_id: str, *, name: str, day: date, every_year: bool, by: str
    ) -> DateRow:
        """An own date (R82), kept from now; listed from the year of its day."""
        date_id = new_id(CALENDAR_DATE)
        await self._session.execute(
            pg_insert(calendar_dates).values(
                tenant_id=tenant_id,
                id=date_id,
                year=day.year,
                name=name,
                day=day,
                kept=True,
                every_year=every_year,
                changed_by=by,
            )
        )
        return DateRow(
            id=date_id,
            year=day.year,
            key=None,
            name=name,
            day=day,
            kept=True,
            every_year=every_year,
        )

    async def remove_own(self, tenant_id: str, date_id: str) -> bool:
        """*Remove*: the own date goes, and so do its plans. False if no such date."""
        result = await self._session.execute(
            delete(calendar_dates).where(
                calendar_dates.c.tenant_id == tenant_id,
                calendar_dates.c.id == date_id,
                calendar_dates.c.name.is_not(None),
            )
        )
        if not cast("CursorResult[Any]", result).rowcount:
            return False
        await self._session.execute(
            delete(calendar_plans).where(
                calendar_plans.c.tenant_id == tenant_id,
                calendar_plans.c.date_key == f"o:{date_id}",
            )
        )
        return True

    # ── The plans ────────────────────────────────────────────────────────────

    async def plans(self, tenant_id: str, *, since: date) -> list[Plan]:
        """Every plan for a day from ``since`` on."""
        result = await self._session.execute(
            select(calendar_plans)
            .where(calendar_plans.c.tenant_id == tenant_id, calendar_plans.c.day >= since)
            .order_by(calendar_plans.c.day, calendar_plans.c.id)
        )
        return [_plan(row) for row in result.all()]

    async def plan(self, tenant_id: str, plan_id: str) -> Plan | None:
        row = (
            await self._session.execute(
                select(calendar_plans).where(
                    calendar_plans.c.tenant_id == tenant_id, calendar_plans.c.id == plan_id
                )
            )
        ).first()
        return None if row is None else _plan(row)

    async def store_plan(
        self,
        tenant_id: str,
        *,
        date_key: str,
        day: date,
        name: str,
        answer: Mapping[str, Any],
        prompt_revision: str | None,
        at: datetime,
    ) -> Plan:
        """A plan that passed the checks. A plan made again drops the old
        answer **and the owner's edits** (they were told first, §5)."""
        values = {
            "name": name,
            "answer": dict(answer),
            "edits": {},
            "made_at": at,
            "prompt_revision": prompt_revision,
            "failed_at": None,
            "failure": None,
            "requested_at": None,
            "requested_by": None,
        }
        return await self._upsert(tenant_id, date_key=date_key, day=day, values=values)

    async def fail_plan(
        self, tenant_id: str, *, date_key: str, day: date, name: str, failure: str, at: datetime
    ) -> Plan:
        """The answer failed the checks twice. An earlier plan, if any, stays."""
        values = {
            "name": name,
            "failed_at": at,
            "failure": failure,
            "requested_at": None,
            "requested_by": None,
        }
        return await self._upsert(tenant_id, date_key=date_key, day=day, values=values)

    async def _upsert(
        self, tenant_id: str, *, date_key: str, day: date, values: Mapping[str, Any]
    ) -> Plan:
        statement = pg_insert(calendar_plans).values(
            tenant_id=tenant_id, id=new_id(CALENDAR_PLAN), date_key=date_key, day=day, **values
        )
        row = (
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[
                        calendar_plans.c.tenant_id,
                        calendar_plans.c.date_key,
                        calendar_plans.c.day,
                    ],
                    set_=dict(values),
                ).returning(calendar_plans)
            )
        ).one()
        return _plan(row)

    async def save_texts(
        self, tenant_id: str, plan_id: str, texts: Mapping[str, str]
    ) -> Plan | None:
        """*Save* on a draft: the owner's words replace the model's on the page."""
        plan = await self.plan(tenant_id, plan_id)
        if plan is None:
            return None
        edits = {**plan.edits, **{k: v for k, v in texts.items() if k in TEXT_FIELDS}}
        await self._session.execute(
            update(calendar_plans)
            .where(calendar_plans.c.tenant_id == tenant_id, calendar_plans.c.id == plan_id)
            .values(edits=edits)
        )
        return await self.plan(tenant_id, plan_id)

    async def ask_again(self, tenant_id: str, plan_id: str, *, by: str) -> Plan | None:
        """*Make it again*: GROW makes a fresh plan as soon as it can."""
        await self._session.execute(
            update(calendar_plans)
            .where(calendar_plans.c.tenant_id == tenant_id, calendar_plans.c.id == plan_id)
            .values(requested_at=func.now(), requested_by=by)
        )
        return await self.plan(tenant_id, plan_id)

    async def asked_again(self, tenant_id: str) -> list[Plan]:
        """The plans waiting for *Make it again*, oldest request first."""
        result = await self._session.execute(
            select(calendar_plans)
            .where(
                calendar_plans.c.tenant_id == tenant_id,
                calendar_plans.c.requested_at.is_not(None),
            )
            .order_by(calendar_plans.c.requested_at, calendar_plans.c.id)
        )
        return [_plan(row) for row in result.all()]

    async def forget_request(self, tenant_id: str, plan_id: str) -> None:
        """A request that can no longer be answered (the date passed, or went)."""
        await self._session.execute(
            update(calendar_plans)
            .where(calendar_plans.c.tenant_id == tenant_id, calendar_plans.c.id == plan_id)
            .values(requested_at=None, requested_by=None)
        )

    async def delete_plans_before(self, tenant_id: str, day: date) -> int:
        """The retention sweep: every plan for a day before ``day``."""
        result = await self._session.execute(
            delete(calendar_plans).where(
                calendar_plans.c.tenant_id == tenant_id, calendar_plans.c.day < day
            )
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def any_plans(self, tenant_id: str) -> bool:
        """Whether a plan is left for a later sweep to delete."""
        return bool(
            await self._session.scalar(
                select(exists().where(calendar_plans.c.tenant_id == tenant_id))
            )
        )


__all__ = [
    "CALENDAR_DATES",
    "CALENDAR_PLANS",
    "CALENDAR_SETTINGS",
    "COMING_UP_MONTHS",
    "LAST_CHANCE_DAYS",
    "LAUNCH_DAYS",
    "MAX_EDIT_CHARS",
    "MAX_NAME_CHARS",
    "MOVING_DAYS",
    "PLANS_KEPT_DAYS",
    "PLAN_DAYS_BEFORE",
    "QUIET_MONTHS",
    "SUGGESTED",
    "SUGGESTED_BY_KEY",
    "TEASER_DAYS",
    "TEXT_FIELDS",
    "TIME_ZONES",
    "CalendarRepository",
    "Choice",
    "Country",
    "DateRow",
    "Group",
    "Occurrence",
    "Plan",
    "PlanState",
    "Suggested",
    "add_months",
    "black_friday",
    "calendar_dates",
    "calendar_plans",
    "calendar_settings",
    "kept_occurrences",
    "last_working_day",
    "moving_day",
    "nth_weekday",
    "post_days",
    "shop_today",
    "suggested_for",
    "this_years_list",
    "year_saved",
]
