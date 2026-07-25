"""Event schemas.

Defined now, used later. Phase 1 has one agent, so there is nothing to publish
between agents yet — but the event bus arrives with agent #2
(docs/architecture/agent-runtime.md §4), and defining the vocabulary here keeps
the seam open at no cost.

Also used for inbound store webhooks, where the payload is treated as a *hint*:
we re-fetch the entity from the adapter rather than trusting pushed data, which
removes data poisoning from the threat surface entirely
(docs/architecture/security-model.md §8).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from neura_domain.base import DomainModel


class EventKind(StrEnum):
    # From the store, inbound
    ORDER_CREATED = "order.created"
    ORDER_UPDATED = "order.updated"
    ORDER_CANCELLED = "order.cancelled"
    PRODUCT_UPDATED = "product.updated"
    CUSTOMER_CREATED = "customer.created"
    CART_UPDATED = "cart.updated"

    # From us, outbound to the merchant
    CONVERSATION_STARTED = "conversation.started"
    CONVERSATION_RESOLVED = "conversation.resolved"
    CONVERSATION_ESCALATED = "conversation.escalated"
    ACTION_PENDING_APPROVAL = "agent.action.pending_approval"
    STORE_SYNC_FAILED = "store.sync.failed"
    BUDGET_THRESHOLD_REACHED = "budget.threshold.reached"


class Event(DomainModel):
    event_id: str
    kind: EventKind
    tenant_id: str
    occurred_at: datetime
    source: str = Field(description="'store' | 'agent:<key>' | 'system'")
    entity_type: str | None = None
    external_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def is_inbound(self) -> bool:
        return self.source == "store"
