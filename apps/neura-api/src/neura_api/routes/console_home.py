"""What every member's Home reads beyond their own screens. ADR-0058, R12.

    GET /v1/console/shops/{tenant_id}/home    {"mode", "practice", "handed"}

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
  permission is (`AGENTS.md` rule 3).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_api.routes.console_usage import PERIODS
from neura_core.identity import role_may
from neura_core.identity.roles import CONVERSATIONS_READ, HOME_READ
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.usage import UsageMeter, today

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: The period *handed to a person* is counted over: Home's own, the last 7 days.
HANDED_PERIOD = "7d"


@router.get("/home", summary="The mode, and for whoever reads chats, how many were handed over")
async def home(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(HOME_READ))],
) -> dict[str, Any]:
    reads_chats = role_may(actor.role, CONVERSATIONS_READ)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        tenant = await TenantRepository(session).get(actor.tenant_id)
        handed = None
        if reads_chats:
            lookback = PERIODS[HANDED_PERIOD] or 0
            totals = await UsageMeter(session).totals(
                actor.tenant_id, since=today() - timedelta(days=lookback)
            )
            handed = totals.escalations

    mode = tenant.config.mode.value if tenant else "unknown"
    return envelope(
        {"mode": mode, "practice": mode == "shadow", "handed": handed},
        request_id=getattr(request.state, "request_id", None),
    )


__all__ = ["HANDED_PERIOD", "router"]
