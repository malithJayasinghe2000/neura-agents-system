"""The owner's side of the paired suggestion — [ADR-0050].

Four console endpoints, mounted under SELL's prefix through the same
``neura.agent_routes`` seam as the feed and MCP, so ``neura-api`` still never
learns an agent's name:

    GET    /console/shops/{tenant}/suggestions                    each product, and who decides it
    GET    /console/shops/{tenant}/suggestions/catalogue          find a product to choose
    GET    /console/shops/{tenant}/suggestions/{product}/preview  what a basket shows with it now
    PUT    /console/shops/{tenant}/suggestions/{product}          the owner's choice
    DELETE /console/shops/{tenant}/suggestions/{product}          back to automatic

**Who.** The console's own session, membership and role check, stated on each
route with SELL's own permission, ``sell:suggestions:write`` (ADR-0058 §1: each
agent brings its own permissions; the Owner holds every one, nobody else holds
this one yet). Then the tenant's entitlement to this agent — checked here,
inside the agent, which is what keeps the agent's name out of the deployable.

**Only the preview calls the shop, and only when the owner opens a product**
(2026-09-28, the owner's approved redesign). Everything else — titles, ids,
categories, prices, who decides — comes from the synced catalogue. The preview
runs the basket's own ``suggest()`` with the basket's own cache and choices, so
what it shows is what a shopper's basket would show at that moment; the one
difference is that **it never queues the model** (:class:`_ReadOnlyPairings`).
Before it, the screen said *"Automatic"* over an empty row for every product the
words decided, because a word-path answer is computed live and never stored.

**Nothing here writes to the shop** (ADR-0010). A choice is our row, about our
suggestion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from neura_agent_sell.pairing import Pairing, suggest
from neura_agent_sell.pairing import select as pairing_rules
from neura_agent_sell.pairing.cache import source_hash
from neura_agent_sell.pairing.choices import DatabaseOwnerChoices
from neura_agent_sell.pairing.schema import sell_pairings
from neura_api.dependencies import ConsoleActor, Permitted
from neura_commerce.identity import EntityType
from neura_commerce.sync.schema import synced_entities
from neura_core import AgentNotEnabledError, NotFoundError, ValidationError, get_logger
from neura_core.db import get_database
from neura_core.tenancy import TenantRepository
from neura_core.tenancy.schema import tenant_stores
from neura_domain import Product

log = get_logger(__name__)

#: Products per page of the screen — the same as Conversations.
PAGE_SIZE = 25

#: The category filter's word for "no category at all", which is not an id.
NO_CATEGORY = "none"

#: How many products the list reads to count them and filter by who decides.
#: A bound, not a judgement — who decides is worked out per product, so a count
#: needs every product — and the counts say when they stopped short
#: (``meta.counted_all``) rather than presenting a part as the whole.
MAX_SCANNED = 2000

#: Who decides a product's suggestions, as the list reports it: the owner, a
#: stored AI pairing (``automatic``), or the product's own words when a basket
#: first shows it (``pending``).
MODES = ("owner", "automatic", "pending")

#: Results the product picker returns for one search.
PICKER_LIMIT = 20

#: SELL's own permission (ADR-0058 §1): choosing what shows with a product, and
#: the screen that does it. The Owner's alone for now (§2).
SUGGESTIONS = "sell:suggestions:write"

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


async def _store(actor: ConsoleActor, agent_key: str) -> str:
    """The shop has this agent, and the id of its store.

    Who the person is, and whether their role may, was decided on the route
    before this runs (``Permitted``).
    """
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
    return str(store_id)


def register(router: APIRouter, agent_key: str) -> None:
    """Attach the four endpoints to SELL's router."""

    @router.get("/console/shops/{tenant_id}/suggestions", include_in_schema=False)
    async def list_suggestions(
        actor: Annotated[ConsoleActor, Depends(Permitted(SUGGESTIONS))],
        after: Annotated[str | None, Query(max_length=255)] = None,
        q: Annotated[str | None, Query(max_length=100)] = None,
        mode: Annotated[str | None, Query(max_length=16)] = None,
        category: Annotated[str | None, Query(max_length=128)] = None,
    ) -> dict[str, Any]:
        store_id = await _store(actor, agent_key)
        wanted = _mode(mode)
        classified, counted_all = await _rows(actor.tenant_id, store_id, q=q)

        # The category menu: every category the searched products carry, and
        # how many have none — given the search, never given the category
        # filter itself, so the menu always offers every way out.
        categories = await _category_menu(actor.tenant_id, classified)

        # A category id is data, never a branch: an unknown one matches nothing
        # rather than being refused, which is what an honest filter on it shows.
        # `none` is the one word that is not an id: products with no category,
        # the ones that can never get an automatic suggestion.
        if category:
            classified = [
                item
                for item in classified
                if (
                    not item["category_ids"]
                    if category == NO_CATEGORY
                    else category in item["category_ids"]
                )
            ]

        # Counts for the chips, given the search and the category — never given
        # the mode filter itself, so each chip says what choosing it would show.
        counts = {"all": len(classified)} | {
            name: sum(1 for item in classified if item["mode"] == name) for name in MODES
        }
        kept = [item for item in classified if wanted is None or item["mode"] == wanted]

        # Pages of PAGE_SIZE, the way Conversations pages: a cursor to fetch, and
        # a position that is counted for the words "Showing 26-38 of 38".
        start = 0
        if after:
            # Position in the order the catalogue was read in, rather than a
            # string comparison that could disagree with the database's.
            position = next((i for i, item in enumerate(kept) if item["product_id"] == after), None)
            start = (
                position + 1
                if position is not None
                else next(
                    (i for i, item in enumerate(kept) if item["product_id"] > after), len(kept)
                )
            )
        page = await _decorate(actor.tenant_id, kept[start : start + PAGE_SIZE])
        has_more = start + PAGE_SIZE < len(kept)
        before = start - PAGE_SIZE - 1

        return {
            "data": {"products": page, "max_chosen": pairing_rules.MAX_CHOSEN},
            "meta": {
                "has_more": has_more,
                "next_cursor": page[-1]["product_id"] if has_more and page else None,
                "total": len(kept),
                "offset": start,
                "has_previous": start > 0,
                # `null` with `has_previous` true means the page before is the first.
                "previous_cursor": kept[before]["product_id"]
                if start > 0 and before >= 0
                else None,
                "counts": counts,
                "counted_all": counted_all,
                "categories": categories,
            },
        }

    @router.get(
        "/console/shops/{tenant_id}/suggestions/{product_id}/preview", include_in_schema=False
    )
    async def preview(
        request: Request,
        actor: Annotated[ConsoleActor, Depends(Permitted(SUGGESTIONS))],
        product_id: Annotated[str, Path(max_length=128)],
    ) -> dict[str, Any]:
        """What a shopper's basket shows with this product **now** — asked of the shop.

        The basket's own ``suggest()``, its own cache and its own owner choices,
        through the same seams the storefront route uses, so the preview cannot
        drift from what a shopper sees. It differs in exactly one way: the cache
        is read-only, so **opening a product never queues the model**.

        A shop that does not answer is reported as that (``reachable: false``),
        not as an empty result: ``suggest()`` forgives a failed lookup as a
        missing product, which on this screen would read as *"not in your shop"*.
        """
        from neura_agent_sell import routes as sell_routes

        store_id = await _store(actor, agent_key)
        asked_at = datetime.now(UTC)
        tried = await _computed(actor.tenant_id, store_id, product_id)
        # The product as the list shows it, so the screen can head the preview
        # even when a filter or a page has left it out of the list.
        found, _ = await _rows(actor.tenant_id, store_id, product_id=product_id)
        row = (await _decorate(actor.tenant_id, found))[0] if found else None

        try:
            connection = await request.app.state.stores.connect(actor.tenant_id, store_id=store_id)
        except Exception as exc:
            log.warning(
                "pairing_preview_unreachable", tenant_id=actor.tenant_id, error=type(exc).__name__
            )
            return {"data": _preview_payload(product_id, asked_at, None, tried, row)}

        try:
            try:
                anchor = await connection.adapter.get_product(product_id)
            except Exception as exc:
                log.warning(
                    "pairing_preview_unreachable",
                    tenant_id=actor.tenant_id,
                    error=type(exc).__name__,
                )
                return {"data": _preview_payload(product_id, asked_at, None, tried, row)}

            pairing = (
                Pairing(reason="not_found")
                if anchor is None
                else await suggest(
                    [product_id],
                    adapter=connection.adapter,
                    capabilities=connection.capabilities,
                    tenant_id=actor.tenant_id,
                    cache=_ReadOnlyPairings(
                        sell_routes._pairing_cache(actor.tenant_id, connection.store_id)
                    ),
                    choices=sell_routes._owner_choices(actor.tenant_id, connection.store_id),
                )
            )
        finally:
            await sell_routes._close(connection.adapter)

        log.info(
            "pairing_previewed",
            tenant_id=actor.tenant_id,
            product_id=product_id,
            origin=pairing.origin,
            reason=pairing.reason,
            shown=len(pairing.suggestions),
        )
        return {"data": _preview_payload(product_id, asked_at, pairing, tried, row)}

    @router.get("/console/shops/{tenant_id}/suggestions/catalogue", include_in_schema=False)
    async def find_products(
        actor: Annotated[ConsoleActor, Depends(Permitted(SUGGESTIONS))],
        q: Annotated[str, Query(min_length=1, max_length=100)],
    ) -> dict[str, Any]:
        await _store(actor, agent_key)
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
                {
                    "product_id": str(row.external_id),
                    "title": _title(row.document),
                    "price": _price(row.document),
                }
                for row in rows
            ]
        }

    @router.put("/console/shops/{tenant_id}/suggestions/{product_id}", include_in_schema=False)
    async def choose(
        actor: Annotated[ConsoleActor, Depends(Permitted(SUGGESTIONS))],
        product_id: Annotated[str, Path(max_length=128)],
        body: Choice,
    ) -> dict[str, Any]:
        store_id = await _store(actor, agent_key)

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
        actor: Annotated[ConsoleActor, Depends(Permitted(SUGGESTIONS))],
        product_id: Annotated[str, Path(max_length=128)],
    ) -> dict[str, Any]:
        store_id = await _store(actor, agent_key)
        removed = await DatabaseOwnerChoices(
            get_database(), tenant_id=actor.tenant_id, store_id=store_id
        ).reset(product_id)
        log.info("pairing_owner_reset", tenant_id=actor.tenant_id, product_id=product_id)
        return {"data": {"product_id": product_id, "mode": "automatic", "reset": removed}}


