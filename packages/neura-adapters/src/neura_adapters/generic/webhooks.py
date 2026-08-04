"""The signed webhook contract.

The store pushes a small notification — "order 1001 changed" — and we fetch the
entity ourselves. Deliberately: a payload we fetch is a payload we trust the
shape of, and a notification carrying no customer data is a notification that
cannot leak one if it is mis-delivered.

The signature is what makes the endpoint safe to expose. Without it, anyone who
learns a merchant's webhook URL can make us re-read arbitrary entities on
demand. Three properties, each closing a specific attack:

* **The timestamp is signed with the body.** Otherwise a captured request can be
  replayed forever, because the signature stays valid.
* **A tolerance window bounds replay.** Signed-but-old requests are rejected.
* **Comparison is constant-time.** A byte-by-byte comparison leaks, through
  timing, how much of a guessed signature was correct.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from neura_commerce import AdapterError

# The algorithm lives in `neura_core.webhooks.signing` and is shared with the
# outbound direction (api-design.md §9). It moved down there in milestone 1.14
# rather than being copied: two implementations of one signature scheme diverge,
# and the divergence shows up as an integration that mysteriously stops
# verifying. Re-exported here so every existing importer of this module — the
# reference store, the conformance tool, the tests — is unaffected.
from neura_core.webhooks.signing import (
    DEFAULT_TOLERANCE_S,
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    TIMESTAMP_HEADER,
    matches,
    sign,
    signing_payload,
    within_tolerance,
)

#: Events a conforming store may send. Unknown names parse — a store on a later
#: spec version must not break this one — but the receiver ignores them.
KNOWN_EVENTS = frozenset(
    {
        "product.created",
        "product.updated",
        "product.deleted",
        "order.created",
        "order.updated",
        "customer.updated",
        "policy.updated",
    }
)


class WebhookSignatureError(AdapterError):
    """A webhook could not be proved to come from the store.

    Never retryable and never partially honoured: an unverified webhook is an
    anonymous instruction to go read a merchant's data.
    """

    code = "WEBHOOK_SIGNATURE_INVALID"
    error_type = "authentication_error"
    http_status = 401
    retryable = False


class WebhookEvent(BaseModel):
    """What a store sends. No entity data — only what changed."""

    model_config = ConfigDict(extra="ignore")

    event: str
    external_id: str
    occurred_at: datetime | None = None
    detail: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_known(self) -> bool:
        return self.event in KNOWN_EVENTS

    @property
    def entity_type(self) -> str:
        return self.event.split(".", 1)[0]


def verify(
    body: bytes,
    *,
    signature: str | None,
    timestamp: str | int | None,
    secret: str,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
    now: datetime | None = None,
) -> None:
    """Raise ``WebhookSignatureError`` unless this request is genuine and fresh.

    Returns ``None`` on success rather than a boolean: a caller who forgets to
    check a returned bool has an open endpoint, and a caller who forgets to
    catch an exception has an outage. One of those failure modes is survivable.
    """
    if not signature:
        raise WebhookSignatureError(f"missing {SIGNATURE_HEADER}")
    if timestamp is None:
        raise WebhookSignatureError(f"missing {TIMESTAMP_HEADER}")

    try:
        ts = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise WebhookSignatureError(f"{TIMESTAMP_HEADER} must be a unix timestamp") from exc

    reference = int((now or datetime.now(UTC)).timestamp())
    if not within_tolerance(ts, now=reference, tolerance_s=tolerance_s):
        raise WebhookSignatureError(
            f"timestamp is {abs(reference - ts)}s away from now, outside the {tolerance_s}s window"
        )

    if not matches(body, signature, secret, timestamp=ts):
        raise WebhookSignatureError("signature does not match")


def parse(body: bytes) -> WebhookEvent:
    """Parse a verified body. Verify first — this does not authenticate anything."""
    return WebhookEvent.model_validate_json(body)


#: Re-exports are deliberate, not leftovers. Callers of this module — the CLI's
#: example generator, the reference store, the conformance tests — import the
#: signing primitives from here because this is the module that documents the
#: *inbound* contract. Naming them keeps that true after the algorithm moved
#: down into `neura_core`.
__all__ = [
    "DEFAULT_TOLERANCE_S",
    "KNOWN_EVENTS",
    "SIGNATURE_HEADER",
    "SIGNATURE_PREFIX",
    "TIMESTAMP_HEADER",
    "WebhookEvent",
    "WebhookSignatureError",
    "matches",
    "parse",
    "sign",
    "signing_payload",
    "verify",
    "within_tolerance",
]
