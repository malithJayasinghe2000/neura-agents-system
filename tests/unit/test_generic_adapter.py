"""The Generic Commerce Interface — Tier 2, the MVP integration path.

What is actually being tested here is the product claim: a store nobody has
written code for implements a published spec and works. So the tests that matter
most are the ones where the store gets it *wrong*, because a conformance tool
that only ever passes is a tool nobody has tested.

The store under test is fictional ("reference"). Test data stays
platform-neutral, or the abstraction is quietly undone by its own test suite.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from neura_adapters.generic import GenericAdapter, webhooks
from neura_adapters.generic.adapter import SPEC_CAPABILITIES
from neura_adapters.generic.cli import check_store
from neura_adapters.generic.reference import DEFAULT_TOKEN, Defect, ReferenceStore
from neura_adapters.generic.spec import build_openapi, render
from neura_adapters.generic.wire import PROVENANCE_FIELDS, SPEC_VERSION
from neura_commerce import (
    AdapterAuthError,
    AdapterError,
    AdapterMappingError,
    AdapterRateLimitedError,
    AdapterRegistry,
    AdapterTimeoutError,
    AdapterUnavailableError,
    CommerceAdapter,
    Cursor,
    ProductQuery,
    Severity,
    SyncQuery,
    run_conformance,
)
from neura_domain import Capability, CustomerRef, OrderStatus, ProductStatus

REPO_ROOT = Path(__file__).resolve().parents[2]


def adapter_for(store: ReferenceStore, *, token: str | None = DEFAULT_TOKEN) -> GenericAdapter:
    return GenericAdapter(
        base_url=store.base_url(),
        tenant_id="tn_test",
        token=token,
        transport=store.transport(),
    )


def adapter_for_handler(handler, *, token: str | None = DEFAULT_TOKEN) -> GenericAdapter:
    return GenericAdapter(
        base_url="https://store.example.com/neura/v1",
        tenant_id="tn_test",
        token=token,
        transport=httpx.MockTransport(handler),
    )


# ── The claim: an unmodified core serves an unknown store ────────────────────


async def test_conformant_store_passes_every_check() -> None:
    store = ReferenceStore()
    adapter = adapter_for(store)

    report = await check_store(adapter)
    await adapter.aclose()

    assert report.is_conformant, [f.message for f in report.errors]
    assert not report.warnings, [f.message for f in report.warnings]


async def test_generic_adapter_satisfies_the_contract() -> None:
    """Structural, not inherited — a third party can conform without importing us."""
    store = ReferenceStore()
    adapter = adapter_for(store)
    assert isinstance(adapter, CommerceAdapter)
    await adapter.aclose()


async def test_registry_discovers_the_adapter_by_entry_point() -> None:
    """The core finds adapters without importing them. That indirection is the
    whole platform-independence mechanism, so it is worth an actual test."""
    registry = AdapterRegistry()
    registry.discover()

    assert "generic" in registry.platforms()
    assert registry.capabilities_of("generic") == SPEC_CAPABILITIES

    adapter = registry.create("generic", base_url="https://x.example.com", tenant_id="tn_test")
    assert isinstance(adapter, GenericAdapter)
    await adapter.aclose()


async def test_capabilities_come_from_the_store_not_the_class() -> None:
    """One adapter class, many stores, different subsets.

    A store that has not implemented policies must not be given a policy tool
    just because another Tier 2 store has.
    """
    store = ReferenceStore(
        capabilities=frozenset({Capability.ORDER_READ, Capability.CUSTOMER_READ})
    )
    adapter = adapter_for(store)

    assert Capability.POLICY_READ in adapter.capabilities  # the class-level ceiling

    status = await adapter.health()

    assert status.capabilities == {Capability.ORDER_READ, Capability.CUSTOMER_READ}
    assert adapter.capabilities == status.capabilities
    assert Capability.POLICY_READ not in adapter.capabilities
    await adapter.aclose()


# ── Reading entities ─────────────────────────────────────────────────────────


async def test_reads_an_order_into_the_canonical_model() -> None:
    adapter = adapter_for(ReferenceStore())

    order = await adapter.get_order("1001")

    assert order is not None
    assert order.order_number == "1001"
    assert order.status is OrderStatus.SHIPPED
    assert order.tracking_numbers == ["TRK000001"]
    assert order.total is not None
    assert str(order.total) == "49.00 USD"
    await adapter.aclose()


async def test_provenance_is_ours_and_a_store_cannot_assert_it() -> None:
    """A store claiming another tenant's id would be a cross-tenant data leak."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "external_id": "1001",
                "order_number": "1001",
                "status": "shipped",
                "neura_id": "ent_attacker",
                "tenant_id": "tn_someone_else",
                "platform": "not-generic",
                "synced_at": "1999-01-01T00:00:00Z",
            },
        )

    adapter = adapter_for_handler(handler)
    order = await adapter.get_order("1001")

    assert order is not None
    assert order.tenant_id == "tn_test"
    assert order.platform == "generic"
    assert order.neura_id != "ent_attacker"
    assert order.synced_at > datetime(2020, 1, 1, tzinfo=UTC)
    await adapter.aclose()


