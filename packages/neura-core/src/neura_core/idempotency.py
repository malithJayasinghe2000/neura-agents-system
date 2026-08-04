"""Idempotency keys — replaying a write instead of repeating it.

api-design.md §4: every write endpoint accepts ``Idempotency-Key``. Key, endpoint
and a hash of the request body are stored for 24 hours; a replay returns the
original response with ``Idempotency-Replayed: true``, and the same key with a
*different* body is a ``409``.

**This is not polish.** The one write endpoint that matters is chat, and a chat
turn costs model calls, tool calls against a merchant's shop, and a row in the
usage meter. A client that retries on a timeout it never saw the response to
would otherwise be billed twice for one shopper's question and would produce two
divergent replies to it. The document's own reason still holds too: an AI agent
calling this API will retry more aggressively than a human-written client.

**Keys are per tenant.** They are namespaced by ``tenant_id`` and the table is
under the same forced Row-Level Security as everything else, so one merchant
cannot replay — or collide with — another's request by guessing a key. That is
not a hypothetical: ``idk_...`` values are chosen by clients, and two merchants
using the same library will eventually choose the same one.

**Why PostgreSQL rather than Redis.** The stored response has to be exactly as
durable as the effect it describes. A cache that loses a record while the turn
it recorded survives turns a replay back into a repeat, silently, and only under
load.

**Two transactions, not one, and the split is load-bearing.** The claim commits
*before* the work starts — an uncommitted claim is invisible to the concurrent
retry it exists to stop. The completion commits *with* the work, so a response is
recorded exactly when the effect it describes is durable. Doing either the other
way round produces a system that works in every test and duplicates turns under
concurrency.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, cast

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Table,
    Text,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.db import metadata
from neura_core.errors import ConflictError, IdempotencyConflictError

IDEMPOTENCY_KEYS = "idempotency_keys"

#: api-design.md §4. Long enough to cover any retry a client will make, short
#: enough that a key reused next week is a new request rather than a mystery.
DEFAULT_TTL = timedelta(hours=24)


class RecordState(StrEnum):
    IN_FLIGHT = "in_flight"
    """Claimed, still running. A second request holding the same key while the
    first is in flight is a *concurrent* retry, not a replay — there is no
    response to give it yet."""

    COMPLETED = "completed"


#: One client-supplied key and the response it earned.
#:
#: ``request_hash`` is what makes the 409 possible: the same key with a different
#: body is a client bug, and the document is explicit that surfacing it beats
#: silently doing the wrong thing.
idempotency_keys = Table(
    IDEMPOTENCY_KEYS,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("idempotency_key", String(255), primary_key=True),
    # Part of the identity, not just data: the same key on two endpoints is two
    # requests, and treating them as one would replay a chat reply into a
    # webhook registration.
    Column("endpoint", String(255), primary_key=True),
    Column("request_hash", String(64), nullable=False),
    Column("state", String(32), nullable=False, server_default=RecordState.IN_FLIGHT.value),
    Column("response_status", Integer, nullable=True),
    Column("response_body", JSONB, nullable=True),
    #: Echoed back on the replay so a client can correlate the retry with the
    #: original run in our logs.
    Column("request_id", Text, nullable=False, server_default=""),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Index("ix_idempotency_keys_expires_at", "expires_at"),
)


def request_fingerprint(body: bytes) -> str:
    """A hash of the exact request body.

    The **raw** bytes. Re-serialising parsed JSON changes key order and
    whitespace, so two byte-identical retries would fingerprint differently and
    the replay would become a 409 — the least helpful possible outcome for a
    client that did everything right.
    """
    return hashlib.sha256(body).hexdigest()


@dataclass(frozen=True, slots=True)
class Replay:
    """A previously completed response, ready to return again."""

    status: int
    body: dict[str, Any]
    request_id: str


class IdempotencyStore:
    """Claim, complete and replay idempotency keys for one tenant."""

    def __init__(self, session: AsyncSession, *, ttl: timedelta = DEFAULT_TTL) -> None:
        self._session = session
        self._ttl = ttl

    async def claim(
        self,
        tenant_id: str,
        *,
        key: str,
        endpoint: str,
        request_hash: str,
        request_id: str = "",
        now: datetime | None = None,
    ) -> Replay | None:
        """Take the key, or return the response it already earned.

        Three outcomes, and the middle one is the one implementations usually
        get wrong:

        * **Nothing recorded** — the key is claimed ``in_flight`` and ``None`` is
          returned. The caller does the work.
        * **Recorded and still in flight** — a ``409``. Not a replay: the first
          request has not finished, so there is no response to hand back, and
          waiting for one would tie up a connection on a request that may be
          about to fail. ``CONFLICT`` rather than ``IDEMPOTENCY_KEY_REUSED``,
          because the client did nothing wrong and retrying later will work.
        * **Recorded, completed, same body** — the stored response.

        A completed record whose body hash differs is
        :class:`IdempotencyConflictError`, which is the ``409`` api-design.md §4
        specifies for a genuine client bug.
        """
        moment = now or datetime.now(UTC)

        # Expiry is enforced on read as well as by the sweeper, because a
        # sweeper that stops running must not silently extend every key's
        # lifetime to forever.
        existing = await self._get(tenant_id, key=key, endpoint=endpoint)
        if existing is not None and existing.expires_at <= moment:
            await self._forget(tenant_id, key=key, endpoint=endpoint)
            existing = None

        if existing is None:
            try:
                await self._insert(
                    tenant_id,
                    key=key,
                    endpoint=endpoint,
                    request_hash=request_hash,
                    request_id=request_id,
                    now=moment,
                )
            except IntegrityError as exc:
                # Two concurrent first-attempts. The loser is told to retry
                # rather than being allowed to run the work a second time.
                raise ConflictError(
                    "A request with this Idempotency-Key is already in flight.",
                    details={"idempotency_key": key},
                ) from exc
            return None

        if existing.request_hash != request_hash:
            raise IdempotencyConflictError(
                "This Idempotency-Key was already used with a different request body.",
                details={"idempotency_key": key, "endpoint": endpoint},
            )

        if existing.state is RecordState.IN_FLIGHT:
            raise ConflictError(
                "A request with this Idempotency-Key is already in flight.",
                details={"idempotency_key": key},
            )

        return Replay(
            status=existing.response_status or 200,
            body=existing.response_body or {},
            request_id=existing.request_id,
        )

    async def complete(
        self,
        tenant_id: str,
        *,
        key: str,
        endpoint: str,
        status: int,
        body: dict[str, Any],
    ) -> None:
        """Record the response this key earned."""
        await self._session.execute(
            update(idempotency_keys)
            .where(idempotency_keys.c.tenant_id == tenant_id)
            .where(idempotency_keys.c.idempotency_key == key)
            .where(idempotency_keys.c.endpoint == endpoint)
            .values(
                state=RecordState.COMPLETED.value,
                response_status=status,
                response_body=body,
            )
        )

    async def release(self, tenant_id: str, *, key: str, endpoint: str) -> None:
        """Give the key back after a failure, so the client may retry.

        A request that raised has no response worth replaying, and a key left
        ``in_flight`` forever would turn one transient error into 24 hours of
        409s for a client doing exactly what it was told to do.
        """
        await self._forget(tenant_id, key=key, endpoint=endpoint)

    async def purge_expired(self, tenant_id: str, *, now: datetime | None = None) -> int:
        result = await self._session.execute(
            delete(idempotency_keys)
            .where(idempotency_keys.c.tenant_id == tenant_id)
            .where(idempotency_keys.c.expires_at <= (now or datetime.now(UTC)))
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    # ── Internals ────────────────────────────────────────────────────────────

    async def _insert(
        self,
        tenant_id: str,
        *,
        key: str,
        endpoint: str,
        request_hash: str,
        request_id: str,
        now: datetime,
    ) -> None:
        await self._session.execute(
            pg_insert(idempotency_keys).values(
                tenant_id=tenant_id,
                idempotency_key=key,
                endpoint=endpoint,
                request_hash=request_hash,
                state=RecordState.IN_FLIGHT.value,
                request_id=request_id,
                created_at=now,
                expires_at=now + self._ttl,
            )
        )

    async def _get(self, tenant_id: str, *, key: str, endpoint: str) -> _Record | None:
        row = (
            await self._session.execute(
                select(idempotency_keys)
                .where(idempotency_keys.c.tenant_id == tenant_id)
                .where(idempotency_keys.c.idempotency_key == key)
                .where(idempotency_keys.c.endpoint == endpoint)
            )
        ).first()
        if row is None:
            return None
        return _Record(
            request_hash=str(row.request_hash),
            state=RecordState(row.state),
            response_status=row.response_status,
            response_body=dict(row.response_body) if row.response_body else None,
            request_id=str(row.request_id or ""),
            expires_at=row.expires_at,
        )

    async def _forget(self, tenant_id: str, *, key: str, endpoint: str) -> None:
        await self._session.execute(
            delete(idempotency_keys)
            .where(idempotency_keys.c.tenant_id == tenant_id)
            .where(idempotency_keys.c.idempotency_key == key)
            .where(idempotency_keys.c.endpoint == endpoint)
        )


@dataclass(frozen=True, slots=True)
class _Record:
    request_hash: str
    state: RecordState
    response_status: int | None
    response_body: dict[str, Any] | None
    request_id: str
    expires_at: datetime


__all__ = [
    "DEFAULT_TTL",
    "IDEMPOTENCY_KEYS",
    "IdempotencyStore",
    "RecordState",
    "Replay",
    "idempotency_keys",
    "request_fingerprint",
]
