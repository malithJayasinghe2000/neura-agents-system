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
* **The shop is asked only when the screen asks** (``?stock=now``, redesigned
  2026-09-28 from the owner's approved mockup). Titles, categories and prices
  come from the synced catalogue; whether each listed product can be bought
  *now* is one question to the shop — one stock lookup for every product on
  the list, never one per product — because the synced copy can be days old
  (it said the test shop's sold-out jumper was in stock). Home reads this
  route without the parameter and never reaches the shop.

**A second tab, *Rarely added to cart*** (ADR-0071), is ``GET …/sold-out/rarely-added``:
in-stock products that 10 or more visitors opened in 7 days and fewer than 1 in
10 of them added to the cart. The same events, the same permission, the same
catalogue read, and the same refusals: counts only, no session token, nothing
for a shopper, no model, and the shop is never asked.

**Not gated by the SELL entitlement.** 0046 calls this a SELL surface, and the
argument for that is in the ADR — but ``neura-api`` may not learn an agent's
name (AGENTS.md), and every console screen so far is agent-agnostic. What gates
it is the data: a shop that has no agreement or never switched observation on
has no events, and the screen says which of those it can see.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select

from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_api.routes.console_shop import _close
from neura_commerce.identity import EntityType
from neura_commerce.sync.schema import synced_entities
from neura_core import ValidationError, get_logger, get_settings
from neura_core.identity.roles import SOLD_OUT_READ
from neura_core.observation import (
    RARELY_MIN_VISITORS,
    RARELY_ONE_IN,
    ObservedEventRepository,
    RarelyAdded,
    SoldOutDemand,
)
from neura_core.tenancy import TenantRepository
from neura_domain import Capability, InventoryLevel

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: ADR-0046 §7's window. Fixed, not a choice on the screen: retention is also
#: seven days, so there is nothing older to choose.
WINDOW_DAYS = 7

#: The most products one page lists. A shop with more sold-out products than
#: this has a different problem, and the payload says the list was cut.
LIMIT = 100

#: The one value ``?stock=`` takes. Anything else is a 400: a parameter quietly
#: ignored would read as "your shop was asked" when it was not.
STOCK_NOW = "now"


@dataclass(frozen=True, slots=True)
class StockNow:
    """What the shop said about the listed products' stock, just now.

    ``answered`` is false when the shop could not be asked — unreachable, or its
    connection does not share stock. ``in_stock`` then holds nothing, and the
    screen says it could not check rather than showing yesterday's copy.
    """

    asked_at: datetime
    answered: bool
    #: ``unreachable`` · ``not_supported`` — ``None`` when it answered.
    reason: str | None = None
    #: Per product: ``True`` / ``False``; absent when the shop said nothing about it.
    in_stock: Mapping[str, bool] = field(default_factory=dict)


@router.get("/sold-out", summary="Products viewed while they could not be bought")
async def sold_out(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(SOLD_OUT_READ))],
    stock: Annotated[str | None, Query(max_length=16)] = None,
) -> dict[str, Any]:
    if stock not in (None, "", STOCK_NOW):
        raise ValidationError(
            "Unknown stock parameter.", details={"stock": stock, "expected": [STOCK_NOW]}
        )
    now = datetime.now(UTC)
    since = now - timedelta(days=WINDOW_DAYS)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        events = ObservedEventRepository(session)
        demand = await events.sold_out_demand(actor.tenant_id, since=since, limit=LIMIT + 1)
        unknown = await events.views_of_unknown_stock(actor.tenant_id, since=since)
        receiving = await events.any_views_since(actor.tenant_id, since=since)
        tenant = await TenantRepository(session).get(actor.tenant_id)
        shown = demand[:LIMIT]
        catalogue = await _catalogue(session, actor.tenant_id, [d.product_id for d in shown])
        names = await _category_names(
            session, actor.tenant_id, sorted({c for p in catalogue.values() for c in p["cats"]})
        )

    # Only when asked, and only when there is something to ask about: an empty
    # list costs the merchant's server nothing.
    live = (
        await _stock_now(request, actor.tenant_id, shown, catalogue)
        if stock == STOCK_NOW and shown
        else None
    )

    return envelope(
        {
            "period": {"since": since.isoformat(), "through": now.isoformat(), "days": WINDOW_DAYS},
            "agreement": bool(tenant and tenant.may_hold_personal_data),
            "agreement_since": (
                tenant.dpa_signed_at.isoformat() if tenant and tenant.dpa_signed_at else None
            ),
            # Did any product view arrive in the window, sold out or not. A yes
            # or no — see `any_views_since`.
            "receiving": receiving,
            # How long a view is kept before the retention sweep deletes it — the
            # setting that sweep enforces, so "we keep it for N days" on the
            # screen cannot drift from what actually happens.
            "kept_days": get_settings().retention_observed_events_days,
            "products": [_product(d, catalogue.get(d.product_id), names, live) for d in shown],
            "truncated": len(demand) > LIMIT,
            # `null` when the shop was not asked (Home, or an empty list).
            "stock": (
                None
                if live is None
                else {
                    "asked_at": live.asked_at.isoformat(),
                    "answered": live.answered,
                    "reason": live.reason,
                }
            ),
            "caveats": _caveats(shown, unknown),
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.get(
    "/sold-out/rarely-added",
    summary="In-stock products many visitors opened and few added to the cart",
)
async def rarely_added(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(SOLD_OUT_READ))],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    since = now - timedelta(days=WINDOW_DAYS)

    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        events = ObservedEventRepository(session)
        listed = await events.rarely_added(actor.tenant_id, since=since, limit=LIMIT + 1)
        receiving = await events.any_views_since(actor.tenant_id, since=since)
        tenant = await TenantRepository(session).get(actor.tenant_id)
        shown = listed[:LIMIT]
        catalogue = await _catalogue(session, actor.tenant_id, [p.product_id for p in shown])

    return envelope(
        {
            "period": {"since": since.isoformat(), "through": now.isoformat(), "days": WINDOW_DAYS},
            "agreement": bool(tenant and tenant.may_hold_personal_data),
            "agreement_since": (
                tenant.dpa_signed_at.isoformat() if tenant and tenant.dpa_signed_at else None
            ),
            "receiving": receiving,
            "kept_days": get_settings().retention_observed_events_days,
            # The rule, from the code that applies it, so the screen's
            # *How this works* cannot drift from it (ADR-0071 §1).
            "min_visitors": RARELY_MIN_VISITORS,
            "one_in": RARELY_ONE_IN,
            "products": [_rarely(p, catalogue.get(p.product_id)) for p in shown],
            "truncated": len(listed) > LIMIT,
            "caveats": _rarely_caveats(shown),
        },
        request_id=getattr(request.state, "request_id", None),
    )


async def _stock_now(
    request: Request,
    tenant_id: str,
    shown: Sequence[SoldOutDemand],
    catalogue: Mapping[str, dict[str, Any]],
) -> StockNow:
    """One stock lookup at the shop for every product listed.

    The same rule the shop applies when it records a view (ADR-0049): a product
    can be bought when **any** of its variants has stock. The variant ids come
    from the synced catalogue; a product it lacks is asked about by its own id.

    Every failure is a result, never an error: a shop that did not answer is
    said on the screen, and the counts above it are still right.
    """
    asked_at = datetime.now(UTC)
    variants = {
        d.product_id: _variant_ids(catalogue.get(d.product_id), d.product_id) for d in shown
    }

    try:
        connection = await request.app.state.stores.connect(tenant_id)
    except Exception as exc:
        log.info(
            "console_sold_out_stock_unreachable", tenant_id=tenant_id, error=type(exc).__name__
        )
        return StockNow(asked_at=asked_at, answered=False, reason="unreachable")

    try:
        if Capability.INVENTORY_READ not in connection.capabilities:
            return StockNow(asked_at=asked_at, answered=False, reason="not_supported")
        try:
            levels = await connection.adapter.get_inventory(
                sorted({vid for ids in variants.values() for vid in ids})
            )
        except Exception as exc:
            log.info(
                "console_sold_out_stock_unreachable", tenant_id=tenant_id, error=type(exc).__name__
            )
            return StockNow(asked_at=asked_at, answered=False, reason="unreachable")
    finally:
        # An adapter holds an HTTP client; one abandoned per page view leaks a pool.
        await _close(connection.adapter)

    return StockNow(
        asked_at=asked_at, answered=True, in_stock=in_stock_by_product(variants, levels)
    )


def in_stock_by_product(
    variants: Mapping[str, Iterable[str]], levels: Iterable[InventoryLevel]
) -> dict[str, bool]:
    """``True`` when any of a product's variants is in stock, ``False`` when the
    shop reported on its variants and none is; left out when the shop said
    nothing about any of them — a product it no longer has is not "sold out"."""
    reported = {level.variant_external_id: level.in_stock for level in levels}
    result: dict[str, bool] = {}
    for product_id, ids in variants.items():
        known = [reported[vid] for vid in ids if vid in reported]
        if known:
            result[product_id] = any(known)
    return result


def _variant_ids(entry: Mapping[str, Any] | None, product_id: str) -> list[str]:
    ids = list((entry or {}).get("variants") or [])
    return ids or [product_id]


async def _catalogue(
    session: Any, tenant_id: str, product_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """What the synced catalogue holds for each product — never the shop."""
    if not product_ids:
        return {}
    entities = synced_entities.c
    rows = (
        await session.execute(
            select(entities.external_id, entities.document)
            .where(entities.tenant_id == tenant_id)
            .where(entities.entity_type == EntityType.PRODUCT.value)
            .where(entities.external_id.in_(list(product_ids)))
        )
    ).all()
    return {str(row.external_id): _entry(row.document or {}) for row in rows}


def _entry(document: Mapping[str, Any]) -> dict[str, Any]:
    price = document.get("price_range_min") or {}
    return {
        "title": document.get("title"),
        "url": document.get("url"),
        "image": next(iter(document.get("image_urls") or []), None),
        "cats": [str(c) for c in (document.get("category_ids") or [])],
        "price": (
            {"amount": str(price["amount"]), "currency": str(price.get("currency") or "")}
            if price.get("amount")
            else None
        ),
        "variants": [
            str(v["external_id"])
            for v in (document.get("variants") or [])
            if isinstance(v, dict) and v.get("external_id")
        ],
    }


async def _category_names(session: Any, tenant_id: str, category_ids: list[str]) -> dict[str, str]:
    """Name per category id, for the ids the synced catalogue holds."""
    if not category_ids:
        return {}
    entities = synced_entities.c
    rows = (
        await session.execute(
            select(entities.external_id, entities.document)
            .where(entities.tenant_id == tenant_id)
            .where(entities.entity_type == EntityType.CATEGORY.value)
            .where(entities.external_id.in_(category_ids))
        )
    ).all()
    return {
        str(row.external_id): str(name)
        for row in rows
        if (name := (row.document or {}).get("name") or (row.document or {}).get("title"))
    }


def _product(
    demand: SoldOutDemand,
    catalogue: Mapping[str, Any] | None,
    names: Mapping[str, str],
    live: StockNow | None,
) -> dict[str, Any]:
    entry = catalogue or {}
    return {
        "product_id": demand.product_id,
        # `None` when the synced catalogue does not hold it — the screen says so
        # rather than inventing a name or hiding the demand.
        "title": entry.get("title"),
        "url": entry.get("url"),
        # Names only; an id the catalogue cannot name is left out, not shown as a code.
        "categories": [names[c] for c in entry.get("cats", []) if c in names],
        "price": entry.get("price"),
        "views": demand.views,
        "sessions": demand.sessions,
        "last_viewed_at": demand.last_viewed_at.isoformat(),
        # From the shop, just now — `null` when it was not asked, did not
        # answer, or said nothing about this product.
        "in_stock_now": (live.in_stock.get(demand.product_id) if live else None),
    }


def _rarely(product: RarelyAdded, catalogue: Mapping[str, Any] | None) -> dict[str, Any]:
    entry = catalogue or {}
    return {
        "product_id": product.product_id,
        # `None` when the synced catalogue does not hold it, as on Sold out.
        "title": entry.get("title"),
        "url": entry.get("url"),
        "image": entry.get("image"),
        "price": entry.get("price"),
        "visitors": product.visitors,
        "added": product.added,
        "last_viewed_at": product.last_viewed_at.isoformat(),
    }


def _rarely_caveats(products: Sequence[RarelyAdded]) -> list[str]:
    """What these counts do not say. Only when something is listed, as on Sold out."""
    if not products:
        return []
    return [
        "A visitor is one browsing session, not one person: someone on two devices counts "
        "twice. Your shop leaves out known search-engine robots; one it doesn't recognise "
        "may still be counted. We never know who the shopper was.",
        "We see cart adds, not orders, so we can't say who bought.",
    ]


def _caveats(products: Sequence[SoldOutDemand], unknown: int) -> list[str]:
    """What these counts do not say — written here, not in the JavaScript (ADR-0020 §3).

    Each appears only when it is true, so the list is never boilerplate. That a
    listed product may be back in stock is no longer one of them: the screen
    asks the shop and says, per product.
    """
    caveats: list[str] = []
    if products:
        caveats.append(
            "A visit is one browsing session, not one person: someone on two devices counts "
            "twice. Your shop leaves out known search-engine robots; one it doesn't recognise "
            "may still be counted. We never know who the shopper was."
        )
    if unknown:
        caveats.append(
            f"{unknown} product view(s) in this period were recorded without stock information "
            "and are not counted here."
        )
    return caveats


__all__ = ["LIMIT", "STOCK_NOW", "WINDOW_DAYS", "StockNow", "in_stock_by_product", "router"]
