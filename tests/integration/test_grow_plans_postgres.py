"""GROW's calendar step against a real PostgreSQL (ADR-0072 §5, §8).

A fake model stands in for the real one (the real one is measured by the eval,
Rule 4); everything else is real: the dates, the plans, the synced catalogue,
the two GROW pages' rows, the switches, the queue.

* **When**: a kept date 21 days away or closer gets a plan; 22 days away does
  not yet; a date kept late gets one on the next run; a suggested date only once
  its year's list is saved (R91).
* **What the model is given**: labels and counts, never a shopper's question or
  a conversation id; only products in stock.
* **Refused twice**: stored as *could not be made*, and not asked again unasked.
* **Make it again**: answered at once by its own job; the owner's edits go.
* **The switch** ``grow.calendar``: off, no plan and no call; the night check
  still runs.
* **An outage** stores nothing and makes the queue retry.
* **A stored plan books the retention sweep**, in its own transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, insert, select, update

from neura_agent_core.calendar import (
    CalendarRepository,
    PlanState,
    calendar_dates,
    calendar_plans,
    calendar_settings,
    kept_occurrences,
    shop_today,
)
from neura_agent_core.calendar import Country as CalendarCountry
from neura_agent_core.conversations import conversation_messages, conversations
from neura_agent_core.gaps import page_gap_fixes, page_gap_scans, page_gaps
from neura_agent_core.wanted import WantedItem, WantedRepository, wanted_hides, wanted_items
from neura_agent_grow.campaign import PlanAnswer
from neura_agent_grow.jobs import (
    CALENDAR_PLANS,
    CalendarPlansHandler,
    GapScanProviderError,
    NightRunHandler,
)
from neura_agent_grow.plans import make_plans
from neura_api.jobs.daily import book_daily_jobs
from neura_api.jobs.retention import RETENTION_SWEEP, enqueue_sweep
from neura_commerce.sync.schema import synced_entities
from neura_core import Database, get_database, get_settings
from neura_core.jobs import JobQueue, JobStatus
from neura_core.jobs.schema import job_queue
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.schema import tenant_usage, tenants
from neura_core.tenancy.switches import SwitchRepository, tenant_switches

pytestmark = pytest.mark.integration

GROWING = "tn_iplan_a"
OTHER = "tn_iplan_b"
NOW = datetime.now(UTC)
TODAY = shop_today(CalendarCountry.SRI_LANKA, NOW)
BY = "usr_owner"


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
    for tenant_id in (GROWING, OTHER):
        async with database.tenant_session(tenant_id) as session:
            for table in (
                calendar_plans,
                calendar_dates,
                calendar_settings,
                page_gaps,
                page_gap_fixes,
                page_gap_scans,
                wanted_items,
                wanted_hides,
                tenant_switches,
                conversation_messages,
                conversations,
                synced_entities,
                job_queue,
                tenant_usage,
                tenants,
            ):
                await session.execute(delete(table))


def _product(external_id: str, title: str, **document: Any) -> dict[str, Any]:
    return {
        "platform": "generic",
        "entity_type": "product",
        "external_id": external_id,
        "neura_id": f"nr_{external_id}",
        "fingerprint": "f" * 32,
        "document": {"title": title, **document},
    }


async def _shop(database: Database, tenant_id: str = GROWING) -> None:
    async with database.tenant_session(tenant_id) as session:
        await TenantRepository(session).create(
            tenant_id=tenant_id, name="Ceylon Test Tea", enabled_agents=("care", "grow")
        )
        for row in (
            _product("4", "Ceylon Black Tea BOPF 400g", category_ids=["c1"]),
            _product("5", "Green Tea Loose Leaf 100g"),
            _product("6", "Draft Tea", status="draft"),
            _product("7", "Sold Out Tea", variants=[{"external_id": "7a", "in_stock": False}]),
        ):
            await session.execute(insert(synced_entities).values(tenant_id=tenant_id, **row))
        await session.execute(
            insert(synced_entities).values(
                tenant_id=tenant_id,
                platform="generic",
                entity_type="category",
                external_id="c1",
                neura_id="nr_c1",
                fingerprint="f" * 32,
                document={"name": "Black tea"},
            )
        )


async def _own(database: Database, days: int, name: str = "Our big sale") -> str:
    async with database.tenant_session(GROWING) as session:
        row = await CalendarRepository(session).add_own(
            GROWING, name=name, day=TODAY + timedelta(days=days), every_year=False, by=BY
        )
    return row.date_key


def _answer(**overrides: Any) -> PlanAnswer:
    values: dict[str, Any] = {
        "theme": "A tea sale",
        "idea": "Tea for everyone.",
        "product_ids": ["4", "5"],
        "act_on": [],
        "teaser": "Something is coming.",
        "launch": "Our teas are here. [your offer].",
        "last_chance": "Last days for [your offer].",
        "email_subject": "Our sale",
        "email_body": "Hello,\n\nOur sale is here.",
        "banner": "Our sale: [your offer]",
    }
    values.update(overrides)
    return PlanAnswer(**values)


class _Model:
    """Answers with the given answers in turn (the last one repeats)."""

    def __init__(self, *answers: PlanAnswer | Exception) -> None:
        self.answers = list(answers) or [_answer()]
        self.seen: list[str] = []

    async def chat_structured(self, role: Any, request: Any, schema: Any) -> Any:
        self.seen.append(request.messages[-1].content)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer

        class _Result:
            value = answer
            response = None

        return _Result()


async def _make(database: Database, model: _Model, **kwargs: Any) -> Any:
    return await make_plans(
        database,
        GROWING,
        llm=model,
        prompt="plan",
        prompt_revision="test",
        now=NOW,
        **kwargs,
    )


async def _plans(database: Database) -> list[Any]:
    async with database.tenant_session(GROWING) as session:
        return await CalendarRepository(session).plans(GROWING, since=TODAY)


async def test_a_plan_is_made_21_days_before_and_not_22(db: Database) -> None:
    await _shop(db)
    due = await _own(db, 21, "In 21 days")
    await _own(db, 22, "In 22 days")
    model = _Model()

    result = await _make(db, model)

    assert (result.made, result.failed, result.calls) == (1, 0, 1)
    [plan] = await _plans(db)
    assert (plan.date_key, plan.name, plan.state) == (due, "In 21 days", PlanState.READY)
    assert plan.answer is not None and plan.answer["products"] == ["4", "5"]
    assert plan.prompt_revision == "test"
    again = await _make(db, model)
    assert again.calls == 0, "a date with a plan is not planned again"


async def test_a_date_kept_late_gets_its_plan_and_a_suggested_one_waits_for_the_save(
    db: Database,
) -> None:
    await _shop(db)
    await _own(db, 5, "In 5 days")
    model = _Model()
    first = await _make(db, model)
    assert first.made == 1, "only the own date: the year's list was never saved"

    async with db.tenant_session(GROWING) as session:
        await CalendarRepository(session).save_year(
            GROWING,
            TODAY.year,
            suggested=dict.fromkeys(("eleven_eleven", "black_friday", "payday"), (True, None)),
            own={},
            by=BY,
        )
    second = await _make(db, model)
    async with db.tenant_session(GROWING) as session:
        rows = await CalendarRepository(session).rows(GROWING)
    expected = [
        o
        for o in kept_occurrences(
            rows,
            CalendarCountry.SRI_LANKA,
            start=TODAY + timedelta(days=1),
            end=TODAY + timedelta(days=22),
        )
        if o.key is not None and o.day is not None
    ]
    assert second.made == len(expected)


async def test_the_model_is_given_labels_and_counts_and_products_in_stock(
    db: Database,
) -> None:
    await _shop(db)
    await _own(db, 10)
    async with db.tenant_session(GROWING) as session:
        for n in (1, 2):
            await WantedRepository(session).record(
                GROWING,
                WantedItem(
                    conversation_id=f"cnv_secret_{n}",
                    message_id=f"msg_{n}",
                    label="matcha",
                    question="Do you have matcha? Saman, 0771234567",
                    asked_at=NOW - timedelta(days=1),
                ),
            )
    model = _Model()

    await _make(db, model)

    [seen] = model.seen
    assert '"label": "matcha"' in seen and '"shoppers": 2' in seen
    assert "Do you have matcha" not in seen and "0771234567" not in seen
    assert "cnv_secret" not in seen and "msg_1" not in seen
    assert "Ceylon Black Tea BOPF 400g" in seen and '"category": "Black tea"' in seen
    assert "Draft Tea" not in seen and "Sold Out Tea" not in seen
    assert "Ceylon Test Tea" in seen


async def test_refused_twice_is_stored_as_could_not_be_made_and_not_asked_again(
    db: Database,
) -> None:
    await _shop(db)
    await _own(db, 10)
    model = _Model(_answer(launch="20% off"), _answer(product_ids=["999", "4"]))

    result = await _make(db, model)

    assert (result.made, result.failed, result.calls) == (0, 1, 2)
    [plan] = await _plans(db)
    assert plan.state is PlanState.FAILED and plan.failure == "product"
    assert (await _make(db, _Model())).calls == 0, "only Make it again asks again"


async def test_an_outage_stores_nothing(db: Database) -> None:
    await _shop(db)
    await _own(db, 10)
    result = await _make(db, _Model(TimeoutError("down")))
    assert result.stopped == "provider" and result.made == 0
    assert await _plans(db) == []


async def test_a_stored_plan_books_the_retention_sweep(db: Database) -> None:
    await _shop(db)
    await _own(db, 10)
    await _make(db, _Model(), after_store=enqueue_sweep)
    async with db.tenant_session(GROWING) as session:
        kinds = (await session.execute(select(job_queue.c.kind))).scalars().all()
    assert kinds == [RETENTION_SWEEP]


class _Context:
    def __init__(self, db: Database, tenant_id: str, job: Any) -> None:
        self.db, self.tenant_id, self.job = db, tenant_id, job


async def _running(db: Database, kind: str | None = None) -> Any:
    async with db.tenant_session(GROWING) as session:
        if kind is None:
            [kind] = await book_daily_jobs(session, GROWING)
            [job_id] = (
                await session.execute(select(job_queue.c.id).where(job_queue.c.kind == kind))
            ).scalars()
        else:
            job_id = (await JobQueue(session).enqueue(GROWING, kind, dedupe_key=kind)).id
        await session.execute(
            update(job_queue).where(job_queue.c.id == job_id).values(status="running")
        )
        return await JobQueue(session).get(job_id)


async def test_the_night_run_reaches_a_shop_with_no_chats_and_meters_the_calls(
    db: Database,
) -> None:
    await _shop(db)
    await _own(db, 21)
    job = await _running(db)

    summary = await NightRunHandler(_Model())(_Context(db, GROWING, job))

    assert "1 plan(s) made" in summary and "0 repl(ies) read" in summary
    async with db.tenant_session(GROWING) as session:
        usage = (await session.execute(select(tenant_usage.c.llm_calls))).scalars().all()
        again = await JobQueue(session).get(job.id)
        kinds = set((await session.execute(select(job_queue.c.kind))).scalars().all())
    assert sum(usage) == 1, "the call is charged to the shop"
    assert again is not None and again.status is JobStatus.PENDING
    assert RETENTION_SWEEP in kinds, "the plan is something to expire"


async def test_switched_off_no_plan_is_made_and_the_night_check_still_runs(
    db: Database,
) -> None:
    await _shop(db)
    await _own(db, 10)
    async with db.tenant_session(GROWING) as session:
        await SwitchRepository(session).set(GROWING, "grow.calendar", on=False, by="usr_admin")
    job = await _running(db)
    model = _Model()

    summary = await NightRunHandler(model)(_Context(db, GROWING, job))

    assert model.seen == []
    assert "calendar's plans: switched off" in summary and "repl(ies) read" in summary
    assert await _plans(db) == []


async def test_make_it_again_is_answered_at_once_and_the_edits_go(db: Database) -> None:
    await _shop(db)
    await _own(db, 10)
    await _make(db, _Model())
    [plan] = await _plans(db)
    async with db.tenant_session(GROWING) as session:
        repository = CalendarRepository(session)
        await repository.save_texts(GROWING, plan.id, {"banner": "My banner"})
        await repository.ask_again(GROWING, plan.id, by=BY)
    job = await _running(db, CALENDAR_PLANS)

    summary = await CalendarPlansHandler(_Model(_answer(theme="A new theme")))(
        _Context(db, GROWING, job)
    )

    assert "1 plan(s) made" in summary
    [again] = await _plans(db)
    assert again.id == plan.id and again.state is PlanState.READY
    assert again.answer is not None and again.answer["theme"] == "A new theme"
    assert again.edits == {}


async def test_the_owners_products_are_written_around_and_kept_for_make_it_again(
    db: Database,
) -> None:
    """D20 (R124 to R126): exactly the owner's products, a sold-out one included."""
    await _shop(db)
    await _own(db, 10)
    await _make(db, _Model())
    [plan] = await _plans(db)
    async with db.tenant_session(GROWING) as session:
        await CalendarRepository(session).choose_products(GROWING, plan.id, ["7", "4"], by=BY)
    model = _Model(_answer(product_ids=["4", "5"]), _answer(product_ids=["7", "4"]))

    await CalendarPlansHandler(model)(_Context(db, GROWING, await _running(db, CALENDAR_PLANS)))

    # Not the products in stock: the owner's two, the sold-out tea too, and
    # the first answer (which swapped one) refused for it.
    assert "Sold Out Tea" in model.seen[0] and "Green Tea Loose Leaf" not in model.seen[0]
    assert model.seen[0].endswith("Choose 2 products.")
    assert len(model.seen) == 2
    [made] = await _plans(db)
    assert made.answer is not None and made.answer["products"] == ["7", "4"]
    assert made.owner_products == ("7", "4")

    async with db.tenant_session(GROWING) as session:
        await CalendarRepository(session).ask_again(GROWING, plan.id, by=BY)
    again = _Model(_answer(product_ids=["4", "7"]))
    await CalendarPlansHandler(again)(_Context(db, GROWING, await _running(db, CALENDAR_PLANS)))
    assert "Sold Out Tea" in again.seen[0]
    [kept] = await _plans(db)
    assert kept.owner_products == ("7", "4")


