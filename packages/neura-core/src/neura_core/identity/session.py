"""The console session cookie. ADR-0026 §3.

A signed value naming **the person and nothing else**. Not the tenant, not their
role, not what they may do — only who they are.

## Why so little is in it

Everything a cookie carries is an assertion the browser makes about itself, and
a cookie is valid until it expires no matter what changes in the meantime. Put
the tenant in it and removing somebody's access does nothing until then; put the
role in it and a demotion is advisory. So the cookie answers exactly one
question — *who is this?* — and every authorisation decision is re-derived from
``memberships`` on the request (`AGENTS.md` rule 3).

## Why signed rather than stored

There is no ``sessions`` table to grow, prune, or lose on a restart. The trade
is that a session cannot be destroyed server-side by deleting a row — which is
acceptable **only** because the cookie grants no authority by itself. Revoking a
membership takes effect on the person's very next request.

## Why not a JWT

A JWT would bring an algorithm field the verifier is expected to read from the
token itself, which is the source of a well-known family of vulnerabilities, and
a great deal of machinery for claims we deliberately do not carry. This is an
HMAC over three fields with the algorithm fixed in code.
"""

from __future__ import annotations

import base64
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from neura_core.logging import get_logger

log = get_logger(__name__)

#: How long a signed-in browser stays signed in. Long enough that a merchant
#: checking their console weekly is not asked to fetch mail every time; short
#: enough that a forgotten session on a shared machine expires.
SESSION_TTL = timedelta(days=30)

#: The cookie's name. ``__Host-`` is not decoration: browsers refuse to accept a
#: cookie with that prefix unless it is Secure, path ``/`` and carries **no**
#: Domain attribute — which makes it impossible for a sibling subdomain to set
#: or overwrite it. That is a real attack on cookie-based sessions and the
#: prefix is the only defence the browser will enforce for us.
COOKIE_NAME = "__Host-fn_session"

#: Version tag, so the format can change without every signed-in browser
#: silently failing an HMAC check and looking like a broken login.
_VERSION = "1"


@dataclass(frozen=True, slots=True)
class Session:
    """A verified session. Constructed only by :func:`verify`."""

    user_id: str
    issued_at: datetime
    expires_at: datetime
    #: When the admin typed the code from their phone in this sign-in
    #: (ADR-0067), or ``None``. Only admin pages read it.
    code_at: datetime | None = None


def issue(
    user_id: str, secret: str, *, now: datetime | None = None, code_at: datetime | None = None
) -> str:
    """Sign a session for ``user_id``.

    ``user_id`` must already have been proved — by redeeming a one-time token.
    Signing an unverified id produces a perfectly valid cookie for a person who
    never authenticated, and nothing downstream could tell.

    ``now`` is the sign-in's own time: after an admin types their code the
    cookie is issued again with the **same** ``now`` and a ``code_at``, so the
    12 hours an admin page allows still count from the email link (ADR-0067).
    """
    if not user_id:
        raise ValueError("refusing to issue a session with no user id")

    moment = now or datetime.now(UTC)
    payload = {
        "v": _VERSION,
        "sub": user_id,
        "iat": int(moment.timestamp()),
        "exp": int((moment + SESSION_TTL).timestamp()),
    }
    if code_at is not None:
        payload["code"] = int(code_at.timestamp())
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_sign(body, secret)}"


def verify(cookie: str, secret: str, *, now: datetime | None = None) -> Session | None:
    """Check a cookie and return the session, or ``None``.

    ``None`` for every kind of failure — malformed, wrong signature, expired,
    unknown version. A caller that distinguished them would be telling whoever
    presented the cookie which part they got wrong.
    """
    if not cookie or "." not in cookie:
        return None

    body, _, signature = cookie.rpartition(".")

    # Constant time. A comparison that returns early leaks how much of a forged
    # signature was right, one byte at a time.
    if not hmac.compare_digest(signature, _sign(body, secret)):
        return None

    try:
        payload = json.loads(_unb64(body))
        if payload.get("v") != _VERSION:
            return None
        user_id = str(payload["sub"])
        issued_at = datetime.fromtimestamp(int(payload["iat"]), tz=UTC)
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=UTC)
        code_at = (
            datetime.fromtimestamp(int(payload["code"]), tz=UTC) if "code" in payload else None
        )
    except (ValueError, KeyError, TypeError):
        # A well-signed cookie that will not parse means our own format changed
        # under a live session, not an attack — but the answer is the same.
        return None

    if not user_id or expires_at <= (now or datetime.now(UTC)):
        return None

    return Session(user_id=user_id, issued_at=issued_at, expires_at=expires_at, code_at=code_at)


def _sign(body: str, secret: str) -> str:
    if not secret:
        raise ValueError("refusing to sign a session with an empty secret")
    return _b64(hmac.new(secret.encode(), body.encode(), sha256).digest())


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


__all__ = ["COOKIE_NAME", "SESSION_TTL", "Session", "issue", "verify"]
