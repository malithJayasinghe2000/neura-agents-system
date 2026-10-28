"""The code from an admin's phone: TOTP, RFC 6238. ADR-0067 §1 and §5.

**The standard library only** (HMAC-SHA1, as the RFC and every authenticator app
use it): the whole algorithm is a dozen lines, and a dependency for it would be
more to trust than to read. ``tests/unit/test_totp.py`` holds it to the RFC's own
table.

6 digits, a new code every 30 seconds. **The code before and after the current
one are accepted**, because a phone's clock drifts, and **a code works once**:
the caller keeps the last step that matched and passes it back.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime
from urllib.parse import quote, urlencode

STEP_SECONDS = 30
DIGITS = 6
#: Steps either side of now that are still accepted.
DRIFT_STEPS = 1
ISSUER = "FiveNeurals"


def new_secret() -> str:
    """A fresh key: 160 random bits (the RFC's size for SHA-1), in base32."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def code_at(secret: str, step: int) -> str:
    """The code for one 30-second step (RFC 4226's dynamic truncation)."""
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def step_of(moment: datetime) -> int:
    return int(moment.timestamp()) // STEP_SECONDS


def matching_step(secret: str, code: str, *, now: datetime, last_step: int | None) -> int | None:
    """The step ``code`` belongs to, or ``None``. Never a step at or before
    ``last_step``, so a code that worked once does not work again."""
    typed = code.replace(" ", "")
    if len(typed) != DIGITS or not typed.isdigit():
        return None
    current = step_of(now)
    for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret, step), typed):
            return step
    return None


def otpauth_uri(secret: str, *, account: str) -> str:
    """The address an authenticator app reads from the QR code."""
    label = quote(f"{ISSUER}:{account}", safe=":")
    query = urlencode(
        {"secret": secret, "issuer": ISSUER, "digits": DIGITS, "period": STEP_SECONDS}
    )
    return f"otpauth://totp/{label}?{query}"


def grouped(secret: str) -> str:
    """The key as a person types it: groups of four."""
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


__all__ = [
    "DIGITS",
    "STEP_SECONDS",
    "code_at",
    "grouped",
    "matching_step",
    "new_secret",
    "otpauth_uri",
    "step_of",
]