async def test_ids_are_stable_across_fetches() -> None:
    """Webhooks are delivered twice and syncs re-run; the same order must stay
    the same entity, or conversation history points at a stranger."""
    adapter = adapter_for(ReferenceStore())

    first = await adapter.get_order("1001")
    second = await adapter.get_order("1001")

    assert first is not None and second is not None
    assert first.neura_id == second.neura_id
    await adapter.aclose()


async def test_unknown_fields_are_dropped_but_kept_in_raw() -> None:
    """A spec that breaks when a store adds a field is a spec that cannot evolve."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "external_id": "1001",
                "order_number": "1001",
                "status": "shipped",
                "warehouse_zone": "B12",
                "lines": [{"title": "Skillet", "quantity": 1, "internal_cost": "12.00"}],
            },
        )

    adapter = adapter_for_handler(handler)
    order = await adapter.get_order("1001")

    assert order is not None
    assert order.lines[0].title == "Skillet"
    assert order.raw is not None
    assert order.raw["warehouse_zone"] == "B12"
    await adapter.aclose()


async def test_an_empty_map_sent_as_an_empty_list_is_accepted() -> None:
    """Most commerce platforms are written in PHP, whose json_encode turns an
    empty map into `[]`. Rejecting that would fail a majority of correct
    implementations over a field nobody set. A non-empty list still fails."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "external_id": "9",
                "title": "Skillet",
                "variants": [{"external_id": "9-1", "sku": "SK-9", "options": []}],
            },
        )

    adapter = adapter_for_handler(handler)
    product = await adapter.get_product("9")

    assert product is not None
    assert product.variants[0].options == {}
    await adapter.aclose()


async def test_a_non_empty_list_where_a_map_belongs_is_still_a_mapping_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "external_id": "9",
                "title": "Skillet",
                "variants": [{"external_id": "9-1", "options": ["large"]}],
            },
        )

    adapter = adapter_for_handler(handler)
    with pytest.raises(AdapterMappingError):
        await adapter.get_product("9")
    await adapter.aclose()


async def test_an_unknown_status_degrades_instead_of_losing_the_order() -> None:
    """One unmapped string must not make an order unreadable — but it is a
    warning in conformance, because "unknown" is a poor answer to a customer."""
    store = ReferenceStore(defects=frozenset({Defect.PLATFORM_STATUS}))
    adapter = adapter_for(store)

    orders = await adapter.find_orders_for_customer(CustomerRef(email="shopper@example.com"))

    assert orders
    assert all(order.status is OrderStatus.UNKNOWN for order in orders)
    assert all(order.order_number for order in orders)
    await adapter.aclose()


