"""Delivering the outbox — signed, retried, and visible when it fails.

The queue itself is ``neura_core.webhooks``; this is the part that needs an HTTP
client and a clock, both of which belong to the deployable rather than to shared
infrastructure.

**How a drainer finds work under Row-Level Security.** No transaction can ask
"which deliveries are due?" across tenants — a session that has not named a
tenant matches no row anywhere (ADR-0008), and that is the property, not a
limitation to route around. The three ways out were a second database role with
``BYPASSRLS``, a policy exemption, or an index of *which tenants have work* kept
outside PostgreSQL. This takes the third: enqueuing adds the tenant id to a Redis
set, and the drainer opens one scoped session per tenant named in it.

The cost is stated rather than hidden. If Redis loses that set, undelivered rows
are stranded until that tenant's next event re-registers them — the rows are
safe, the *schedule* is not. That is open question **P7**, and
``make webhook-drain TENANT=…`` is the repair.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx

from neura_core import Database, get_logger
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

#: The Redis set naming tenants with queued deliveries.
PENDING_TENANTS_KEY = "neura:webhooks:tenants"

#: How often the drainer wakes. Deliveries are not latency-critical — a merchant
#: reacting to `conversation.escalated` is opening a support queue, not steering
#: a robot — and a tighter loop would spend most of its time asking Redis for an
#: empty set.
POLL_INTERVAL_S = 5.0

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

    def __init__(
        self,
        db: Database,
        redis: Any | None,
        *,
        poll_interval_s: float = POLL_INTERVAL_S,
    ) -> None:
        self._db = db
        self._redis: Any | None = redis
        self._poll_interval_s = poll_interval_s
        self._client = httpx.AsyncClient(follow_redirects=False)
        self._task: asyncio.Task[None] | None = None
        # A process-local fallback for the tenant index, so a deployment
        # without Redis still delivers the events it queued while it was up.
        # Deliberately not a substitute: it does not survive a restart, which is
        # exactly what the Redis set is for.
        self._local: set[str] = set()

    async def note(self, tenant_id: str) -> None:
        """Record that this tenant has queued work. Called after enqueuing."""
        self._local.add(tenant_id)
        if self._redis is None:
            return
        try:
            await self._redis.sadd(PENDING_TENANTS_KEY, tenant_id)
        except Exception as exc:  # the rows are safe either way
            log.error("webhook_index_write_failed", tenant_id=tenant_id, error=str(exc))

    async def pending_tenants(self) -> set[str]:
        tenants = set(self._local)
        if self._redis is not None:
            try:
                members = await self._redis.smembers(PENDING_TENANTS_KEY)
                tenants |= {m.decode() if isinstance(m, bytes) else str(m) for m in members}
            except Exception as exc:
                log.error("webhook_index_read_failed", error=str(exc))
        return tenants

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

    async def run_once(self) -> int:
        total = 0
        for tenant_id in await self.pending_tenants():
            try:
                total += await self.drain_tenant(tenant_id)
            except Exception as exc:  # one tenant must not stop the rest
                log.error("webhook_drain_failed", tenant_id=tenant_id, error=str(exc))
                continue
            await self._forget_if_idle(tenant_id)
        return total

    async def _forget_if_idle(self, tenant_id: str) -> None:
        """Drop a tenant from the index once nothing is pending for them.

        Without this the drainer opens a transaction per registered tenant per
        poll forever, which is a slow leak that only shows up on a busy
        deployment.
        """
        async with self._db.tenant_session(tenant_id) as session:
            outstanding = await WebhookRepository(session).list_deliveries(
                tenant_id, status=DeliveryStatus.PENDING, limit=1
            )
        if outstanding:
            return

        self._local.discard(tenant_id)
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.srem(PENDING_TENANTS_KEY, tenant_id)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._client.aclose()

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # the loop must outlive a bad poll
                log.error("webhook_drainer_error", error=str(exc))
            await asyncio.sleep(self._poll_interval_s)


__all__ = [
    "PENDING_TENANTS_KEY",
    "POLL_INTERVAL_S",
    "RETAIN_DELIVERED",
    "TIMEOUT_S",
    "Attempt",
    "WebhookDrainer",
    "deliver",
]
