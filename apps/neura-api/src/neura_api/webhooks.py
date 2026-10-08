"""Delivering the outbox — signed, retried, and visible when it fails.

The queue itself is ``neura_core.webhooks``; this is the part that needs an HTTP
client and a clock, both of which belong to the deployable rather than to shared
infrastructure.

**This class used to own a loop and a Redis set; it owns neither now.** No
transaction can ask "which deliveries are due?" across tenants (ADR-0008), so
1.14 kept an index of *which tenants have work* outside PostgreSQL and polled it
every five seconds. That index is gone: a ``webhook.drain`` job is written **in
the same transaction as the deliveries**, and the scheduler of
[ADR-0022](../../../../docs/architecture/adr/0022-scheduling-under-rls.md) finds
it. See ``neura_api.jobs.webhooks`` for what replaced it and why the two costs it
carried — a silently lost schedule, and a ``sadd`` that could only happen *after*
the commit — are both gone rather than moved.

What is left here is exactly what a deployable owes the outbox: an HTTP client, a
signature, and the arithmetic of one attempt. ``make webhook-drain TENANT=…``
still forces a pass by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import httpx

from neura_api.addresses import outbound_transport
from neura_core import Database, get_logger, get_settings
from neura_core.webhooks import (
    Delivery,
    DeliveryStatus,
    WebhookRepository,
    event_body,
    sign,
)
from neura_core.webhooks.signing import (
    EVENT_ID_HEADER,
    EVENT_TYPE_HEADER,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
)

log = get_logger(__name__)

#: A merchant's endpoint gets this long to acknowledge. Short, because a slow
#: endpoint must not be able to occupy the drainer: we retry, they recover.
TIMEOUT_S = 10.0

#: Successful deliveries are dropped after this. The outbox is a queue, not a
#: log — the audit log is the log.
RETAIN_DELIVERED = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class Attempt:
    """What one POST did."""

    ok: bool
    status: int | None = None
    error: str = ""


async def deliver(
    client: httpx.AsyncClient,
    *,
    url: str,
    secret: str,
    delivery: Delivery,
) -> Attempt:
    """Sign and POST one event (api-design.md §9).

    The body is produced **once** and both signed and sent, because signing a
    re-serialisation of what was sent is the classic way to ship a signature
    that never verifies.

    Any 2xx is a success. Everything else is a failure to be retried, including
    a 4xx: a merchant's endpoint returning 404 because they have not deployed
    the handler yet should get the event when they do, and distinguishing
    "permanently wrong" from "temporarily wrong" from a status code is a guess.
    Sustained failure disables the endpoint instead, which is a decision made on
    evidence rather than on one response.
    """
    body = event_body(delivery)
    signature, timestamp = sign(body, secret)

    try:
        response = await client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: signature,
                TIMESTAMP_HEADER: str(timestamp),
                EVENT_ID_HEADER: delivery.event_id,
                EVENT_TYPE_HEADER: delivery.event.value,
                "User-Agent": "neura-webhooks/1",
            },
            timeout=TIMEOUT_S,
        )
    except httpx.HTTPError as exc:
        return Attempt(ok=False, error=f"{type(exc).__name__}: {exc}")

    if 200 <= response.status_code < 300:
        return Attempt(ok=True, status=response.status_code)
    return Attempt(ok=False, status=response.status_code, error=f"HTTP {response.status_code}")


class WebhookDrainer:
    """Sends what the outbox holds, one tenant at a time."""

    def __init__(self, db: Database, *, production: bool | None = None) -> None:
        self._db = db
        production = get_settings().is_production if production is None else production
        # A shop's own address, so the same rule as its bridge (G78): in
        # production only public addresses, checked as each delivery connects.
        self._client = httpx.AsyncClient(
            follow_redirects=False, transport=outbound_transport(production=production)
        )

    async def drain_tenant(self, tenant_id: str, *, limit: int = 50) -> int:
        """Attempt every due delivery for one tenant. Returns how many were sent.

        Each delivery gets its own transaction. One endpoint being slow must not
        hold a database connection open for the others, and a batch that failed
        halfway would otherwise re-attempt deliveries that had already succeeded.
        """
        async with self._db.tenant_session(tenant_id) as session:
            due = await WebhookRepository(session).due(tenant_id, limit=limit)

        delivered = 0
        for delivery in due:
            if await self._attempt(tenant_id, delivery):
                delivered += 1
        return delivered

    async def _attempt(self, tenant_id: str, delivery: Delivery) -> bool:
        async with self._db.tenant_session(tenant_id) as session:
            repository = WebhookRepository(session)
            endpoint = await repository.get(delivery.endpoint_id)
            if endpoint is None:
                # The merchant deleted the endpoint while this was queued.
                await repository.mark_failed(delivery, error="endpoint removed")
                return False
            secret = await repository.secret_for(tenant_id, endpoint.id)
            url = endpoint.url

        attempt = await deliver(self._client, url=url, secret=secret, delivery=delivery)

        async with self._db.tenant_session(tenant_id) as session:
            repository = WebhookRepository(session)
            if attempt.ok:
                await repository.mark_delivered(delivery.id)
            else:
                status = await repository.mark_failed(delivery, error=attempt.error)
                if status is DeliveryStatus.DEAD:
                    # Named at ERROR so it reaches an operator, and readable by
                    # the merchant through GET /v1/webhooks/deliveries. A
                    # dead-letter nobody is told about is a dropped event.
                    log.error(
                        "webhook_dead_lettered",
                        tenant_id=tenant_id,
                        endpoint_id=delivery.endpoint_id,
                        event_type=delivery.event.value,
                        event_id=delivery.event_id,
                        last_error=attempt.error,
                    )
            await repository.record_endpoint_result(delivery.endpoint_id, ok=attempt.ok)

        log.info(
            "webhook_attempted",
            tenant_id=tenant_id,
            event_type=delivery.event.value,
            ok=attempt.ok,
            status=attempt.status,
            attempts=delivery.attempts + 1,
        )
        return attempt.ok

    async def aclose(self) -> None:
        """Release the HTTP client. There is no loop left to stop."""
        await self._client.aclose()


__all__ = [
    "RETAIN_DELIVERED",
    "TIMEOUT_S",
    "Attempt",
    "WebhookDrainer",
    "deliver",
]