async def test_unknown_capabilities_are_ignored_not_fatal() -> None:
    """A store built against a later spec version must still be usable."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "spec_version": "1.0",
                "platform": "reference",
                "capabilities": ["order.read", "cart.teleport"],
            },
        )

    adapter = adapter_for_handler(handler)
    status = await adapter.health()

    assert status.capabilities == {Capability.ORDER_READ}
    await adapter.aclose()


async def test_a_missing_entity_is_none_not_an_error() -> None:
    adapter = adapter_for(ReferenceStore())

    assert await adapter.get_order("does-not-exist") is None
    assert await adapter.get_product("does-not-exist") is None
    assert await adapter.get_customer("does-not-exist") is None
    await adapter.aclose()


async def test_ids_containing_slashes_are_escaped() -> None:
    """Order references legitimately contain slashes; unescaped, "INV/2026/01"
    silently requests a different resource."""
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # raw_path, not path: the decoded form would show a slash either way and
        # the test would pass while the request went to the wrong resource.
        seen.append(request.url.raw_path)
        return httpx.Response(404, json={})

    adapter = adapter_for_handler(handler)
    await adapter.get_order("INV/2026/01")

    assert seen == [b"/neura/v1/orders/INV%2F2026%2F01"]
    await adapter.aclose()


async def test_an_identifierless_lookup_asks_for_nothing() -> None:
    """Without an identifier this would fetch every order the store has."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"items": []})

    adapter = adapter_for_handler(handler)

    assert await adapter.find_orders_for_customer(CustomerRef()) == []
    assert await adapter.get_inventory([]) == []
    assert calls == []
    await adapter.aclose()


# ── Pagination ───────────────────────────────────────────────────────────────


async def test_cursors_are_opaque_and_round_trip() -> None:
    """A store's cursor is its own business; we only hand it back."""
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("cursor"))
        if request.url.params.get("cursor") == "opaque::whatever/=+":
            return httpx.Response(200, json={"items": [], "next_cursor": None})
        return httpx.Response(200, json={"items": [], "next_cursor": "opaque::whatever/=+"})

    adapter = adapter_for_handler(handler)

    first = await adapter.list_products(SyncQuery())
    assert first.next_cursor is not None
    assert first.has_more

    second = await adapter.list_products(SyncQuery(), first.next_cursor)
    assert not second.has_more
    assert seen == [None, "opaque::whatever/=+"]
    await adapter.aclose()


async def test_search_reaches_the_store_as_query_parameters() -> None:
    store = ReferenceStore()
    adapter = adapter_for(store)

    page = await adapter.search_products(ProductQuery(text="Skillet 3", limit=10))

    assert [p.external_id for p in page.items] == ["3"]
    assert page.items[0].status is ProductStatus.ACTIVE
    assert store.requests[-1].url.params["q"] == "Skillet 3"
    await adapter.aclose()


async def test_an_empty_search_is_an_empty_page_not_an_error() -> None:
    """The commonest outcome in a product catalogue."""
    adapter = adapter_for(ReferenceStore())

    page = await adapter.search_products(ProductQuery(text="zzz_no_such_thing"))

    assert page.items == []
    assert not page.has_more
    await adapter.aclose()


async def test_pagination_walks_the_whole_catalogue() -> None:
    adapter = adapter_for(ReferenceStore(product_count=5))

    seen: list[str] = []
    cursor: Cursor | None = None
    for _ in range(10):
        page = await adapter.list_products(SyncQuery(limit=2), cursor)
        seen.extend(p.external_id for p in page.items)
        if not page.has_more:
            break
        cursor = page.next_cursor

    assert seen == ["1", "2", "3", "4", "5"]
    await adapter.aclose()


async def test_incremental_sync_passes_updated_since_through() -> None:
    adapter = adapter_for(ReferenceStore())
    since = datetime(2026, 1, 4, tzinfo=UTC)

    page = await adapter.list_products(SyncQuery(updated_since=since))

    assert [p.external_id for p in page.items] == ["3", "4", "5"]
    await adapter.aclose()


