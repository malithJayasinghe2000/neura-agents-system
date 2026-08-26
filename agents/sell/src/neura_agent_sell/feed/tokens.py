"""Minting, storing and resolving a feed's address.

The address *is* the credential (ADR-0024), so everything here is about one
question: given a string out of a URL, which tenant's catalogue — if any — does
it name?

**The lookup is the ADR-0014 bootstrap, unchanged.** The tenant is not known
until the token resolves, so the read happens on ``Database.credential_session``,
which sets ``app.api_key_hash`` and no ``app.tenant_id``, is ``READ ONLY``, and
can therefore see exactly the row for a credential the caller already holds.
Everything after it is an ordinary scoped session. **No new exemption was
created for the feed** — the problem is the same problem authentication already
had, and reusing the answer is what keeps the number of ways into this database
at one.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from neura_agent_sell.feed.schema import sell_feeds
from neura_core import get_logger

log = get_logger(__name__)

#: Distinguishable at a glance from `fn_sk_`/`fn_pk_` API keys, because it is
#: not one and must never be pasted into an `Authorization` header.
PREFIX = "fn_feed_"

#: 32 bytes. The token is the entire access control on a public URL, so it is
#: sized to be unguessable rather than to be typed — nobody types this, they
#: paste it into a submission form once.
_ENTROPY_BYTES = 32

#: Matched before the database is touched, so a crawler probing `/feed/robots.txt`
#: costs a regex rather than a query.
_TOKEN = re.compile(rf"^{re.escape(PREFIX)}[A-Za-z0-9_-]{{20,}}$")

_PREFIX_CHARS = 8

#: `last_served_at` is written at most this often per feed.
#:
#: A popular feed is fetched constantly, and a write per request turns a cached
#: read into a database write per crawler hit — the same reasoning `api_keys`
#: applies to `last_used_at`. The merchant-visible question is "is anything
#: reading my feed", and an hour's resolution answers it exactly as well.
SERVED_AT_RESOLUTION = timedelta(hours=1)

_FEEDS = sell_feeds.c


@dataclass(frozen=True, slots=True)
class IssuedFeed:
    """A freshly minted feed address. ``token`` exists exactly once — here.

    Returned rather than stored, so the caller has to decide visibly what to do
    with it. Nothing in this module writes the plaintext anywhere, which is what
    makes "we cannot show you your URL twice" true rather than a policy.
    """

    token: str
    token_prefix: str
    token_hash: str


@dataclass(frozen=True, slots=True)
class ResolvedFeed:
    """Which catalogue a URL names."""

    feed_id: str
    tenant_id: str
    store_id: str
    last_served_at: datetime | None = None


def generate() -> IssuedFeed:
    """Mint an address."""
    token = f"{PREFIX}{secrets.token_urlsafe(_ENTROPY_BYTES)}"
    return IssuedFeed(
        token=token,
        token_prefix=token[: len(PREFIX) + _PREFIX_CHARS],
        token_hash=fingerprint(token),
    )


def fingerprint(token: str) -> str:
    """The stored form. One-way, and the only thing ever compared."""
    return hashlib.sha256(token.encode()).hexdigest()


def matches(token: str, token_hash: str) -> bool:
    """Constant-time, for the reason `keys.matches` gives: it is one line either
    way, and a reviewer should not have to work out which line it is."""
    return hmac.compare_digest(fingerprint(token), token_hash)


def is_well_formed(token: str) -> bool:
    """Does this even look like a feed token?

    Checked before any database work. A public URL is scanned constantly, and
    `/v1/sell/feed/wp-admin/products.json` should cost a regex rather than a
    connection from the pool.
    """
    return bool(_TOKEN.match(token))


async def resolve(db: Any, token: str) -> ResolvedFeed | None:
    """Which tenant's catalogue this URL names, or ``None``.

    ``None`` covers every failure identically — malformed, unknown, rotated —
    and the route turns all of them into the same ``404``. A distinct "this feed
    was rotated" reply would confirm to a scanner that it had found a real
    tenant, which is the same oracle `orders.py` refuses to become when it uses
    one message for "no such order" and "not your order".
    """
    if not is_well_formed(token):
        return None

    token_hash = fingerprint(token)

    async with db.credential_session(token_hash) as session:
        row = (
            await session.execute(
                select(
                    _FEEDS.id,
                    _FEEDS.tenant_id,
                    _FEEDS.store_id,
                    _FEEDS.token_hash,
                    _FEEDS.last_served_at,
                ).where(_FEEDS.token_hash == token_hash, _FEEDS.rotated_at.is_(None))
            )
        ).one_or_none()

    if row is None:
        return None

    # The row was selected *by* the hash, so this can only fail if the policy
    # ever stopped filtering. Which is exactly when a redundant check is the one
    # that matters — and it is constant-time, so it costs nothing to keep.
    if not matches(token, row.token_hash):
        log.error("feed_token_mismatch_after_lookup", feed_id=row.id)
        return None

    return ResolvedFeed(
        feed_id=row.id,
        tenant_id=row.tenant_id,
        store_id=row.store_id,
        last_served_at=row.last_served_at,
    )


def should_record_serve(feed: ResolvedFeed, *, now: datetime | None = None) -> bool:
    """Is this fetch worth a write?

    Rate-limited to :data:`SERVED_AT_RESOLUTION`, so a crawler hammering a feed
    produces one write an hour rather than one per request.
    """
    if feed.last_served_at is None:
        return True
    return (now or datetime.now(UTC)) - feed.last_served_at >= SERVED_AT_RESOLUTION


async def record_serve(db: Any, feed: ResolvedFeed) -> None:
    """Stamp ``last_served_at``. Never on the request's critical path.

    Failures are swallowed with a log, deliberately: this is observability, and
    a feed that 500s because a bookkeeping write failed has traded the thing the
    merchant paid for against a timestamp nobody is waiting on.
    """
    try:
        async with db.tenant_session(feed.tenant_id) as session:
            await session.execute(
                update(sell_feeds)
                .where(_FEEDS.id == feed.feed_id, _FEEDS.tenant_id == feed.tenant_id)
                .values(last_served_at=datetime.now(UTC))
            )
    except Exception as exc:
        log.warning("feed_serve_not_recorded", feed_id=feed.feed_id, error=str(exc))


__all__ = [
    "PREFIX",
    "SERVED_AT_RESOLUTION",
    "IssuedFeed",
    "ResolvedFeed",
    "fingerprint",
    "generate",
    "is_well_formed",
    "matches",
    "record_serve",
    "resolve",
    "should_record_serve",
]
