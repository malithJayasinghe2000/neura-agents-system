"""What this shop used, and what those figures are not. ADR-0026, `console.md §3.5`.

**This is the screen where this project's discipline about unmeasured numbers is
most likely to die**, and `console.md §5` says so in as many words. Everything
here is a real counter written by `UsageMeter` since 1.14 — and a real counter
rendered without its denominator, its period, or the thing it excludes becomes a
claim the product has not earned. So the payload carries the caveats rather than
leaving the screen to remember them.

Four of them, each a specific trap:

**1. Zero cost is ambiguous and must not be printed as money.** `PriceTable.cost`
returns `0` for a **local** model and `0` for a cloud model whose price is not
configured (`neura_llm.pricing`, which says so itself: *"reporting an unknown
cost as zero is honest; guessing a price would quietly corrupt the margin
model"*). Nothing below this layer can tell the two apart, so the figure travels
with a flag saying it is unattributed and the screen writes words instead.

**2. There is no deflection rate here, and there will not be one until somebody
measures it.** Escalations over conversations is arithmetic this data supports;
*deflection* is a business claim it does not. A shopper who gave up, or accepted
a wrong answer, counted as deflected — and `CLAUDE.md §4` lists deflection rate
under **unknown**. So the endpoint returns the two counts and no ratio, and names
what the counts do not include.

**3. A shop in shadow mode did all this work and nobody saw any of it.** The
usage row cannot say that; `TenantConfig.mode` can. Without it a merchant reads
"41 conversations, 2 escalated" as a working assistant when no shopper was shown
a single reply — the most misleading screen this console could produce, built
entirely from true numbers.

**4. Every total names its period.** "142 turns" means nothing without "since
when", and a screen that silently changed period between two visits would look
like traffic changing.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from neura_api.dependencies import acting_for
from neura_api.envelopes import envelope
from neura_core import ValidationError, get_logger
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.usage import UsageMeter, UsageTotals, today

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: The periods offered, and the days each looks back. `None` is everything ever
#: recorded — offered because a pilot's *whole* history is often the only sample
#: large enough to say anything, and a screen that could only show 30 days would
#: hide it.
PERIODS: dict[str, int | None] = {"today": 0, "7d": 6, "30d": 29, "all": None}


@router.get("/usage", summary="What this shop used, with every caveat attached")
async def usage(
    request: Request,
    tenant_id: str,
    period: Annotated[str, Query()] = "30d",
) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)

    if period not in PERIODS:
        # Refused rather than defaulted. A silently corrected period returns a
        # different window than the caller asked for while looking like the one
        # they asked for — which on a usage screen is a wrong number, not a
        # wrong parameter.
        raise ValidationError(
            "Unknown period.", details={"period": period, "expected": sorted(PERIODS)}
        )

    lookback = PERIODS[period]
    day = today()
    since = None if lookback is None else day - timedelta(days=lookback)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        meter = UsageMeter(session)
        totals = await meter.totals(actor.tenant_id, since=since)
        # Per agent **for the same period**. Until 2026-09-28 this was today
        # only, on the reading that the meter's per-agent grain is a day and a
        # period sum "would report something nobody measured" — but the rollup
        # is one row per (day, agent), so a period's per-agent figure is the
        # same kind of sum as the period's total, and the rows add up to it.
        per_agent = await meter.by_agent_since(actor.tenant_id, since=since)
        background = await meter.worked_without_a_conversation(actor.tenant_id, since=since)
        first = await meter.first_recorded(actor.tenant_id)
        tenant = await TenantRepository(session).get(actor.tenant_id)

    mode = tenant.config.mode.value if tenant else "unknown"

    return envelope(
        {
            "period": {
                "key": period,
                "since": since.isoformat() if since else None,
                "through": day.isoformat(),
                # `None` days means "everything recorded", which is not a number
                # of days and must not be rendered as one.
                "days": None if lookback is None else lookback + 1,
                # What "everything" starts from; `null` when nothing was ever recorded.
                "first_recorded": first.isoformat() if first else None,
            },
            # The mode is on this payload for the reason in the module docstring:
            # without it, true numbers describe an assistant nobody has met.
            "mode": mode,
            "withheld": mode == "shadow",
            "totals": _totals_payload(totals),
            # For the period above, keyed by agent — the screen names them.
            "by_agent": {key: _totals_payload(value) for key, value in sorted(per_agent.items())},
            # Said once, by the server, rather than hard-coded into a JavaScript
            # bundle — the rule ADR-0020 set for merchant-facing sentences.
            "caveats": _caveats(totals, mode, background=background),
        },
        request_id=getattr(request.state, "request_id", None),
    )


def _totals_payload(totals: UsageTotals) -> dict[str, Any]:
    """Counts, and **no derived ratio of any kind**.

    Every rate this data could support is either already meaningful as a pair of
    counts or is a business claim in disguise. The screen shows "2 of 41", which
    a merchant can check; it does not show "95% deflected", which nobody has
    measured (`CLAUDE.md §4`).
    """
    return {
        "conversations": totals.conversations,
        "turns": totals.turns,
        "escalations": totals.escalations,
        "blocked": totals.blocked,
        "llm_calls": totals.llm_calls,
        "tool_calls": totals.tool_calls,
        "prompt_tokens": totals.prompt_tokens,
        "completion_tokens": totals.completion_tokens,
        "total_tokens": totals.total_tokens,
        "cost": {
            "usd": str(totals.cost_usd),
            # False when the figure is zero, because zero says nothing: a local
            # model is free and an unpriced cloud model also records zero.
            "measured": totals.cost_usd > 0,
        },
    }


def _caveats(totals: UsageTotals, mode: str, *, background: bool = False) -> list[dict[str, str]]:
    """What these numbers do not say, in the merchant's words.

    Returned rather than rendered client-side because a sentence a merchant
    cannot change and nobody reviews is how a wrong promise ships
    ([ADR-0020](../../../../docs/architecture/adr/0020-a-withheld-turn-says-so.md) §3).
    Each one appears only when it is true, so the list is never boilerplate the
    reader learns to skip.

    Each carries a stable ``key`` beside its ``text``, so a screen that shows
    only some figures — the shop's Home shows counts and no cost — can show the
    caveat that belongs to them **by name**, rather than by matching the words
    of a sentence that is free to change.

    *"Practice mode"* is the merchant's word for what the code calls **shadow**
    mode (console.md §3.5): same thing, said the way a shop owner would.
    """
    caveats: list[dict[str, str]] = []

    if mode == "shadow":
        caveats.append(
            {
                "key": "practice_mode",
                "text": (
                    "This shop is in practice mode. Your assistant did all the work below and "
                    "no shopper was shown any of it — the replies are in Review, waiting for "
                    "your verdict."
                ),
            }
        )

    if totals.cost_usd <= 0:
        caveats.append(
            {
                "key": "cost_not_recorded",
                "text": (
                    "No cost is shown because none was recorded. A model running on your own "
                    "hardware costs nothing per message, and a hosted model with no price "
                    "configured also records nothing — this figure cannot tell you which."
                ),
            }
        )

    if background:
        # Without it, an assistant with 0 conversations and 3,326 tokens reads
        # as broken (found on the test shop, 2026-09-28). A feature named, not
        # an agent: this module still does not know which agent does it.
        caveats.append(
            {
                "key": "background_ai",
                "text": (
                    "Some AI work happens without a conversation, like working out product "
                    "suggestions. That is why AI use can be above zero when no shopper was "
                    "chatting."
                ),
            }
        )

    if totals.conversations > 0:
        caveats.append(
            {
                "key": "handed_to_a_person",
                "text": (
                    f"{totals.escalations} of {totals.conversations} conversations were handed "
                    "to a person. That is a count, not a deflection rate: it says nothing about "
                    "whether the other answers were right, or whether the shopper gave up."
                ),
            }
        )

    return caveats


__all__ = ["PERIODS", "router"]