# ── Failures a merchant's store will actually produce ────────────────────────


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AdapterAuthError),
        (403, AdapterAuthError),
        (429, AdapterRateLimitedError),
        (500, AdapterUnavailableError),
        (503, AdapterUnavailableError),
        (418, AdapterError),
    ],
)
async def test_http_failures_become_one_error_hierarchy(status: int, expected: type) -> None:
    """Translated once here so retry and escalation logic is written once."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "nope"}, headers={"Retry-After": "30"})

    adapter = adapter_for_handler(handler)
    with pytest.raises(expected):
        await adapter.get_order("1001")
    await adapter.aclose()


async def test_rate_limiting_carries_retry_after() -> None:
    """Ignoring it is how a sync takes down a merchant's production store."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={}, headers={"Retry-After": "30"})

    adapter = adapter_for_handler(handler)
    with pytest.raises(AdapterRateLimitedError) as caught:
        await adapter.get_order("1001")

    assert caught.value.retry_after_s == 30.0
    assert caught.value.retryable
    await adapter.aclose()


async def test_a_timeout_is_an_adapter_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    adapter = adapter_for_handler(handler)
    with pytest.raises(AdapterTimeoutError):
        await adapter.get_order("1001")
    await adapter.aclose()


async def test_an_html_error_page_is_not_mistaken_for_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    adapter = adapter_for_handler(handler)
    with pytest.raises(AdapterError):
        await adapter.get_order("1001")
    await adapter.aclose()


async def test_an_entity_without_an_id_is_a_mapping_error() -> None:
    """Nothing but an AdapterError may escape an adapter, or every caller above
    has to guess which exceptions a given integration can throw."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"order_number": "1001", "status": "shipped"})

    adapter = adapter_for_handler(handler)
    with pytest.raises(AdapterMappingError):
        await adapter.get_order("1001")
    await adapter.aclose()


async def test_a_float_price_is_refused() -> None:
    """By the time a float arrives the precision is already gone."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "external_id": "1001",
                "order_number": "1001",
                "total": {"amount": 49.99, "currency": "USD"},
            },
        )

    adapter = adapter_for_handler(handler)
    with pytest.raises(AdapterMappingError):
        await adapter.get_order("1001")
    await adapter.aclose()


# ── The conformance tool must be able to fail ────────────────────────────────


@pytest.mark.parametrize(
    ("defect", "check", "severity"),
    [
        (Defect.NO_AUTH, "auth.required", Severity.ERROR),
        (Defect.MISSING_AS_200, "errors.not_found", Severity.ERROR),
        (Defect.SEARCH_ERRORS_ON_EMPTY, "products.search_empty", Severity.ERROR),
        (Defect.STUCK_CURSOR, "pagination", Severity.ERROR),
        (Defect.IGNORES_UPDATED_SINCE, "sync.updated_since", Severity.WARNING),
        (Defect.PLATFORM_STATUS, "orders.status_vocabulary", Severity.WARNING),
        (Defect.IGNORES_LIMIT, "pagination.limit", Severity.WARNING),
        (Defect.NO_PRODUCT_STATUS, "products.status_vocabulary", Severity.WARNING),
    ],
)
async def test_each_defect_is_caught_by_its_check(
    defect: Defect, check: str, severity: Severity
) -> None:
    store = ReferenceStore(defects=frozenset({defect}))
    adapter = adapter_for(store)

    report = await check_store(adapter)
    await adapter.aclose()

    finding = next((f for f in report.findings if f.check == check), None)
    assert finding is not None, f"{defect} was not reported by {check}"
    assert finding.severity is severity
    assert finding.hint or severity is Severity.ERROR