async def test_an_owners_product_gone_from_the_catalogue_is_left_out(db: Database) -> None:
    await _shop(db)
    await _own(db, 10)
    await _make(db, _Model())
    [plan] = await _plans(db)
    async with db.tenant_session(GROWING) as session:
        await CalendarRepository(session).choose_products(GROWING, plan.id, ["gone", "5"], by=BY)
    model = _Model(_answer(product_ids=["5"]))

    await CalendarPlansHandler(model)(_Context(db, GROWING, await _running(db, CALENDAR_PLANS)))

    assert model.seen[0].endswith("Choose 1 product.")
    [made] = await _plans(db)
    assert made.answer is not None and made.answer["products"] == ["5"]


async def test_make_it_again_with_an_outage_makes_the_queue_retry(db: Database) -> None:
    await _shop(db)
    await _own(db, 10)
    await _make(db, _Model())
    [plan] = await _plans(db)
    async with db.tenant_session(GROWING) as session:
        await CalendarRepository(session).ask_again(GROWING, plan.id, by=BY)
    job = await _running(db, CALENDAR_PLANS)
    with pytest.raises(GapScanProviderError):
        await CalendarPlansHandler(_Model(TimeoutError("down")))(_Context(db, GROWING, job))
    [still] = await _plans(db)
    assert still.state is PlanState.MAKING, "the request waits for the retry"


async def test_another_shops_dates_are_never_planned(db: Database) -> None:
    await _shop(db)
    await _shop(db, OTHER)
    async with db.tenant_session(OTHER) as session:
        await CalendarRepository(session).add_own(
            OTHER, name="B's sale", day=TODAY + timedelta(days=3), every_year=False, by=BY
        )
    assert (await _make(db, _Model())).calls == 0
