"""What an outbound webhook *is*, independently of how it is stored or sent."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from neura_core.ids import EVENT, new_id


class WebhookEvent(StrEnum):
    """Events a merchant may subscribe to.

    Exactly the list in api-design.md §9, minus one. ``agent.action.pending_approval``
    is **deliberately absent**: the approval queue does not exist and no WRITE
    tool can be registered ([ADR-0010](../../../docs/architecture/adr/0010-read-only-mvp-tools.md)),
    so an event named for it could never fire. A subscribable event that cannot
    occur is a feature a merchant configures, tests, and then quietly stops
    trusting the rest of the list because of.
    """

    CONVERSATION_STARTED = "conversation.started"
    CONVERSATION_RESOLVED = "conversation.resolved"
    CONVERSATION_ESCALATED = "conversation.escalated"
    STORE_SYNC_FAILED = "store.sync.failed"
    BUDGET_THRESHOLD_REACHED = "budget.threshold.reached"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    """Queued, or waiting out a backoff."""

    DELIVERED = "delivered"

    DEAD = "dead"
    """Every attempt was used. Kept and readable — that is the dead-letter queue
    api-design.md §9 asks for, and a merchant who cannot see what failed cannot
    fix their endpoint."""


class EndpointStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    """Auto-disabled after sustained failure, or switched off by the merchant."""


class WebhookEndpoint(BaseModel):
    """One registered destination. Never carries the signing secret.

    The secret is envelope-encrypted at rest and shown exactly once, at
    registration. Unlike an API key it cannot be *hashed* — we have to reproduce
    it to sign with it — so it is encrypted under the KEK like a store
    credential, which is the same trade and the same reasoning
    (security-model.md §5).
    """

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    url: str
    events: frozenset[WebhookEvent] = frozenset()
    description: str = ""
    status: EndpointStatus = EndpointStatus.ACTIVE
    consecutive_failures: int = 0
    last_delivery_at: datetime | None = None
    created_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status is EndpointStatus.ACTIVE

    def wants(self, event: WebhookEvent) -> bool:
        return self.is_active and event in self.events


class PendingEvent(BaseModel):
    """An event on its way out, before anything has been attempted.

    ``event_id`` is minted here rather than at delivery time because
    at-least-once delivery means the same event may arrive twice, and the
    merchant's dedupe key has to be stable across attempts.
    """

    model_config = ConfigDict(frozen=True)

    event: WebhookEvent
    payload: dict[str, Any] = Field(default_factory=dict)
    event_id: str = Field(default_factory=lambda: new_id(EVENT))
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    conversation_id: str | None = None


class Delivery(BaseModel):
    """One (event, endpoint) pair and what has happened to it so far."""

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    endpoint_id: str
    event: WebhookEvent
    event_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: DeliveryStatus = DeliveryStatus.PENDING
    attempts: int = 0
    next_attempt_at: datetime | None = None
    delivered_at: datetime | None = None
    last_error: str = ""
    created_at: datetime | None = None


__all__ = [
    "Delivery",
    "DeliveryStatus",
    "EndpointStatus",
    "PendingEvent",
    "WebhookEndpoint",
    "WebhookEvent",
]
