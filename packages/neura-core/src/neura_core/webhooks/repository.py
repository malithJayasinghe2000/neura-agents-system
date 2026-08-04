"""Reading and writing webhook endpoints and the delivery outbox.

Every method takes a session that is already tenant-scoped, so none of them
writes a ``WHERE tenant_id`` for safety — Row-Level Security does that, and a
hand-written filter would be the second-best of two defences pretending to be
the first.

**One consequence of ADR-0008 shows up here for the first time and is worth
naming rather than working around.** A background drainer wants to ask "which
deliveries are due?" across every tenant, and there is no such transaction: a
session that has not named a tenant matches no row anywhere. The available
answers were a second database role with ``BYPASSRLS``, a policy exemption, or
an index of *which tenants have work* held somewhere outside PostgreSQL. This
takes the third — the drainer is handed tenant ids and opens one scoped session
per tenant — because the first two buy convenience with the property the whole
design exists to have. The index lives in Redis and is described in
``neura_api.webhooks``; the limitation it carries is recorded as open question
**P7**.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.config import get_settings
from neura_core.crypto import decrypt, encrypt, generate_key, unwrap_dek, wrap_dek
from neura_core.errors import ConfigurationError, NotFoundError, ValidationError
from neura_core.ids import WEBHOOK, WEBHOOK_DELIVERY, new_id
from neura_core.webhooks.models import (
    Delivery,
    DeliveryStatus,
    EndpointStatus,
    PendingEvent,
    WebhookEndpoint,
    WebhookEvent,
)
from neura_core.webhooks.schema import webhook_deliveries, webhook_endpoints

#: api-design.md §9 — "exponential-backoff retry six times". Six *retries* after the
#: first attempt, so seven attempts spanning about half an hour. Long enough for
#: a merchant's brief deploy, short enough that a genuinely dead endpoint is
#: declared dead while somebody still remembers changing it.
MAX_ATTEMPTS = 7

#: 30s, 1m, 2m, 4m, 8m, 16m.
BACKOFF_BASE_S = 30

#: Consecutive failed *deliveries* after which an endpoint stops being offered
#: new events. Not attempts: one unreachable event should not disable an
#: endpoint that is merely behind a flaky hop.
DISABLE_AFTER_FAILURES = 20


def backoff_for(attempts: int) -> timedelta:
    """How long to wait before attempt number ``attempts + 1``."""
    return timedelta(seconds=BACKOFF_BASE_S * (2 ** max(attempts - 1, 0)))


class WebhookRepository:
    """Endpoints and their outbox, for one tenant."""

    def __init__(self, session: AsyncSession, *, kek: str | None = None) -> None:
        self._session = session
        self._kek = kek

    # ── Endpoints ────────────────────────────────────────────────────────────

    async def register(
        self,
        tenant_id: str,
        *,
        url: str,
        events: Sequence[WebhookEvent],
        description: str = "",
        endpoint_id: str | None = None,
    ) -> tuple[WebhookEndpoint, str]:
        """Register a destination and mint its signing secret.

        Returns the record *and* the plaintext secret, in that order, because
        the plaintext is shown exactly once and the caller has to decide
        deliberately what to do with it — the same shape as issuing an API key.
        """
        if not url.startswith("https://") and not _plaintext_urls_allowed():
            # An unencrypted webhook is a signed message sent in the clear: the
            # signature stops forgery, and does nothing about the conversation
            # transcript inside it being readable by every hop in between.
            raise ValidationError(
                "A webhook URL must be https. The signature proves who sent the "
                "event; it does not keep the contents private.",
                details={"url": url},
            )
        if not events:
            # An endpoint subscribed to nothing receives nothing and looks
            # configured. Refused where it is a typo rather than discovered
            # weeks later as "we never got any webhooks".
            raise ValidationError("A webhook endpoint must subscribe to at least one event.")

        secret = generate_key()
        dek = generate_key()
        kek = self._require_kek()
        record_id = endpoint_id or new_id(WEBHOOK)

        await self._session.execute(
            pg_insert(webhook_endpoints).values(
                id=record_id,
                tenant_id=tenant_id,
                url=url,
                events=sorted({e.value for e in events}),
                description=description,
                secret=encrypt(secret, dek, aad=tenant_id.encode()),
                wrapped_dek=wrap_dek(dek, kek, tenant_id=tenant_id),
            )
        )
        stored = await self.get(record_id)
        if stored is None:  # pragma: no cover — RLS would have raised first
            raise ConfigurationError(
                "the webhook endpoint was inserted but is not readable; the "
                "session is scoped to a different tenant than the endpoint."
            )
        return stored, secret

    async def get(self, endpoint_id: str) -> WebhookEndpoint | None:
        row = (
            await self._session.execute(
                select(webhook_endpoints).where(webhook_endpoints.c.id == endpoint_id)
            )
        ).first()
        return None if row is None else _endpoint_from_row(row)

    async def require(self, endpoint_id: str) -> WebhookEndpoint:
        endpoint = await self.get(endpoint_id)
        if endpoint is None:
            raise NotFoundError("No such webhook endpoint.", details={"webhook_id": endpoint_id})
        return endpoint

    async def list_for(self, tenant_id: str) -> list[WebhookEndpoint]:
        rows = (
            await self._session.execute(
                select(webhook_endpoints)
                .where(webhook_endpoints.c.tenant_id == tenant_id)
                .order_by(webhook_endpoints.c.created_at)
            )
        ).all()
        return [_endpoint_from_row(row) for row in rows]

    async def secret_for(self, tenant_id: str, endpoint_id: str) -> str:
        """Decrypt one endpoint's signing secret.

        Plaintext exists only in the caller's memory, only for as long as they
        hold it, and only on the code path that is about to sign with it.
        """
        row = (
            await self._session.execute(
                select(webhook_endpoints).where(webhook_endpoints.c.id == endpoint_id)
            )
        ).first()
        if row is None:
            raise NotFoundError("No such webhook endpoint.", details={"webhook_id": endpoint_id})

        kek = self._require_kek()
        dek = unwrap_dek(str(row.wrapped_dek), kek, tenant_id=tenant_id)
        return decrypt(str(row.secret), dek, aad=tenant_id.encode())

    async def remove(self, endpoint_id: str) -> None:
        """Delete an endpoint. Its pending deliveries go with it.

        Unlike an API key, an endpoint is not a credential and its history is
        not evidence of anything — there is no "what did this endpoint do after
        we stopped it?" to answer. Deliveries are cascaded by hand because
        nothing here uses foreign keys across tenant-scoped tables.
        """
        await self._session.execute(
            delete(webhook_deliveries).where(webhook_deliveries.c.endpoint_id == endpoint_id)
        )
        await self._session.execute(
            delete(webhook_endpoints).where(webhook_endpoints.c.id == endpoint_id)
        )

    # ── The outbox ───────────────────────────────────────────────────────────

    async def enqueue(self, tenant_id: str, event: PendingEvent) -> list[Delivery]:
        """Fan one event out to every endpoint that wants it.

        Called inside the transaction that produced the event, so an event row
        exists exactly when the thing it describes happened. Returns the rows
        written, which is empty — and cheap — for a tenant with no endpoints.
        """
        endpoints = [e for e in await self.list_for(tenant_id) if e.wants(event.event)]
        if not endpoints:
            return []

        payload = {
            "event": event.event.value,
            "event_id": event.event_id,
            "occurred_at": event.occurred_at.isoformat(),
            "data": event.payload,
        }

        created: list[Delivery] = []
        for endpoint in endpoints:
            delivery_id = new_id(WEBHOOK_DELIVERY)
            await self._session.execute(
                pg_insert(webhook_deliveries).values(
                    id=delivery_id,
                    tenant_id=tenant_id,
                    endpoint_id=endpoint.id,
                    event_type=event.event.value,
                    event_id=event.event_id,
                    payload=payload,
                    status=DeliveryStatus.PENDING.value,
                    next_attempt_at=datetime.now(UTC),
                )
            )
            created.append(
                Delivery(
                    id=delivery_id,
                    tenant_id=tenant_id,
                    endpoint_id=endpoint.id,
                    event=event.event,
                    event_id=event.event_id,
                    payload=payload,
                )
            )
        return created

    async def due(
        self, tenant_id: str, *, now: datetime | None = None, limit: int = 50
    ) -> list[Delivery]:
        """Deliveries whose backoff has elapsed, oldest first."""
        moment = now or datetime.now(UTC)
        rows = (
            await self._session.execute(
                select(webhook_deliveries)
                .where(webhook_deliveries.c.tenant_id == tenant_id)
                .where(webhook_deliveries.c.status == DeliveryStatus.PENDING.value)
                .where(webhook_deliveries.c.next_attempt_at <= moment)
                .order_by(webhook_deliveries.c.next_attempt_at)
                .limit(limit)
            )
        ).all()
        return [_delivery_from_row(row) for row in rows]

    async def list_deliveries(
        self,
        tenant_id: str,
        *,
        status: DeliveryStatus | None = None,
        limit: int = 50,
    ) -> list[Delivery]:
        query = select(webhook_deliveries).where(webhook_deliveries.c.tenant_id == tenant_id)
        if status is not None:
            query = query.where(webhook_deliveries.c.status == status.value)
        rows = (
            await self._session.execute(
                query.order_by(webhook_deliveries.c.created_at.desc()).limit(limit)
            )
        ).all()
        return [_delivery_from_row(row) for row in rows]

    async def mark_delivered(self, delivery_id: str, *, at: datetime | None = None) -> None:
        moment = at or datetime.now(UTC)
        await self._session.execute(
            update(webhook_deliveries)
            .where(webhook_deliveries.c.id == delivery_id)
            .values(
                status=DeliveryStatus.DELIVERED.value,
                attempts=webhook_deliveries.c.attempts + 1,
                delivered_at=moment,
                next_attempt_at=None,
                last_error="",
            )
        )

    async def mark_failed(
        self,
        delivery: Delivery,
        *,
        error: str,
        at: datetime | None = None,
    ) -> DeliveryStatus:
        """Record one failed attempt and schedule — or abandon — the next.

        Returns the resulting status so the caller does not have to re-derive
        the retry arithmetic to log what happened.
        """
        moment = at or datetime.now(UTC)
        attempts = delivery.attempts + 1
        exhausted = attempts >= MAX_ATTEMPTS
        status = DeliveryStatus.DEAD if exhausted else DeliveryStatus.PENDING

        await self._session.execute(
            update(webhook_deliveries)
            .where(webhook_deliveries.c.id == delivery.id)
            .values(
                status=status.value,
                attempts=attempts,
                # A dead delivery keeps its last scheduled time rather than
                # gaining a future one nothing will honour.
                next_attempt_at=None if exhausted else moment + backoff_for(attempts),
                # Truncated: an endpoint returning an HTML error page would
                # otherwise put a whole document in a column somebody renders.
                last_error=error[:500],
            )
        )
        return status

    async def record_endpoint_result(
        self,
        endpoint_id: str,
        *,
        ok: bool,
        at: datetime | None = None,
    ) -> None:
        """Update an endpoint's health after an attempt against it.

        A run of failures disables the endpoint. That is not a punishment: an
        endpoint that has rejected twenty consecutive events is a URL the
        merchant changed, and continuing to queue events for it fills a table
        with rows nobody will ever receive.
        """
        moment = at or datetime.now(UTC)
        if ok:
            await self._session.execute(
                update(webhook_endpoints)
                .where(webhook_endpoints.c.id == endpoint_id)
                .values(consecutive_failures=0, last_delivery_at=moment, updated_at=func.now())
            )
            return

        await self._session.execute(
            update(webhook_endpoints)
            .where(webhook_endpoints.c.id == endpoint_id)
            .values(
                consecutive_failures=webhook_endpoints.c.consecutive_failures + 1,
                last_delivery_at=moment,
                updated_at=func.now(),
                status=func.case(
                    (
                        webhook_endpoints.c.consecutive_failures + 1 >= DISABLE_AFTER_FAILURES,
                        EndpointStatus.DISABLED.value,
                    ),
                    else_=webhook_endpoints.c.status,
                ),
            )
        )

    async def purge_delivered(self, tenant_id: str, *, older_than: datetime) -> int:
        """Drop successfully delivered rows. Failures and dead letters stay.

        The outbox is a queue, not a log — the audit log is the log. Keeping
        every delivered row forever would make the drainer's index scan grow
        without bound for no reader.
        """
        result = await self._session.execute(
            delete(webhook_deliveries)
            .where(webhook_deliveries.c.tenant_id == tenant_id)
            .where(webhook_deliveries.c.status == DeliveryStatus.DELIVERED.value)
            .where(webhook_deliveries.c.delivered_at < older_than)
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    def _require_kek(self) -> str:
        kek = self._kek or get_settings().kek
        if kek == "change-me":
            raise ConfigurationError(
                "NEURA_KEK is still the placeholder, so webhook signing secrets "
                "would be encrypted under a key that is published in "
                ".env.example. Generate one with `neura_core.crypto.generate_key()`.",
            )
        return kek


def _plaintext_urls_allowed() -> bool:
    """``http://`` endpoints are accepted in development and nowhere else.

    A local integrator testing against ``http://localhost:4000`` should not have
    to stand up TLS; a production merchant should not be able to ask for their
    customers' conversations in the clear.
    """
    return not get_settings().is_production


def _endpoint_from_row(row: Any) -> WebhookEndpoint:
    return WebhookEndpoint(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        url=str(row.url),
        events=frozenset(WebhookEvent(e) for e in (row.events or ()) if e in _KNOWN_EVENTS),
        description=str(row.description),
        status=EndpointStatus(row.status),
        consecutive_failures=int(row.consecutive_failures),
        last_delivery_at=row.last_delivery_at,
        created_at=row.created_at,
    )


def _delivery_from_row(row: Any) -> Delivery:
    return Delivery(
        id=str(row.id),
        tenant_id=str(row.tenant_id),
        endpoint_id=str(row.endpoint_id),
        event=WebhookEvent(row.event_type),
        event_id=str(row.event_id),
        payload=dict(row.payload or {}),
        status=DeliveryStatus(row.status),
        attempts=int(row.attempts),
        next_attempt_at=row.next_attempt_at,
        delivered_at=row.delivered_at,
        last_error=str(row.last_error or ""),
        created_at=row.created_at,
    )


#: Rows written by a newer deployment may name an event this one has never heard
#: of. Dropped on read rather than raised: a rolled-back deployment must still be
#: able to list a merchant's endpoints.
_KNOWN_EVENTS = frozenset(e.value for e in WebhookEvent)


def event_body(delivery: Delivery) -> bytes:
    """The exact bytes that are signed and sent.

    Produced once and reused for both, because signing a re-serialisation of
    what was sent is the classic way to ship a signature that never verifies.
    """
    return json.dumps(delivery.payload, sort_keys=True, separators=(",", ":")).encode()


__all__ = [
    "BACKOFF_BASE_S",
    "DISABLE_AFTER_FAILURES",
    "MAX_ATTEMPTS",
    "WebhookRepository",
    "backoff_for",
    "event_body",
]
