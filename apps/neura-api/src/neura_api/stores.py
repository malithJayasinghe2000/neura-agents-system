"""Getting from a tenant to a live connection to their shop.

A turn needs three things from the merchant's store: an adapter to call it with,
the credentials to authenticate, and the list of capabilities the store actually
declares. All three come from the tenant's ``tenant_stores`` row, and none of
them is configured here.

**The adapter is built through the registry, never imported.** ``neura_api``
must not import ``neura_adapters`` — an import-linter contract fails the build if
it does — because the moment the deployable knows a platform name, platform
independence is a claim rather than a property. ``neura_commerce.registry``
resolves the platform string stored on the row to a factory that registered
itself via an entry point.

**Capabilities come from the store, not from us.** ``GET /health`` on the
merchant's own bridge says what it can do; a store that cannot search orders
declares so, and ``find_orders_for_customer`` is then never shown to the model
for that tenant. Declaring capabilities here would test our assumptions about a
shop rather than the shop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from neura_api.addresses import adapter_transport
from neura_commerce import registry
from neura_core import (
    Database,
    NotFoundError,
    ServiceUnavailableError,
    get_logger,
    get_settings,
)
from neura_core.tenancy import StoreConnectionRepository
from neura_core.tenancy.schema import tenant_stores
from neura_domain import Capability

log = get_logger(__name__)

#: How long a store's declared capabilities are reused before asking again.
#:
#: A capability set changes when a merchant upgrades their bridge, which is a
#: deploy on their side and not a per-request event. Asking every turn would put
#: a round trip to the merchant's server in front of every shopper's message —
#: and the failure mode of a stale entry is bounded and safe: a newly-added
#: capability is unavailable for at most a minute, and a *removed* one produces
#: a tool call the store refuses, which the executor already handles.
CAPABILITY_TTL_S = 60.0


@dataclass(frozen=True, slots=True)
class StoreConnection:
    """One tenant's shop, ready to be handed to a runtime."""

    store_id: str
    platform: str
    base_url: str
    adapter: Any
    capabilities: frozenset[Capability]


@dataclass(slots=True)
class _CachedCapabilities:
    capabilities: frozenset[Capability]
    expires_at: float


class StoreDirectory:
    """Resolves a tenant to a connected store. One per process."""

    def __init__(
        self, db: Database, *, ttl_s: float = CAPABILITY_TTL_S, production: bool | None = None
    ) -> None:
        self._db = db
        self._ttl_s = ttl_s
        #: In production every call to a shop connects only to public addresses,
        #: checked as it connects (G47, G78): the address passed a check once, but
        #: a name can be pointed somewhere else afterwards.
        self._production = get_settings().is_production if production is None else production
        self._capabilities: dict[str, _CachedCapabilities] = {}

    async def rows_for(self, tenant_id: str) -> list[dict[str, str]]:
        """A tenant's connections, without their secrets. Safe to render."""
        async with self._db.tenant_session(tenant_id) as session:
            return await StoreConnectionRepository(session).list_for(tenant_id)

    async def connect(self, tenant_id: str, *, store_id: str | None = None) -> StoreConnection:
        """Build an adapter for a tenant's store.

        With no ``store_id`` the tenant's first connection is used. That is the
        MVP shape — one merchant, one shop — and it is stated rather than
        implied, because ``tenant_stores`` already allows several and a future
        route will have to say which.

        **The caller owns the adapter and must close it.** Adapters hold an HTTP
        client; one built per turn and abandoned leaks a connection pool per
        shopper.
        """
        async with self._db.tenant_session(tenant_id) as session:
            query = select(tenant_stores).where(tenant_stores.c.tenant_id == tenant_id)
            if store_id is not None:
                query = query.where(tenant_stores.c.id == store_id)
            row = (
                await session.execute(query.order_by(tenant_stores.c.created_at).limit(1))
            ).first()

            if row is None:
                raise NotFoundError(
                    "This account has no store connected. Register one with "
                    "POST /v1/stores before starting a conversation.",
                    code="NO_STORE_CONNECTED",
                    details={"store_id": store_id} if store_id else None,
                )

            credentials = await StoreConnectionRepository(session).credentials_for(
                tenant_id, str(row.id)
            )

        platform = str(row.platform)
        try:
            adapter = registry.create(
                platform,
                base_url=str(row.base_url),
                tenant_id=tenant_id,
                **adapter_transport(production=self._production),
                **credentials,
            )
        except KeyError as exc:
            # The row names a platform this deployment has no adapter for —
            # a partial rollback, or a connector that failed to load at startup.
            raise ServiceUnavailableError(
                "No adapter for this store's platform is installed in this deployment.",
                details={"store_id": str(row.id)},
            ) from exc

        return StoreConnection(
            store_id=str(row.id),
            platform=platform,
            base_url=str(row.base_url),
            adapter=adapter,
            capabilities=await self._negotiate(str(row.id), adapter),
        )

    async def _negotiate(self, store_id: str, adapter: Any) -> frozenset[Capability]:
        cached = self._capabilities.get(store_id)
        now = time.monotonic()
        if cached is not None and cached.expires_at > now:
            return cached.capabilities

        health = await adapter.health()
        if not health.ok:
            raise ServiceUnavailableError(
                "The connected store is not reachable.",
                code="STORE_UNAVAILABLE",
                details={"store_id": store_id},
            )

        capabilities = frozenset(health.capabilities)
        self._capabilities[store_id] = _CachedCapabilities(capabilities, now + self._ttl_s)
        return capabilities

    def forget(self, store_id: str) -> None:
        """Drop a cached capability set — after a reconnect, or a health check."""
        self._capabilities.pop(store_id, None)


__all__ = ["CAPABILITY_TTL_S", "StoreConnection", "StoreDirectory"]
