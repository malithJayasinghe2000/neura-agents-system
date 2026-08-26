"""The PostgreSQL-backed ``EntityStore`` and ``SyncStateStore``.

The seam these fill has been open since milestone 1.8, and until now a restart
lost the whole synced catalogue. The Protocols in ``store.py`` and ``state.py``
are unchanged: this file is what they were defined *for*.

Three properties this file is responsible for, each the reason a fake would not
have proved anything:

* **Every statement runs inside a tenant-scoped transaction.** The caller passes
  an ``AsyncSession`` from ``Database.tenant_session``, so Row-Level Security
  turns a missing ``WHERE tenant_id`` into an empty result rather than a leak.
  The explicit tenant predicates are belt *and* braces — they also keep the
  planner on the primary key.
* **Every write is one ``ON CONFLICT`` statement on the natural key.** A webhook
  delivered twice, a backfill overlapping an incremental and a reconcile
  rewriting what is already there must all converge on one row.
* **A stored document is validated on the way out.** The column is ``jsonb``,
  so PostgreSQL cannot check that a row is still a valid ``Product``. Pydantic
  can, and a row that fails is raised as :class:`StoredEntityInvalidError` rather
  than skipped — schema drift that reads as "the shop has fewer products today"
  is the kind of failure nobody notices for a month.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from typing import cast as cast_typing

from pydantic import ValidationError
from sqlalchemy import Result, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from neura_commerce.identity import EntityKey, EntityType
from neura_commerce.pagination import Cursor
from neura_commerce.sync.schema import sync_checkpoints, synced_entities
from neura_commerce.sync.state import SyncCheckpoint, SyncKey
from neura_commerce.sync.store import (
    CrossTenantWriteError,
    EntityPage,
    StoredEntity,
    StoredEntityInvalidError,
    SyncStoreError,
    WriteResult,
    fingerprint,
    key_for,
    model_for,
    with_id,
)
from neura_domain import CanonicalEntity

_ENTITIES = synced_entities.c
_CHECKPOINTS = sync_checkpoints.c


class PostgresEntityStore:
    """Synced entities in PostgreSQL. One instance per tenant-scoped session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Writing ──────────────────────────────────────────────────────────────

    async def upsert(self, entities: Sequence[CanonicalEntity]) -> WriteResult:
        """Write a batch, reporting created / updated / unchanged.

        The three-way split is not cosmetic. ``unchanged`` is how a sync proves
        it is idempotent, and it is what tells the indexing step downstream that
        it can skip re-embedding text nobody edited — the difference between a
        nightly reconcile and a nightly catalogue rewrite.

        Unchanged rows are not written at all, so their ``updated_at`` does not
        move. Same reasoning as ``document_chunks.content_hash``: a row's
        timestamp should answer "when did this change", not "when did a job
        run".
        """
        result = WriteResult()
        if not entities:
            return result

        # One read of the fingerprints per (platform, type) touched, rather than
        # one per entity. A backfill page is 100 products of the same type.
        known = await self._known(entities)
        now = datetime.now(UTC)
        rows: list[dict[str, Any]] = []

        for entity in entities:
            key = key_for(entity)
            digest = fingerprint(entity)
            existing = known.get(key.as_tuple())

            if existing is None:
                result.created += 1
            elif existing.fingerprint == digest:
                result.unchanged += 1
                result.external_ids.append(entity.external_id)
                continue
            else:
                result.updated += 1

            # The recorded id wins over the adapter's freshly minted one.
            neura_id = existing.neura_id if existing else entity.neura_id
            document = entity if neura_id == entity.neura_id else with_id(entity, neura_id)

            rows.append(
                {
                    "tenant_id": key.tenant_id,
                    "platform": key.platform,
                    "entity_type": key.entity_type.value,
                    "external_id": key.external_id,
                    "neura_id": neura_id,
                    "fingerprint": digest,
                    "document": document.model_dump(mode="json"),
                    "created_at": now,
                    "updated_at": now,
                }
            )
            result.external_ids.append(entity.external_id)

        if rows:
            statement = insert(synced_entities).values(rows)
            upsert = statement.on_conflict_do_update(
                index_elements=["tenant_id", "platform", "entity_type", "external_id"],
                set_={
                    "fingerprint": statement.excluded.fingerprint,
                    "document": statement.excluded.document,
                    "updated_at": statement.excluded.updated_at,
                },
                # neura_id is deliberately absent from the SET clause. The
                # ordinary case is already handled above, in Python; this
                # covers the one that is not — two workers inserting the same
                # new entity at once, where the loser holds an id it minted
                # before the winner's row existed. Stated rather than tested:
                # the suite does not reproduce that race.
            )
            try:
                await self._session.execute(upsert)
            except DBAPIError as exc:
                raise _translate(exc) from exc

        return result

    async def delete(self, key: EntityKey) -> bool:
        result = await self._session.execute(
            delete(synced_entities).where(*_where(key)),
        )
        return _rowcount(result) > 0

    # ── Reading ──────────────────────────────────────────────────────────────

    async def get(self, key: EntityKey) -> CanonicalEntity | None:
        row = (
            await self._session.execute(select(_ENTITIES.document).where(*_where(key)))
        ).one_or_none()

        if row is None:
            return None
        return _rehydrate(key.entity_type, row.document, key)

    async def page(
        self,
        tenant_id: str,
        platform: str,
        entity_type: EntityType,
        *,
        limit: int,
        after: str | None = None,
    ) -> EntityPage:
        """A slice of one scope, in ``external_id`` order.

        Keyset pagination, not ``OFFSET``. An offset re-scans everything it
        skips, so page 400 of a large catalogue costs four hundred pages of work
        — and worse, it *shifts* when a sync inserts a row behind the cursor,
        which silently drops a product from the feed. The filter and the order
        together are a prefix of the primary key, so each page is a range scan
        that starts exactly where the last one stopped.

        ``limit + 1`` rows are read and the extra one is discarded. It answers
        "is there another page" from the same statement that produced this one;
        a separate ``COUNT`` runs at a different moment and can disagree with
        the page it is describing.
        """
        rows = (
            await self._session.execute(
                select(_ENTITIES.external_id, _ENTITIES.document)
                .where(
                    *_scope(tenant_id, platform, entity_type),
                    *([_ENTITIES.external_id > after] if after is not None else []),
                )
                .order_by(_ENTITIES.external_id)
                .limit(limit + 1)
            )
        ).all()

        window = rows[:limit]
        entities = [
            _rehydrate(
                entity_type,
                row.document,
                EntityKey(
                    tenant_id=tenant_id,
                    platform=platform,
                    entity_type=entity_type,
                    external_id=row.external_id,
                ),
            )
            for row in window
        ]
        return EntityPage(
            entities=entities,
            next_after=window[-1].external_id if len(rows) > limit and window else None,
        )

    async def external_ids(
        self, tenant_id: str, platform: str, entity_type: EntityType
    ) -> set[str]:
        rows = (
            (
                await self._session.execute(
                    select(_ENTITIES.external_id).where(*_scope(tenant_id, platform, entity_type))
                )
            )
            .scalars()
            .all()
        )
        return set(rows)

    async def count(self, tenant_id: str, platform: str, entity_type: EntityType) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(synced_entities)
            .where(*_scope(tenant_id, platform, entity_type))
        )
        return int(total or 0)

    async def fingerprints(
        self, tenant_id: str, platform: str, entity_type: EntityType
    ) -> dict[str, str]:
        rows = (
            await self._session.execute(
                select(_ENTITIES.external_id, _ENTITIES.fingerprint).where(
                    *_scope(tenant_id, platform, entity_type)
                )
            )
        ).all()
        return {row.external_id: row.fingerprint for row in rows}

    async def stored(self, key: EntityKey) -> StoredEntity | None:
        """The row *and* its bookkeeping.

        Beyond the Protocol, and it earns its place: ``get`` returns the entity,
        which cannot answer "did this write move the fingerprint" or "is the
        ``neura_id`` still the one we minted first". Both are properties the
        tests have to be able to assert directly.
        """
        row = (
            await self._session.execute(
                select(_ENTITIES.document, _ENTITIES.neura_id, _ENTITIES.fingerprint).where(
                    *_where(key)
                )
            )
        ).one_or_none()

        if row is None:
            return None
        return StoredEntity(
            key=key,
            neura_id=row.neura_id,
            fingerprint=row.fingerprint,
            entity=_rehydrate(key.entity_type, row.document, key),
        )

    # ── Internals ────────────────────────────────────────────────────────────

    async def _known(
        self, entities: Sequence[CanonicalEntity]
    ) -> dict[tuple[str, str, str, str], _Known]:
        """Fingerprint and id for everything in this batch's scopes.

        Scoped reads rather than an ``IN`` over the batch's keys: a page is one
        tenant, one platform, one entity type, so this is a primary-key range
        scan and the result is what ``upsert`` needs for every row in it.
        """
        scopes = {(e.tenant_id, e.platform, key_for(e).entity_type) for e in entities}
        found: dict[tuple[str, str, str, str], _Known] = {}

        for tenant_id, platform, entity_type in scopes:
            rows = (
                await self._session.execute(
                    select(_ENTITIES.external_id, _ENTITIES.neura_id, _ENTITIES.fingerprint).where(
                        *_scope(tenant_id, platform, entity_type)
                    )
                )
            ).all()
            for row in rows:
                key = (tenant_id, platform, entity_type.value, row.external_id)
                found[key] = _Known(neura_id=row.neura_id, fingerprint=row.fingerprint)

        return found


