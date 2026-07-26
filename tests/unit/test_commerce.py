"""The commerce adapter layer.

The most consequential tests in the repository. If this layer is wrong, the
product's entire market position — "works with any commerce platform" — is
false.

The fake platform below is called "acme" deliberately: eval data and tests must
stay platform-neutral, or they quietly re-couple us to whichever platform was
implemented first.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from neura_commerce import (
    AdapterRegistry,
    CommerceAdapter,
    ConformanceReport,
    Cursor,
    EntityKey,
    EntityMap,
    EntityType,
    HealthStatus,
    Page,
    ProductQuery,
    Requirement,
    Severity,
    SyncQuery,
    clamp_page_size,
    describe_gap,
    filter_by_capability,
    negotiate,
    run_conformance,
)
from neura_domain import (
    Capability,
    Category,
    Customer,
    CustomerRef,
    InventoryLevel,
    Money,
    Order,
    OrderStatus,
    Policy,
    PolicyKind,
    Product,
    ProductStatus,
)

NOW = datetime.now(UTC)


# ── A well-behaved fake platform ─────────────────────────────────────────────


class AcmeAdapter:
    """A correct adapter for a fictional platform.

    Nothing in the core knows this exists — it is discovered through the
    registry and used through the protocol.
    """

    platform = "acme"
    capabilities = frozenset(
        {
            Capability.PRODUCT_READ,
            Capability.PRODUCT_SEARCH,
            Capability.ORDER_READ,
            Capability.CUSTOMER_READ,
            Capability.POLICY_READ,
        }
    )

    def __init__(self, tenant_id: str = "tn_test", product_count: int = 5) -> None:
        self.tenant_id = tenant_id
        self._products = [self._product(str(i)) for i in range(1, product_count + 1)]

    def _product(self, external_id: str) -> Product:
        return Product(
            neura_id=f"ne_{external_id}",
            tenant_id=self.tenant_id,
            external_id=external_id,
            platform=self.platform,
            synced_at=NOW,
            title=f"Cast Iron Skillet {external_id}",
            description="Pre-seasoned, oven safe.",
            status=ProductStatus.ACTIVE,
            price_range_min=Money(amount=Decimal("29.99"), currency="USD"),
        )

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=True, platform=self.platform, capabilities=self.capabilities)

    async def get_product(self, external_id: str) -> Product | None:
        return next((p for p in self._products if p.external_id == external_id), None)

    async def search_products(self, query: ProductQuery) -> Page[Product]:
        if not query.text:
            return Page(items=self._products[: query.limit])
        matches = [p for p in self._products if query.text.lower() in p.title.lower()]
        return Page(items=matches[: query.limit])

    async def list_products(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Product]:
        offset = int((cursor.state.get("offset", 0)) if cursor else 0)
        chunk = self._products[offset : offset + query.limit]
        next_offset = offset + len(chunk)
        has_more = next_offset < len(self._products)
        return Page(
            items=chunk,
            next_cursor=Cursor(state={"offset": next_offset}) if has_more else None,
        )

    async def list_categories(self) -> list[Category]:
        return [
            Category(
                neura_id="ne_c1",
                tenant_id=self.tenant_id,
                external_id="c1",
                platform=self.platform,
                synced_at=NOW,
                name="Cookware",
            )
        ]

    async def get_inventory(self, variant_external_ids: list[str]) -> list[InventoryLevel]:
        return [
            InventoryLevel(variant_external_id=vid, quantity=10, in_stock=True)
            for vid in variant_external_ids
        ]

    async def get_order(self, external_id: str) -> Order | None:
        if external_id != "1001":
            return None
        return Order(
            neura_id="ne_o1",
            tenant_id=self.tenant_id,
            external_id="1001",
            platform=self.platform,
            synced_at=NOW,
            order_number="1001",
            status=OrderStatus.SHIPPED,
            customer_email="jane@example.com",
        )

    async def list_orders(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Order]:
        order = await self.get_order("1001")
        return Page(items=[order] if order else [])

    async def find_orders_for_customer(self, ref: CustomerRef) -> list[Order]:
        if ref.email != "jane@example.com":
            return []
        order = await self.get_order("1001")
        return [order] if order else []

    async def get_customer(self, external_id: str) -> Customer | None:
        if external_id != "cust_88":
            return None
        return Customer(
            neura_id="ne_cu1",
            tenant_id=self.tenant_id,
            external_id="cust_88",
            platform=self.platform,
            synced_at=NOW,
            email="jane@example.com",
            first_name="Jane",
        )

    async def get_policies(self) -> list[Policy]:
        return [
            Policy(
                neura_id="ne_p1",
                tenant_id=self.tenant_id,
                external_id="returns",
                platform=self.platform,
                synced_at=NOW,
                kind=PolicyKind.RETURNS,
                title="Returns",
                body="Items may be returned within 30 days of delivery.",
            )
        ]


# ── The headline test ────────────────────────────────────────────────────────


class TestAnyPlatformIntegrates:
    """A platform the core has never heard of must work with no core changes.

    This is the product claim, expressed as a test.
    """

    def test_a_new_platform_satisfies_the_protocol_structurally(self) -> None:
        """No inheritance, no import from us — structural typing only.

        That is what lets a third party conform to the published spec without
        depending on our package.
        """
        assert isinstance(AcmeAdapter(), CommerceAdapter)

    async def test_it_passes_conformance_unmodified(self) -> None:
        report = await run_conformance(AcmeAdapter())
        assert report.is_conformant, [f.message for f in report.errors]

    async def test_it_returns_canonical_models_not_platform_payloads(self) -> None:
        order = await AcmeAdapter().get_order("1001")
        assert order is not None
        # A canonical enum, never a platform's own status string.
        assert order.status is OrderStatus.SHIPPED
        assert isinstance(order.status, OrderStatus)

    async def test_the_registry_finds_it_without_the_core_importing_it(self) -> None:
        reg = AdapterRegistry()
        reg.register("acme", AcmeAdapter, AcmeAdapter.capabilities)

        adapter = reg.create("acme", tenant_id="tn_1")
        assert (await adapter.health()).platform == "acme"
        assert "acme" in reg.platforms()


# ── Capability negotiation ───────────────────────────────────────────────────


class TestNegotiation:
    def test_a_store_meeting_requirements_is_compatible(self) -> None:
        requirement = Requirement(
            name="NEURA-CARE",
            required=frozenset({Capability.ORDER_READ, Capability.POLICY_READ}),
        )
        result = negotiate(requirement, AcmeAdapter.capabilities)
        assert result.compatible
        assert not result.missing

    def test_a_store_missing_a_requirement_is_told_which_one(self) -> None:
        """Merchants read this when connecting, so it names the capability."""
        requirement = Requirement(
            name="NEURA-CARE",
            required=frozenset({Capability.ORDER_READ, Capability.CART_WRITE}),
        )
        result = negotiate(requirement, AcmeAdapter.capabilities)

        assert not result.compatible
        assert Capability.CART_WRITE in result.missing
        assert "cart.write" in result.explain()

    def test_missing_optional_capability_degrades_rather_than_failing(self) -> None:
        """Graceful degradation is what lets simple stores integrate at all."""
        requirement = Requirement(
            name="NEURA-CARE",
            required=frozenset({Capability.ORDER_READ}),
            optional=frozenset({Capability.INVENTORY_READ}),
        )
        result = negotiate(requirement, AcmeAdapter.capabilities)

        assert result.compatible
        assert not result.is_fully_supported
        assert "reduced functionality" in result.explain()

    def test_tools_are_filtered_to_what_the_store_supports(self) -> None:
        """The security property: an unavailable tool is never registered.

        A model cannot invoke a tool it was never shown, however persuasive an
        injected instruction is.
        """
        tools = [
            ("get_order_status", frozenset({Capability.ORDER_READ})),
            ("search_products", frozenset({Capability.PRODUCT_SEARCH})),
            ("cancel_order", frozenset({Capability.ORDER_WRITE})),
        ]
        available = filter_by_capability(tools, AcmeAdapter.capabilities, requires=lambda t: t[1])
        names = {name for name, _ in available}

        assert "get_order_status" in names
        assert "cancel_order" not in names, "a write tool must not survive filtering"

    def test_gap_description_feeds_the_system_prompt(self) -> None:
        """So the model states its limits instead of apologising vaguely."""
        gap = describe_gap(
            frozenset({Capability.ORDER_READ, Capability.ORDER_WRITE}),
            AcmeAdapter.capabilities,
        )
        assert gap == "order.write"

    def test_no_gap_is_an_empty_string(self) -> None:
        assert describe_gap(frozenset({Capability.ORDER_READ}), AcmeAdapter.capabilities) == ""


# ── Pagination ───────────────────────────────────────────────────────────────


class TestPagination:
    def test_cursor_round_trips(self) -> None:
        cursor = Cursor(state={"offset": 40, "sort": "id"})
        assert Cursor.decode(cursor.encode()).state == cursor.state

    def test_cursor_is_url_safe(self) -> None:
        """Cursors travel in query strings and get checkpointed in the database."""
        encoded = Cursor(state={"last_id": "abc/def+ghi=="}).encode()
        assert "/" not in encoded
        assert "+" not in encoded

    def test_start_cursor_is_empty(self) -> None:
        assert Cursor.start().is_start

    def test_page_size_is_clamped(self) -> None:
        """An unbounded limit lets one call pull an entire catalogue into memory."""
        assert clamp_page_size(999_999) == 500
        assert clamp_page_size(None) == 100
        assert clamp_page_size(0) == 100
        assert clamp_page_size(50) == 50

    def test_empty_page_is_a_valid_result(self) -> None:
        page: Page[Product] = Page.empty()
        assert len(page) == 0
        assert not page.has_more

    async def test_pagination_terminates_and_does_not_repeat(self) -> None:
        adapter = AcmeAdapter(product_count=5)
        seen: list[str] = []
        cursor: Cursor | None = None

        for _ in range(10):
            page = await adapter.list_products(SyncQuery(limit=2), cursor)
            seen.extend(p.external_id for p in page.items)
            if not page.has_more:
                break
            cursor = page.next_cursor

        assert seen == ["1", "2", "3", "4", "5"]
        assert len(seen) == len(set(seen)), "pagination repeated items"


# ── Identity mapping ─────────────────────────────────────────────────────────


class TestEntityMap:
    def test_same_entity_always_resolves_to_the_same_id(self) -> None:
        """Idempotency matters: webhooks WILL be delivered twice."""
        entity_map = EntityMap()
        key = EntityKey("tn_1", "acme", EntityType.ORDER, "1001")
        assert entity_map.resolve(key) == entity_map.resolve(key)

    def test_two_tenants_can_both_have_order_1001(self) -> None:
        """The collision that scoping by tenant makes structurally impossible."""
        entity_map = EntityMap()
        a = entity_map.resolve(EntityKey("tn_a", "acme", EntityType.ORDER, "1001"))
        b = entity_map.resolve(EntityKey("tn_b", "acme", EntityType.ORDER, "1001"))
        assert a != b

    def test_same_id_on_different_platforms_stays_distinct(self) -> None:
        entity_map = EntityMap()
        a = entity_map.resolve(EntityKey("tn_1", "acme", EntityType.ORDER, "1001"))
        b = entity_map.resolve(EntityKey("tn_1", "other", EntityType.ORDER, "1001"))
        assert a != b

    def test_reverse_lookup_finds_the_platform_entity(self) -> None:
        entity_map = EntityMap()
        key = EntityKey("tn_1", "acme", EntityType.ORDER, "1001")
        assert entity_map.reverse(entity_map.resolve(key)) == key

    def test_empty_external_id_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="external_id"):
            EntityKey("tn_1", "acme", EntityType.ORDER, "")

    def test_offboarding_removes_every_mapping_for_a_tenant(self) -> None:
        """A mapping left behind still links a real person to a real order."""
        entity_map = EntityMap()
        entity_map.resolve(EntityKey("tn_a", "acme", EntityType.ORDER, "1"))
        entity_map.resolve(EntityKey("tn_a", "acme", EntityType.ORDER, "2"))
        kept = entity_map.resolve(EntityKey("tn_b", "acme", EntityType.ORDER, "1"))

        assert entity_map.forget_tenant("tn_a") == 2
        assert len(entity_map) == 1
        assert entity_map.reverse(kept) is not None


# ── Conformance catches bad adapters ─────────────────────────────────────────


class TestConformanceCatchesFailures:
    """A conformance suite that passes everything is worse than none at all."""

    async def test_raising_instead_of_returning_none_is_an_error(self) -> None:
        class RaisesOnMissing(AcmeAdapter):
            async def get_product(self, external_id: str) -> Product | None:
                found = await super().get_product(external_id)
                if found is None:
                    raise KeyError(external_id)
                return found

        report = await run_conformance(RaisesOnMissing())
        assert not report.is_conformant
        assert any("get_product" in f.message for f in report.errors)

    async def test_erroring_on_empty_search_is_an_error(self) -> None:
        class RejectsEmptySearch(AcmeAdapter):
            async def search_products(self, query: ProductQuery) -> Page[Product]:
                if not query.text:
                    raise ValueError("query required")
                return await super().search_products(query)

        report = await run_conformance(RejectsEmptySearch())
        assert not report.is_conformant

    async def test_declaring_no_capabilities_is_an_error(self) -> None:
        """Reachable but useless — the agent would get no tools at all."""

        class DeclaresNothing(AcmeAdapter):
            async def health(self) -> HealthStatus:
                return HealthStatus(ok=True, platform="acme", capabilities=frozenset())

        report = await run_conformance(DeclaresNothing())
        assert not report.is_conformant
        assert any("capabilit" in f.message for f in report.errors)

    async def test_claiming_incremental_sync_without_honouring_it_warns(self) -> None:
        """Worse than not claiming it: we would silently never sync older data."""

        class LiesAboutSync(AcmeAdapter):
            capabilities = AcmeAdapter.capabilities | {Capability.INCREMENTAL_SYNC}

            async def health(self) -> HealthStatus:
                return HealthStatus(ok=True, platform="acme", capabilities=self.capabilities)

        report = await run_conformance(LiesAboutSync())
        assert any("updated_since" in f.message for f in report.warnings)

    async def test_a_cursor_that_never_advances_is_caught(self) -> None:
        """Otherwise sync loops forever, quietly."""

        class StuckCursor(AcmeAdapter):
            async def list_products(
                self, query: SyncQuery, cursor: Cursor | None = None
            ) -> Page[Product]:
                return Page(items=self._products[:2], next_cursor=Cursor(state={"offset": 0}))

        report = await run_conformance(StuckCursor())
        assert not report.is_conformant

    async def test_capability_disagreement_is_flagged(self) -> None:
        """health() and the class attribute disagreeing makes behaviour unpredictable."""

        class Inconsistent(AcmeAdapter):
            async def health(self) -> HealthStatus:
                return HealthStatus(
                    ok=True,
                    platform="acme",
                    capabilities=frozenset({Capability.ORDER_READ}),
                )

        report = await run_conformance(Inconsistent())
        assert any("differ" in f.message for f in report.warnings)

    async def test_report_lists_what_passed(self) -> None:
        report: ConformanceReport = await run_conformance(AcmeAdapter())
        assert "health" in report.passed_checks
        assert all(f.severity is not Severity.ERROR for f in report.findings)


# ── Registry ─────────────────────────────────────────────────────────────────


class TestRegistry:
    def test_unknown_platform_lists_the_alternatives(self) -> None:
        reg = AdapterRegistry()
        reg.register("acme", AcmeAdapter, AcmeAdapter.capabilities)

        with pytest.raises(KeyError, match="acme"):
            reg.create("nonexistent")

    def test_capabilities_readable_without_instantiating(self) -> None:
        """So the UI can show support before credentials are entered."""
        reg = AdapterRegistry()
        reg.register("acme", AcmeAdapter, AcmeAdapter.capabilities)
        assert Capability.ORDER_READ in reg.capabilities_of("acme")
