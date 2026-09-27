"""Products people wanted while they were sold out — ADR-0046 stage 1.

**One merchant-facing screen, and the whole of what it may say.** For each
product: how many times its page was viewed while it could not be bought, and
from how many browsing sessions, in the last seven days. That is the count
ADR-0046 §3 approves — no identity, no email, nothing contactable — and it is
built on ADR-0049's ``in_stock``, recorded with each view, so a product
restocked on Friday still shows Monday's demand.

**What it refuses to do, each written down elsewhere and enforced here:**

* **No session token leaves this module.** The repository returns counts.
* **Nothing here reaches a shopper**, and the order — most-viewed first — is
  for the merchant's reading only (0046 §6).
* **No call to the shop.** Titles come from the synced catalogue; a product it
  does not hold is shown by its id and says so, rather than being fetched live
  on every page load or silently dropped.

**Not gated by the SELL entitlement.** 0046 calls this a SELL surface, and the
argument for that is in the ADR — but ``neura-api`` may not learn an agent's
name (AGENTS.md), and every console screen so far is agent-agnostic. What gates
it is the data: a shop that has no agreement or never switched observation on
has no events, and the screen says which of those it can see.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from sqlalchemy import select

from neura_api.dependencies import acting_for
from neura_api.envelopes import envelope
from neura_commerce.sync.schema import synced_entities
from neura_core.observation import ObservedEventRepository, SoldOutDemand
from neura_core.tenancy import TenantRepository

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: ADR-0046 §7's window. Fixed, not a choice on the screen: retention is also
#: seven days, so there is nothing older to choose.
WINDOW_DAYS = 7

#: The most products one page lists. A shop with more sold-out products than
#: this has a different problem, and the payload says the list was cut.
LIMIT = 100


@router.get("/sold-out", summary="Products viewed while they could not be bought")
async def sold_out(request: Request, tenant_id: str) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)
    now = datetime.now(UTC)
    since = now - timedelta(days=WINDOW_DAYS)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        events = ObservedEventRepository(session)
        demand = await events.sold_out_demand(actor.tenant_id, since=since, limit=LIMIT + 1)
        unknown = await events.views_of_unknown_stock(actor.tenant_id, since=since)
        tenant = await TenantRepository(session).get(actor.tenant_id)
        titles = await _catalogue(session, actor.tenant_id, [d.product_id for d in demand])

    agreement = bool(tenant and tenant.may_hold_personal_data)
    shown = demand[:LIMIT]

    return envelope(
        {
            "period": {"since": since.isoformat(), "through": now.isoformat(), "days": WINDOW_DAYS},
            "agreement": agreement,
            "products": [_product(d, titles.get(d.product_id)) for d in shown],
            "truncated": len(demand) > LIMIT,
            "caveats": _caveats(shown, unknown),
        },
        request_id=getattr(request.state, "request_id", None),
    )


async def _catalogue(
    session: Any, tenant_id: str, product_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """Title and URL for each product, from the synced catalogue — never the shop."""
    if not product_ids:
        return {}
    entities = synced_entities.c
    rows = (
        await session.execute(
            select(entities.external_id, entities.document)
            .where(entities.tenant_id == tenant_id)
            .where(entities.entity_type == "product")
            .where(entities.external_id.in_(list(product_ids)))
        )
    ).all()
    return {
        str(row.external_id): {"title": row.document.get("title"), "url": row.document.get("url")}
        for row in rows
    }


def _product(demand: SoldOutDemand, catalogue: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "product_id": demand.product_id,
        # `None` when the synced catalogue does not hold it — the screen says so
        # rather than inventing a name or hiding the demand.
        "title": (catalogue or {}).get("title"),
        "url": (catalogue or {}).get("url"),
        "views": demand.views,
        "sessions": demand.sessions,
        "last_viewed_at": demand.last_viewed_at.isoformat(),
    }


def _caveats(products: Sequence[SoldOutDemand], unknown: int) -> list[str]:
    """What these counts do not say — written here, not in the JavaScript (ADR-0020 §3).

    Each appears only when it is true, so the list is never boilerplate.
    """
    caveats: list[str] = []
    if products:
        caveats.append(
            "Each product was sold out when these views happened. Some may be back in "
            "stock now — this list is the demand you had while you could not sell it."
        )
        caveats.append(
            "A session is one browsing visit, not one person: someone on two devices counts "
            "twice, and search-engine crawlers are not filtered out."
        )
    if unknown:
        caveats.append(
            f"{unknown} product view(s) in this period were recorded without stock information "
            "and are not counted here."
        )
    return caveats


__all__ = ["LIMIT", "WINDOW_DAYS", "router"]
