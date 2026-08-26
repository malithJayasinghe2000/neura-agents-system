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
* **The stored `neura_id` survives a content change.** An adapter mints a fresh
  one on every fetch, so writing the incoming id would give a product a new
  permanent identity each time a merchant edits its title — which is the exact
  opposite of what `identity.py` exists for. Both implementations keep the id
  they first recorded.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from neura_commerce.identity import EntityKey, EntityType
from neura_core import NeuraError
from neura_domain import CanonicalEntity, Category, Customer, Order, Policy, Product


class SyncStoreError(NeuraError):
    """Something went wrong persisting a sync.

    Declared beside the Protocol rather than beside the PostgreSQL
    implementation, so a caller can handle these without importing a storage
    backend it otherwise never names.
    """

    code = "SYNC_STORE_ERROR"


class CrossTenantWriteError(SyncStoreError):
    """A write was refused because it belongs to another tenant.

    Row-Level Security doing its job, not a bug in it. Named because it is a
    security event: something upstream resolved the tenant one way and built an
    entity another way, and that deserves an alert rather than a driver stack
    trace.
    """

    code = "SYNC_CROSS_TENANT_WRITE"


class StoredEntityInvalidError(SyncStoreError):
    """A stored document no longer validates against its canonical model.

    The stated cost of storing entities as documents (ADR-0021), surfaced rather
    than swallowed. Either ``neura-domain`` gained a required field without a
    backfill, or the row was written by something that is not the sync engine.
    """

    code = "SYNC_STORED_ENTITY_INVALID"


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
class EntityPage:
    """A slice of one scope, in ``external_id`` order.

    Added for the product feed, the first caller that needs to read *back* what
    was synced rather than reconcile it. Everything before it wanted keys, counts
    or fingerprints; a feed wants the documents themselves.

    **Still within ADR-0021.** The filter is ``(tenant_id, platform,
    entity_type)`` and the order is ``external_id`` — together a prefix of the
    natural primary key, so this is a range scan rather than a query over an
    entity's *contents*. The day something wants "products under 50" that is
    still a superseding ADR and still not a column.

    Ordered by ``external_id`` rather than ``updated_at`` deliberately: a cursor
    over a column a sync mutates skips or repeats rows when a write lands
    mid-page, and a feed that silently omits products is the failure hardest to
    notice — nothing errors, the catalogue is just smaller than the shop.
    """

    entities: list[CanonicalEntity] = field(default_factory=list)
    #: The ``external_id`` to resume after. ``None`` means this was the last page.
    next_after: str | None = None


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

    async def page(
        self,
        tenant_id: str,
        platform: str,
        entity_type: EntityType,
        *,
        limit: int,
        after: str | None = None,
    ) -> EntityPage: ...


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
            key = key_for(entity)
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

            # The first id wins. See the module docstring: the incoming one is
            # freshly minted by the adapter and means nothing. Stamped onto the
            # entity too, so a reader cannot get one id from the row and a
            # different one from the object inside it.
            neura_id = existing.neura_id if existing else entity.neura_id
            stored = entity if neura_id == entity.neura_id else with_id(entity, neura_id)

            self._rows[key.as_tuple()] = StoredEntity(
                key=key, neura_id=neura_id, fingerprint=digest, entity=stored
            )
            result.external_ids.append(entity.external_id)

        return result

    async def delete(self, key: EntityKey) -> bool:
        return self._rows.pop(key.as_tuple(), None) is not None

    async def get(self, key: EntityKey) -> CanonicalEntity | None:
        row = self._rows.get(key.as_tuple())
        return row.entity if row else None

    async def page(
        self,
        tenant_id: str,
        platform: str,
        entity_type: EntityType,
        *,
        limit: int,
        after: str | None = None,
    ) -> EntityPage:
        rows = sorted(
            (
                row
                for row in self._scoped(tenant_id, platform, entity_type)
                if after is None or row.key.external_id > after
            ),
            key=lambda r: r.key.external_id,
        )
        window = rows[:limit]
        # Reading one row past the window is what says "there is more". A count
        # query can disagree with the page it describes, because the two run at
        # different moments.
        more = len(rows) > limit
        return EntityPage(
            entities=[row.entity for row in window],
            next_after=window[-1].key.external_id if more and window else None,
        )

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


def with_id(entity: CanonicalEntity, neura_id: str) -> CanonicalEntity:
    """The same entity under a different ``neura_id``.

    Used when a store already holds this entity: the id it recorded first is the
    stable one, and the adapter's freshly minted replacement is discarded.
    """
    return entity.model_copy(update={"neura_id": neura_id})


def key_for(entity: CanonicalEntity) -> EntityKey:
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

#: The reverse direction, for rehydrating a stored document. Both maps live here
#: so a new entity type cannot be added to one and forgotten in the other.
#:
#: ``EntityType.VARIANT`` is deliberately absent: a variant is a field of a
#: ``Product``, not an entity with provenance of its own, so there is no
#: ``CanonicalEntity`` to build and a store asked for one should say so rather
#: than guess.
_MODELS: dict[EntityType, type[CanonicalEntity]] = {
    EntityType.PRODUCT: Product,
    EntityType.CATEGORY: Category,
    EntityType.CUSTOMER: Customer,
    EntityType.ORDER: Order,
    EntityType.POLICY: Policy,
}


def model_for(entity_type: EntityType) -> type[CanonicalEntity]:
    """Which canonical model a stored document of this type deserialises to."""
    model = _MODELS.get(entity_type)
    if model is None:
        raise ValueError(
            f"{entity_type.value!r} is not a stored entity type — it has no "
            "CanonicalEntity of its own"
        )
    return model
