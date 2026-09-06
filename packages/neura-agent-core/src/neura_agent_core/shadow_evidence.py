"""Where a turn's captured evidence is kept — [ADR-0034] §3, §4.

One row per shadowed turn, holding the bundle
:mod:`neura_agent_core.evidence` recorded while that turn ran.

## Why this is not in the audit log

The audit log is append-only and hash-chained because it is evidence *about* the
system, for somebody asking later whether it behaved. **This is evidence *for*
the system** — the material a graded turn needs to be run again — and it holds a
merchant's catalogue rather than a record of our own conduct.

Two consequences follow, and both are the reason for a separate table:

* **It must be deletable.** A shadow turn is kept under the merchant's retention
  policy, and this dies with it. In a hash chain a lawful deletion is
  indistinguishable from tampering, which would make the chain's one useful
  property useless.
* **It is not a security control.** Nothing gates on it, nothing reads it during
  a turn, and losing a row costs one unpromotable turn rather than an
  unanswerable audit question.

## Immutable, and content-addressed

Insert-only — **and the database enforces it, not this file.** The app role has
no ``UPDATE`` privilege on this table (migration `5b7e2c1904af`), so an immutable
row is one PostgreSQL will not let anybody change rather than one no method
happens to change. ``record`` also refuses a second bundle for a turn that
already has one, which is the friendlier of the two failures and not the one
that is load-bearing. The bundle's ``content_hash`` is stored beside
it so the exported fixture and the row can be tied together, and so two turns
that genuinely saw the same shop are recognisable as such.

## Tenant-scoped, and store-scoped inside that

``tenant_id`` carries the RLS policy every other tenant table has. ``store_id``
is a column rather than an afterthought because the data model has always
permitted several stores per tenant, and two stores may use the same
``external_id`` for different products — an evidence row that could not say which
store it came from would be a quiet way to replay the wrong catalogue.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from neura_agent_core.evidence import EvidenceBundle, EvidenceError
from neura_core import get_logger, metadata

log = get_logger(__name__)

SHADOW_EVIDENCE = "shadow_evidence"

#: One captured boundary. The primary key is ``(tenant_id, shadow_turn_id)``
#: rather than the content hash: a turn has exactly one bundle, and making the
#: hash the key would silently merge two turns that happened to see an identical
#: shop into one row that neither could then be traced from.
shadow_evidence = Table(
    SHADOW_EVIDENCE,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("shadow_turn_id", String(64), primary_key=True),
    #: Which store's boundary. Never exported — see `evidence.export_fixture`.
    Column("store_id", String(64), nullable=False),
    #: The artefact's identity. Not unique: two turns may legitimately capture
    #: the same shop, and they then share one exported fixture file.
    Column("content_hash", String(64), nullable=False),
    Column("bundle", JSONB, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Promotion looks a turn up by id; nothing scans this table.
    Index("ix_shadow_evidence_hash", "tenant_id", "content_hash"),
    # This table exists only to make one shadow turn reproducible, so it lives
    # and dies with that turn. `ON DELETE CASCADE` rather than a retention sweep
    # that has to remember a second table — remembering is what retention sweeps
    # stop doing (open question S10).
    #
    # Composite because `shadow_turns` is keyed `(tenant_id, id)`: a
    # single-column reference could not be declared, and would otherwise let one
    # tenant's evidence hang off another tenant's turn.
    ForeignKeyConstraint(
        ["tenant_id", "shadow_turn_id"],
        ["shadow_turns.tenant_id", "shadow_turns.id"],
        name="fk_shadow_evidence_turn",
        ondelete="CASCADE",
    ),
)


class ShadowEvidenceRepository:
    """Captured evidence, for one tenant. The session is already tenant-scoped."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, tenant_id: str, shadow_turn_id: str, bundle: EvidenceBundle) -> str:
        """Write one turn's evidence. Returns its content hash.

        Called inside the shadow turn's own transaction ([ADR-0034] §3), so
        *"withheld from the shopper"*, *"recorded for a human"* and
        *"reproducible later"* commit together or not at all. A turn whose
        evidence was written afterwards is a turn that is sometimes promotable
        and sometimes not, for reasons nobody can see.
        """
        if await self.get(tenant_id, shadow_turn_id) is not None:
            # §4. Evidence is immutable; a second capture for one turn means a
            # caller is re-recording, and silently replacing the first would
            # change what an already-promoted case replays.
            raise EvidenceError(
                f"evidence already recorded for turn {shadow_turn_id!r}; it is immutable"
            )

        content_hash = bundle.content_hash()
        await self._session.execute(
            shadow_evidence.insert().values(
                tenant_id=tenant_id,
                shadow_turn_id=shadow_turn_id,
                store_id=bundle.store_id,
                content_hash=content_hash,
                bundle=bundle.model_dump(mode="json"),
                captured_at=bundle.captured_at,
            )
        )
        return content_hash

    async def get(self, tenant_id: str, shadow_turn_id: str) -> EvidenceBundle | None:
        """One turn's evidence, or ``None`` when it was never captured.

        ``None`` is the ordinary answer for any turn that ran before capture
        existed, and promotion turns it into a refusal rather than reconstructing
        anything ([ADR-0034] §1).
        """
        row = (
            await self._session.execute(
                select(shadow_evidence)
                .where(shadow_evidence.c.tenant_id == tenant_id)
                .where(shadow_evidence.c.shadow_turn_id == shadow_turn_id)
            )
        ).one_or_none()
        return None if row is None else _bundle(row.bundle)


def _bundle(payload: dict[str, Any]) -> EvidenceBundle | None:
    """A stored bundle, or ``None`` if this row cannot be replayed.

    A schema the current code does not understand is logged and refused rather
    than coerced: a bundle half-read is a replay that answers confidently with
    the wrong thing, which §6 exists to prevent.
    """
    try:
        return EvidenceBundle.model_validate(payload)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("evidence_unreadable", error=str(exc))
        return None


__all__ = [
    "SHADOW_EVIDENCE",
    "ShadowEvidenceRepository",
    "shadow_evidence",
]
