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

## Redesigned 2026-09-28 — a checklist, and Sync now

From the owner's approved mockup (`console.md §3.4`, canvas boards 21-23). The
screen became a *Get set up* checklist, so this route now also says, read from
our own tables and never from the shop:

* **whether the chat box is on the shop** — the most recently used live public
  key's ``last_used_at`` and the addresses it is allowed on. Two columns are
  selected, so the key, its prefix, its hash and its scopes cannot be returned
  (the same structural guarantee as the credentials above);
* **the data agreement** and **whether product views arrive** — the two facts
  Sold out's *Is it working?* shows, over the same seven days;
* **how much of the catalogue search by meaning covers** — synced products that
  have at least one chunk in the index. Display only: rebuilding the index runs
  a model, and this screen does not offer it.

**Sync now is the third console write** (after grading and the owner's
suggestions), and it writes **only our copy**: it queues the sync job that
already exists (`enqueue_sync`), which hands back the queued or running job
rather than adding a second — pressing it four times is one sync. It is a
**full** read, not an incremental one: the screen promises that stock changes
show up after the next sync, and a shop's *changed since* filter follows a
product's own edits, so a sale that lowers stock is invisible to it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import exists, func, or_, select

from neura_agent_core.rag.schema import document_chunks
from neura_api.dependencies import ConsoleActor, Permitted
from neura_api.envelopes import envelope
from neura_api.jobs import SYNC_STORE, enqueue_sync
from neura_api.jobs.sync import dedupe_key_for
from neura_commerce.identity import EntityType
from neura_commerce.sync.postgres import PostgresEntityStore, PostgresSyncStateStore
from neura_commerce.sync.schema import synced_entities
from neura_core import NotFoundError, ServiceUnavailableError, get_logger
from neura_core.identity.roles import CONNECTION_WRITE
from neura_core.jobs import JobQueue
from neura_core.observation import ObservedEventRepository
from neura_core.tenancy import (
    ApiKeyKind,
    ShopCheckRepository,
    ShopTokenRepository,
    StoreConnectionRepository,
    TenantRepository,
    api_keys,
)

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])

#: What the catalogue is counted for. Products and categories are what CARE
#: retrieves and what SELL shortlists; orders and customers are looked up live
#: through the store and are deliberately **not** synced (commerce-integration.md),
#: so counting them here would report zero and read as a broken sync. Variants
#: were dropped 2026-09-28: sizes and colours live inside a product's document,
#: so the count always read 0 beside a catalogue that plainly had them.
COUNTED = (EntityType.PRODUCT, EntityType.CATEGORY, EntityType.POLICY)

#: *"Your shop is sending product views"* looks back as far as Sold out does, so
#: the two screens cannot disagree about the same fact.
VIEWS_WINDOW_DAYS = 7


