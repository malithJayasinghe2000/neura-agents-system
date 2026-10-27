"""GROW's background work: the night check. ADR-0064 §6.

``grow.gaps.scan`` runs once a day per shop with GROW, on ADR-0022's queue,
booked first by the shop's first chat (``neura_api.jobs.daily``) and then by
itself. **The only place GROW calls a model**, and never while a shopper waits.

Before anything is spent, three checks, all read in one short transaction:

1. **The shop still has GROW.** If not, the job finishes and books nothing more.
2. **FiveNeurals has not switched the check off** (ADR-0065). Off, no chat is
   read and no model asked; the job books tomorrow, so switching on needs no
   booking. Switched on again, the scan starts from that moment (R52): the chats
   from while it was off are never read.
3. **The shop's daily AI budget** (ADR-0015). Over the ceiling, nothing is asked
   today and the job books tomorrow: the replies wait and are read then.

**Every call is metered** to the shop as ``llm_calls`` with no turn, exactly as
SELL's pairing is: background work that cost money and reported none would hide
spend from the shop and from the admin dashboard.

A provider outage **raises**, so the queue retries with backoff; the scan saved
its progress after every reply, so the retry starts where it stopped.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from neura_agent_grow.manifest import MANIFEST
from neura_agent_grow.prompts import REVISION, load_prompts
from neura_agent_grow.scan import scan_shop
from neura_core import get_logger
from neura_core.jobs import JobQueue
from neura_core.tenancy import Admission, BudgetLimits, TenantRepository, UsageDelta, UsageMeter
from neura_core.tenancy.switches import SwitchRepository

log = get_logger(__name__)

GAPS_SCAN = "grow.gaps.scan"
#: The switch FiveNeurals may turn off for one shop (the manifest's ``switches``).
GAPS_SWITCH = "grow.gaps"
PROMPT_NAME = "find_gap"
INTERVAL = timedelta(days=1)


class GapScanProviderError(Exception):
    """The model could not be reached. A retry, not a result."""


class GapScanHandler:
    """Runs one ``grow.gaps.scan`` job for one shop."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    async def __call__(self, context: Any) -> str:
        now = datetime.now(UTC)
        async with context.db.tenant_session(context.tenant_id) as session:
            tenant = await TenantRepository(session).get(context.tenant_id)
            if tenant is None or not tenant.may_use(MANIFEST.key):
                await JobQueue(session).complete(context.job.id)
                return "the shop no longer has NEURA-GROW; not booked again"
            switch = await SwitchRepository(session).get(context.tenant_id, GAPS_SWITCH)
            if switch is not None and not switch.on:
                await JobQueue(session).reschedule(context.job.id, run_after=now + INTERVAL)
                log.info("grow_scan_switched_off", tenant_id=context.tenant_id)
                return "skipped: switched off by FiveNeurals; booked for tomorrow"
            spend = await UsageMeter(session).spend_today(context.tenant_id)
            limits = BudgetLimits.resolve(tenant)
            if limits.admit(spend) is Admission.ESCALATE_ONLY:
                await JobQueue(session).reschedule(context.job.id, run_after=now + INTERVAL)
                log.warning("grow_scan_skipped_over_budget", tenant_id=context.tenant_id)
                return "skipped: the shop is over its daily hard budget; booked for tomorrow"

        metered = _metered(self._llm)
        try:
            result = await scan_shop(
                context.db,
                context.tenant_id,
                llm=metered,
                prompt=load_prompts()[PROMPT_NAME],
                prompt_revision=REVISION,
                now=now,
                not_before=switch.changed_at if switch is not None else None,
            )
        finally:
            await _meter(context, metered)

        if result.stopped:
            raise GapScanProviderError(f"the model was unreachable: {result.summary()}")

        async with context.db.tenant_session(context.tenant_id) as session:
            await JobQueue(session).reschedule(context.job.id, run_after=now + INTERVAL)
        return result.summary()


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
    return {GAPS_SCAN: GapScanHandler(llm)}


__all__ = [
    "GAPS_SCAN",
    "GAPS_SWITCH",
    "INTERVAL",
    "GapScanHandler",
    "GapScanProviderError",
    "build_handlers",
]
