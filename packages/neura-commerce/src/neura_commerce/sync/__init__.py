"""The sync engine — a merchant's shop, mirrored locally.

Four mechanisms, each covering a failure of the one before it: a resumable
backfill, incremental polling, webhook-driven refresh of a single entity, and a
reconciliation pass that repairs the drift the other three leave behind.

Runs in the worker process. Full reasoning in
docs/architecture/commerce-integration.md §6.
"""

from neura_commerce.sync.engine import (
    MAX_ATTEMPTS,
    MAX_PAGES,
    SYNCED_TYPES,
    ReconcileOutcome,
    SyncEngine,
    SyncOutcome,
    Throttle,
)
from neura_commerce.sync.state import (
    InMemorySyncStateStore,
    SyncCheckpoint,
    SyncKey,
    SyncStateStore,
)
from neura_commerce.sync.store import (
    EntityStore,
    InMemoryEntityStore,
    StoredEntity,
    WriteResult,
    fingerprint,
)
from neura_commerce.sync.throttle import (
    DEFAULT_BURST,
    DEFAULT_RATE_PER_SECOND,
    NoLimit,
    RateLimiter,
)

__all__ = [
    "DEFAULT_BURST",
    "DEFAULT_RATE_PER_SECOND",
    "MAX_ATTEMPTS",
    "MAX_PAGES",
    "SYNCED_TYPES",
    "EntityStore",
    "InMemoryEntityStore",
    "InMemorySyncStateStore",
    "NoLimit",
    "RateLimiter",
    "ReconcileOutcome",
    "StoredEntity",
    "SyncCheckpoint",
    "SyncEngine",
    "SyncKey",
    "SyncOutcome",
    "SyncStateStore",
    "Throttle",
    "WriteResult",
    "fingerprint",
]
