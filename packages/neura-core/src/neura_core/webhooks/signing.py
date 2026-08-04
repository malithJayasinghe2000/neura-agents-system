"""The HMAC scheme both directions of webhook share.

There are two webhook flows in this system and they point opposite ways. A
merchant's store signs a notification and we verify it
(``neura_adapters.generic.webhooks``); we sign an event and the merchant's
endpoint verifies it (api-design.md §9). **They use the same scheme on purpose**
— an integrator who has already written verification code for one direction has
written it for both, and a single algorithm is a single thing to get right.

The primitive lives here, at the bottom of the dependency graph, because the
adapter package is *above* this one and cannot be imported by it. The adapter's
module re-exports these functions rather than keeping a second copy: two
implementations of a signature scheme diverge, and the divergence shows up as an
integration that mysteriously stops verifying.

Three properties, each closing a specific attack:

* **The timestamp is signed with the body.** Otherwise a captured request can be
  replayed forever, because the signature stays valid.
* **A tolerance window bounds replay.** Signed-but-old requests are rejected.
* **Comparison is constant-time.** A byte-by-byte comparison leaks, through
  timing, how much of a guessed signature was correct.
"""

from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_HEADER = "X-Neura-Signature"
TIMESTAMP_HEADER = "X-Neura-Timestamp"

#: Present on outbound events only. The merchant dedupes on it, which is what
#: makes at-least-once delivery safe for them to accept.
EVENT_ID_HEADER = "X-Neura-Event-Id"
EVENT_TYPE_HEADER = "X-Neura-Event"

SIGNATURE_PREFIX = "sha256="

#: How far out of date a signed request may be. Five minutes tolerates clock
#: drift on a merchant's server without leaving a replay window worth using.
DEFAULT_TOLERANCE_S = 300


def signing_payload(body: bytes, timestamp: int) -> bytes:
    """Exactly what is signed: ``<timestamp>.<raw body>``.

    The **raw** body, byte for byte. Re-serialising parsed JSON before signing or
    verifying changes key order and whitespace, and the signature stops matching
    for reasons no log will explain.
    """
    return f"{timestamp}.".encode() + body


def sign(body: bytes, secret: str, *, timestamp: int | None = None) -> tuple[str, int]:
    """Produce ``(signature, timestamp)`` for a body."""
    ts = timestamp if timestamp is not None else int(time.time())
    digest = hmac.new(secret.encode(), signing_payload(body, ts), hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}", ts


def matches(body: bytes, signature: str, secret: str, *, timestamp: int) -> bool:
    """Constant-time check of a presented signature against a recomputed one."""
    expected, _ = sign(body, secret, timestamp=timestamp)
    return hmac.compare_digest(expected, signature.strip())


def within_tolerance(timestamp: int, *, now: int, tolerance_s: int = DEFAULT_TOLERANCE_S) -> bool:
    return abs(now - timestamp) <= tolerance_s


__all__ = [
    "DEFAULT_TOLERANCE_S",
    "EVENT_ID_HEADER",
    "EVENT_TYPE_HEADER",
    "SIGNATURE_HEADER",
    "SIGNATURE_PREFIX",
    "TIMESTAMP_HEADER",
    "matches",
    "sign",
    "signing_payload",
    "within_tolerance",
]
