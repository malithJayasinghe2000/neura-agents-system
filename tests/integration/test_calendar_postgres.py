"""The Marketing calendar's data against a real PostgreSQL (ADR-0072).

What only the database can show:

* **Where the shop is** (G119): Sri Lanka until the shop says otherwise.
* **Save this year's dates** (R89): one row per suggested date and year, saved
  again in place; a moving date's day the owner set; an own date's tick.
* **Own dates** (R82): added kept; *Remove* takes its plans with it.
* **Plans** (R87): one per date and day; made again, the owner's edits go; a
  failed try keeps an earlier plan; *Make it again* waits until answered.
* **The retention sweep** deletes a plan 30 days after its date, and only then
  (ADR-0072 §8).
* **Isolation**: another shop's dates and plans are invisible (row-level
  security). That shop removal knows the three tables (G76) is held by
  ``test_tenant_drop_postgres.py``.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from neura_agent_core.calendar import (
    CalendarRepository,
    Country,
    PlanState,
    calendar_dates,
    calendar_plans,
    calendar_settings,
    kept_occurrences,
    year_saved,
)
from neura_api.jobs.retention import sweep
from neura_core import Database, Settings, get_database, get_settings

pytestmark = pytest.mark.integration

TENANT_A = "tn_cal_a"
TENANT_B = "tn_cal_b"
NOW = datetime.now(UTC)
TODAY = NOW.date()
BY = "usr_owner"
ANSWER = {
    "theme": "A Ceylon tea Avurudu",
    "idea": "Families buy tea for the New Year table.",
    "products": ["4", "5"],
    "act_on": [],
    "texts": {"teaser": "Avurudu is coming. [your offer] soon."},
}


@pytest.fixture
async def db():
    get_settings.cache_clear()
    get_database.cache_clear()
    database = Database.from_settings()
    if not await database.ping():
        await database.dispose()
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    await _purge(database)
    try:
        yield database
    finally:
        await _purge(database)
        await database.dispose()


async def _purge(database: Database) -> None:
    for tenant_id in (TENANT_A, TENANT_B):
        async with database.tenant_session(tenant_id) as session:
            for table in (calendar_plans, calendar_dates, calendar_settings):
                await session.execute(delete(table))


async def test_a_shop_is_in_sri_lanka_until_it_says_otherwise(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        repository = CalendarRepository(session)
        assert await repository.country(TENANT_A) is Country.SRI_LANKA
        await repository.set_country(TENANT_A, Country.OTHER, by=BY)
        await repository.set_country(TENANT_A, Country.OTHER, by=BY)
    async with db.tenant_session(TENANT_A) as session:
        assert await CalendarRepository(session).country(TENANT_A) is Country.OTHER


async def test_saving_a_year_twice_keeps_one_row_per_date(db: Database) -> None:
    vesak = date(TODAY.year, 5, 20)
    async with db.tenant_session(TENANT_A) as session:
        repository = CalendarRepository(session)
        await repository.save_year(
            TENANT_A,
            TODAY.year,
            suggested={"black_friday": (True, None), "vesak": (True, None)},
            own={},
            by=BY,
        )
        await repository.save_year(
            TENANT_A,
            TODAY.year,
            suggested={"black_friday": (False, None), "vesak": (True, vesak)},
            own={},
            by=BY,
        )
        rows = await repository.rows(TENANT_A)
    by_key = {row.key: row for row in rows}
    assert len(rows) == 2
    assert by_key["black_friday"].kept is False
    assert by_key["vesak"].day == vesak
    assert year_saved(rows, TODAY.year)
    assert not year_saved(rows, TODAY.year + 1)


async def test_an_own_date_is_kept_and_remove_takes_its_plans(db: Database) -> None:
    day = TODAY + timedelta(days=20)
    async with db.tenant_session(TENANT_A) as session:
        repository = CalendarRepository(session)
        own = await repository.add_own(TENANT_A, name="Test date", day=day, every_year=False, by=BY)
        await repository.store_plan(
            TENANT_A,
            date_key=own.date_key,
            day=day,
            name="Test date",
            answer=ANSWER,
            prompt_revision="test",
            at=NOW,
        )
        rows = await repository.rows(TENANT_A)
        found = kept_occurrences(
            rows, Country.SRI_LANKA, start=TODAY, end=TODAY + timedelta(days=365)
        )
        assert [(o.name, o.day, o.date_key) for o in found] == [("Test date", day, own.date_key)]
        assert not year_saved(rows, TODAY.year), "an own date does not save the year"

        assert await repository.remove_own(TENANT_A, own.id) is True
        assert await repository.remove_own(TENANT_A, own.id) is False
        assert await repository.rows(TENANT_A) == []
        assert await repository.plans(TENANT_A, since=TODAY) == []


async def test_a_suggested_row_cannot_be_written_twice_for_a_year(db: Database) -> None:
    with pytest.raises(IntegrityError):
        async with db.tenant_session(TENANT_A) as session:
            for date_id in ("cal_1", "cal_2"):
                await session.execute(
                    calendar_dates.insert().values(
                        tenant_id=TENANT_A,
                        id=date_id,
                        year=2027,
                        key="christmas",
                        kept=True,
                        changed_by=BY,
                    )
                )


async def test_a_plan_made_again_drops_the_owners_edits(db: Database) -> None:
    day = TODAY + timedelta(days=21)
    async with db.tenant_session(TENANT_A) as session:
        repository = CalendarRepository(session)
        first = await repository.store_plan(
            TENANT_A,
            date_key="s:avurudu",
            day=day,
            name="Avurudu",
            answer=ANSWER,
            prompt_revision="rev1",
            at=NOW,
        )
        edited = await repository.save_texts(
            TENANT_A, first.id, {"teaser": "My own words, 20% off", "unknown": "dropped"}
        )
        assert edited is not None
        assert edited.texts()["teaser"] == "My own words, 20% off"
        assert "unknown" not in edited.edits

        asked = await repository.ask_again(TENANT_A, first.id, by=BY)
        assert asked is not None and asked.state is PlanState.MAKING
        assert [p.id for p in await repository.asked_again(TENANT_A)] == [first.id]

        again = await repository.store_plan(
            TENANT_A,
            date_key="s:avurudu",
            day=day,
            name="Avurudu",
            answer={**ANSWER, "theme": "A new theme"},
            prompt_revision="rev2",
            at=NOW,
        )
    assert again.id == first.id, "one plan per date and day"
    assert again.edits == {}
    assert again.answer is not None and again.answer["theme"] == "A new theme"
    assert again.state is PlanState.READY
    assert again.prompt_revision == "rev2"


async def test_a_failed_try_keeps_an_earlier_plan(db: Database) -> None:
    day = TODAY + timedelta(days=10)
    async with db.tenant_session(TENANT_A) as session:
        repository = CalendarRepository(session)
        await repository.store_plan(
            TENANT_A,
            date_key="s:payday",
            day=day,
            name="Payday",
            answer=ANSWER,
            prompt_revision="rev1",
            at=NOW,
        )
        kept = await repository.fail_plan(
            TENANT_A, date_key="s:payday", day=day, name="Payday", failure="checks", at=NOW
        )
        never = await repository.fail_plan(
            TENANT_A, date_key="s:christmas", day=day, name="Christmas", failure="checks", at=NOW
        )
    assert kept.answer == ANSWER and kept.state is PlanState.READY
    assert kept.failure == "checks"
    assert never.answer is None and never.state is PlanState.FAILED


async def test_the_sweep_deletes_a_plan_30_days_after_its_date(db: Database) -> None:
    async with db.tenant_session(TENANT_A) as session:
        repository = CalendarRepository(session)
        for days_ago in (31, 29):
            await repository.store_plan(
                TENANT_A,
                date_key="s:payday",
                day=TODAY - timedelta(days=days_ago),
                name="Payday",
                answer=ANSWER,
                prompt_revision="test",
                at=NOW,
            )
    async with db.tenant_session(TENANT_A) as session:
        result = await sweep(session, TENANT_A, now=NOW, settings=Settings())
    assert result.plans_deleted == 1
    assert result.remaining, "the newer plan is still to be swept later"
    async with db.tenant_session(TENANT_A) as session:
        left = await CalendarRepository(session).plans(TENANT_A, since=TODAY - timedelta(days=60))
    assert [p.day for p in left] == [TODAY - timedelta(days=29)]


async def test_another_shops_dates_and_plans_are_never_seen(db: Database) -> None:
    async with db.tenant_session(TENANT_B) as session:
        repository = CalendarRepository(session)
        await repository.set_country(TENANT_B, Country.OTHER, by=BY)
        await repository.add_own(
            TENANT_B, name="B's sale", day=TODAY + timedelta(days=5), every_year=False, by=BY
        )
        plan = await repository.store_plan(
            TENANT_B,
            date_key="s:christmas",
            day=TODAY + timedelta(days=5),
            name="Christmas",
            answer=ANSWER,
            prompt_revision="test",
            at=NOW,
        )
    async with db.tenant_session(TENANT_A) as session:
        repository = CalendarRepository(session)
        assert await repository.country(TENANT_A) is Country.SRI_LANKA
        assert await repository.rows(TENANT_A) == []
        assert await repository.plan(TENANT_A, plan.id) is None
        assert await repository.ask_again(TENANT_A, plan.id, by=BY) is None
        assert await repository.save_texts(TENANT_A, plan.id, {"teaser": "x"}) is None
        # Even a read that names B's shop sees nothing under A's session.
        assert (await session.execute(select(calendar_dates))).all() == []
        assert (await session.execute(select(calendar_plans))).all() == []
        assert await repository.any_plans(TENANT_B) is False
    async with db.tenant_session(TENANT_B) as session:
        stored = await CalendarRepository(session).plan(TENANT_B, plan.id)
    assert stored is not None and stored.requested_at is None
