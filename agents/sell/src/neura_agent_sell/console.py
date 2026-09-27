"""The owner's side of the paired suggestion — [ADR-0050].

Four console endpoints, mounted under SELL's prefix through the same
``neura.agent_routes`` seam as the feed and MCP, so ``neura-api`` still never
learns an agent's name:

    GET    /console/shops/{tenant}/suggestions            what each product shows now
    GET    /console/shops/{tenant}/suggestions/catalogue  find a product to choose
    PUT    /console/shops/{tenant}/suggestions/{product}  the owner's choice
    DELETE /console/shops/{tenant}/suggestions/{product}  back to automatic

**Who.** The console's own session and membership check (``acting_for``), then
the tenant's entitlement to this agent — checked here, inside the agent, which is
what keeps the agent's name out of the deployable.

**Nothing here calls the shop.** Titles and ids come from the synced catalogue.
A shopper's basket page asks the live shop whether each chosen product is still
buyable; this screen only records what the owner wants shown.

**Nothing here writes to the shop** (ADR-0010). A choice is our row, about our
suggestion.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from neura_agent_sell.pairing import select as pairing_rules
from neura_agent_sell.pairing.cache import source_hash
from neura_agent_sell.pairing.choices import DatabaseOwnerChoices
from neura_agent_sell.pairing.schema import sell_pairings
from neura_commerce.identity import EntityType
from neura_commerce.sync.schema import synced_entities
from neura_core import AgentNotEnabledError, NotFoundError, ValidationError, get_logger
from neura_core.db import get_database
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.schema import tenant_stores
from neura_domain import Product

log = get_logger(__name__)

#: Products per page of the screen.
PAGE_SIZE = 50

#: Results the product picker returns for one search.
PICKER_LIMIT = 20

_ENTITIES = synced_entities.c
_PAIRINGS = sell_pairings.c
_PRODUCT = EntityType.PRODUCT.value

#: A product id as the nine endpoints report it. Same alphabet the storefront
#: route accepts, so a choice can only name something a page could send.
_PRODUCT_ID = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class Choice(BaseModel):
    """The owner's list for one product. Empty means *show nothing*."""

    model_config = ConfigDict(extra="forbid")

    product_ids: list[Annotated[str, _PRODUCT_ID]] = Field(
        default_factory=list, max_length=pairing_rules.MAX_CHOSEN
    )


async def _owner(request: Request, tenant_id: str, agent_key: str) -> tuple[Any, str]:
    """A console member of this shop, the shop has this agent, and its store id."""
    from neura_api.dependencies import acting_for

    actor = await acting_for(request, tenant_id)
    db = get_database()
    async with db.tenant_session(actor.tenant_id) as session:
        tenant = await TenantRepository(session).get(actor.tenant_id)
        store_id = await session.scalar(
            select(tenant_stores.c.id)
            .where(tenant_stores.c.tenant_id == actor.tenant_id)
            .order_by(tenant_stores.c.created_at)
            .limit(1)
        )

    if tenant is None or not tenant.may_use(agent_key):
        raise AgentNotEnabledError(
            "Suggestions are part of NEURA-SELL, which this shop does not have.",
            details={"agent": agent_key},
        )
    if store_id is None:
        raise NotFoundError(
            "No shop is connected yet, so there is nothing to suggest.",
            code="NO_STORE_CONNECTED",
        )
    return actor, str(store_id)