class _ReadOnlyPairings:
    """The basket's pairing cache, minus the one thing a preview must never do.

    On a shopper's basket a miss queues a model computation ([ADR-0045] §2: the
    first *shopper* is answered from words, and the model runs for the next).
    An owner opening a product in the console is not that first use, and a
    screen that queued the model for every product an owner clicked through
    would spend a model call per click — so this reads what is stored and
    queues nothing.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    async def get(self, product_id: str, *, source_hash: str) -> list[str] | None:
        result: list[str] | None = await self._inner.get(product_id, source_hash=source_hash)
        return result

    async def queue(self, product_id: str, *, source_hash: str) -> None:
        return None


def _preview_payload(
    product_id: str,
    asked_at: datetime,
    pairing: Pairing | None,
    tried: dict[str, Any] | None,
    row: dict[str, Any] | None,
) -> dict[str, Any]:
    """The preview as the screen reads it. ``pairing`` is ``None`` when the shop
    did not answer — which is said, never shown as an empty result."""
    return {
        "product_id": product_id,
        # The list's row for this product; `null` when the synced catalogue
        # does not hold it.
        "product": row,
        "reachable": pairing is not None,
        "asked_at": asked_at.isoformat(),
        # owner · model · words — null when nothing is shown.
        "origin": (pairing.origin or None) if pairing else None,
        # Why nothing is shown, when nothing is — see `Pairing.reason`.
        "reason": (pairing.reason or None) if pairing else None,
        "heading": (pairing.heading or None) if pairing else None,
        # The same cards a basket gets: id, title, in_stock, price, currency, url, image.
        "suggestions": pairing.suggestions if pairing else [],
        # What the AI looked for, if it has run for this product's current text.
        "ai": tried,
    }


async def _computed(tenant_id: str, store_id: str, product_id: str) -> dict[str, Any] | None:
    """What the AI looked for and how many products it found — or ``None``.

    Only for a pairing computed from the product's **current** text (the same
    rule as :func:`_usable`): kinds the AI named for words the owner has since
    changed describe a product that no longer exists.
    """
    async with get_database().tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                select(_PAIRINGS.kinds, _PAIRINGS.suggested_ids, _PAIRINGS.source_hash)
                .where(_PAIRINGS.tenant_id == tenant_id)
                .where(_PAIRINGS.store_id == store_id)
                .where(_PAIRINGS.product_id == product_id)
            )
        ).first()
        document = await session.scalar(
            select(_ENTITIES.document)
            .where(_ENTITIES.tenant_id == tenant_id)
            .where(_ENTITIES.entity_type == _PRODUCT)
            .where(_ENTITIES.external_id == product_id)
        )
    if row is None or document is None:
        return None
    try:
        current = source_hash(Product.model_validate(document)) == str(row.source_hash)
    except Exception:
        return None
    if not current:
        return None
    return {
        "kinds": [str(kind) for kind in (row.kinds or [])],
        "found": len(row.suggested_ids or []),
    }


async def _rows(
    tenant_id: str, store_id: str, *, q: str | None = None, product_id: str | None = None
) -> tuple[list[dict[str, Any]], bool]:
    """Products from the synced catalogue, each with who decides it and what it
    shows — every product (bounded by :data:`MAX_SCANNED`), those whose title
    matches ``q``, or the one ``product_id``. Returns the rows and whether the
    bound left any out.
    """
    db = get_database()
    async with db.tenant_session(tenant_id) as session:
        query = (
            select(_ENTITIES.external_id, _ENTITIES.document)
            .where(_ENTITIES.tenant_id == tenant_id)
            .where(_ENTITIES.entity_type == _PRODUCT)
            .order_by(_ENTITIES.external_id)
            .limit(MAX_SCANNED + 1)
        )
        if q and q.strip():
            query = query.where(_ENTITIES.document["title"].astext.ilike(f"%{q.strip()}%"))
        if product_id is not None:
            query = query.where(_ENTITIES.external_id == product_id)
        scanned = (await session.execute(query)).all()
        counted_all = len(scanned) <= MAX_SCANNED
        scanned = scanned[:MAX_SCANNED]
        ids = [str(row.external_id) for row in scanned]

        stored = {
            str(row.product_id): (list(row.suggested_ids or []), str(row.source_hash))
            for row in (
                await session.execute(
                    select(_PAIRINGS.product_id, _PAIRINGS.suggested_ids, _PAIRINGS.source_hash)
                    .where(_PAIRINGS.tenant_id == tenant_id)
                    .where(_PAIRINGS.store_id == store_id)
                    .where(_PAIRINGS.product_id.in_(ids))
                )
            ).all()
        }

    choices = await DatabaseOwnerChoices(db, tenant_id=tenant_id, store_id=store_id).for_products(
        ids
    )

    rows: list[dict[str, Any]] = []
    for row in scanned:
        pid = str(row.external_id)
        choice = choices.get(pid)
        if choice is not None:
            decided, suggested, chosen_at = "owner", choice.chosen_ids, choice.chosen_at
        elif (automatic := _usable(stored.get(pid), row.document)) is not None:
            decided, suggested, chosen_at = "automatic", automatic, None
        else:
            decided, suggested, chosen_at = "pending", [], None
        rows.append(
            {
                "product_id": pid,
                "title": _title(row.document),
                "mode": decided,
                "suggested": suggested,
                "chosen_at": chosen_at.isoformat() if isinstance(chosen_at, datetime) else None,
                "category_ids": _category_ids(row.document),
                "price": _price(row.document),
            }
        )
    return rows, counted_all


async def _decorate(tenant_id: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Titles for what each row suggests and names for its categories — for the
    rows about to be sent, not for every row counted."""
    titles = await _titles(tenant_id, sorted({sid for row in rows for sid in row["suggested"]}))
    names = await _category_names(
        tenant_id, sorted({cid for row in rows for cid in row["category_ids"]})
    )
    for row in rows:
        row["suggested"] = [
            {"product_id": sid, "title": titles.get(sid)} for sid in row["suggested"]
        ]
        # Names, in the product's own order; an id the catalogue cannot name is
        # left out rather than shown as a code.
        row["categories"] = [names[cid] for cid in row.pop("category_ids") if cid in names]
    return rows


