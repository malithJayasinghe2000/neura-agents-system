"""A switch per feature, per shop: FiveNeurals may switch one feature off. ADR-0065.

A **switch** is one feature of one assistant, for one shop: on or off. **No row
means on** (§1): a switch is a way to stop something, never a second place a
feature must be turned on. Only an admin changes one (R50), from the admin
dashboard; the feature's own code reads it before it spends anything.

**Keys, never agents' names**, here: an agent declares its switches in its
manifest (``grow.gaps``), the API lists them from the manifests it discovered,
and this table stores whatever key it is given. ``changed_at`` is what lets a
feature switched on again start from that moment (R52).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, String, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from neura_core.db import metadata

TENANT_SWITCHES = "tenant_switches"

tenant_switches = Table(
    TENANT_SWITCHES,
    metadata,
    Column("tenant_id", String(64), primary_key=True),
    Column("key", String(64), primary_key=True),
    Column("enabled", Boolean, nullable=False),
    Column("changed_at", DateTime(timezone=True), nullable=False),
    #: The admin's user id.
    Column("changed_by", String(64), nullable=False),
)


@dataclass(frozen=True, slots=True)
class Switch:
    key: str
    on: bool
    changed_at: datetime
    changed_by: str


class SwitchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def all(self, tenant_id: str) -> dict[str, Switch]:
        """Every switch this shop has a record for. A key not here is on."""
        rows = (
            await self._session.execute(
                select(tenant_switches).where(tenant_switches.c.tenant_id == tenant_id)
            )
        ).all()
        return {
            row.key: Switch(
                key=row.key, on=row.enabled, changed_at=row.changed_at, changed_by=row.changed_by
            )
            for row in rows
        }

    async def get(self, tenant_id: str, key: str) -> Switch | None:
        return (await self.all(tenant_id)).get(key)

    async def is_on(self, tenant_id: str, key: str) -> bool:
        found = await self.get(tenant_id, key)
        return found is None or found.on

    async def set(
        self, tenant_id: str, key: str, *, on: bool, by: str, now: datetime | None = None
    ) -> Switch | None:
        """Set a switch. ``None`` when it already was so: nothing changes."""
        current = await self.get(tenant_id, key)
        if (current is None and on) or (current is not None and current.on is on):
            return None
        when = now or datetime.now(UTC)
        values = {"enabled": on, "changed_at": when, "changed_by": by}
        await self._session.execute(
            pg_insert(tenant_switches)
            .values(tenant_id=tenant_id, key=key, **values)
            .on_conflict_do_update(index_elements=["tenant_id", "key"], set_=values)
        )
        return Switch(key=key, on=on, changed_at=when, changed_by=by)


__all__ = ["TENANT_SWITCHES", "Switch", "SwitchRepository", "tenant_switches"]