def register(router: APIRouter, agent_key: str) -> None:
    """Attach the four endpoints to SELL's router."""

    @router.get("/console/shops/{tenant_id}/suggestions", include_in_schema=False)
    async def list_suggestions(
        request: Request,
        tenant_id: str,
        after: Annotated[str | None, Query(max_length=255)] = None,
        q: Annotated[str | None, Query(max_length=100)] = None,
    ) -> dict[str, Any]:
        actor, store_id = await _owner(request, tenant_id, agent_key)
        db = get_database()

        async with db.tenant_session(actor.tenant_id) as session:
            query = (
                select(_ENTITIES.external_id, _ENTITIES.document)
                .where(_ENTITIES.tenant_id == actor.tenant_id)
                .where(_ENTITIES.entity_type == _PRODUCT)
                .order_by(_ENTITIES.external_id)
                .limit(PAGE_SIZE + 1)
            )
            if after:
                query = query.where(_ENTITIES.external_id > after)
            if q and q.strip():
                query = query.where(_ENTITIES.document["title"].astext.ilike(f"%{q.strip()}%"))
            rows = (await session.execute(query)).all()
            page = rows[:PAGE_SIZE]
            ids = [str(row.external_id) for row in page]

            stored = {
                str(row.product_id): (list(row.suggested_ids or []), str(row.source_hash))
                for row in (
                    await session.execute(
                        select(_PAIRINGS.product_id, _PAIRINGS.suggested_ids, _PAIRINGS.source_hash)
                        .where(_PAIRINGS.tenant_id == actor.tenant_id)
                        .where(_PAIRINGS.store_id == store_id)
                        .where(_PAIRINGS.product_id.in_(ids))
                    )
                ).all()
            }

        choices = await DatabaseOwnerChoices(
            db, tenant_id=actor.tenant_id, store_id=store_id
        ).for_products(ids)

        items: list[dict[str, Any]] = []
        wanted: set[str] = set()
        for row in page:
            product_id = str(row.external_id)
            choice = choices.get(product_id)
            if choice is not None:
                mode, suggested, chosen_at = "owner", choice.chosen_ids, choice.chosen_at
            elif (automatic := _usable(stored.get(product_id), row.document)) is not None:
                mode, suggested, chosen_at = "automatic", automatic, None
            else:
                mode, suggested, chosen_at = "pending", [], None
            wanted.update(suggested)
            items.append(
                {
                    "product_id": product_id,
                    "title": _title(row.document),
                    "mode": mode,
                    "suggested": suggested,
                    "chosen_at": chosen_at.isoformat() if isinstance(chosen_at, datetime) else None,
                }
            )

        titles = await _titles(actor.tenant_id, sorted(wanted))
        for item in items:
            item["suggested"] = [
                {"product_id": sid, "title": titles.get(sid)} for sid in item["suggested"]
            ]

        return {
            "data": {"products": items, "max_chosen": pairing_rules.MAX_CHOSEN},
            "meta": {
                "has_more": len(rows) > PAGE_SIZE,
                "next_cursor": ids[-1] if len(rows) > PAGE_SIZE and ids else None,
            },
        }

    @router.get("/console/shops/{tenant_id}/suggestions/catalogue", include_in_schema=False)
    async def find_products(
        request: Request,
        tenant_id: str,
        q: Annotated[str, Query(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        actor, _ = await _owner(request, tenant_id, agent_key)
        async with get_database().tenant_session(actor.tenant_id) as session:
            rows = (
                await session.execute(
                    select(_ENTITIES.external_id, _ENTITIES.document)
                    .where(_ENTITIES.tenant_id == actor.tenant_id)
                    .where(_ENTITIES.entity_type == _PRODUCT)
                    .where(_ENTITIES.document["title"].astext.ilike(f"%{q.strip()}%"))
                    .order_by(_ENTITIES.external_id)
                    .limit(PICKER_LIMIT)
                )
            ).all()
        return {
            "data": [
                {"product_id": str(row.external_id), "title": _title(row.document)} for row in rows
            ]
        }

    @router.put("/console/shops/{tenant_id}/suggestions/{product_id}", include_in_schema=False)
    async def choose(
        request: Request,
        tenant_id: str,
        product_id: Annotated[str, Path(max_length=128)],
        body: Choice,
    ) -> dict[str, Any]:
        actor, store_id = await _owner(request, tenant_id, agent_key)

        chosen = list(dict.fromkeys(body.product_ids))
        if product_id in chosen:
            raise ValidationError(
                "A product cannot be suggested with itself.", details={"product_id": product_id}
            )

        known = set(await _titles(actor.tenant_id, [product_id, *chosen]))
        missing = [pid for pid in [product_id, *chosen] if pid not in known]
        if missing:
            # Only products from the shop's own catalogue. A choice naming
            # anything else is refused here, where it is a mistake the owner
            # can see, rather than silently shown as nothing on a basket page.
            raise ValidationError(
                "Only products from your own synced catalogue can be chosen.",
                code="UNKNOWN_PRODUCT",
                details={"missing": missing},
            )

        await DatabaseOwnerChoices(
            get_database(), tenant_id=actor.tenant_id, store_id=store_id
        ).choose(product_id, chosen, chosen_by=actor.user_id)

        log.info(
            "pairing_owner_chose",
            tenant_id=actor.tenant_id,
            product_id=product_id,
            chosen=len(chosen),
        )
        return {"data": {"product_id": product_id, "mode": "owner", "suggested": chosen}}

    @router.delete("/console/shops/{tenant_id}/suggestions/{product_id}", include_in_schema=False)
    async def reset(
        request: Request,
        tenant_id: str,
        product_id: Annotated[str, Path(max_length=128)],
    ) -> dict[str, Any]:
        actor, store_id = await _owner(request, tenant_id, agent_key)
        removed = await DatabaseOwnerChoices(
            get_database(), tenant_id=actor.tenant_id, store_id=store_id
        ).reset(product_id)
        log.info("pairing_owner_reset", tenant_id=actor.tenant_id, product_id=product_id)
        return {"data": {"product_id": product_id, "mode": "automatic", "reset": removed}}


def _usable(stored: tuple[list[str], str] | None, document: Any) -> list[str] | None:
    """A computed pairing the request path would actually use, or ``None``.

    The same rule as ``DatabasePairingCache.get``: a pairing whose product text
    has changed since is ignored on the basket page, so it must not be reported
    here as what shoppers see.
    """
    if stored is None:
        return None
    ids, stored_hash = stored
    if not ids:
        # A stored EMPTY pairing — the model ran and matched nothing. The basket
        # page then answers from the product's own words, so reporting "chosen
        # by AI" over an empty list would describe something no shopper sees.
        # Found by driving this screen against the real shop, 2026-09-27.
        return None
    try:
        current = source_hash(Product.model_validate(document))
    except Exception:
        return None
    return [str(i) for i in ids][: pairing_rules.MAX_CHOSEN] if stored_hash == current else None


async def _titles(tenant_id: str, product_ids: list[str]) -> dict[str, str | None]:
    """Title per product id, for the ids the synced catalogue holds."""
    if not product_ids:
        return {}
    async with get_database().tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(_ENTITIES.external_id, _ENTITIES.document)
                .where(_ENTITIES.tenant_id == tenant_id)
                .where(_ENTITIES.entity_type == _PRODUCT)
                .where(_ENTITIES.external_id.in_(product_ids))
            )
        ).all()
    return {str(row.external_id): _title(row.document) for row in rows}


def _title(document: Any) -> str | None:
    title = (document or {}).get("title")
    return str(title) if title else None


__all__ = ["PAGE_SIZE", "PICKER_LIMIT", "register"]
