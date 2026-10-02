"""A conformant store, in memory — the spec by example.

Three jobs, all of which need the *same* implementation to stay honest:

* ``neura-conformance --self-test`` runs the tool against this store, so a
  developer can tell "my store is wrong" from "your tool is broken" without
  asking us.
* Tests exercise the adapter against something that behaves like a real store
  rather than a mock that agrees with whatever the adapter does.
* It is the shortest readable answer to "what exactly should my endpoint
  return?" — and it is generated from the canonical models, so it cannot drift
  from the published spec.

``Defect`` deliberately makes it possible to build a *broken* store. A
conformance tool that has never been shown a failing store is a tool nobody has
tested (packages/neura-commerce/src/neura_commerce/conformance.py says the same
thing about adapters).

Not production code: no database, no concurrency, no persistence.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from neura_adapters.generic.wire import SPEC_VERSION, to_wire
from neura_domain import (
    Capability,
    Category,
    Customer,
    Fulfillment,
    FulfillmentStatus,
    InventoryLevel,
    Money,
    Order,
    OrderLine,
    OrderStatus,
    PaymentStatus,
    Policy,
    PolicyKind,
    Product,
    ProductStatus,
    ProductVariant,
)

DEFAULT_TOKEN = "reference-token"  # noqa: S105 — a fixture credential, never a real one

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

REFERENCE_CAPABILITIES = frozenset(
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
    }
)


class Defect(StrEnum):
    """Ways a real store gets the interface wrong.

    Every member here is a mistake worth catching before it reaches a customer
    conversation, not an invented edge case.
    """

    NO_AUTH = "no_auth"
    """Serves order and customer data to anyone who knows the URL."""

    MISSING_AS_200 = "missing_as_200"
    """Returns 200 with an empty body instead of 404 for an unknown id."""

    SEARCH_ERRORS_ON_EMPTY = "search_errors_on_empty"
    """500s on an empty query instead of returning an empty page."""

    STUCK_CURSOR = "stuck_cursor"
    """Returns the same cursor forever — sync never terminates."""

    IGNORES_UPDATED_SINCE = "ignores_updated_since"
    """Declares incremental sync and ignores the filter."""

    PLATFORM_STATUS = "platform_status"
    """Leaks its own status vocabulary instead of the canonical enum."""

    IGNORES_LIMIT = "ignores_limit"
    """Returns the whole collection regardless of ``limit``."""

    NO_PRODUCT_STATUS = "no_product_status"
    """Sends products without a status, so NEURA-SELL never recommends one (G69)."""


class ReferenceStore:
    """An in-memory store that implements the Generic Commerce Interface."""

    def __init__(
        self,
        *,
        prefix: str = "/neura/v1",
        token: str | None = DEFAULT_TOKEN,
        platform: str = "reference",
        capabilities: frozenset[Capability] = REFERENCE_CAPABILITIES,
        defects: frozenset[Defect] = frozenset(),
        product_count: int = 5,
        order_count: int = 3,
    ) -> None:
        self.prefix = prefix.rstrip("/")
        self.token = token
        self.platform = platform
        self.capabilities = capabilities
        self.defects = defects
        self.requests: list[httpx.Request] = []

        self.products = [_product(str(i), i) for i in range(1, product_count + 1)]
        self.orders = [_order(str(1000 + i), i) for i in range(1, order_count + 1)]
        self.customers = [_customer("c1")]
        self.categories = [_category("cookware")]
        self.policies = [_policy()]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def base_url(self, host: str = "https://store.example.com") -> str:
        return f"{host}{self.prefix}"

    # ── Routing ──────────────────────────────────────────────────────────────

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        parsed = urlparse(str(request.url))
        path = parsed.path.removeprefix(self.prefix) or "/"
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if path == "/health":
            return self._health()

        if not self._authorised(request):
            return _json(401, {"error": "missing or invalid bearer token"})

        if path == "/products":
            return self._products(params)
        if path.startswith("/products/"):
            return self._one(self.products, path.removeprefix("/products/"))
        if path == "/categories":
            return _json(200, [to_wire(c) for c in self.categories])
        if path == "/inventory":
            return self._inventory(params)
        if path == "/orders":
            return self._orders(params)
        if path.startswith("/orders/"):
            return self._one(self.orders, path.removeprefix("/orders/"))
        if path.startswith("/customers/"):
            return self._one(self.customers, path.removeprefix("/customers/"))
        if path == "/policies":
            return _json(200, [to_wire(p) for p in self.policies])

        return _json(404, {"error": f"no such endpoint: {path}"})

    def _authorised(self, request: httpx.Request) -> bool:
        if self.token is None or Defect.NO_AUTH in self.defects:
            return True
        return bool(request.headers.get("Authorization") == f"Bearer {self.token}")

    # ── Endpoints ────────────────────────────────────────────────────────────

    def _health(self) -> httpx.Response:
        return _json(
            200,
            {
                "status": "ok",
                "spec_version": SPEC_VERSION,
                "platform": self.platform,
                "capabilities": sorted(c.value for c in self.capabilities),
            },
        )

    def _products(self, params: dict[str, str]) -> httpx.Response:
        query = params.get("q")
        if not query and Defect.SEARCH_ERRORS_ON_EMPTY in self.defects:
            return _json(500, {"error": "empty query"})

        items = list(self.products)
        if query:
            items = [p for p in items if query.lower() in p.title.lower()]
        if params.get("in_stock_only") == "true":
            items = [p for p in items if any(v.in_stock for v in p.variants)]

        payloads = [to_wire(p) for p in items]
        if Defect.NO_PRODUCT_STATUS in self.defects:
            for payload in payloads:
                payload.pop("status", None)

        return self._paginate_payloads(payloads, params, updated=[p.updated_at for p in items])

    def _orders(self, params: dict[str, str]) -> httpx.Response:
        items = list(self.orders)
        if email := params.get("email"):
            items = [o for o in items if o.customer_email == email]
        if number := params.get("order_number"):
            items = [o for o in items if o.order_number == number]
        if customer := params.get("customer_id"):
            items = [o for o in items if o.customer_external_id == customer]

        payloads = [to_wire(o) for o in items]
        if Defect.PLATFORM_STATUS in self.defects:
            for payload in payloads:
                payload["status"] = "awaiting_shipment_from_warehouse"

        return self._paginate_payloads(payloads, params, updated=[o.updated_at for o in items])

    def _inventory(self, params: dict[str, str]) -> httpx.Response:
        wanted = {v for v in (params.get("variant_ids") or "").split(",") if v}
        levels = [
            InventoryLevel(
                variant_external_id=variant.external_id,
                quantity=variant.stock_quantity or 0,
                in_stock=bool(variant.in_stock),
            )
            for product in self.products
            for variant in product.variants
            if variant.external_id in wanted
        ]
        return _json(200, [level.model_dump(mode="json") for level in levels])

    def _one(self, collection: list[Any], external_id: str) -> httpx.Response:
        for entity in collection:
            if entity.external_id == external_id:
                return _json(200, to_wire(entity))
        if Defect.MISSING_AS_200 in self.defects:
            return _json(200, {})
        return _json(404, {"error": f"no such entity: {external_id}"})

    # ── Pagination ───────────────────────────────────────────────────────────

    def _paginate_payloads(
        self,
        payloads: list[dict[str, Any]],
        params: dict[str, str],
        *,
        updated: list[datetime | None],
    ) -> httpx.Response:
        since = params.get("updated_since")
        if since and Defect.IGNORES_UPDATED_SINCE not in self.defects:
            boundary = datetime.fromisoformat(since)
            payloads = [
                payload
                for payload, stamp in zip(payloads, updated, strict=True)
                if stamp is not None and stamp >= boundary
            ]

        limit = _int(params.get("limit"), default=100)
        if Defect.IGNORES_LIMIT in self.defects:
            limit = len(payloads) or 1

        start = _int(params.get("cursor"), default=0)
        window = payloads[start : start + limit]
        end = start + len(window)

        next_cursor: str | None = None
        if end < len(payloads):
            next_cursor = str(start if Defect.STUCK_CURSOR in self.defects else end)

        return _json(200, {"items": window, "next_cursor": next_cursor})


# ── Fixture data ─────────────────────────────────────────────────────────────


def _product(external_id: str, n: int) -> Product:
    return Product(
        neura_id=f"ent_{external_id}",
        tenant_id="tn_reference",
        external_id=external_id,
        platform="reference",
        synced_at=_EPOCH,
        title=f"Cast Iron Skillet {n}",
        description="Pre-seasoned, oven safe to 260°C.",
        status=ProductStatus.ACTIVE,
        variants=[
            ProductVariant(
                external_id=f"{external_id}-v1",
                sku=f"SKILLET-{n}",
                price=Money(amount=Decimal("49.00"), currency="USD"),
                in_stock=True,
                stock_quantity=12,
            )
        ],
        price_range_min=Money(amount=Decimal("49.00"), currency="USD"),
        price_range_max=Money(amount=Decimal("49.00"), currency="USD"),
        updated_at=_EPOCH + timedelta(days=n),
    )


def _order(external_id: str, n: int) -> Order:
    return Order(
        neura_id=f"ent_{external_id}",
        tenant_id="tn_reference",
        external_id=external_id,
        platform="reference",
        synced_at=_EPOCH,
        order_number=external_id,
        status=OrderStatus.SHIPPED,
        payment_status=PaymentStatus.PAID,
        fulfillment_status=FulfillmentStatus.FULFILLED,
        customer_external_id="c1",
        customer_email="shopper@example.com",
        lines=[
            OrderLine(
                title=f"Cast Iron Skillet {n}",
                sku=f"SKILLET-{n}",
                quantity=1,
                unit_price=Money(amount=Decimal("49.00"), currency="USD"),
                total=Money(amount=Decimal("49.00"), currency="USD"),
            )
        ],
        fulfillments=[
            Fulfillment(
                status=FulfillmentStatus.FULFILLED,
                carrier="ExamplePost",
                tracking_number=f"TRK{n:06d}",
                shipped_at=_EPOCH + timedelta(days=n),
            )
        ],
        total=Money(amount=Decimal("49.00"), currency="USD"),
        placed_at=_EPOCH + timedelta(days=n - 1),
        updated_at=_EPOCH + timedelta(days=n),
    )


def _customer(external_id: str) -> Customer:
    return Customer(
        neura_id=f"ent_{external_id}",
        tenant_id="tn_reference",
        external_id=external_id,
        platform="reference",
        synced_at=_EPOCH,
        email="shopper@example.com",
        first_name="Sam",
        last_name="Shopper",
        order_count=3,
    )


def _category(external_id: str) -> Category:
    return Category(
        neura_id=f"ent_{external_id}",
        tenant_id="tn_reference",
        external_id=external_id,
        platform="reference",
        synced_at=_EPOCH,
        name="Cookware",
    )


def _policy() -> Policy:
    return Policy(
        neura_id="ent_returns",
        tenant_id="tn_reference",
        external_id="returns",
        platform="reference",
        synced_at=_EPOCH,
        kind=PolicyKind.RETURNS,
        title="Returns",
        body="Unused items may be returned within 30 days of delivery for a full refund.",
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _json(status: int, payload: Any) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )


def _int(value: str | None, *, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default
