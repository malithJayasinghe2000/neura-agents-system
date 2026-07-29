"""The audit log — append-only and hash-chained.

Every LLM call, every tool decision (**allowed and rejected alike**), every
escalation and every configuration change, with the tenant, conversation, trace,
actor and outcome (security-model.md §9.1).

**Why the chain.** An audit log that can be edited afterwards is not evidence of
anything. Each entry's hash covers its own content *and* the previous entry's
hash, so removing or altering any row breaks verification of every row after it.
That does not make tampering impossible — it makes it detectable, which is the
achievable property and the one an auditor asks about.

**Why rejections matter most.** The injection suite asserts on what the policy
engine *refused*, not on whether a reply sounded like a refusal — a model can
apologise politely while the tool ran anyway. Without the rejections recorded
here, "injection resistance 1.00" would be a claim about text, and the one
release-blocking gate in the project would be measuring the wrong thing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from neura_agent_core.graph.schema import audit_log
from neura_core import get_logger, new_id

log = get_logger(__name__)

#: The first entry's predecessor. A fixed, obviously-synthetic value so the
#: start of a chain is unambiguous rather than an empty string that could also
#: mean "somebody deleted row one".
GENESIS_HASH = "0" * 64


class AuditEvent(StrEnum):
    TOOL_DECISION = "tool.decision"
    TOOL_EXECUTED = "tool.executed"
    LLM_CALL = "llm.call"
    RETRIEVAL = "retrieval"
    ESCALATION = "escalation"
    GUARD_BLOCK = "guard.block"
    CONFIG_CHANGE = "config.change"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One recorded fact. Immutable by construction."""

    tenant_id: str
    event_type: AuditEvent
    actor: str
    outcome: str
    conversation_id: str | None = None
    trace_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def digest(self, *, sequence: int, previous_hash: str, recorded_at: datetime) -> str:
        """This entry's link in the chain.

        Every field that matters is inside the hash, including the sequence
        number and the timestamp — otherwise entries could be reordered, or a
        row swapped for another with the same content, without detection.

        ``sort_keys`` is not cosmetic: without it the same payload hashes
        differently between processes and verification fails for no reason.
        """
        material = json.dumps(
            {
                "sequence": sequence,
                "previous_hash": previous_hash,
                "tenant_id": self.tenant_id,
                "conversation_id": self.conversation_id,
                "trace_id": self.trace_id,
                "event_type": self.event_type.value,
                "actor": self.actor,
                "outcome": self.outcome,
                "payload": self.payload,
                "recorded_at": recorded_at.isoformat(),
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(material.encode()).hexdigest()


class AuditSink(Protocol):
    """Where audit entries go. A Protocol so the graph can be tested without a
    database, and so a deployment can add a second sink later without the
    callers changing."""

    async def record(self, entry: AuditEntry) -> str: ...


class PostgresAuditLog:
    """The durable audit log. One instance per tenant-scoped session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, entry: AuditEntry) -> str:
        """Append one entry and return its hash.

        Runs inside the caller's transaction on purpose. A tool decision and its
        audit record commit together or not at all — an action that happened
        without a record is exactly what the log exists to make impossible.
        """
        sequence, previous_hash = await self._tip(entry.tenant_id)
        recorded_at = datetime.now(UTC)
        entry_hash = entry.digest(
            sequence=sequence, previous_hash=previous_hash, recorded_at=recorded_at
        )

        await self._session.execute(
            insert(audit_log).values(
                id=new_id("aud"),
                tenant_id=entry.tenant_id,
                conversation_id=entry.conversation_id,
                trace_id=entry.trace_id,
                sequence=sequence,
                event_type=entry.event_type.value,
                actor=entry.actor,
                outcome=entry.outcome,
                payload=entry.payload,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
                recorded_at=recorded_at,
            )
        )
        return entry_hash

    async def verify(self, tenant_id: str) -> tuple[bool, str | None]:
        """Re-walk the chain. Returns ``(intact, first_broken_entry_id)``.

        The point of the whole design: this is the query that answers "has
        anything been altered or removed?" — and it must be runnable on demand,
        by an auditor, without trusting the application that wrote the rows.
        """
        rows = (
            await self._session.execute(
                select(audit_log)
                .where(audit_log.c.tenant_id == tenant_id)
                .order_by(audit_log.c.sequence)
            )
        ).all()

        expected_previous = GENESIS_HASH
        expected_sequence = 1

        for row in rows:
            if row.sequence != expected_sequence or row.previous_hash != expected_previous:
                return False, row.id

            entry = AuditEntry(
                tenant_id=row.tenant_id,
                event_type=AuditEvent(row.event_type),
                actor=row.actor,
                outcome=row.outcome,
                conversation_id=row.conversation_id,
                trace_id=row.trace_id,
                payload=dict(row.payload or {}),
            )
            recomputed = entry.digest(
                sequence=row.sequence,
                previous_hash=row.previous_hash,
                recorded_at=row.recorded_at,
            )
            if recomputed != row.entry_hash:
                return False, row.id

            expected_previous = row.entry_hash
            expected_sequence += 1

        return True, None

    async def _tip(self, tenant_id: str) -> tuple[int, str]:
        """The next sequence number and the hash it must chain from."""
        row = (
            await self._session.execute(
                select(audit_log.c.sequence, audit_log.c.entry_hash)
                .where(audit_log.c.tenant_id == tenant_id)
                .order_by(audit_log.c.sequence.desc())
                .limit(1)
            )
        ).first()

        if row is None:
            return 1, GENESIS_HASH
        return row.sequence + 1, row.entry_hash

    async def count(self, tenant_id: str) -> int:
        total = await self._session.scalar(
            select(func.count()).select_from(audit_log).where(audit_log.c.tenant_id == tenant_id)
        )
        return int(total or 0)


class InMemoryAuditLog:
    """Correct, not durable. Lets the graph be exercised without a database."""

    def __init__(self) -> None:
        self.entries: list[tuple[AuditEntry, int, str]] = []
        self._tips: dict[str, tuple[int, str]] = {}

    async def record(self, entry: AuditEntry) -> str:
        sequence, previous_hash = self._tips.get(entry.tenant_id, (1, GENESIS_HASH))
        entry_hash = entry.digest(
            sequence=sequence, previous_hash=previous_hash, recorded_at=datetime.now(UTC)
        )
        self.entries.append((entry, sequence, entry_hash))
        self._tips[entry.tenant_id] = (sequence + 1, entry_hash)
        return entry_hash

    def for_tenant(self, tenant_id: str) -> list[AuditEntry]:
        return [e for e, _, _ in self.entries if e.tenant_id == tenant_id]
