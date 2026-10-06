"""Registering, testing and inspecting outbound webhooks (api-design.md §9).

Four endpoints from the document, plus one it implies and does not name:
``GET /v1/webhooks/deliveries``. The document promises "a dead-letter queue
visible to the merchant", and a queue with no way to look at it is a queue that
is visible to us. That endpoint is the visibility.

**The signing secret is shown exactly once**, at registration, and is never
retrievable afterwards. It is *encrypted* rather than hashed, because unlike an
API key we have to reproduce it in order to sign with it — so the trade is stated
here rather than assumed: a database dump plus the KEK yields signing secrets,
which is why the KEK lives in the environment and never in the database.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from neura_api.addresses import check_webhook_address
from neura_api.dependencies import require
from neura_api.envelopes import envelope
from neura_api.jobs.webhooks import enqueue_drain
from neura_core import ValidationError, get_logger, get_settings
from neura_core.tenancy import AuthenticatedCaller
from neura_core.webhooks import (
    DeliveryStatus,
    PendingEvent,
    WebhookEndpoint,
    WebhookEvent,
    WebhookRepository,
)

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class RegisterWebhook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    #: At least one. An endpoint subscribed to nothing receives nothing and
    #: looks configured, which is the worst of both.
    events: list[WebhookEvent] = Field(min_length=1)
    description: str = Field(default="", max_length=255)


@router.post(
    "",
    summary="Register an endpoint. Returns the signing secret, once.",
    responses={400: {"description": "Not https, or no events subscribed"}},
)
async def register(
    request: Request,
    body: RegisterWebhook,
    caller: Annotated[AuthenticatedCaller, Depends(require("webhooks:write"))],
) -> dict[str, Any]:
    await check_webhook_address(body.url, production=get_settings().is_production)
    database = request.app.state.database
    async with database.tenant_session(caller.tenant_id) as session:
        endpoint, secret = await WebhookRepository(session).register(
            caller.tenant_id,
            url=body.url,
            events=body.events,
            description=body.description,
        )

    log.info("webhook_registered", tenant_id=caller.tenant_id, webhook_id=endpoint.id)
    return envelope(
        {
            **_endpoint_payload(endpoint),
            # The only time this value is ever returned. Nothing logs it: the
            # redaction filter would probably catch it, and relying on a safety
            # net is not the same as not falling.
            "secret": secret,
            "secret_note": (
                "Store this now — it is not retrievable. Verify each delivery by "
                "computing HMAC-SHA256 over `<X-Neura-Timestamp>.<raw body>`."
            ),
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.get("", summary="List registered endpoints")
async def list_endpoints(
    request: Request,
    caller: Annotated[AuthenticatedCaller, Depends(require("webhooks:read"))],
) -> dict[str, Any]:
    database = request.app.state.database
    async with database.tenant_session(caller.tenant_id) as session:
        endpoints = await WebhookRepository(session).list_for(caller.tenant_id)
    return envelope(
        [_endpoint_payload(e) for e in endpoints],
        request_id=getattr(request.state, "request_id", None),
    )


@router.delete("/{webhook_id}", summary="Remove an endpoint and its queued events")
async def remove(
    request: Request,
    webhook_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require("webhooks:write"))],
) -> dict[str, Any]:
    database = request.app.state.database
    async with database.tenant_session(caller.tenant_id) as session:
        repository = WebhookRepository(session)
        await repository.require(webhook_id)
        await repository.remove(webhook_id)

    log.info("webhook_removed", tenant_id=caller.tenant_id, webhook_id=webhook_id)
    return envelope(
        {"id": webhook_id, "deleted": True},
        request_id=getattr(request.state, "request_id", None),
    )


@router.post(
    "/{webhook_id}/test",
    summary="Queue a test event to this endpoint",
    responses={400: {"description": "The endpoint is not subscribed to that event"}},
)
async def send_test(
    request: Request,
    webhook_id: str,
    caller: Annotated[AuthenticatedCaller, Depends(require("webhooks:write"))],
    event: Annotated[WebhookEvent, Query()] = WebhookEvent.CONVERSATION_RESOLVED,
) -> dict[str, Any]:
    """Queue one event, through the ordinary outbox.

    Not sent inline. A test that took a different path to a real delivery would
    prove that the *test* works — and the failures worth catching here are a
    wrong URL, a signature the merchant's code rejects, and a handler that
    times out, all of which live in the path this shares.
    """
    database = request.app.state.database
    async with database.tenant_session(caller.tenant_id) as session:
        repository = WebhookRepository(session)
        endpoint = await repository.require(webhook_id)
        if event not in endpoint.events:
            raise ValidationError(
                "This endpoint is not subscribed to that event.",
                details={
                    "event": event.value,
                    "subscribed": sorted(e.value for e in endpoint.events),
                },
            )

        pending = PendingEvent(
            event=event,
            payload={"test": True, "webhook_id": webhook_id},
        )
        deliveries = await repository.enqueue(caller.tenant_id, pending)
        # In the same transaction as the deliveries, so the two cannot disagree
        # about whether this event exists (ADR-0022).
        if deliveries:
            await enqueue_drain(session, caller.tenant_id)

    return envelope(
        {
            "event_id": pending.event_id,
            "event": event.value,
            "queued": len(deliveries),
        },
        request_id=getattr(request.state, "request_id", None),
    )


@router.get(
    "/deliveries",
    summary="Recent deliveries, including the dead-letter queue",
)
async def list_deliveries(
    request: Request,
    caller: Annotated[AuthenticatedCaller, Depends(require("webhooks:read"))],
    status: Annotated[DeliveryStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """``?status=dead`` is the dead-letter queue api-design.md §9 promises.

    A merchant who cannot see what failed cannot fix their endpoint, and a
    dead-letter queue only we can read is a dropped event with extra steps.
    """
    database = request.app.state.database
    async with database.tenant_session(caller.tenant_id) as session:
        deliveries = await WebhookRepository(session).list_deliveries(
            caller.tenant_id, status=status, limit=limit
        )
    return envelope(
        [
            {
                "id": d.id,
                "endpoint_id": d.endpoint_id,
                "event": d.event.value,
                "event_id": d.event_id,
                "status": d.status.value,
                "attempts": d.attempts,
                "last_error": d.last_error,
                "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
            }
            for d in deliveries
        ],
        request_id=getattr(request.state, "request_id", None),
    )


def _endpoint_payload(endpoint: WebhookEndpoint) -> dict[str, Any]:
    return {
        "id": endpoint.id,
        "url": endpoint.url,
        "events": sorted(e.value for e in endpoint.events),
        "description": endpoint.description,
        "status": endpoint.status.value,
        "consecutive_failures": endpoint.consecutive_failures,
        "last_delivery_at": (
            endpoint.last_delivery_at.isoformat() if endpoint.last_delivery_at else None
        ),
        "created_at": endpoint.created_at.isoformat() if endpoint.created_at else None,
    }
