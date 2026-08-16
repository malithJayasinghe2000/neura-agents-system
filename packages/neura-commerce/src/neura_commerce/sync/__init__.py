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
from neura_commerce.sync.postgres import (
    DatabaseEntityStore,
    DatabaseSyncStateStore,
    PostgresEntityStore,
    PostgresSyncStateStore,
)
from neura_commerce.sync.schema import sync_checkpoints, synced_entities
from neura_commerce.sync.state import (
    InMemorySyncStateStore,
    SyncCheckpoint,
    SyncKey,
    SyncStateStore,
)
from neura_commerce.sync.store import (
    CrossTenantWriteError,
    EntityStore,
    InMemoryEntityStore,
    StoredEntity,
    StoredEntityInvalidError,
    SyncStoreError,
    WriteResult,
    fingerprint,
    key_for,
    model_for,
    with_id,
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
    "CrossTenantWriteError",
    "DatabaseEntityStore",
    "DatabaseSyncStateStore",
    "EntityStore",
    "InMemoryEntityStore",
    "InMemorySyncStateStore",
    "NoLimit",
    "PostgresEntityStore",
    "PostgresSyncStateStore",
    "RateLimiter",
    "ReconcileOutcome",
    "StoredEntity",
    "StoredEntityInvalidError",
    "SyncCheckpoint",
    "SyncEngine",
    "SyncKey",
    "SyncOutcome",
    "SyncStateStore",
    "SyncStoreError",
    "Throttle",
    "WriteResult",
    "fingerprint",
    "key_for",
    "model_for",
    "sync_checkpoints",
    "synced_entities",
    "with_id",
]
