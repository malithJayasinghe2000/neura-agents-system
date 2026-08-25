"""The ``sync.store`` handler — the first thing the scheduler exists to run.

A sync is the case that made open question **P7** unavoidable rather than
merely awkward. The synced catalogue became durable on 2026-08-16
([ADR-0021](../../../../../docs/architecture/adr/0021-synced-entities-are-documents.md)),
and nothing scheduled one, because a worker could not ask whose catalogue was
due. The webhook answer did not generalise and the CORS answer went around the
question; a sync has no request and no credential to go around it *with*.

**Everything this handler needs, it reads from the tenant's own row.** It is
given a tenant id and a payload, and from those it opens a scoped session,
decrypts that merchant's store credentials, builds an adapter through the
registry — never by importing one — and crawls. Nothing about the tenant is
configured in this process.
"""

from __future__ import annotations

from typing import Any

from neura_api.jobs.runner import JobContext
from neura_api.stores import StoreDirectory
from neura_commerce import EntityType
from neura_commerce.sync import (
    SYNCED_TYPES,
    DatabaseEntityStore,
    DatabaseSyncStateStore,
    RateLimiter,
    SyncEngine,
    SyncOutcome,
)
from neura_core import ValidationError, get_logger
from neura_core.jobs import JobQueue

log = get_logger(__name__)

#: The job kind. One string, in one place, because it is written by whatever
#: schedules the sync and read by the registry that dispatches it.
SYNC_STORE = "sync.store"

#: A shop we do not know is a shop we assume is small. This is the setting that
#: decides whether a backfill is polite or a denial of service against a
#: merchant's production server, so it is stated here rather than defaulted.
SYNC_RATE_PER_SECOND = 10.0
SYNC_BURST = 10
SYNC_PAGE_SIZE = 50


def dedupe_key_for(store_id: str | None) -> str:
    """One live sync per store, not one per time somebody asked for it.

    A sync enqueued three times while the first is still pending is one sync —
    which is the behaviour a merchant expects and the behaviour that stops a
    webhook storm from queueing a thousand crawls of the same catalogue.
    """
    return store_id or "default"


async def enqueue_sync(
    session: Any,
    tenant_id: str,
    *,
    store_id: str | None = None,
    incremental: bool = True,
) -> Any:
    """Queue a sync for one tenant, inside the caller's transaction.

    Takes a session rather than a ``Database`` deliberately: the point of a
    durable queue over an out-of-band index is that the job row commits with
    whatever decided the sync was needed. A helper that opened its own
    transaction would give that away at the first call site.
    """
    return await JobQueue(session).enqueue(
        tenant_id,
        SYNC_STORE,
        payload={"store_id": store_id, "incremental": incremental},
        dedupe_key=dedupe_key_for(store_id),
    )


class SyncStoreHandler:
    """Runs one ``sync.store`` job.

    Holds the :class:`StoreDirectory` so its capability cache is shared with the
    rest of the process — asking a merchant's ``/health`` once per sync rather
    than once per entity type.
    """

    def __init__(self, stores: StoreDirectory) -> None:
        self._stores = stores

    async def __call__(self, context: JobContext) -> str:
        payload = context.job.payload
        store_id = payload.get("store_id")
        if store_id is not None and not isinstance(store_id, str):
            # The column is `jsonb`, so PostgreSQL cannot check this — the same
            # accepted cost ADR-0021 states for a stored document, and the same
            # answer: the reader validates, and a bad value is an error rather
            # than a silently ignored field.
            raise ValidationError(
                "sync.store payload: store_id must be a string or absent.",
                details={"job_id": context.job.id},
            )
        incremental = bool(payload.get("incremental", True))
        types = _entity_types(payload)

        connection = await self._stores.connect(context.tenant_id, store_id=store_id)
        try:
            engine = SyncEngine(
                connection.adapter,
                tenant_id=context.tenant_id,
                entities=DatabaseEntityStore(context.db, context.tenant_id),
                state=DatabaseSyncStateStore(context.db, context.tenant_id),
                throttle=RateLimiter(rate_per_second=SYNC_RATE_PER_SECOND, burst=SYNC_BURST),
                page_size=SYNC_PAGE_SIZE,
            )
            outcomes = [await _run_one(engine, entity_type, incremental) for entity_type in types]
        finally:
            # The adapter holds an HTTP client. One built per job and abandoned
            # leaks a connection pool per sync.
            await _close(connection.adapter)

        failed = [outcome for outcome in outcomes if outcome.error is not None]
        if failed:
            # Raised, not logged and swallowed: a partially failed sync must be
            # retried, and the queue is what decides whether this is attempt two
            # or a dead letter. Reporting success here would leave a catalogue
            # half-crawled and a job row saying it was done.
            raise SyncJobFailedError(
                "; ".join(f"{o.entity_type.value}: {o.error}" for o in failed),
            )

        return " · ".join(outcome.summary() for outcome in outcomes)


class SyncJobFailedError(Exception):
    """At least one entity type did not finish. The checkpoint survives, so the
    retry resumes rather than restarting."""


async def _run_one(engine: SyncEngine, entity_type: EntityType, incremental: bool) -> SyncOutcome:
    return (
        await engine.incremental(entity_type) if incremental else await engine.backfill(entity_type)
    )


def _entity_types(payload: dict[str, Any]) -> tuple[EntityType, ...]:
    """Which types this job covers. Absent means all of them.

    A named list is rejected rather than filtered if it contains a type that is
    not synced at all — orders and customers are read live through the adapter
    (commerce-integration.md §6.1), and a job that quietly synced nothing because
    every type it named was unsyncable would report success.
    """
    named = payload.get("entity_types")
    if named is None:
        return SYNCED_TYPES
    if not isinstance(named, list) or not named:
        raise ValidationError("sync.store payload: entity_types must be a non-empty list.")

    try:
        requested = tuple(EntityType(value) for value in named)
    except ValueError as exc:
        raise ValidationError(f"sync.store payload: {exc}") from exc

    unsyncable = [t.value for t in requested if t not in SYNCED_TYPES]
    if unsyncable:
        raise ValidationError(
            "sync.store payload: these entity types are read live and never "
            "synced — see commerce-integration.md §6.1.",
            details={"entity_types": unsyncable},
        )
    return requested


async def _close(adapter: object) -> None:
    closer = getattr(adapter, "aclose", None)
    if closer is not None:
        await closer()


__all__ = [
    "SYNC_BURST",
    "SYNC_PAGE_SIZE",
    "SYNC_RATE_PER_SECOND",
    "SYNC_STORE",
    "SyncJobFailedError",
    "SyncStoreHandler",
    "dedupe_key_for",
    "enqueue_sync",
]
