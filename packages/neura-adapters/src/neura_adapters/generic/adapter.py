"""``GenericAdapter`` — the Tier 2 integration, and the MVP path.

A store implements nine read-only endpoints; this adapter consumes them. Nothing
is written by us per merchant, which is the only way to serve a store nobody
will ever write a native adapter for
(docs/architecture/adr/0009-generic-commerce-interface.md).

Two properties worth stating plainly, because they are easy to lose later:

* **Capabilities are per store, not per class.** One ``GenericAdapter`` class
  serves every Tier 2 merchant, and they will not implement the same subset. The
  class advertises what the *interface* covers; ``health()`` replaces that with
  what *this* store declares.
* **This is not an authorisation boundary.** ``get_order`` returns whatever the
  store returns, to whoever asks. Whether the person in the chat window may see
  that order is decided by ownership verification in the policy engine
  (docs/architecture/security-model.md §3). Splitting that check across
  integrations would guarantee it is implemented differently in each.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import quote

import httpx

from neura_adapters.generic.client import DEFAULT_TIMEOUT_S, GenericClient
from neura_adapters.generic.wire import parse_health, to_canonical
from neura_commerce import (
    AdapterMappingError,
    ConformanceReport,
    Cursor,
    EntityKey,
    EntityMap,
    EntityType,
    HealthStatus,
    Page,
    ProductQuery,
    SyncQuery,
    clamp_page_size,
)
from neura_core import get_logger
from neura_domain import (
    CanonicalEntity,
    Capability,
    Category,
    Customer,
    CustomerRef,
    InventoryLevel,
    Order,
    Policy,
    Product,
)

log = get_logger(__name__)

#: What the published interface covers. An individual store declares its own
#: subset in ``GET /health``; this is the ceiling, not a promise about any store.
SPEC_CAPABILITIES = frozenset(
    {
        Capability.PRODUCT_READ,
        Capability.PRODUCT_SEARCH,
        Capability.CATEGORY_READ,
        Capability.INVENTORY_READ,
        Capability.ORDER_READ,
        Capability.ORDER_SEARCH,
        Capability.CUSTOMER_READ,
        Capability.POLICY_READ,
        Capability.INCREMENTAL_SYNC,
        Capability.REALTIME_EVENTS,
    }
)

#: The nine endpoints. Kept in one place so the client, the OpenAPI document and
#: the conformance tool cannot describe different interfaces.
PATH_HEALTH = "/health"
PATH_PRODUCTS = "/products"
PATH_PRODUCT = "/products/{id}"
PATH_CATEGORIES = "/categories"
PATH_INVENTORY = "/inventory"
PATH_ORDERS = "/orders"
PATH_ORDER = "/orders/{id}"
PATH_CUSTOMER = "/customers/{id}"
PATH_POLICIES = "/policies"

_CURSOR_TOKEN = "token"  # noqa: S105 — a pagination marker, not a credential


class GenericAdapter:
    """Reads a store that implements the Generic Commerce Interface."""

    platform: ClassVar[str] = "generic"

    #: Declared capabilities. A class-level default so the registry can answer
    #: "what can this integration do?" before any store is connected; replaced
    #: per instance by ``health()`` with what the store itself declares.
    capabilities: frozenset[Capability] = SPEC_CAPABILITIES

    def __init__(
        self,
        *,
        base_url: str,
        tenant_id: str,
        token: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
        entity_map: EntityMap | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.capabilities = SPEC_CAPABILITIES
        self._client = GenericClient(
            base_url, token=token, timeout_s=timeout_s, transport=transport
        )
        # Ids must survive a re-sync: the same order fetched twice is the same
        # entity, or every conversation history points at a stranger.
        self._ids = entity_map or EntityMap()
        self._spec_version: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def client(self) -> GenericClient:
        """The underlying transport.

        Exposed for the conformance tool alone, which has to inspect status
        codes, headers and anonymous requests — precisely what the canonical
        interface exists to hide from everything else. Nothing in the agent path
        should reach for this.
        """
        return self._client

    async def run_protocol_checks(self, report: ConformanceReport) -> None:
        """The checks only the wire can show: status codes, headers, the token.

        Found by ``neura_commerce.check_adapter`` through its shape, so the
        dashboard runs exactly what the terminal tool runs without learning that
        this adapter exists (ADR-0052 §4).
        """
        # Imported here: http_checks imports this module for its paths.
        from neura_adapters.generic.http_checks import run_http_checks

        # What /health listed (the shared suite asked it first), so an address
        # the shop never built is never knocked on (G50).
        await run_http_checks(self._client, report, frozenset(self.capabilities))

    @property
    def spec_version(self) -> str | None:
        """What the store said it implements. ``None`` until ``health()`` runs."""
        return self._spec_version

    # ── Connectivity ─────────────────────────────────────────────────────────

    async def health(self) -> HealthStatus:
        started = time.perf_counter()
        payload = await self._client.get_json(PATH_HEALTH)
        latency_ms = int((time.perf_counter() - started) * 1000)

        if payload is None:
            # 404 on /health means the interface is not mounted where we were
            # told it is — a configuration error, not an unhealthy store.
            return HealthStatus(
                ok=False,
                platform=self.platform,
                detail=f"no interface at {self._client.base_url}{PATH_HEALTH}",
                latency_ms=latency_ms,
            )

        status = parse_health(payload, fallback_platform=self.platform, latency_ms=latency_ms)
        self.capabilities = status.capabilities
        self._spec_version = status.spec_version
        log.info(
            "generic_store_health",
            ok=status.ok,
            spec_version=status.spec_version,
            capabilities=sorted(c.value for c in status.capabilities),
        )
        return status

    # ── Catalogue ────────────────────────────────────────────────────────────

    async def get_product(self, external_id: str) -> Product | None:
        payload = await self._client.get_json(PATH_PRODUCT.format(id=_path(external_id)))
        return None if payload is None else self._entity(Product, EntityType.PRODUCT, payload)

    async def search_products(self, query: ProductQuery) -> Page[Product]:
        params: dict[str, Any] = {
            "q": query.text or None,
            "limit": clamp_page_size(query.limit),
            "locale": query.locale,
        }
        if query.category_ids:
            params["category_ids"] = ",".join(query.category_ids)
        if query.in_stock_only:
            params["in_stock_only"] = "true"

        payload = await self._client.get_json(PATH_PRODUCTS, params=params)
        return self._page(Product, EntityType.PRODUCT, payload)

    async def list_products(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Product]:
        payload = await self._client.get_json(PATH_PRODUCTS, params=_sync_params(query, cursor))
        return self._page(Product, EntityType.PRODUCT, payload)

    async def list_categories(self) -> list[Category]:
        payload = await self._client.get_json(PATH_CATEGORIES)
        return self._items(Category, EntityType.CATEGORY, payload)

    async def get_inventory(self, variant_external_ids: list[str]) -> list[InventoryLevel]:
        if not variant_external_ids:
            return []

        payload = await self._client.get_json(
            PATH_INVENTORY, params={"variant_ids": ",".join(variant_external_ids)}
        )
        raw_items = _raw_items(payload)
        # InventoryLevel is not a synced entity — it has no provenance and no
        # identity of its own, so it validates directly.
        return [InventoryLevel.model_validate(item) for item in raw_items]

    # ── Orders ───────────────────────────────────────────────────────────────

    async def get_order(self, external_id: str) -> Order | None:
        payload = await self._client.get_json(PATH_ORDER.format(id=_path(external_id)))
        return None if payload is None else self._entity(Order, EntityType.ORDER, payload)

    async def list_orders(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Order]:
        payload = await self._client.get_json(PATH_ORDERS, params=_sync_params(query, cursor))
        return self._page(Order, EntityType.ORDER, payload)

    async def find_orders_for_customer(self, ref: CustomerRef) -> list[Order]:
        params = {
            "customer_id": ref.external_id,
            "email": ref.email,
            "phone": ref.phone,
            "order_number": ref.order_ref,
        }
        if not any(params.values()):
            # Without an identifier this would ask the store for every order it
            # has, which is both useless and the shape of a data-exfiltration bug.
            return []

        payload = await self._client.get_json(PATH_ORDERS, params=params)
        return self._page(Order, EntityType.ORDER, payload).items

    # ── Customers ────────────────────────────────────────────────────────────

    async def get_customer(self, external_id: str) -> Customer | None:
        payload = await self._client.get_json(PATH_CUSTOMER.format(id=_path(external_id)))
        return None if payload is None else self._entity(Customer, EntityType.CUSTOMER, payload)

    # ── Store content ────────────────────────────────────────────────────────

    async def get_policies(self) -> list[Policy]:
        payload = await self._client.get_json(PATH_POLICIES)
        return self._items(Policy, EntityType.POLICY, payload)

    # ── Mapping ──────────────────────────────────────────────────────────────

    def _entity[T: CanonicalEntity](
        self, model: type[T], entity_type: EntityType, payload: Any
    ) -> T:
        external_id = str(payload.get("external_id", "")) if isinstance(payload, dict) else ""
        if not external_id:
            # Every entity must be identifiable, or the identity map cannot key
            # it and a re-sync would create a duplicate. Raised as a mapping
            # error rather than the ValueError the identity map would throw:
            # nothing but an AdapterError may escape an adapter, or every caller
            # above has to guess which exceptions a given integration can emit.
            raise AdapterMappingError(
                f"{model.__name__} payload has no external_id",
                details={"received": sorted(payload) if isinstance(payload, dict) else []},
            )

        neura_id = self._ids.resolve(
            EntityKey(
                tenant_id=self.tenant_id,
                platform=self.platform,
                entity_type=entity_type,
                external_id=external_id,
            )
        )
        return to_canonical(
            model,
            payload,
            neura_id=neura_id,
            tenant_id=self.tenant_id,
            platform=self.platform,
            synced_at=datetime.now(UTC),
        )

    def _items[T: CanonicalEntity](
        self, model: type[T], entity_type: EntityType, payload: Any
    ) -> list[T]:
        return [self._entity(model, entity_type, item) for item in _raw_items(payload)]

    def _page[T: CanonicalEntity](
        self, model: type[T], entity_type: EntityType, payload: Any
    ) -> Page[T]:
        return Page(
            items=self._items(model, entity_type, payload),
            next_cursor=_next_cursor(payload),
        )


def _sync_params(query: SyncQuery, cursor: Cursor | None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "limit": clamp_page_size(query.limit),
        "locale": query.locale,
    }
    if query.updated_since is not None:
        params["updated_since"] = query.updated_since.isoformat()
    if cursor is not None and not cursor.is_start:
        params["cursor"] = cursor.state.get(_CURSOR_TOKEN)
    return params


def _raw_items(payload: Any) -> list[Any]:
    """Items from either envelope shape.

    A bare list is accepted for the unpaginated endpoints (``/categories``,
    ``/policies``, ``/inventory``); everything else sends ``{"items": [...]}``.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        items = payload.get("items", [])
        return list(items) if isinstance(items, list) else []
    return []


def _next_cursor(payload: Any) -> Cursor | None:
    """Wrap the store's opaque token.

    Opaque means opaque: we never parse it, only hand it back. A store is free
    to encode a page number, a keyset or an internal token, and may change that
    without telling us.
    """
    if not isinstance(payload, dict):
        return None
    token = payload.get("next_cursor")
    if token in (None, ""):
        return None
    return Cursor(state={_CURSOR_TOKEN: str(token)})


def _path(external_id: str) -> str:
    """Escape an id for use in a path.

    Order references legitimately contain slashes and spaces in some stores;
    without escaping, "INV/2026/01" silently becomes a request for a different
    resource.
    """
    return quote(external_id, safe="")
