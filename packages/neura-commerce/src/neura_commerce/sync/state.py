"""Where a sync got to.

A backfill of a large catalogue is a long crawl, and long things get
interrupted: a worker is redeployed, a store rate-limits us, a process is
killed. Without a checkpoint, every interruption starts the crawl again — and a
sync that never finishes is indistinguishable from one that never ran.

Two things are remembered per (tenant, platform, entity type):

* **The cursor**, so a backfill resumes mid-crawl rather than restarting.
* **The high-water mark**, so the next incremental pass asks for "changed since
  the last thing I saw" rather than "changed since I started", which would miss
  anything edited *during* the previous run.

Storage arrives with the database work; this module owns the shape and the key
derivation, so both stay in one place (as with ``identity.EntityMap``).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from neura_commerce.identity import EntityType
from neura_commerce.pagination import Cursor


@dataclass(frozen=True, slots=True)
class SyncKey:
    """One sync stream. Scoped by tenant *and* platform, like everything else.

    Two tenants sync independently, and one tenant may run two stores.
    """

    tenant_id: str
    platform: str
    entity_type: EntityType

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.tenant_id, self.platform, self.entity_type.value)


@dataclass(frozen=True, slots=True)
class SyncCheckpoint:
    """The position of one sync stream."""

    key: SyncKey

    #: Where the in-progress backfill got to. ``None`` means no crawl is running.
    cursor: Cursor | None = None

    #: The newest ``updated_at`` we have successfully stored. The next
    #: incremental pass starts here.
    updated_through: datetime | None = None

    #: When a full crawl last ran to completion. Until this is set, the local
    #: copy is partial — and a partial catalogue that looks complete is how an
    #: agent ends up confidently telling a shopper a product does not exist.
    completed_at: datetime | None = None

    #: Entities written by the last run, for the merchant-facing health view.
    last_run_count: int = 0

    @property
    def is_backfilling(self) -> bool:
        return self.cursor is not None

    @property
    def has_completed_backfill(self) -> bool:
        return self.completed_at is not None

    def advanced_to(self, cursor: Cursor | None) -> SyncCheckpoint:
        return replace(self, cursor=cursor)

    def finished(self, *, at: datetime, count: int, high_water: datetime | None) -> SyncCheckpoint:
        return replace(
            self,
            cursor=None,
            completed_at=at,
            last_run_count=count,
            # Never move the mark backwards: a page containing one old entity
            # must not rewind the whole stream and re-sync everything after it.
            updated_through=_latest(self.updated_through, high_water),
        )


def _latest(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    return max(current, candidate)


class SyncStateStore(Protocol):
    """Persistence for checkpoints. Backed by PostgreSQL later."""

    async def load(self, key: SyncKey) -> SyncCheckpoint | None: ...

    async def save(self, checkpoint: SyncCheckpoint) -> None: ...

    async def all_for_tenant(self, tenant_id: str) -> list[SyncCheckpoint]: ...


class InMemorySyncStateStore:
    """In-memory checkpoints, for tests and for a single-process worker."""

    def __init__(self) -> None:
        self._checkpoints: dict[tuple[str, str, str], SyncCheckpoint] = {}

    async def load(self, key: SyncKey) -> SyncCheckpoint | None:
        return self._checkpoints.get(key.as_tuple())

    async def save(self, checkpoint: SyncCheckpoint) -> None:
        self._checkpoints[checkpoint.key.as_tuple()] = checkpoint

    async def all_for_tenant(self, tenant_id: str) -> list[SyncCheckpoint]:
        return [c for c in self._checkpoints.values() if c.key.tenant_id == tenant_id]