async def test_an_unauthenticated_store_is_not_conformant() -> None:
    """The finding that is an incident rather than a bug: a store serving orders
    to anyone who knows the URL."""
    store = ReferenceStore(defects=frozenset({Defect.NO_AUTH}))
    adapter = adapter_for(store)

    report = await check_store(adapter)
    await adapter.aclose()

    assert not report.is_conformant
    assert {f.check for f in report.errors} >= {"auth.required", "auth.rejects_wrong_token"}
    # A shop that lists orders is checked where its customers are.
    assert all("/orders" in f.message for f in report.errors if f.check.startswith("auth."))


#: The guide's first three addresses: /health, /products, /products/{id}.
PRODUCTS_ONLY = frozenset({Capability.PRODUCT_READ, Capability.PRODUCT_SEARCH})


def built_products_only(store: ReferenceStore):
    """A bridge routed the way many frameworks route: an address that was never
    built answers 404 before any token check runs (G50)."""

    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix(store.prefix)
        if path in ("/health", "/products") or path.startswith("/products/"):
            return store.handle(request)
        store.requests.append(request)
        return httpx.Response(404, json={"error": f"no such endpoint: {path}"})

    return handle


async def test_a_shop_that_never_built_orders_is_not_failed_for_them() -> None:
    """G50: the check knocked on /orders anyway, read the 404 as an open door,
    and two false failures locked the owner's Connect."""
    store = ReferenceStore(capabilities=PRODUCTS_ONLY)
    adapter = adapter_for_handler(built_products_only(store))

    report = await check_store(adapter)
    await adapter.aclose()

    assert report.is_conformant, [f.message for f in report.errors]
    assert {"auth.required", "auth.rejects_wrong_token", "errors.not_found"} <= set(
        report.passed_checks
    )
    assert not [r for r in store.requests if r.url.path.startswith(f"{store.prefix}/orders")]


async def test_a_shop_without_orders_still_has_its_token_checked() -> None:
    store = ReferenceStore(capabilities=PRODUCTS_ONLY, defects=frozenset({Defect.NO_AUTH}))
    adapter = adapter_for(store)

    report = await check_store(adapter)
    await adapter.aclose()

    errors = {f.check: f for f in report.errors}
    assert {"auth.required", "auth.rejects_wrong_token"} <= errors.keys()
    assert errors["auth.required"].message.startswith("/products ")
    assert errors["auth.required"].hint.endswith("can read the store's products.")


async def test_a_shop_without_orders_is_asked_for_a_missing_product_instead() -> None:
    store = ReferenceStore(capabilities=PRODUCTS_ONLY, defects=frozenset({Defect.MISSING_AS_200}))
    adapter = adapter_for(store)

    report = await check_store(adapter)
    await adapter.aclose()

    finding = next(f for f in report.errors if f.check == "errors.not_found")
    assert finding.message.startswith("an unknown product id returned HTTP 200")
    assert "about a product that does not exist" in finding.hint


def with_product_statuses(store: ReferenceStore, statuses: list[str | None]):
    """The store's products, each given the next status in turn; ``None`` leaves it out."""

    def handle(request: httpx.Request) -> httpx.Response:
        response = store.handle(request)
        if request.url.path != f"{store.prefix}/products" or response.status_code != 200:
            return response
        payload = response.json()
        for item, status in zip(payload["items"], statuses, strict=False):
            if status is None:
                item.pop("status", None)
            else:
                item["status"] = status
        return httpx.Response(200, json=payload)

    return handle


async def test_products_without_a_status_are_warned_about_not_failed() -> None:
    """G69: a missing status reads as "unknown", and NEURA-SELL recommends only
    "active" products, so a shop that leaves it out gets nothing recommended
    while the check stayed green. The format allows it, so it warns and Connect
    stays open."""
    store = ReferenceStore(defects=frozenset({Defect.NO_PRODUCT_STATUS}))
    adapter = adapter_for(store)

    report = await check_store(adapter)
    await adapter.aclose()

    assert report.is_conformant, [f.message for f in report.errors]
    finding = next(f for f in report.findings if f.check == "products.status_vocabulary")
    assert finding.severity is Severity.WARNING
    assert finding.message == "5 of 5 products read have no usable status: no status (5)"
    assert '"status": "active"' in finding.hint
    assert 'never recommends a product that is not "active"' in finding.hint


