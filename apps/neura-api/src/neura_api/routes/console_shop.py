"""The merchant's own shop, as the console shows it. ADR-0026, `console.md §3.4`.

**Read-only in v1, and that is a decision rather than an unfinished screen.**
`console.md §3.4` designs a *connect* form — URL plus token, written through the
envelope-encryption path. It is not built here, and the reason is the shape of
the console's authority rather than the size of the form:

> The console's entire write surface today is one grading verdict. Adding a
> browser form that submits a store credential makes the highest-value target in
> the application, on the screen a merchant opens least often, before anybody has
> connected a shop through anything but the CLI.

Connecting stays on `POST /v1/stores` and `make tenant-new`, exactly as it works
now. This is the same reasoning ADR-0026 §6 used to defer the approval queue —
do not build authority before there is something that needs it — and it is
recorded so that whoever adds the form later is adding it deliberately.

## What the screen must never show, and how that is guaranteed here

`console.md §3.4`: **the console never displays a stored credential**, not even
masked to its owner, because a field that can be revealed is a field that gets
revealed in a screen-share. The guarantee is structural rather than careful:
this module reads through `StoreConnectionRepository.list_for`, which selects
four columns — id, platform, base_url, status — and cannot return `credentials`
or `wrapped_dek` because it never asks for them. Nothing here decrypts anything;
`StoreDirectory.connect` is the only path that does, and it is used only for the
live probe below, whose response carries capabilities and no secret.

## The live probe is opt-in

A page load must not make an outbound request to the merchant's own server every
time somebody glances at it. So the checkpointed state — last sync, counts,
status — comes from the database, and *"is it reachable right now?"* is a
separate call the merchant asks for. `routes/stores.py` makes the same
distinction for the same reason: a cached "everything is fine" is the least
useful possible answer to somebody whose shop is down.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from neura_api.dependencies import acting_for
from neura_api.envelopes import envelope
from neura_commerce.identity import EntityType
from neura_commerce.sync.postgres import PostgresEntityStore, PostgresSyncStateStore
from neura_core import NotFoundError, ServiceUnavailableError, get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: What the catalogue is counted for. Products and categories are what CARE
#: retrieves and what SELL shortlists; orders and customers are looked up live
#: through the store and are deliberately **not** synced (commerce-integration.md),
#: so counting them here would report zero and read as a broken sync.
COUNTED = (EntityType.PRODUCT, EntityType.VARIANT, EntityType.CATEGORY, EntityType.POLICY)


@router.get("/store", summary="This shop's connection, its last sync and what was synced")
async def shop_store(request: Request, tenant_id: str) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)

    directory = request.app.state.stores
    # Four columns, no secrets — see this module's docstring. The safety is that
    # the query does not select them, not that something downstream strips them.
    rows = await directory.rows_for(actor.tenant_id)

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        checkpoints = await PostgresSyncStateStore(session).all_for_tenant(actor.tenant_id)
        entities = PostgresEntityStore(session)
        counts = {
            row["id"]: {
                kind.value: await entities.count(actor.tenant_id, row["platform"], kind)
                for kind in COUNTED
            }
            for row in rows
        }

    by_platform: dict[str, list[dict[str, Any]]] = {}
    for checkpoint in checkpoints:
        by_platform.setdefault(checkpoint.key.platform, []).append(_checkpoint_payload(checkpoint))

    return envelope(
        {
            "stores": [
                {
                    **row,
                    "catalogue": counts.get(row["id"], {}),
                    "syncs": sorted(
                        by_platform.get(row["platform"], []), key=lambda s: str(s["entity_type"])
                    ),
                }
                for row in rows
            ],
            # Said plainly rather than left for the screen to infer from an
            # empty list. "No shop connected" and "we could not read your
            # shops" are different sentences and only one of them is true here.
            "connected": bool(rows),
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/store/{store_id}/health", summary="Is this shop reachable right now?")
async def shop_health(request: Request, tenant_id: str, store_id: str) -> dict[str, Any]:
    """A live call to the merchant's own server, made only when asked.

    Deliberately **not** part of the screen's first render: a page load that
    probes an external host every time somebody glances at it turns a dashboard
    into a monitoring agent nobody asked for. The cache is bypassed for the
    reason `routes/stores.py` gives — this is the endpoint somebody hits when
    something is wrong, and a cached "everything is fine" is the least useful
    possible answer to that.

    Returns a **200 describing a failure** rather than a 503, because from the
    console's point of view "your shop did not answer" is the result, not an
    error in this API. A 503 here would be indistinguishable from our own
    outage in exactly the moment a merchant is trying to tell the two apart.
    """
    actor = await acting_for(request, tenant_id)
    directory = request.app.state.stores

    rows = await directory.rows_for(actor.tenant_id)
    if not any(row["id"] == store_id for row in rows):
        raise NotFoundError("No such store connection.", details={"store_id": store_id})

    directory.forget(store_id)
    try:
        connection = await directory.connect(actor.tenant_id, store_id=store_id)
    except ServiceUnavailableError as unreachable:
        log.info("console_store_unreachable", tenant_id=actor.tenant_id, store_id=store_id)
        return envelope(
            {
                "id": store_id,
                "reachable": False,
                # The adapter's own words. A friendlier sentence invented here
                # would hide the one detail whoever fixes this needs.
                "detail": str(unreachable),
                "capabilities": [],
            },
            request_id=getattr(request.state, "request_id", None),
        )

    try:
        return envelope(
            {
                "id": store_id,
                "reachable": True,
                "detail": "",
                # What the *store* declares, not what we assume it can do.
                # Sorted, so a merchant diffing two checks sees a change only
                # when the capabilities changed.
                "capabilities": sorted(c.value for c in connection.capabilities),
            },
            request_id=getattr(request.state, "request_id", None),
        )
    finally:
        # An adapter holds an HTTP client. One built and abandoned leaks a
        # connection pool — per page view, on this route.
        await _close(connection.adapter)


def _checkpoint_payload(checkpoint: Any) -> dict[str, Any]:
    """One entity type's sync position.

    ``completed_at`` is nullable and is **not** defaulted to anything. A sync
    that has never finished and a sync that finished at the epoch are different
    facts, and only one of them should make a merchant worry.
    """
    return {
        "entity_type": checkpoint.key.entity_type.value,
        "completed_at": (checkpoint.completed_at.isoformat() if checkpoint.completed_at else None),
        "updated_through": (
            checkpoint.updated_through.isoformat() if checkpoint.updated_through else None
        ),
        "last_run_count": checkpoint.last_run_count,
        # Whether a crawl is mid-flight. The cursor itself is **not** returned:
        # it is opaque by design (api-design.md §5) and a merchant can do
        # nothing with it but paste it somewhere it will go stale.
        "in_progress": checkpoint.cursor is not None,
    }


async def _close(adapter: Any) -> None:
    closer = getattr(adapter, "aclose", None) or getattr(adapter, "close", None)
    if closer is None:
        return
    result = closer()
    if hasattr(result, "__await__"):
        await result


__all__ = ["COUNTED", "router"]
