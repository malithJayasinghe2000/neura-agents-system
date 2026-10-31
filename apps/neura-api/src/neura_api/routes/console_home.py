"""What every member's Home reads beyond their own screens. ADR-0058, R12.

    GET /v1/console/shops/{tenant_id}/home    {"mode", "practice", "handed", "waiting", "gaps", "wanted", "rarely_added"}

The Owner's Home reads Usage, which only the Owner may open (money). Support and
the Developer see on Home only the parts about their own work (the owner's
decision, R12), and two of those parts live on Usage's payload: **whether
practice mode is on**, which both need (a reply Support grades, and a test the
Developer runs, depend on it; G86), and **how many chats were handed to a
person in the last 7 days**, which is Support's work.

So this route gives exactly those two facts and nothing else of Usage:

* ``mode`` and ``practice`` to every member (``shop:home:read``);
* ``handed`` only to a role that may read chats (``shop:conversations:read``),
  the same number as Usage's 7 days; ``null`` for any other, so a Developer
  learns nothing about shoppers here either. Checked in code, as every
  permission is (`AGENTS.md` rule 3);
* ``waiting`` only to a role that may answer them (``shop:handovers:write``):
  how many handed-over shoppers wait for the shop's answer (ADR-0062 §6), for
  Home's *Needs you* and the menu's count; ``null`` for any other;
* ``gaps`` only to a role that may open *Missing from your pages*
  (``shop:gaps:write``): how many questions the page shows, the page's own
  count (ADR-0064, Home's line); ``null`` for any other;
* ``wanted`` only to the Owner (``shop:wanted:read``, ADR-0068 §4): how many
  things *Shoppers asked for* shows, the page's own count; ``null`` for any other;
* ``rarely_added`` only to a role that may open *Sold out* (``shop:sold_out:read``,
  the Owner, ADR-0071 §4): how many products *Rarely added to cart* lists, the
  tab's own count; ``null`` for any other. Whether the shop has NEURA-SELL is
  the screen's to check, as for the Sold out card.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from neura_agent_core.gaps import GAP_DAYS, PageGapRepository
from neura_agent_core.waiting import WaitingAnswerRepository
from neura_agent_core.wanted import WantedRepository
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_api.routes.console_sold_out import WINDOW_DAYS
from neura_api.routes.console_usage import PERIODS
from neura_core.identity import role_may
from neura_core.identity.roles import (
    CONVERSATIONS_READ,
    GAPS_WRITE,
    HANDOVERS_WRITE,
    HOME_READ,
    SOLD_OUT_READ,
    WANTED_READ,
)
from neura_core.observation import ObservedEventRepository
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.usage import UsageMeter, today

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: The period *handed to a person* is counted over: Home's own, the last 7 days.
HANDED_PERIOD = "7d"


@router.get(
    "/home",
    summary="The mode; how many chats were handed over; how many shoppers wait for an answer",
)
async def home(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(HOME_READ))],
) -> dict[str, Any]:
    reads_chats = role_may(actor.role, CONVERSATIONS_READ)
    answers = role_may(actor.role, HANDOVERS_WRITE)
    finds_gaps = role_may(actor.role, GAPS_WRITE)
    reads_wanted = role_may(actor.role, WANTED_READ)
    reads_sold_out = role_may(actor.role, SOLD_OUT_READ)
    since = datetime.now(UTC) - timedelta(days=GAP_DAYS)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        tenant = await TenantRepository(session).get(actor.tenant_id)
        handed = None
        if reads_chats:
            lookback = PERIODS[HANDED_PERIOD] or 0
            totals = await UsageMeter(session).totals(
                actor.tenant_id, since=today() - timedelta(days=lookback)
            )
            handed = totals.escalations
        waiting = (
            await WaitingAnswerRepository(session).count_waiting(actor.tenant_id)
            if answers
            else None
        )
        gaps = (
            await PageGapRepository(session).count_topics(actor.tenant_id, since=since)
            if finds_gaps
            else None
        )
        wanted = (
            await WantedRepository(session).count_topics(actor.tenant_id, since=since)
            if reads_wanted
            else None
        )
        rarely_added = (
            await ObservedEventRepository(session).count_rarely_added(
                actor.tenant_id, since=datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
            )
            if reads_sold_out
            else None
        )

    mode = tenant.config.mode.value if tenant else "unknown"
    return envelope(
        {
            "mode": mode,
            "practice": mode == "shadow",
            "handed": handed,
            "waiting": waiting,
            "gaps": gaps,
            "wanted": wanted,
            "rarely_added": rarely_added,
        },
        request_id=getattr(request.state, "request_id", None),
    )


__all__ = ["HANDED_PERIOD", "router"]