class PostgresSyncStateStore:
    """Sync checkpoints in PostgreSQL. One instance per tenant-scoped session.

    The checkpoint is what makes a backfill resumable, and it is written after
    every page — so this is the hottest small write in the sync path. One row
    per ``(tenant, platform, entity_type)``, upserted.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load(self, key: SyncKey) -> SyncCheckpoint | None:
        row = (
            await self._session.execute(
                select(
                    _CHECKPOINTS.cursor,
                    _CHECKPOINTS.updated_through,
                    _CHECKPOINTS.completed_at,
                    _CHECKPOINTS.last_run_count,
                ).where(
                    _CHECKPOINTS.tenant_id == key.tenant_id,
                    _CHECKPOINTS.platform == key.platform,
                    _CHECKPOINTS.entity_type == key.entity_type.value,
                )
            )
        ).one_or_none()

        if row is None:
            return None
        return _checkpoint(key, row)

    async def save(self, checkpoint: SyncCheckpoint) -> None:
        key = checkpoint.key
        now = datetime.now(UTC)

        statement = insert(sync_checkpoints).values(
            tenant_id=key.tenant_id,
            platform=key.platform,
            entity_type=key.entity_type.value,
            # None once a crawl finishes, which is how `is_backfilling` reads
            # false again after a resume.
            cursor=checkpoint.cursor.encode() if checkpoint.cursor else None,
            updated_through=checkpoint.updated_through,
            completed_at=checkpoint.completed_at,
            last_run_count=checkpoint.last_run_count,
            created_at=now,
            updated_at=now,
        )
        upsert = statement.on_conflict_do_update(
            index_elements=["tenant_id", "platform", "entity_type"],
            set_={
                "cursor": statement.excluded.cursor,
                "updated_through": statement.excluded.updated_through,
                "completed_at": statement.excluded.completed_at,
                "last_run_count": statement.excluded.last_run_count,
                "updated_at": statement.excluded.updated_at,
            },
        )

        try:
            await self._session.execute(upsert)
        except DBAPIError as exc:
            raise _translate(exc) from exc

    async def all_for_tenant(self, tenant_id: str) -> list[SyncCheckpoint]:
        rows = (
            await self._session.execute(
                select(
                    _CHECKPOINTS.platform,
                    _CHECKPOINTS.entity_type,
                    _CHECKPOINTS.cursor,
                    _CHECKPOINTS.updated_through,
                    _CHECKPOINTS.completed_at,
                    _CHECKPOINTS.last_run_count,
                )
                .where(_CHECKPOINTS.tenant_id == tenant_id)
                .order_by(_CHECKPOINTS.platform, _CHECKPOINTS.entity_type)
            )
        ).all()

        return [
            _checkpoint(
                SyncKey(tenant_id, row.platform, EntityType(row.entity_type)),
                row,
            )
            for row in rows
        ]


class DatabaseEntityStore:
    """An :class:`EntityStore` that opens its own short transaction per call.

    ``PostgresEntityStore`` needs a live session, which is right for a backfill:
    one transaction, thousands of rows. It is wrong for the worker's long-lived
    :class:`~neura_commerce.sync.engine.SyncEngine`, which holds a store for the
    lifetime of the process and makes calls minutes apart across HTTP waits —
    holding a pooled connection open across a merchant's slow API is how a
    handful of tenants exhaust the pool while the fix looks like "make the pool
    bigger".

    Same shape, and the same reasoning, as ``rag.postgres.DatabaseVectorStore``.
    """

    def __init__(self, db: Any, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def upsert(self, entities: Sequence[CanonicalEntity]) -> WriteResult:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresEntityStore(session).upsert(entities)

    async def delete(self, key: EntityKey) -> bool:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresEntityStore(session).delete(key)

    async def get(self, key: EntityKey) -> CanonicalEntity | None:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresEntityStore(session).get(key)

    async def page(
        self,
        tenant_id: str,
        platform: str,
        entity_type: EntityType,
        *,
        limit: int,
        after: str | None = None,
    ) -> EntityPage:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresEntityStore(session).page(
                tenant_id, platform, entity_type, limit=limit, after=after
            )

    async def external_ids(
        self, tenant_id: str, platform: str, entity_type: EntityType
    ) -> set[str]:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresEntityStore(session).external_ids(tenant_id, platform, entity_type)

    async def count(self, tenant_id: str, platform: str, entity_type: EntityType) -> int:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresEntityStore(session).count(tenant_id, platform, entity_type)

    async def fingerprints(
        self, tenant_id: str, platform: str, entity_type: EntityType
    ) -> dict[str, str]:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresEntityStore(session).fingerprints(tenant_id, platform, entity_type)

    async def stored(self, key: EntityKey) -> StoredEntity | None:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresEntityStore(session).stored(key)


class DatabaseSyncStateStore:
    """A :class:`SyncStateStore` that opens its own transaction per call.

    Same argument as :class:`DatabaseEntityStore`, and it matters more here: the
    checkpoint is saved after every page, interleaved with HTTP calls to the
    merchant's shop.
    """

    def __init__(self, db: Any, tenant_id: str) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def load(self, key: SyncKey) -> SyncCheckpoint | None:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresSyncStateStore(session).load(key)

    async def save(self, checkpoint: SyncCheckpoint) -> None:
        async with self._db.tenant_session(self._tenant_id) as session:
            await PostgresSyncStateStore(session).save(checkpoint)

    async def all_for_tenant(self, tenant_id: str) -> list[SyncCheckpoint]:
        async with self._db.tenant_session(self._tenant_id) as session:
            return await PostgresSyncStateStore(session).all_for_tenant(tenant_id)


# ── Helpers ──────────────────────────────────────────────────────────────────


class _Known:
    """What we already hold for one key: enough to decide the write, no more."""

    __slots__ = ("fingerprint", "neura_id")

    def __init__(self, *, neura_id: str, fingerprint: str) -> None:
        self.neura_id = neura_id
        self.fingerprint = fingerprint


def _where(key: EntityKey) -> tuple[Any, ...]:
    return (
        _ENTITIES.tenant_id == key.tenant_id,
        _ENTITIES.platform == key.platform,
        _ENTITIES.entity_type == key.entity_type.value,
        _ENTITIES.external_id == key.external_id,
    )


def _scope(tenant_id: str, platform: str, entity_type: EntityType) -> tuple[Any, ...]:
    return (
        _ENTITIES.tenant_id == tenant_id,
        _ENTITIES.platform == platform,
        _ENTITIES.entity_type == entity_type.value,
    )


def _checkpoint(key: SyncKey, row: Any) -> SyncCheckpoint:
    return SyncCheckpoint(
        key=key,
        cursor=Cursor.decode(row.cursor) if row.cursor else None,
        updated_through=row.updated_through,
        completed_at=row.completed_at,
        last_run_count=row.last_run_count,
    )


def _rehydrate(entity_type: EntityType, document: Any, key: EntityKey) -> CanonicalEntity:
    """A stored document, back to the canonical model that defines it.

    ADR-0021 puts validation here rather than in the column type. A row that
    fails is an error and not a skipped entity — a store that quietly drops rows
    it cannot parse reports a shrinking catalogue, and "the agent stopped
    knowing about twelve products" is a bug found by a shopper.
    """
    try:
        return model_for(entity_type).model_validate(document)
    except ValidationError as exc:
        raise StoredEntityInvalidError(
            f"the stored {entity_type.value} {key.external_id!r} does not validate "
            "against its canonical model — either neura-domain changed without a "
            "backfill, or this row was not written by the sync engine",
            details={"key": list(key.as_tuple()), "errors": exc.error_count()},
        ) from exc


def _rowcount(result: Result[Any]) -> int:
    """How many rows a DELETE touched.

    ``Result`` is the declared return type of ``session.execute``; only the
    ``CursorResult`` it actually is carries ``rowcount``.
    """
    return int(cast_typing(CursorResult[Any], result).rowcount or 0)


def _translate(exc: DBAPIError) -> SyncStoreError:
    detail = str(getattr(exc, "orig", exc)).lower()
    if "row-level security" in detail or "row level security" in detail:
        return CrossTenantWriteError(
            "the database refused a sync write — this transaction is scoped to a "
            "different tenant than the entity being written. Row-Level Security "
            "worked; something upstream resolved the tenant inconsistently."
        )
    return SyncStoreError(f"sync store write failed: {exc}")
