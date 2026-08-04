"""Outbound webhooks — the events we push to a merchant (api-design.md §9).

Signing lives in :mod:`neura_core.webhooks.signing` and is shared with the
*inbound* direction in ``neura_adapters.generic.webhooks``: one scheme, one
implementation, so an integrator writes verification code once.

Delivery itself is not here. It needs an HTTP client and a scheduler, both of
which belong to the deployable rather than to shared infrastructure —
``neura_api.webhooks`` drains the outbox this package defines.
"""

from neura_core.webhooks.models import (
    Delivery,
    DeliveryStatus,
    EndpointStatus,
    PendingEvent,
    WebhookEndpoint,
    WebhookEvent,
)
from neura_core.webhooks.repository import (
    BACKOFF_BASE_S,
    DISABLE_AFTER_FAILURES,
    MAX_ATTEMPTS,
    WebhookRepository,
    backoff_for,
    event_body,
)
from neura_core.webhooks.schema import (
    WEBHOOK_DELIVERIES,
    WEBHOOK_ENDPOINTS,
    webhook_deliveries,
    webhook_endpoints,
)
from neura_core.webhooks.signing import (
    DEFAULT_TOLERANCE_S,
    EVENT_ID_HEADER,
    EVENT_TYPE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    TIMESTAMP_HEADER,
    matches,
    sign,
    signing_payload,
    within_tolerance,
)

__all__ = [
    "BACKOFF_BASE_S",
    "DEFAULT_TOLERANCE_S",
    "DISABLE_AFTER_FAILURES",
    "EVENT_ID_HEADER",
    "EVENT_TYPE_HEADER",
    "MAX_ATTEMPTS",
    "SIGNATURE_HEADER",
    "SIGNATURE_PREFIX",
    "TIMESTAMP_HEADER",
    "WEBHOOK_DELIVERIES",
    "WEBHOOK_ENDPOINTS",
    "Delivery",
    "DeliveryStatus",
    "EndpointStatus",
    "PendingEvent",
    "WebhookEndpoint",
    "WebhookEvent",
    "WebhookRepository",
    "backoff_for",
    "event_body",
    "matches",
    "sign",
    "signing_payload",
    "webhook_deliveries",
    "webhook_endpoints",
    "within_tolerance",
]