async def test_each_unusable_product_status_is_named_with_its_count() -> None:
    """The format has the word "unknown", but it means the same as none; a word the
    format does not know is read as "unknown" too. Our own names stay out of it (G53)."""
    store = ReferenceStore()
    adapter = adapter_for_handler(
        with_product_statuses(store, ["active", None, "enabled", "unknown", "enabled"])
    )

    report = await check_store(adapter)
    await adapter.aclose()

    finding = next(f for f in report.findings if f.check == "products.status_vocabulary")
    assert finding.message == (
        '4 of 5 products read have no usable status: "enabled" (2), "unknown" (1), no status (1)'
    )
    assert "ProductStatus" not in finding.hint


async def test_draft_and_archived_products_are_not_a_status_problem() -> None:
    """A shop may hide products on purpose; only a missing or unknown word is warned about."""
    store = ReferenceStore()
    adapter = adapter_for_handler(
        with_product_statuses(store, ["active", "draft", "archived", "active", "active"])
    )

    report = await check_store(adapter)
    await adapter.aclose()

    assert "products.status_vocabulary" in report.passed_checks


def _store_without_policies() -> ReferenceStore:
    store = ReferenceStore()
    store.policies = []
    return store


@pytest.mark.parametrize(
    "store",
    [
        *(ReferenceStore(defects=frozenset({defect})) for defect in Defect),
        _store_without_policies(),
    ],
    ids=[*(defect.value for defect in Defect), "no_policies"],
)
async def test_the_full_check_speaks_to_the_bridges_developer(store: ReferenceStore) -> None:
    """G53: since the owner copies the full check to the developer, its words are
    the developer's. Not our function names, not our type names, not a file they
    cannot get, and no number nobody measured (CLAUDE.md §4)."""
    adapter = adapter_for(store)
    report = await check_store(adapter)
    await adapter.aclose()

    words = " ".join(f"{f.message} {f.hint}" for f in report.findings)
    assert report.findings, "this broken store was not reported at all"
    for ours in (r"\w+\(\)", r"ProductStatus", r"enums in the spec", r"support volume", "\u2014"):
        assert not re.search(ours, words), f"{ours!r} in: {words}"


async def test_running_without_a_token_says_so_rather_than_passing_quietly() -> None:
    store = ReferenceStore(token=None)
    adapter = adapter_for(store, token=None)

    report = await check_store(adapter)
    await adapter.aclose()

    warning = next(f for f in report.findings if f.check == "auth.required")
    assert warning.severity is Severity.WARNING
    assert "--token" in warning.hint


async def test_a_store_declaring_nothing_is_reported_as_unusable() -> None:
    store = ReferenceStore(capabilities=frozenset())
    adapter = adapter_for(store)

    report = await run_conformance(adapter)
    await adapter.aclose()

    assert not report.is_conformant
    assert any(f.check == "health" for f in report.errors)


# ── Webhooks ─────────────────────────────────────────────────────────────────


def test_a_correctly_signed_webhook_verifies() -> None:
    body = b'{"event":"order.updated","external_id":"1001"}'
    signature, timestamp = webhooks.sign(body, "shh")

    webhooks.verify(body, signature=signature, timestamp=timestamp, secret="shh")

    event = webhooks.parse(body)
    assert event.event == "order.updated"
    assert event.is_known
    assert event.entity_type == "order"


def test_a_tampered_body_fails() -> None:
    body = b'{"event":"order.updated","external_id":"1001"}'
    signature, timestamp = webhooks.sign(body, "shh")

    with pytest.raises(webhooks.WebhookSignatureError):
        webhooks.verify(
            b'{"event":"order.updated","external_id":"9999"}',
            signature=signature,
            timestamp=timestamp,
            secret="shh",
        )


