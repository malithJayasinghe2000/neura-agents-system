"""Where synced entities are kept.

The seam between the sync engine and the database. Defined as a Protocol so the
engine can be built, tested and reasoned about before the schema exists — and so
the PostgreSQL implementation, when it lands, has a contract to satisfy rather
than a shape to invent.

Two decisions are encoded here rather than left to each caller:

* **Every write is an upsert** keyed on (tenant, platform, entity type, external
  id). Webhooks are delivered twice, backfills overlap incrementals, and a
  reconcile re-writes what is already there. A store that could produce
  duplicates would produce them within a day.
* **Every entity carries a fingerprint** of its content. Reconciliation needs to
  answer "is what I hold still what the shop has?" without re-reading every
  field of every row, and an `updated_at` cannot answer it — some platforms
  don't touch the timestamp on every edit.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from neura_commerce.identity import EntityKey, EntityType
from neura_domain import CanonicalEntity

#: Excluded from the fingerprint. These change on every read without the shop
#: having changed anything, and including them would make every reconcile
#: report drift that is not there.
_VOLATILE_FIELDS = frozenset({"neura_id", "tenant_id", "platform", "synced_at", "raw"})


def fingerprint(entity: CanonicalEntity) -> str:
    """A stable content hash.

    Deliberately over the canonical fields only. ``raw`` is excluded because a
    platform may reorder or enrich its own payload without the meaning changing,
    and re-embedding a whole catalogue because a shop upgraded its software is
    an expensive way to achieve nothing.
    """
    payload = entity.model_dump(mode="json", exclude=set(_VOLATILE_FIELDS))
    encoded = repr(sorted(payload.items())).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class StoredEntity:
    key: EntityKey
    neura_id: str
    fingerprint: str
    entity: CanonicalEntity


@dataclass(slots=True)
class WriteResult:
    """What a batch of writes actually changed.

    ``unchanged`` is not noise: it is how a sync proves it is idempotent, and how
    the indexing step downstream knows it can skip re-embedding text nobody
    edited.
    """

    created: int = 0
    updated: int = 0
    unchanged: int = 0
    external_ids: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        return self.created + self.updated

    @property
    def seen(self) -> int:
        return self.created + self.updated + self.unchanged

    def merge(self, other: WriteResult) -> None:
        self.created += other.created
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.external_ids.extend(other.external_ids)


class EntityStore(Protocol):
    """Persistence for synced entities."""

    async def upsert(self, entities: Sequence[CanonicalEntity]) -> WriteResult: ...

    async def delete(self, key: EntityKey) -> bool: ...

    async def get(self, key: EntityKey) -> CanonicalEntity | None: ...

    async def external_ids(
        self, tenant_id: str, platform: str, entity_type: EntityType
    ) -> set[str]: ...

    async def count(self, tenant_id: str, platform: str, entity_type: EntityType) -> int: ...

    async def fingerprints(
        self, tenant_id: str, platform: str, entity_type: EntityType
    ) -> dict[str, str]: ...


class InMemoryEntityStore:
    """In-memory implementation. Correct, not durable.

    Used by tests and by the smoke run against a real shop. The PostgreSQL
    implementation replaces this class and nothing else — which is the point of
    the Protocol above.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, str], StoredEntity] = {}

    async def upsert(self, entities: Sequence[CanonicalEntity]) -> WriteResult:
        result = WriteResult()

        for entity in entities:
            key = _key_for(entity)
            digest = fingerprint(entity)
            existing = self._rows.get(key.as_tuple())

            if existing is None:
                result.created += 1
            elif existing.fingerprint == digest:
                # Same content. Recorded as seen, but not as a write: the
                # difference is what stops a nightly reconcile from looking like
                # a nightly catalogue rewrite.
                result.unchanged += 1
                result.external_ids.append(entity.external_id)
                continue
            else:
                result.updated += 1

            self._rows[key.as_tuple()] = StoredEntity(
                key=key, neura_id=entity.neura_id, fingerprint=digest, entity=entity
            )
            result.external_ids.append(entity.external_id)

        return result

    async def delete(self, key: EntityKey) -> bool:
        return self._rows.pop(key.as_tuple(), None) is not None

    async def get(self, key: EntityKey) -> CanonicalEntity | None:
        row = self._rows.get(key.as_tuple())
        return row.entity if row else None

    async def external_ids(
        self, tenant_id: str, platform: str, entity_type: EntityType
    ) -> set[str]:
        return {row.key.external_id for row in self._scoped(tenant_id, platform, entity_type)}

    async def count(self, tenant_id: str, platform: str, entity_type: EntityType) -> int:
        return len(self._scoped(tenant_id, platform, entity_type))

    async def fingerprints(
        self, tenant_id: str, platform: str, entity_type: EntityType
    ) -> dict[str, str]:
        return {
            row.key.external_id: row.fingerprint
            for row in self._scoped(tenant_id, platform, entity_type)
        }

    def _scoped(self, tenant_id: str, platform: str, entity_type: EntityType) -> list[StoredEntity]:
        return [
            row
            for row in self._rows.values()
            if row.key.tenant_id == tenant_id
            and row.key.platform == platform
            and row.key.entity_type is entity_type
        ]


def _key_for(entity: CanonicalEntity) -> EntityKey:
    return EntityKey(
        tenant_id=entity.tenant_id,
        platform=entity.platform,
        entity_type=_ENTITY_TYPES[type(entity).__name__],
        external_id=entity.external_id,
    )


_ENTITY_TYPES = {
    "Product": EntityType.PRODUCT,
    "Category": EntityType.CATEGORY,
    "Customer": EntityType.CUSTOMER,
    "Order": EntityType.ORDER,
    "Policy": EntityType.POLICY,
}
