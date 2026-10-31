"""GROW's background work: the night run, and *Make it again*. ADR-0064 §6, ADR-0072 §5.

**The night run** (``grow.gaps.scan``, the kind it has had since the first GROW
page, so jobs already queued keep running) books itself once a day per shop with
GROW. It has two steps, each with its own switch (ADR-0065):

1. **the night check** (``grow.gaps``): reads the shop's new chats, for *Missing
   from your pages* and *Shoppers asked for*;
2. **the calendar's plans** (``grow.calendar``, ADR-0072 §5): a campaign plan
   21 days before each kept date.

It is booked at a shop's first chat and, since the calendar, also when FiveNeurals
approves a shop and when its calendar is saved, so it reaches a shop with no
chats (ADR-0072 §8; ``neura_api.jobs.daily``). **The only place GROW calls a
model**, and never while a shopper waits.

**Make it again** (``grow.calendar.plans``): booked by the console to run at once
(the manifest's ``on_demand``, so the API names no agent). It answers the plans
asked for again, and nothing else.

Before anything is spent, three checks, read in one short transaction:

1. **The shop still has GROW.** If not, the job finishes and books nothing more.
2. **The step's switch is on** (ADR-0065). A step switched off reads nothing and
   asks no model. Switched on again, the night check starts from that moment
   (R52): the chats from while it was off are never read.
3. **The shop's daily AI budget** (ADR-0015). Over the ceiling, nothing is asked
   today and the job books tomorrow.

**Every call is metered** to the shop as ``llm_calls`` with no turn, exactly as
SELL's pairing is. A provider outage **raises**, so the queue retries with
backoff; each step saved its progress, so the retry starts where it stopped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from neura_agent_core.calendar import CalendarRepository
from neura_agent_grow.manifest import MANIFEST
from neura_agent_grow.plans import PlansResult, make_plans
from neura_agent_grow.prompts import REVISION, load_prompts
from neura_agent_grow.scan import scan_shop
from neura_core import get_logger
from neura_core.jobs import JobQueue
from neura_core.tenancy import Admission, BudgetLimits, TenantRepository, UsageDelta, UsageMeter
from neura_core.tenancy.switches import Switch, SwitchRepository

log = get_logger(__name__)

#: The night run's kind. Named for its first step; kept so queued jobs still run.
GAPS_SCAN = "grow.gaps.scan"
#: *Make it again*, run at once (the manifest's ``on_demand``).
CALENDAR_PLANS = "grow.calendar.plans"
#: The switches FiveNeurals may turn off for one shop (the manifest's ``switches``).
GAPS_SWITCH = "grow.gaps"
CALENDAR_SWITCH = "grow.calendar"
PROMPT_NAME = "find_gap"
PLAN_PROMPT = "plan_campaign"
INTERVAL = timedelta(days=1)
#: How soon a *Make it again* run looks again for requests made while it ran.
AGAIN = timedelta(seconds=5)


class GapScanProviderError(Exception):
    """The model could not be reached. A retry, not a result."""


def _off(switch: Switch | None) -> bool:
    return switch is not None and not switch.on


class _Admitted:
    """What the three checks found: whether to go on, and each step's switch."""

    def __init__(self, reason: str = "", switches: dict[str, Switch | None] | None = None) -> None:
        self.reason = reason
        self.switches = switches or {}


async def _admit(context: Any, now: datetime, *, once: bool) -> _Admitted:
    """``once``: a job that runs once (*Make it again*) finishes rather than
    booking tomorrow."""
    async with context.db.tenant_session(context.tenant_id) as session:
        tenant = await TenantRepository(session).get(context.tenant_id)
        if tenant is None or not tenant.may_use(MANIFEST.key):
            await JobQueue(session).complete(context.job.id)
            return _Admitted("the shop no longer has NEURA-GROW; not booked again")
        switches = SwitchRepository(session)
        found = {
            key: await switches.get(context.tenant_id, key)
            for key in (GAPS_SWITCH, CALENDAR_SWITCH)
        }
        spend = await UsageMeter(session).spend_today(context.tenant_id)
        if BudgetLimits.resolve(tenant).admit(spend) is Admission.ESCALATE_ONLY:
            if once:
                await JobQueue(session).complete(context.job.id)
            else:
                await JobQueue(session).reschedule(context.job.id, run_after=now + INTERVAL)
            log.warning("grow_run_skipped_over_budget", tenant_id=context.tenant_id)
            return _Admitted(
                "skipped: the shop is over its daily hard budget"
                + ("" if once else "; booked for tomorrow")
            )
    return _Admitted(switches=found)