async def _category_menu(tenant_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The category filter's options: each category these products carry, by
    name, with how many products are in it — and how many carry none."""
    held: dict[str, int] = {}
    for row in rows:
        for cid in row["category_ids"]:
            held[cid] = held.get(cid, 0) + 1
    names = await _category_names(tenant_id, sorted(held))
    return {
        # Named ones only, by name: an id the catalogue cannot name is not a
        # choice an owner could recognise.
        "named": sorted(
            (
                {"id": cid, "name": names[cid], "count": count}
                for cid, count in held.items()
                if cid in names
            ),
            key=lambda option: option["name"].lower(),
        ),
        "none": sum(1 for row in rows if not row["category_ids"]),
    }


def _mode(value: str | None) -> str | None:
    """The mode filter, or a 400 — a filter silently ignored returns every
    product while looking filtered."""
    if value in (None, ""):
        return None
    if value not in MODES:
        raise ValidationError(
            "Unknown suggestion mode.", details={"mode": value, "expected": list(MODES)}
        )
    return value


def _category_ids(document: Any) -> list[str]:
    return [str(cid) for cid in ((document or {}).get("category_ids") or [])]


def _price(document: Any) -> dict[str, str] | None:
    """The product's lowest price as the catalogue holds it, or ``None``."""
    price = (document or {}).get("price_range_min") or {}
    if not price.get("amount"):
        return None
    return {"amount": str(price["amount"]), "currency": str(price.get("currency") or "")}


async def _category_names(tenant_id: str, category_ids: list[str]) -> dict[str, str]:
    """Name per category id, for the ids the synced catalogue holds."""
    if not category_ids:
        return {}
    async with get_database().tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(_ENTITIES.external_id, _ENTITIES.document)
                .where(_ENTITIES.tenant_id == tenant_id)
                .where(_ENTITIES.entity_type == EntityType.CATEGORY.value)
                .where(_ENTITIES.external_id.in_(category_ids))
            )
        ).all()
    return {
        str(row.external_id): str(name)
        for row in rows
        if (name := (row.document or {}).get("name") or (row.document or {}).get("title"))
    }


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


__all__ = ["MAX_SCANNED", "MODES", "NO_CATEGORY", "PAGE_SIZE", "PICKER_LIMIT", "register"]
