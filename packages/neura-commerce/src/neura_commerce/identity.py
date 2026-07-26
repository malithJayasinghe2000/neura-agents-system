"""Mapping between a platform's ids and ours.

Two problems this solves:

* **Collisions.** Two merchants may both have an order "1001". Keys are scoped by
  tenant *and* platform, so collision is structurally impossible rather than
  unlikely.
* **Stability.** Our ids never change even if a merchant migrates platforms —
  conversation history keeps pointing at the same order.

Storage arrives with the database work; this module owns the *shape* and the
key derivation so both stay in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from neura_core.ids import NEURA_ENTITY, new_id


class EntityType(StrEnum):
    PRODUCT = "product"
    VARIANT = "variant"
    CATEGORY = "category"
    CUSTOMER = "customer"
    ORDER = "order"
    POLICY = "policy"


@dataclass(frozen=True, slots=True)
class EntityKey:
    """The primary key of the mapping table.

    All four parts are needed. Dropping ``tenant_id`` allows cross-tenant
    collisions; dropping ``platform`` breaks the day a merchant runs two stores.
    """

    tenant_id: str
    platform: str
    entity_type: EntityType
    external_id: str

    def __post_init__(self) -> None:
        if not self.external_id:
            raise ValueError("external_id must not be empty")

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.tenant_id, self.platform, self.entity_type.value, self.external_id)


@dataclass(frozen=True, slots=True)
class EntityMapping:
    key: EntityKey
    neura_id: str


class EntityMap:
    """In-memory identity map.

    Backed by PostgreSQL later; the interface is what matters now so the sync
    engine and adapters can be built against it. Kept deliberately small — an
    identity map that grows features becomes a second, worse ORM.
    """

    def __init__(self) -> None:
        self._by_external: dict[tuple[str, str, str, str], str] = {}
        self._by_neura: dict[str, EntityKey] = {}

    def resolve(self, key: EntityKey) -> str:
        """Return the existing neura_id, or mint one.

        Idempotent by construction: syncing the same entity twice must produce
        the same id, because webhooks *will* be delivered twice.
        """
        existing = self._by_external.get(key.as_tuple())
        if existing is not None:
            return existing

        neura_id = new_id(NEURA_ENTITY)
        self._by_external[key.as_tuple()] = neura_id
        self._by_neura[neura_id] = key
        return neura_id

    def lookup(self, key: EntityKey) -> str | None:
        return self._by_external.get(key.as_tuple())

    def reverse(self, neura_id: str) -> EntityKey | None:
        """Which platform entity does this id refer to?

        Needed to act on something the agent referenced in a past conversation.
        """
        return self._by_neura.get(neura_id)

    def forget_tenant(self, tenant_id: str) -> int:
        """Drop every mapping for a tenant. Returns how many were removed.

        Part of the deletion fan-out: a mapping table left behind after
        offboarding still links a real person to a real order
        (docs/architecture/security-model.md §6.2).
        """
        doomed = [k for k in self._by_external if k[0] == tenant_id]
        for key_tuple in doomed:
            neura_id = self._by_external.pop(key_tuple)
            self._by_neura.pop(neura_id, None)
        return len(doomed)

    def __len__(self) -> int:
        return len(self._by_external)
