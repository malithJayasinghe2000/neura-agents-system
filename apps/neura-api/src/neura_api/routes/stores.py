"""Connecting a merchant's shop (api-design.md §7, "Store connection").

Without this there is nothing for an agent to talk to, which is why it is in 1.14
rather than waiting for a merchant console: a tenant, a key and an agent are not
enough to answer "where is my order?".

**``GET /v1/stores/{id}`` returns the negotiated capability list**, and that is
the endpoint an integrator actually needs. It is the one place a developer sees,
concretely, which agent abilities their platform does and does not support —
before they discover it from a conversation that quietly never calls a tool.

Sync is deliberately not here. ``POST /v1/stores/{id}/sync`` is specified in
api-design.md and is **not implemented in 1.14**, because the sync engine's entity
persistence is still in-memory (the ``EntityStore`` seam from milestone 1.8). An
endpoint that started a sync whose results vanished when the process restarted
would be exactly the write-to-nothing this milestone exists to stop shipping.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from neura_api.dependencies import require
from neura_api.envelopes import envelope
from neura_core import NotFoundError, ServiceUnavailableError, get_logger
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


async def _close(adapter: object) -> None:
    closer = getattr(adapter, "aclose", None)
    if closer is not None:
        await closer()