@router.get("/store", summary="This shop's connection, its last sync and what was synced")
async def shop_store(
    request: Request, actor: Annotated[ConsoleActor, Depends(Permitted(CONNECTION_WRITE))]
) -> dict[str, Any]:
    directory = request.app.state.stores
    # Four columns, no secrets — see this module's docstring. The safety is that
    # the query does not select them, not that something downstream strips them.
    rows = await directory.rows_for(actor.tenant_id)
    now = datetime.now(UTC)

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
        searchable = {
            row["id"]: await _searchable_products(session, actor.tenant_id, row["platform"])
            for row in rows
        }
        jobs = JobQueue(session)
        asked = {
            row["id"]: await jobs.find_by_dedupe(
                actor.tenant_id, SYNC_STORE, dedupe_key_for(row["id"]), live_only=True
            )
            for row in rows
        }
        tenant = await TenantRepository(session).get(actor.tenant_id)
        receiving = await ObservedEventRepository(session).any_views_since(
            actor.tenant_id, since=now - timedelta(days=VIEWS_WINDOW_DAYS)
        )
        chat_box = await _chat_box(session, actor.tenant_id, now)
        # ADR-0052: whether a token is waiting (when, never what), and each
        # connection's last check and when its token was set.
        token_made_at = await ShopTokenRepository(session).made_at(actor.tenant_id)
        check_repo = ShopCheckRepository(session)
        last_checks = {
            row["id"]: await check_repo.latest(actor.tenant_id, store_id=row["id"]) for row in rows
        }
        connect_check = None if rows else await check_repo.latest(actor.tenant_id, store_id=None)
        connections = StoreConnectionRepository(session)
        token_set = {
            row["id"]: await connections.credentials_set_at(actor.tenant_id, row["id"])
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
                    "index": {
                        "products": counts[row["id"]][EntityType.PRODUCT.value],
                        "searchable": searchable[row["id"]],
                    },
                    # A sync somebody asked for that has not finished. Only the
                    # status and when — the payload and any error stay here.
                    "sync_asked": _asked_payload(asked[row["id"]]),
                    "notes": _notes(
                        products=counts[row["id"]][EntityType.PRODUCT.value],
                        searchable=searchable[row["id"]],
                    ),
                    "last_check": last_checks[row["id"]],
                    "token_set_at": _iso(token_set[row["id"]]),
                }
                for row in rows
            ],
            # Before the shop is connected: whether a token is waiting (when,
            # never what) and the last check of the typed address (ADR-0052).
            "connect": None
            if rows
            else {"token_made_at": _iso(token_made_at), "last_check": connect_check},
            # Said plainly rather than left for the screen to infer from an
            # empty list. "No shop connected" and "we could not read your
            # shops" are different sentences and only one of them is true here.
            "connected": bool(rows),
            # The rest of the checklist: facts about the shop, not about one
            # connection, and every one of them read from our own tables.
            "setup": {
                "chat_box": chat_box,
                "agreement_since": (
                    tenant.dpa_signed_at.isoformat() if tenant and tenant.dpa_signed_at else None
                ),
                # A yes or no, never a count — see `any_views_since`.
                "receiving": receiving,
                "window_days": VIEWS_WINDOW_DAYS,
            },
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.post(
    "/store/{store_id}/sync",
    summary="Read this shop again into our copy of its catalogue",
    status_code=202,
)
async def shop_sync(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(CONNECTION_WRITE))],
    store_id: str,
) -> dict[str, Any]:
    """*Sync now* — owner-approved 2026-09-28 (`console.md §3.4`).

    Queues the job that already exists and returns at once: a crawl inside a
    request would time out, and the worker is where a sync runs. **It writes our
    copy and nothing else** — the adapter it runs through has no write method to
    call (ADR-0010). A full read, for the reason in this module's docstring.

    **Pressing it twice is one sync**: `enqueue_sync` hands back the job still
    queued or running for this store rather than adding another.
    """

    rows = await request.app.state.stores.rows_for(actor.tenant_id)
    if not any(row["id"] == store_id for row in rows):
        # Checked before queueing: a job for a store that is not this shop's
        # would dead-letter later, the slowest possible way to say 404.
        raise NotFoundError("No such store connection.", details={"store_id": store_id})

    db = request.app.state.database
    async with db.tenant_session(actor.tenant_id) as session:
        job = await enqueue_sync(session, actor.tenant_id, store_id=store_id, incremental=False)

    log.info(
        "console_sync_requested",
        tenant_id=actor.tenant_id,
        store_id=store_id,
        user_id=actor.user_id,
        job_id=job.id,
    )
    return envelope(
        {"id": store_id, "sync_asked": _asked_payload(job)},
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("/store/{store_id}/health", summary="Is this shop reachable right now?")
async def shop_health(
    request: Request,
    actor: Annotated[ConsoleActor, Depends(Permitted(CONNECTION_WRITE))],
    store_id: str,
) -> dict[str, Any]:
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


async def _searchable_products(session: Any, tenant_id: str, platform: str) -> int:
    """Synced products that search by meaning can find: at least one chunk indexed.

    Counted from the catalogue's side, so an index entry for a product the shop
    no longer has does not inflate the figure. Across every embedding model —
    the console does not know which one the assistant is configured with.
    """
    product = EntityType.PRODUCT.value
    synced = synced_entities.c
    indexed = document_chunks.c
    total = await session.scalar(
        select(func.count())
        .select_from(synced_entities)
        .where(synced.tenant_id == tenant_id)
        .where(synced.platform == platform)
        .where(synced.entity_type == product)
        .where(
            exists()
            .where(indexed.tenant_id == tenant_id)
            .where(indexed.source_type == product)
            .where(indexed.source_id == synced.external_id)
        )
    )
    return int(total or 0)


async def _chat_box(session: Any, tenant_id: str, now: datetime) -> dict[str, Any] | None:
    """Is the chat box on the shop? The most recently used live public key.

    **Two columns, selected by name** — when it was last used and the addresses
    it works from. The key, its prefix, its hash and its scopes are never read
    here, so no later edit to the payload can leak one. ``None`` when the shop
    has no live public key at all.

    A public key only works from its allowed addresses (ADR-0014), so a key
    that has been used at all was used from one of them.
    """
    keys = api_keys.c
    row = (
        await session.execute(
            select(keys.last_used_at, keys.allowed_origins)
            .where(keys.tenant_id == tenant_id)
            .where(keys.kind == ApiKeyKind.PUBLIC.value)
            .where(keys.revoked_at.is_(None))
            .where(or_(keys.expires_at.is_(None), keys.expires_at > now))
            .order_by(keys.last_used_at.desc().nulls_last(), keys.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return {
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "origins": sorted(row.allowed_origins or ()),
    }


def _asked_payload(job: Any) -> dict[str, Any] | None:
    if job is None:
        return None
    return {
        "status": job.status.value,
        "queued_at": job.created_at.isoformat() if job.created_at else None,
    }


def _notes(*, products: int, searchable: int) -> list[dict[str, str]]:
    """The sentences under the catalogue's figures, in the merchant's words.

    From the server, like Usage's caveats (ADR-0020's rule for merchant-facing
    sentences), and by key so the screen places each beside its own figure.
    """
    notes = [
        {
            # True until something schedules a sync — ADR-0022's undecided
            # "cron-shaped table". Whoever builds that changes this sentence.
            "key": "no_schedule",
            "text": (
                "New products and stock changes show up after the next sync — "
                "nothing syncs by itself yet."
            ),
        }
    ]
    if products:
        missing = products - searchable
        notes.append(
            {
                "key": "index",
                "text": (
                    f"Search by meaning covers all {products} products."
                    if missing <= 0
                    else (
                        f"Search by meaning covers {searchable} of {products} products — "
                        f"the other {missing} {'is' if missing == 1 else 'are'} not in it yet, "
                        f"so the AI can't find {'it' if missing == 1 else 'them'} that way."
                    )
                ),
            }
        )
    return notes


async def _close(adapter: Any) -> None:
    closer = getattr(adapter, "aclose", None) or getattr(adapter, "close", None)
    if closer is None:
        return
    result = closer()
    if hasattr(result, "__await__"):
        await result


__all__ = ["COUNTED", "router"]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
