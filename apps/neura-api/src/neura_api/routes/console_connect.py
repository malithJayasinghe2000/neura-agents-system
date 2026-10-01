"""The shop owner connects their own shop. ADR-0052, `console.md §3.4`.

Five actions, all behind the console session and the shop taken from the
membership, never from the request (`acting_for`):

| action | what it writes |
|:--|:--|
| ``POST /token`` | a new shop token, sealed; returned **once** |
| ``POST /checks`` | a check row and its job; the worker asks the shop |
| ``GET /checks/{id}`` | nothing; the result, never a token |
| ``POST /connect`` | the connection (address + the token NEURA made) and a full sync |
| ``POST /store/{id}/token`` | a new token over an existing connection; returned **once** |

**The browser never sends a token** (§1). NEURA makes it, so NEURA already holds
it: the only thing a form here sends is an address, and every address is checked
against the public-address rule before anything calls it (§3, `addresses.py`).

**A token is shown by the response that made it and by nothing else.** No route
here, or in `console_shop.py`, reads one back. Making, replacing and connecting
each write an audit event in the same transaction, naming who and which shop,
never the token (§8).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from neura_agent_core.audit import AuditEntry, AuditEvent, PostgresAuditLog
from neura_api.addresses import check_shop_address
from neura_api.dependencies import ConsoleActor, acting_for
from neura_api.envelopes import envelope
from neura_api.jobs import enqueue_check, enqueue_sync, live_check_id
from neura_api.jobs.shop_check import STANDARD_BRIDGE
from neura_core import ConflictError, NotFoundError, ValidationError, get_logger, get_settings
from neura_core.tenancy import (
    ShopCheckRepository,
    ShopTokenRepository,
    StoreConnectionRepository,
    new_shop_token,
)

log = get_logger(__name__)

router = APIRouter(prefix="/console/shops/{tenant_id}", tags=["console"])


class CheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The bridge's address, before the shop is connected. Leave it out to check
    #: a connection that exists (``store_id``).
    address: str | None = Field(default=None, max_length=2048)
    store_id: str | None = Field(default=None, max_length=64)


class ConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(min_length=1, max_length=2048)


@router.post("/token", summary="Make the shop token, before the shop is connected")
async def make_token(request: Request, tenant_id: str) -> dict[str, Any]:
    """Step 1. Returned **once**; making another replaces it (ADR-0052 §1)."""
    actor = await acting_for(request, tenant_id)
    if await request.app.state.stores.rows_for(actor.tenant_id):
        raise ConflictError(
            "This shop is already connected. Make a new token from its connection instead.",
            code="ALREADY_CONNECTED",
        )

    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        tokens = ShopTokenRepository(session)
        token = await tokens.make(actor.tenant_id, made_by=actor.user_id)
        made_at = await tokens.made_at(actor.tenant_id)
        await _audit(session, actor, "shop_token.made")

    log.info("console_shop_token_made", tenant_id=actor.tenant_id, user_id=actor.user_id)
    return envelope(
        {"token": token, "made_at": _iso(made_at)},
        request_id=getattr(request.state, "request_id", None),
    )


@router.post("/checks", summary="Run the full check against the shop's bridge", status_code=202)
async def start_check(request: Request, tenant_id: str, body: CheckRequest) -> dict[str, Any]:
    """Queue the check and return at once; the worker asks the shop (ADR-0052 §4).

    **One at a time per shop:** while a check is queued or running, pressing
    again returns that one rather than asking the shop a second time.
    """
    actor = await acting_for(request, tenant_id)
    production = get_settings().is_production

    store_id = body.store_id
    if store_id is not None:
        rows = await request.app.state.stores.rows_for(actor.tenant_id)
        row = next((r for r in rows if r["id"] == store_id), None)
        if row is None:
            raise NotFoundError("No such store connection.", details={"store_id": store_id})
        address = row["base_url"]
    else:
        if not body.address:
            raise _invalid("Type your bridge's address first.")
        # Refused here too, before anything is queued, so the owner hears it at
        # once; the worker checks again before it calls (§3).
        address = await check_shop_address(body.address, production=production)

    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        checks = ShopCheckRepository(session)
        running = await live_check_id(session, actor.tenant_id)
        if running is not None and (current := await checks.get(actor.tenant_id, running)):
            return envelope(
                {"check": current}, request_id=getattr(request.state, "request_id", None)
            )

        if store_id is None and await ShopTokenRepository(session).made_at(actor.tenant_id) is None:
            raise ConflictError("Make the shop token first.", code="NO_SHOP_TOKEN")

        check_id = await checks.create(
            actor.tenant_id, address=address, store_id=store_id, requested_by=actor.user_id
        )
        await enqueue_check(session, actor.tenant_id, check_id)
        check = await checks.get(actor.tenant_id, check_id)

    log.info("console_shop_check_requested", tenant_id=actor.tenant_id, check_id=check_id)
    return envelope({"check": check}, request_id=getattr(request.state, "request_id", None))


@router.get("/checks/{check_id}", summary="One check and, once it has run, its result")
async def read_check(request: Request, tenant_id: str, check_id: str) -> dict[str, Any]:
    actor = await acting_for(request, tenant_id)
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        check = await ShopCheckRepository(session).get(actor.tenant_id, check_id)
    if check is None:
        raise NotFoundError("No such check.", details={"check_id": check_id})
    return envelope({"check": check}, request_id=getattr(request.state, "request_id", None))


@router.post("/connect", summary="Connect the shop and copy its catalogue")
async def connect(request: Request, tenant_id: str, body: ConnectRequest) -> dict[str, Any]:
    """Step 3. Only after a clean check of **this** address, made with **this**
    token (ADR-0052 §5). Saves the connection and queues the full copy."""
    actor = await acting_for(request, tenant_id)
    address = await check_shop_address(body.address, production=get_settings().is_production)
    directory = request.app.state.stores
    if await directory.rows_for(actor.tenant_id):
        raise ConflictError("This shop is already connected.", code="ALREADY_CONNECTED")

    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        tokens = ShopTokenRepository(session)
        made_at = await tokens.made_at(actor.tenant_id)
        credentials = await tokens.credentials(actor.tenant_id)
        if made_at is None or not credentials:
            raise ConflictError("Make the shop token first.", code="NO_SHOP_TOKEN")

        last = await ShopCheckRepository(session).latest(
            actor.tenant_id, store_id=None, finished_only=True
        )
        if last is None or not _passed(last, address=address, since=made_at):
            raise ConflictError(
                "Check this address first. Connect works after a check with no problems.",
                code="CHECK_FIRST",
            )

        store_id = await StoreConnectionRepository(session).connect(
            actor.tenant_id, platform=STANDARD_BRIDGE, base_url=address, credentials=credentials
        )
        await tokens.discard(actor.tenant_id)
        # The clean check that allowed this becomes the connection's first one.
        await ShopCheckRepository(session).attach(actor.tenant_id, last["id"], store_id=store_id)
        await _audit(session, actor, "store.connected", store_id=store_id, address=address)
        job = await enqueue_sync(session, actor.tenant_id, store_id=store_id, incremental=False)

    directory.forget(store_id)
    log.info("console_shop_connected", tenant_id=actor.tenant_id, store_id=store_id, job_id=job.id)
    return envelope(
        {"id": store_id, "base_url": address}, request_id=getattr(request.state, "request_id", None)
    )


@router.post("/store/{store_id}/token", summary="Make a new token for a connected shop")
async def replace_token(request: Request, tenant_id: str, store_id: str) -> dict[str, Any]:
    """*Make a new token* (ADR-0052 §2). Returned **once**.

    NEURA stops sending the old token at once. The shop's bridge still accepts it
    until the developer puts the new one in, because the bridge checks it (G49);
    the screen says so.
    """
    actor = await acting_for(request, tenant_id)
    directory = request.app.state.stores
    if not any(row["id"] == store_id for row in await directory.rows_for(actor.tenant_id)):
        raise NotFoundError("No such store connection.", details={"store_id": store_id})

    token = new_shop_token()
    async with request.app.state.database.tenant_session(actor.tenant_id) as session:
        stores = StoreConnectionRepository(session)
        await stores.replace_credentials(actor.tenant_id, store_id, {"token": token})
        set_at = await stores.credentials_set_at(actor.tenant_id, store_id)
        await _audit(session, actor, "shop_token.replaced", store_id=store_id)

    # The capability set negotiated with the old token must not outlive it.
    directory.forget(store_id)
    log.info("console_shop_token_replaced", tenant_id=actor.tenant_id, store_id=store_id)
    return envelope(
        {"token": token, "made_at": _iso(set_at)},
        request_id=getattr(request.state, "request_id", None),
    )


def _passed(check: dict[str, Any] | None, *, address: str, since: datetime) -> bool:
    """A finished, clean check of this address, made after this token."""
    if check is None or check["status"] != "done" or check["address"] != address:
        return False
    if datetime.fromisoformat(check["requested_at"]) < since:
        return False
    return bool((check["result"] or {}).get("conformant"))


async def _audit(session: Any, actor: ConsoleActor, outcome: str, **payload: str) -> None:
    """A person changed how NEURA reaches a shop. Never the token itself."""
    await PostgresAuditLog(session).record(
        AuditEntry(
            tenant_id=actor.tenant_id,
            event_type=AuditEvent.CONFIG_CHANGE,
            actor=actor.user_id,
            outcome=outcome,
            payload=payload,
        )
    )


def _invalid(message: str) -> ValidationError:
    return ValidationError(message, code="ADDRESS_INVALID")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
