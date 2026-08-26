"""Signing a human in. ADR-0026.

One flow, four steps, and the security of the console rests on all four:

1. Someone types an email. A one-time token is generated, its **hash** stored,
   and a link mailed. The response is identical whether or not the address has
   an account.
2. They click the link. The token is looked up by hash, checked for expiry and
   prior use, and **marked consumed in the same transaction** that mints the
   session.
3. The session is a signed cookie naming the *person*. It names no tenant.
4. Every later request re-derives which merchants that person may act for from
   ``memberships``, and only then opens a tenant-scoped transaction.

## Why step 4 is not an optimisation away

Baking the tenant into the cookie at sign-in would save a query per request and
make access **unrevocable**: removing somebody's membership would do nothing
until their cookie expired. Authorisation is re-derived because it must be
withdrawable, which is `AGENTS.md` rule 3 — a claim carried by the client is not
an authorisation decision.

## Why sign-in never says whether an account exists

*"No account with that email"* is an oracle. Anyone could walk a list of shop
owners' addresses through this form and learn which merchants use us — which is
both a customer list and a target list. :func:`request_sign_in_link` therefore
returns the same value in both cases and the caller shows the same screen.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core import ids
from neura_core.identity.schema import login_tokens, memberships, users
from neura_core.logging import get_logger

log = get_logger(__name__)

#: How long a sign-in link works. Short, because it is a bearer credential
#: sitting in an inbox — but not so short that a person who checks mail on their
#: phone five minutes later is locked out. Fifteen minutes is the span at which
#: both of those are true.
TOKEN_TTL = timedelta(minutes=15)

#: Bytes of entropy in the token. Same 256 bits as an API key: this thing signs
#: a person in, so it is not a weaker credential than the one a program holds.
_ENTROPY_BYTES = 32


def _fingerprint(token: str) -> str:
    """SHA-256, exactly as ``tenancy.keys.fingerprint`` does for API keys.

    Not a slow password hash, and deliberately not: the input is 256 bits of
    ``secrets`` output rather than something a human chose, so there is no
    dictionary to attack and nothing for a work factor to buy. What matters is
    that the stored value cannot be replayed, and a hash gives that.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class SignInRequest:
    """A link that was minted, or the fact that none was.

    ``token`` is the plaintext and exists **only** in the moment between minting
    and mailing. It is never stored, never logged and never returned to a
    caller that would put it in a response body.
    """

    token: str = ""
    url: str = ""
    user_id: str = ""

    @property
    def minted(self) -> bool:
        return bool(self.token)


@dataclass(frozen=True, slots=True)
class Membership:
    """One person's access to one merchant."""

    tenant_id: str
    role: str


async def request_sign_in_link(
    session: AsyncSession,
    *,
    email: str,
    console_base_url: str,
    requested_ip: str = "",
    now: datetime | None = None,
) -> SignInRequest:
    """Mint a one-time link for ``email``, if that address has an account.

    Runs in an :meth:`~neura_core.db.Database.identity_session` with **no**
    user id — the person has proved nothing yet, and this call is what starts
    to change that.

    Returns an empty :class:`SignInRequest` for an unknown address. **The caller
    must not distinguish the two in its response**; see the module docstring.
    """
    moment = now or datetime.now(UTC)

    row = (await session.execute(select(users.c.id).where(users.c.email == email))).first()
    if row is None:
        # Logged, because a burst of these is the signature of somebody walking
        # a list of addresses — and it is the only trace such an attempt leaves.
        log.info("sign_in_requested_unknown_email", ip=requested_ip)
        return SignInRequest()

    user_id = str(row[0])
    token = secrets.token_urlsafe(_ENTROPY_BYTES)

    await session.execute(
        login_tokens.insert().values(
            id=ids.new_id(ids.LOGIN_TOKEN),
            user_id=user_id,
            token_hash=_fingerprint(token),
            expires_at=moment + TOKEN_TTL,
            requested_ip=requested_ip,
            created_at=moment,
        )
    )

    query = urlencode({"token": token})
    log.info("sign_in_link_minted", user_id=user_id, ip=requested_ip)
    return SignInRequest(
        token=token,
        url=f"{console_base_url.rstrip('/')}/auth/verify?{query}",
        user_id=user_id,
    )


async def redeem(
    session: AsyncSession,
    *,
    token: str,
    now: datetime | None = None,
) -> str:
    """Consume a sign-in token and return the user id it proves. ``""`` if invalid.

    **Everything about this function is one transaction on purpose.** The read,
    the expiry check and the write that marks the token consumed happen together,
    and the ``UPDATE`` itself re-states the "not yet consumed" condition — so two
    requests racing on a link forwarded to a shared inbox produce exactly one
    winner, decided by the database rather than by the order two coroutines
    happened to run in.

    One value is returned for every kind of failure — unknown, expired, already
    used, malformed. The person on the other end gets one message: *ask for a
    new link.* Distinguishing them would tell an attacker holding a stolen link
    whether it was ever valid.
    """
    if not token:
        return ""

    moment = now or datetime.now(UTC)

    consumed = await session.execute(
        update(login_tokens)
        .where(
            login_tokens.c.token_hash == _fingerprint(token),
            login_tokens.c.consumed_at.is_(None),
            login_tokens.c.expires_at > moment,
        )
        .values(consumed_at=moment)
        .returning(login_tokens.c.user_id)
    )
    row = consumed.first()

    if row is None:
        log.info("sign_in_token_rejected")
        return ""

    user_id = str(row[0])
    await session.execute(update(users).where(users.c.id == user_id).values(last_seen_at=moment))
    log.info("sign_in_succeeded", user_id=user_id)
    return user_id


async def memberships_for(session: AsyncSession, user_id: str) -> list[Membership]:
    """Which merchants this person may act for. The authorisation decision.

    Requires an :meth:`~neura_core.db.Database.identity_session` opened *with*
    ``user_id`` — the ``membership_lookup`` policy reads ``app.user_id``, so a
    session that did not set it correctly returns an empty list rather than an
    error. That is the safe direction (no access rather than wrong access) and
    it is also the confusing one, which is why it is written here.

    Revoked memberships are excluded in the query rather than filtered
    afterwards. A caller that forgot the filter would grant access to somebody
    it had been told to remove.
    """
    if not user_id:
        return []

    rows = (
        await session.execute(
            select(memberships.c.tenant_id, memberships.c.role)
            .where(memberships.c.user_id == user_id, memberships.c.revoked_at.is_(None))
            .order_by(memberships.c.created_at)
        )
    ).all()
    return [Membership(tenant_id=str(r[0]), role=str(r[1])) for r in rows]


async def may_act_for(session: AsyncSession, *, user_id: str, tenant_id: str) -> bool:
    """Is this person allowed to act for this merchant, right now?

    Called on **every** request that names a tenant. The tenant a browser asks
    for is a request parameter and therefore a suggestion; this is what turns it
    into a decision (`AGENTS.md` rule 3).
    """
    return any(m.tenant_id == tenant_id for m in await memberships_for(session, user_id))


__all__ = [
    "TOKEN_TTL",
    "Membership",
    "SignInRequest",
    "may_act_for",
    "memberships_for",
    "redeem",
    "request_sign_in_link",
]
