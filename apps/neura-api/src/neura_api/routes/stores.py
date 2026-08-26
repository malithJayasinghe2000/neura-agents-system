"""Connecting a merchant's shop (api-design.md §7, "Store connection").

Without this there is nothing for an agent to talk to, which is why it is in 1.14
rather than waiting for a merchant console: a tenant, a key and an agent are not
enough to answer "where is my order?".

**``GET /v1/stores/{id}`` returns the negotiated capability list**, and that is
the endpoint an integrator actually needs. It is the one place a developer sees,
concretely, which agent abilities their platform does and does not support —
before they discover it from a conversation that quietly never calls a tool.

**``POST /{store_id}/sync`` queues, it does not crawl.** It was left out of 1.14
twice over — the results vanished on restart (fixed by ADR-0021) and there was
nowhere for the work to run (fixed by ADR-0022) — and it is *still* not a
synchronous endpoint, because a request that crawls a catalogue is a request that
times out. It writes a ``job_queue`` row and returns its id; ``GET
/{store_id}/sync/{job_id}`` is where the answer arrives.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from neura_api.dependencies import require
from neura_api.envelopes import envelope
from neura_api.jobs import SYNC_STORE, enqueue_sync
from neura_core import NotFoundError, ServiceUnavailableError, get_logger
from neura_core.jobs import JobQueue, JobStatus
from neura_core.tenancy import AuthenticatedCaller, StoreConnectionRepository

log = get_logger(__name__)

router = APIRouter(prefix="/stores", tags=["stores"])


class ConnectStore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The platform identifier its adapter registered under. Data, not
    #: behaviour: the core stays ignorant of which platforms exist, and this
    #: string is how a merchant's own connector is found (AGENTS.md rule 1).
    platform: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1)
    #: Envelope-encrypted before it touches the database, under a data key
    #: wrapped by the KEK and bound to this tenant (security-model.md §5).
    #: **Never returned by any endpoint here.**
    credentials: dict[str, str]


@router.post(
    "",
    summary="Register a store and its credentials",
    responses={400: {"description": "Unknown platform, or malformed credentials"}},
)
async def connect(
    request: Request,
    body: ConnectStore,
    caller: Annotated[AuthenticatedCaller, Depends(require("stores:write"))],
) -> dict[str, Any]:
    database = request.app.state.database
    async with database.tenant_session(caller.tenant_id) as session:
        store_id = await StoreConnectionRepository(session).connect(
            caller.tenant_id,
            platform=body.platform,
            base_url=body.base_url,
            credentials=body.credentials,
        )

    # A reconnect with new credentials must not keep serving the capability set
    # negotiated with the old ones.
    request.app.state.stores.forget(store_id)

    log.info(
        "store_connected",
        tenant_id=caller.tenant_id,
        store_id=store_id,
        platform=body.platform,
    )
    return envelope(
        {"id": store_id, "platform": body.platform, "base_url": body.base_url, "status": "active"},
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("", summary="List connected stores")
async def list_stores(
    request: Request,
    caller: Annotated[AuthenticatedCaller, Depends(require("stores:read"))],
) -> dict[str, Any]:
    rows = await request.app.state.stores.rows_for(caller.tenant_id)
    return envelope(rows, request_id=getattr(request.state, "request_id", None))


@router.get(
    "/{store_id}",
    summary="One store, including the capabilities it declares",
    responses={503: {"description": "The store is not reachable"}},
)
async def get_store(
    request: Request,
    store_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require("stores:read"))],
) -> dict[str, Any]:
    rows = await request.app.state.stores.rows_for(caller.tenant_id)
    row = next((r for r in rows if r["id"] == store_id), None)
    if row is None:
        raise NotFoundError("No such store connection.", details={"store_id": store_id})

    connection = await request.app.state.stores.connect(caller.tenant_id, store_id=store_id)
    try:
        return envelope(
            {
                **row,
                # Sorted so a client diffing two responses sees a change only
                # when the capabilities changed.
                "capabilities": sorted(c.value for c in connection.capabilities),
            },
            request_id=getattr(request.state, "request_id", None),
        )
    finally:
        await _close(connection.adapter)


@router.get(
    "/{store_id}/health",
    summary="Is this store reachable right now?",
    responses={503: {"description": "The store is not reachable"}},
)
async def store_health(
    request: Request,
    store_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require("stores:read"))],
) -> dict[str, Any]:
    """A live check, deliberately bypassing the capability cache.

    ``GET /{store_id}`` may answer from a cached negotiation; this is the
    endpoint a merchant hits when something is wrong, and a cached "everything
    is fine" is the least useful possible answer to that question.
    """
    request.app.state.stores.forget(store_id)
    try:
        connection = await request.app.state.stores.connect(caller.tenant_id, store_id=store_id)
    except ServiceUnavailableError:
        raise
    try:
        return envelope(
            {
                "id": connection.store_id,
                "status": "ok",
                "base_url": connection.base_url,
                "capabilities": sorted(c.value for c in connection.capabilities),
            },
            request_id=getattr(request.state, "request_id", None),
        )
    finally:
        await _close(connection.adapter)


class RequestSync(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: ``true`` asks only for what changed since the last run; ``false`` is a
    #: full crawl. Defaults to incremental, because that is the one a merchant
    #: can safely press repeatedly.
    incremental: bool = True


@router.post(
    "/{store_id}/sync",
    summary="Queue a sync of this store's catalogue",
    responses={
        202: {"description": "Queued. Poll the returned job for the outcome."},
        404: {"description": "No such store connection"},
    },
    status_code=202,
)
async def request_sync(
    request: Request,
    store_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require("stores:write"))],
    # Optional, because the default is the useful one. A merchant pressing
    # "sync now" should not have to send a JSON body to say "the ordinary kind".
    body: RequestSync | None = None,
) -> dict[str, Any]:
    """Queue a catalogue sync. **202, never 200.**

    A backfill of a real catalogue is minutes of paginated requests against a
    merchant's own server; doing it inside this request would time out, and
    doing it in a background task inside this *process* would lose it on the
    next deploy. It writes one durable job row and returns
    ([ADR-0022](../../../../../docs/architecture/adr/0022-scheduling-under-rls.md)).

    **Pressing it twice is one sync.** While a sync for this store is still
    queued or running, this returns that job rather than adding another — a
    merchant clicking a button four times should not crawl their own shop four
    times. Once it finishes, the next request queues a fresh one.
    """
    rows = await request.app.state.stores.rows_for(caller.tenant_id)
    if not any(row["id"] == store_id for row in rows):
        # Checked before queueing rather than discovered by the worker. A job
        # that dead-letters an hour later because the store id was a typo is a
        # 404 delivered by the slowest possible route.
        raise NotFoundError("No such store connection.", details={"store_id": store_id})

    database = request.app.state.database
    async with database.tenant_session(caller.tenant_id) as session:
        job = await enqueue_sync(
            session,
            caller.tenant_id,
            store_id=store_id,
            incremental=True if body is None else body.incremental,
        )

    log.info(
        "store_sync_requested",
        tenant_id=caller.tenant_id,
        store_id=store_id,
        job_id=job.id,
        incremental=job.payload.get("incremental"),
    )
    return envelope(
        _sync_payload(job),
        request_id=getattr(request.state, "request_id", None),
    )


@router.get(
    "/{store_id}/sync/{job_id}",
    summary="How a queued sync is going",
    responses={404: {"description": "No such sync for this store"}},
)
async def sync_status(
    request: Request,
    store_id: str,
    job_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require("stores:read"))],
) -> dict[str, Any]:
    """The other half of a 202.

    Row-Level Security is what makes this safe to address by job id alone — a
    job belonging to another tenant is simply not there. The ``store_id`` in the
    path is still checked, so a job id pasted against the wrong store is a 404
    rather than a confusing answer about a different shop.
    """
    database = request.app.state.database
    async with database.tenant_session(caller.tenant_id) as session:
        job = await JobQueue(session).get(job_id)

    if job is None or job.kind != SYNC_STORE or job.payload.get("store_id") != store_id:
        raise NotFoundError(
            "No such sync for this store.",
            details={"store_id": store_id, "job_id": job_id},
        )
    return envelope(_sync_payload(job), request_id=getattr(request.state, "request_id", None))


def _sync_payload(job: Any) -> dict[str, Any]:
    """One shape for both routes, so a client polls what it was handed.

    ``last_error`` is included only on a dead job. On a live one it is the
    *previous* attempt's error and a merchant reading it would see a failure
    beside a job that is still perfectly likely to succeed.
    """
    payload: dict[str, Any] = {
        "job_id": job.id,
        "store_id": job.payload.get("store_id"),
        "status": job.status.value,
        "incremental": job.payload.get("incremental", True),
        "attempts": job.attempts,
        "queued_at": job.created_at.isoformat() if job.created_at else None,
        "next_attempt_at": job.run_after.isoformat() if job.run_after else None,
    }
    if job.status is JobStatus.DEAD:
        payload["last_error"] = job.last_error
    return payload


async def _close(adapter: object) -> None:
    closer = getattr(adapter, "aclose", None)
    if closer is not None:
        await closer()
