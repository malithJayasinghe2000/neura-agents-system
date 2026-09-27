"""Writing and deleting observed events, for one tenant.

There is **no read of an event's content here**, on purpose. Phase 1 shows
nothing (ADR-0044 §9), so nothing needs to select a session id; the only reads
are *"is there anything left?"* and a count for the operator. The first method
that returns rows arrives with ADR-0046 stage 1, which is where displaying
begins.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.observation.models import ObservedEvent
from neura_core.observation.schema import observed_events


class ObservedEventRepository:
    """The session is already tenant-scoped; RLS does the filtering."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, tenant_id: str, event: ObservedEvent) -> bool:
        """Store one event. Returns ``False`` if this event id was already stored.

        ``ON CONFLICT DO NOTHING`` because delivery is at least once: a retry of
        a delivery whose response was lost is the same page view, not a second.
        """
        result = await self._session.execute(
            pg_insert(observed_events)
            .values(
                tenant_id=tenant_id,
                event_id=event.event_id,
                session_id=event.session_id,
                event_type=event.type.value,
                product_id=event.product_id,
                occurred_at=event.occurred_at,
                in_stock=event.in_stock,
            )
            .on_conflict_do_nothing(
                index_elements=[observed_events.c.tenant_id, observed_events.c.event_id]
            )
        )
        return bool(cast("CursorResult[Any]", result).rowcount)

    async def delete_older_than(self, tenant_id: str, cutoff: datetime) -> int:
        """The retention sweep. Returns how many rows went."""
        result = await self._session.execute(
            delete(observed_events)
            .where(observed_events.c.tenant_id == tenant_id)
            .where(observed_events.c.occurred_at < cutoff)
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def delete_all(self, tenant_id: str) -> int:
        """Everything this tenant holds — the agreement was withdrawn.

        ADR-0042 §3's *removal on resolution*: without an agreement there is no
        reason to hold the rows, so they go rather than wait out the period.
        """
        result = await self._session.execute(
            delete(observed_events).where(observed_events.c.tenant_id == tenant_id)
        )
        return int(cast("CursorResult[Any]", result).rowcount or 0)

    async def any_for(self, tenant_id: str) -> bool:
        """Is anything left for a future sweep to delete?"""
        return bool(
            await self._session.scalar(
                select(exists().where(observed_events.c.tenant_id == tenant_id))
            )
        )

    async def count_for(self, tenant_id: str) -> int:
        """How many rows are held. For the operator, never for a screen."""
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(observed_events)
                .where(observed_events.c.tenant_id == tenant_id)
            )
            or 0
        )


__all__ = ["ObservedEventRepository"]