def test_another_merchants_secret_fails() -> None:
    body = b"{}"
    signature, timestamp = webhooks.sign(body, "shh")

    with pytest.raises(webhooks.WebhookSignatureError):
        webhooks.verify(body, signature=signature, timestamp=timestamp, secret="different")


def test_an_old_request_cannot_be_replayed() -> None:
    """Without the window, a captured request stays valid forever."""
    body = b"{}"
    stale = datetime.now(UTC) - timedelta(hours=2)
    signature, timestamp = webhooks.sign(body, "shh", timestamp=int(stale.timestamp()))

    with pytest.raises(webhooks.WebhookSignatureError) as caught:
        webhooks.verify(body, signature=signature, timestamp=timestamp, secret="shh")

    assert "window" in str(caught.value)


def test_the_timestamp_is_part_of_what_is_signed() -> None:
    """Otherwise a replay only needs a fresh timestamp header."""
    body = b"{}"
    signature, timestamp = webhooks.sign(body, "shh")

    with pytest.raises(webhooks.WebhookSignatureError):
        webhooks.verify(body, signature=signature, timestamp=timestamp + 1, secret="shh")


@pytest.mark.parametrize(
    ("signature", "timestamp"),
    [(None, 1), ("sha256=deadbeef", None), ("", 1), ("sha256=deadbeef", "not-a-number")],
)
def test_malformed_signature_headers_are_rejected(signature: str | None, timestamp: object) -> None:
    with pytest.raises(webhooks.WebhookSignatureError):
        webhooks.verify(b"{}", signature=signature, timestamp=timestamp, secret="shh")  # type: ignore[arg-type]


# ── The published spec ───────────────────────────────────────────────────────


def test_the_committed_openapi_document_matches_the_models() -> None:
    """A published contract that drifts from the code is worse than none: a
    merchant's developer implements the stale version and finds out in
    production. Regenerate with `make spec`."""
    committed = REPO_ROOT / "docs" / "spec" / "openapi.json"

    assert committed.exists(), "run: make spec"
    assert committed.read_text(encoding="utf-8") == render(), (
        "docs/spec/openapi.json is out of date — run `make spec`"
    )


def test_the_spec_describes_exactly_the_nine_endpoints() -> None:
    document = build_openapi()

    assert document["openapi"] == "3.1.0"
    assert document["info"]["version"] == SPEC_VERSION
    assert len(document["paths"]) == 9
    assert set(document["paths"]) == {
        "/health",
        "/products",
        "/products/{id}",
        "/categories",
        "/inventory",
        "/orders",
        "/orders/{id}",
        "/customers/{id}",
        "/policies",
    }


def test_the_spec_does_not_ask_a_store_for_our_provenance_fields() -> None:
    """A store cannot know our ids, and must not be trusted to assert its tenant."""
    schemas = build_openapi()["components"]["schemas"]

    for entity in ("Product", "Order", "Customer", "Category", "Policy"):
        properties = set(schemas[entity]["properties"])
        assert not (properties & PROVENANCE_FIELDS), entity


def test_every_data_endpoint_requires_a_token() -> None:
    document = build_openapi()

    assert document["security"] == [{"bearerAuth": []}]
    for path, operations in document["paths"].items():
        if path == "/health":
            assert operations["get"]["security"] == []
            continue
        assert "security" not in operations["get"], f"{path} must inherit global security"
        assert "401" in operations["get"]["responses"], path


def test_the_spec_uses_the_canonical_status_vocabulary() -> None:
    schemas = build_openapi()["components"]["schemas"]
    order_status = schemas["OrderStatus"]["enum"]

    assert set(order_status) == {s.value for s in OrderStatus}
    assert set(schemas["ProductStatus"]["enum"]) == {s.value for s in ProductStatus}


def test_the_document_is_valid_json_and_stable() -> None:
    assert json.loads(render()) == build_openapi()
    assert render() == render()
