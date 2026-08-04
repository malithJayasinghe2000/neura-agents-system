"""The audit sink a served conversation actually gets.

**This is open question S5.** ADR-0012 chose to *block* a recognised attack
rather than escalate it, and its entire answer to "then the merchant never finds
out" is that a block writes a named, countable, tamper-evident ``guard.block``
entry. The graph has written that entry since milestone 1.12 — into ``None``,
because every caller so far has been an eval case or a smoke script. A block with
no sink is a block nobody can count, which is the *cheap and invisible* outcome
ADR-0012 explicitly rejected, wearing the other one's clothes.

Two things this adds over handing ``PostgresAuditLog`` a request-scoped session.

**A session per entry, not one held across the turn.** A turn takes seconds — a
model call, tool calls against a merchant's shop, another model call. Holding a
pooled connection open for all of it would let ten concurrent shoppers exhaust a
ten-connection pool, and the fix would be a bigger pool rather than a shorter
transaction. Each entry gets its own short transaction instead. The cost is that
a security event commits even if the turn that produced it later fails, which is
the right direction to be wrong in: over-recording a block is recoverable, losing
one is not.

**One retry on a sequence collision.** The chain's next sequence number is read
and then written, so two turns for the same tenant finishing together can pick
the same one — the unique constraint catches it, which is the design working, and
the loser should retry rather than fail a shopper's turn over a bookkeeping race.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from neura_agent_core.audit import AuditEntry, PostgresAuditLog
from neura_core import Database, get_logger

log = get_logger(__name__)

#: One retry. A second collision means real contention rather than a race, and
#: retrying forever would turn a hot tenant into a spin loop.
RETRIES = 1


class TenantAuditLog:
    """An :class:`AuditSink` that opens its own tenant-scoped session per entry."""

    def __init__(self, db: Database, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def record(self, entry: AuditEntry) -> str:
        for attempt in range(RETRIES + 1):
            try:
                async with self._db.tenant_session(self._tenant_id) as session:
                    return await PostgresAuditLog(session).record(entry)
            except IntegrityError:
                if attempt == RETRIES:
                    # Raised rather than swallowed. An audit write that fails
                    # silently is the log claiming completeness it does not
                    # have, and the whole value of a hash chain is that a gap
                    # is detectable.
                    log.error(
                        "audit_write_failed",
                        tenant_id=self._tenant_id,
                        event_type=entry.event_type.value,
                    )
                    raise
                log.warning("audit_sequence_collision", tenant_id=self._tenant_id)
        raise AssertionError("unreachable")  # pragma: no cover


__all__ = ["RETRIES", "TenantAuditLog"]