class NightRunHandler:
    """Runs one night run (``grow.gaps.scan``) for one shop: both steps."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def __call__(self, context: Any) -> str:
        now = datetime.now(UTC)
        admitted = await _admit(context, now, once=False)
        if admitted.reason:
            return admitted.reason
        gaps = admitted.switches.get(GAPS_SWITCH)
        calendar = admitted.switches.get(CALENDAR_SWITCH)

        notes: list[str] = []
        stopped = ""
        metered = _metered(self._llm)
        try:
            if _off(gaps):
                log.info("grow_scan_switched_off", tenant_id=context.tenant_id)
                notes.append("the night check: switched off by FiveNeurals")
            else:
                scanned = await scan_shop(
                    context.db,
                    context.tenant_id,
                    llm=metered,
                    prompt=load_prompts()[PROMPT_NAME],
                    prompt_revision=REVISION,
                    now=now,
                    not_before=gaps.changed_at if gaps is not None else None,
                )
                notes.append(scanned.summary())
                stopped = scanned.stopped
            if _off(calendar):
                notes.append("the calendar's plans: switched off by FiveNeurals")
            elif not stopped:
                planned = await _plans(context, metered, now, asked_only=False)
                notes.append(planned.summary())
                stopped = planned.stopped
        finally:
            await _meter(context, metered)

        if stopped:
            raise GapScanProviderError(f"the model was unreachable: {' · '.join(notes)}")

        async with context.db.tenant_session(context.tenant_id) as session:
            await JobQueue(session).reschedule(context.job.id, run_after=now + INTERVAL)
        summary = " · ".join(notes)
        if _off(gaps) and _off(calendar):
            return f"skipped: {summary}; booked for tomorrow"
        return summary


class CalendarPlansHandler:
    """*Make it again*, at once: answers the plans asked for again, nothing else."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def __call__(self, context: Any) -> str:
        now = datetime.now(UTC)
        admitted = await _admit(context, now, once=True)
        if admitted.reason:
            return admitted.reason
        if _off(admitted.switches.get(CALENDAR_SWITCH)):
            # The console refuses *Make it again* while paused; a request made
            # just before stays waiting until FiveNeurals turns it back on.
            return "skipped: the calendar's plans are switched off by FiveNeurals"

        metered = _metered(self._llm)
        try:
            planned = await _plans(context, metered, now, asked_only=True)
        finally:
            await _meter(context, metered)
        if planned.stopped:
            raise GapScanProviderError(f"the model was unreachable: {planned.summary()}")

        # A request made while this ran would wait for the night: look again.
        async with context.db.tenant_session(context.tenant_id) as session:
            if await CalendarRepository(session).asked_again(context.tenant_id):
                await JobQueue(session).reschedule(context.job.id, run_after=now + AGAIN)
        return planned.summary()


async def _plans(context: Any, metered: Any, now: datetime, *, asked_only: bool) -> PlansResult:
    return await make_plans(
        context.db,
        context.tenant_id,
        llm=metered,
        prompt=load_prompts()[PLAN_PROMPT],
        prompt_revision=REVISION,
        now=now,
        asked_only=asked_only,
        after_store=_book_sweep,
    )


async def _book_sweep(session: Any, tenant_id: str) -> None:
    """A stored plan is something to expire (ADR-0072 §8): the sweep is booked in
    the same transaction. Imported here, as ``_metered`` is."""
    from neura_api.jobs.retention import enqueue_sweep

    await enqueue_sweep(session, tenant_id)


async def _meter(context: Any, metered: Any) -> None:
    """Charge the shop for what this job asked of the models: no turn, no chat."""
    spend = getattr(metered, "spend", None)
    if spend is None or not spend.calls:
        return
    async with context.db.tenant_session(context.tenant_id) as session:
        await UsageMeter(session).record(
            context.tenant_id,
            MANIFEST.key,
            UsageDelta(
                llm_calls=spend.calls,
                prompt_tokens=spend.prompt_tokens,
                completion_tokens=spend.completion_tokens,
                cost_usd=spend.cost_usd,
            ),
        )


def _metered(llm: Any) -> Any:
    """Imported here, as SELL's job does: ``make eval``'s discovery has no API."""
    from neura_api.metering import MeteredLLM

    return MeteredLLM(llm)


def build_handlers(*, llm: Any, **_: Any) -> dict[str, Any]:
    """Every job kind GROW owns, keyed by kind."""
    return {GAPS_SCAN: NightRunHandler(llm), CALENDAR_PLANS: CalendarPlansHandler(llm)}


__all__ = [
    "CALENDAR_PLANS",
    "CALENDAR_SWITCH",
    "GAPS_SCAN",
    "GAPS_SWITCH",
    "INTERVAL",
    "CalendarPlansHandler",
    "GapScanProviderError",
    "NightRunHandler",
    "build_handlers",
]
