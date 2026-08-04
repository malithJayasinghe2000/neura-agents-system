"""The request-side half of idempotency.

The store is ``neura_core.idempotency``; this is how a route uses it, and it
exists as one object so that every write endpoint uses it the *same* way. Three
call sites doing this by hand is three chances for one of them to record a
response it never sent.

Two transactions, and the split is load-bearing (see the store's docstring): the
claim commits before the work starts, because an uncommitted claim is invisible
to the concurrent retry it exists to stop; the completion commits with the work,
because a recorded response must be exactly as durable as the effect it
describes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neura_core import Database, get_logger
from neura_core.idempotency import IdempotencyStore, Replay, request_fingerprint

log = get_logger(__name__)

HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotency-Replayed"


@dataclass(frozen=True, slots=True)
class Claim:
    """A held key, or nothing at all if the client did not supply one.

    ``Idempotency-Key`` is optional on the wire — api-design.md §4 says every
    write endpoint *accepts* one, not that it demands one. A client that omits
    it gets today's behaviour and owns the consequences of its own retries.
    """

    key: str | None
    endpoint: str
    tenant_id: str
    request_hash: str = ""

    @property
    def held(self) -> bool:
        return self.key is not None


class Idempotency:
    """Claim, complete and release keys around a write."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def claim(
        self,
        tenant_id: str,
        *,
        key: str | None,
        endpoint: str,
        body: bytes,
        request_id: str = "",
    ) -> tuple[Claim, Replay | None]:
        """Take the key. Returns the claim, and a replay if there is one."""
        if not key:
            return Claim(key=None, endpoint=endpoint, tenant_id=tenant_id), None

        fingerprint = request_fingerprint(body)
        async with self._db.tenant_session(tenant_id) as session:
            replay = await IdempotencyStore(session).claim(
                tenant_id,
                key=key,
                endpoint=endpoint,
                request_hash=fingerprint,
                request_id=request_id,
            )

        if replay is not None:
            log.info("idempotent_replay", tenant_id=tenant_id, endpoint=endpoint)

        return (
            Claim(key=key, endpoint=endpoint, tenant_id=tenant_id, request_hash=fingerprint),
            replay,
        )

    async def complete(self, claim: Claim, *, status: int, body: dict[str, Any]) -> None:
        if not claim.held or claim.key is None:
            return
        async with self._db.tenant_session(claim.tenant_id) as session:
            await IdempotencyStore(session).complete(
                claim.tenant_id,
                key=claim.key,
                endpoint=claim.endpoint,
                status=status,
                body=body,
            )

    async def release(self, claim: Claim) -> None:
        """Hand the key back after a failure, so the client may retry.

        A request that raised has no response worth replaying. A key left held
        would turn one transient error into 24 hours of 409s for a client doing
        exactly what the documentation told it to.
        """
        if not claim.held or claim.key is None:
            return
        async with self._db.tenant_session(claim.tenant_id) as session:
            await IdempotencyStore(session).release(
                claim.tenant_id, key=claim.key, endpoint=claim.endpoint
            )


__all__ = ["HEADER", "REPLAYED_HEADER", "Claim", "Idempotency"]
