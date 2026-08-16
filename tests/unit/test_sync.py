"""The sync engine.

Every test here is a failure we expect in production rather than a feature we
hope works: a worker killed mid-crawl, a webhook delivered twice, a webhook
never delivered at all, a shop that rate-limits us, a product deleted while
nobody was looking.

A sync that only works when nothing goes wrong is a sync that has never run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from neura_commerce import (
    AdapterRateLimitedError,
    AdapterUnavailableError,
    Cursor,
    EntityKey,
    EntityType,
    HealthStatus,
    Page,
    ProductQuery,
    SyncQuery,
)
from neura_commerce.sync import (
    InMemoryEntityStore,
    InMemorySyncStateStore,
    SyncEngine,
    SyncKey,
    fingerprint,
)
from neura_domain import (
    CanonicalEntity,
    Capability,
    Category,
    Customer,
    CustomerRef,
    InventoryLevel,
    Money,
    Order,
    Policy,
    PolicyKind,
    Product,
    ProductStatus,
)

NOW = datetime(2026, 7, 1, tzinfo=UTC)
TENANT = "tn_sync"

FULL_CAPABILITIES = frozenset(
    {
        Capability.PRODUCT_READ,
        Capability.CATEGORY_READ,
        Capability.POLICY_READ,
        Capability.ORDER_READ,
        Capability.CUSTOMER_READ,
        Capability.INCREMENTAL_SYNC,
    }
)


class FakeShop:
    """A shop we can break on purpose.

    Named for a fictional platform: test data that names a real one quietly
    re-couples the core to whichever platform was implemented first.
    """

    platform = "acme"

    def __init__(
        self,
        *,
        products: int = 5,
        capabilities: frozenset[Capability] = FULL_CAPABILITIES,
        page_size: int = 2,
    ) -> None:
        self.capabilities = capabilities
        self.page_size = page_size
        self.calls = 0
        self.fail_after: int | None = None
        self.rate_limit_once = False
        self._products = {str(i): self._product(str(i)) for i in range(1, products + 1)}
        self._policies = [self._policy("returns")]
        self._categories = [self._category("cookware")]

    # ── Data the shop holds ──────────────────────────────────────────────────

    def _product(
        self, external_id: str, *, title: str | None = None, updated_at: datetime | None = None
    ) -> Product:
        return Product(
            neura_id=f"ent_p{external_id}",
            tenant_id=TENANT,
            external_id=external_id,
            platform=self.platform,
            synced_at=NOW,
            title=title or f"Cast Iron Skillet {external_id}",
            status=ProductStatus.ACTIVE,
            price_range_min=Money(amount=Decimal("49.00"), currency="USD"),
            updated_at=updated_at or NOW + timedelta(days=int(external_id)),
        )

    def _policy(self, external_id: str) -> Policy:
        return Policy(
            neura_id=f"ent_{external_id}",
            tenant_id=TENANT,
            external_id=external_id,
            platform=self.platform,
            synced_at=NOW,
            kind=PolicyKind.RETURNS,
            title="Returns",
            body="Thirty days.",
        )

    def _category(self, external_id: str) -> Category:
        return Category(
            neura_id=f"ent_{external_id}",
            tenant_id=TENANT,
            external_id=external_id,
            platform=self.platform,
            synced_at=NOW,
            name="Cookware",
        )

    # ── Shop-owner actions the sync has to notice ────────────────────────────

    def edit_product(self, external_id: str, title: str) -> None:
        # A real shop bumps updated_at on an edit. One that does not is invisible
        # to incremental sync — which is precisely why reconcile exists, and is
        # covered by its own test below.
        self._products[external_id] = self._product(
            external_id, title=title, updated_at=NOW + timedelta(days=100)
        )

    def delete_product(self, external_id: str) -> None:
        self._products.pop(external_id, None)

    def add_product(self, external_id: str) -> None:
        self._products[external_id] = self._product(external_id)

    # ── The adapter contract ─────────────────────────────────────────────────

    async def health(self) -> HealthStatus:
        return HealthStatus(ok=True, platform=self.platform, capabilities=self.capabilities)

    async def get_product(self, external_id: str) -> Product | None:
        return self._products.get(external_id)

    async def search_products(self, query: ProductQuery) -> Page[Product]:
        return Page(items=list(self._products.values()))

    async def list_products(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Product]:
        self.calls += 1

        if self.rate_limit_once:
            self.rate_limit_once = False
            raise AdapterRateLimitedError("slow down", retry_after_s=0.01)

        if self.fail_after is not None and self.calls > self.fail_after:
            raise AdapterUnavailableError("the shop fell over")

        items = sorted(self._products.values(), key=lambda p: int(p.external_id))

        if query.updated_since is not None:
            items = [p for p in items if p.updated_at and p.updated_at >= query.updated_since]

        start = int(cursor.state.get("at", 0)) if cursor else 0
        window = items[start : start + self.page_size]
        end = start + len(window)

        return Page(
            items=window,
            next_cursor=Cursor(state={"at": end}) if end < len(items) else None,
        )

    async def list_categories(self) -> list[Category]:
        return list(self._categories)

    async def get_inventory(self, variant_external_ids: list[str]) -> list[InventoryLevel]:
        return []

    async def get_order(self, external_id: str) -> Order | None:
        return None

    async def list_orders(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Order]:
        return Page.empty()

    async def find_orders_for_customer(self, ref: CustomerRef) -> list[Order]:
        return []

    async def get_customer(self, external_id: str) -> Customer | None:
        return None

    async def get_policies(self) -> list[Policy]:
        return list(self._policies)


def engine_for(shop: FakeShop, **kwargs: object) -> tuple[SyncEngine, InMemoryEntityStore]:
    entities = InMemoryEntityStore()
    engine = SyncEngine(
        shop,  # type: ignore[arg-type]
        tenant_id=TENANT,
        entities=entities,
        state=InMemorySyncStateStore(),
        page_size=2,
        **kwargs,  # type: ignore[arg-type]
    )
    return engine, entities


# ── Backfill ─────────────────────────────────────────────────────────────────


async def test_backfill_crawls_every_page() -> None:
    engine, entities = engine_for(FakeShop(products=5))

    outcome = await engine.backfill(EntityType.PRODUCT)

    assert outcome.completed
    assert outcome.created == 5
    assert outcome.pages == 3
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 5


async def test_backfill_is_idempotent() -> None:
    """Running it twice must not duplicate anything or look like 5 edits."""
    engine, entities = engine_for(FakeShop(products=5))

    await engine.backfill(EntityType.PRODUCT)
    second = await engine.backfill(EntityType.PRODUCT, restart=True)

    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged == 5
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 5


async def test_an_interrupted_backfill_resumes_where_it_stopped() -> None:
    """The reason the checkpoint is written after every page.

    A crawl of a large catalogue will be interrupted — by a deploy, a restart, a
    shop having a bad minute. Starting over each time means it never finishes.
    """
    shop = FakeShop(products=9)
    shop.fail_after = 2  # dies during the third page
    engine, entities = engine_for(shop)

    first = await engine.backfill(EntityType.PRODUCT)

    assert not first.completed
    assert first.error is not None
    stored_after_crash = await entities.count(TENANT, "acme", EntityType.PRODUCT)
    assert 0 < stored_after_crash < 9

    shop.fail_after = None
    resumed = await engine.backfill(EntityType.PRODUCT)

    assert resumed.completed
    # Only the remainder was fetched — the pages before the crash were not
    # re-read, which is the entire benefit.
    assert resumed.created == 9 - stored_after_crash
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 9


async def test_a_shop_without_the_capability_syncs_nothing_and_says_so() -> None:
    shop = FakeShop(capabilities=frozenset({Capability.ORDER_READ}))
    engine, entities = engine_for(shop)

    outcome = await engine.backfill(EntityType.PRODUCT)

    assert outcome.created == 0
    assert outcome.notes and "capability" in outcome.notes[0]
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 0


async def test_categories_and_policies_sync_without_pagination() -> None:
    engine, entities = engine_for(FakeShop())

    categories = await engine.backfill(EntityType.CATEGORY)
    policies = await engine.backfill(EntityType.POLICY)

    assert categories.created == 1
    assert policies.created == 1
    assert await entities.count(TENANT, "acme", EntityType.POLICY) == 1


# ── Incremental ──────────────────────────────────────────────────────────────


async def test_incremental_fetches_only_what_changed() -> None:
    shop = FakeShop(products=5)
    engine, _ = engine_for(shop)
    await engine.backfill(EntityType.PRODUCT)

    shop.edit_product("3", title="Renamed Skillet")
    outcome = await engine.incremental(EntityType.PRODUCT)

    assert outcome.completed
    assert outcome.updated == 1
    assert outcome.created == 0


async def test_incremental_without_a_backfill_runs_the_backfill_first() -> None:
    """Otherwise the local copy has holes no later pass will ever fill."""
    engine, entities = engine_for(FakeShop(products=5))

    outcome = await engine.incremental(EntityType.PRODUCT)

    assert outcome.created == 5
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 5


async def test_a_shop_without_incremental_support_falls_back_loudly() -> None:
    """Silently syncing nothing looks exactly like a shop where nothing
    changed, and the local copy rots without a single error anywhere."""
    shop = FakeShop(products=4, capabilities=FULL_CAPABILITIES - {Capability.INCREMENTAL_SYNC})
    engine, entities = engine_for(shop)
    await engine.backfill(EntityType.PRODUCT)

    outcome = await engine.incremental(EntityType.PRODUCT)

    assert "full backfill" in " ".join(outcome.notes)
    assert outcome.unchanged == 4
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 4


# ── Event-driven refresh ─────────────────────────────────────────────────────


async def test_refresh_updates_one_entity() -> None:
    shop = FakeShop(products=3)
    engine, entities = engine_for(shop)
    await engine.backfill(EntityType.PRODUCT)

    shop.edit_product("2", title="Now Called This")
    outcome = await engine.refresh(EntityType.PRODUCT, "2")

    assert outcome.updated == 1
    stored = await entities.get(EntityKey(TENANT, "acme", EntityType.PRODUCT, "2"))
    assert stored is not None
    assert stored.title == "Now Called This"


async def test_a_webhook_delivered_twice_changes_nothing_the_second_time() -> None:
    """Webhooks *will* arrive twice. Idempotency is not optional."""
    shop = FakeShop(products=3)
    engine, entities = engine_for(shop)
    await engine.backfill(EntityType.PRODUCT)
    shop.edit_product("2", title="Edited Once")

    first = await engine.refresh(EntityType.PRODUCT, "2")
    second = await engine.refresh(EntityType.PRODUCT, "2")

    assert first.updated == 1
    assert second.updated == 0
    assert second.unchanged == 1
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 3


async def test_refreshing_something_the_shop_deleted_removes_it_locally() -> None:
    shop = FakeShop(products=3)
    engine, entities = engine_for(shop)
    await engine.backfill(EntityType.PRODUCT)

    shop.delete_product("2")
    outcome = await engine.refresh(EntityType.PRODUCT, "2")

    assert outcome.deleted == 1
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 2


# ── Reconciliation ───────────────────────────────────────────────────────────


async def test_reconcile_finds_nothing_when_everything_agrees() -> None:
    engine, _ = engine_for(FakeShop(products=4))
    await engine.backfill(EntityType.PRODUCT)

    outcome = await engine.reconcile(EntityType.PRODUCT)

    assert outcome.in_sync
    assert outcome.local_count == outcome.source_count == 4


async def test_reconcile_repairs_a_missed_creation() -> None:
    """The dropped webhook nobody noticed."""
    shop = FakeShop(products=3)
    engine, entities = engine_for(shop)
    await engine.backfill(EntityType.PRODUCT)

    shop.add_product("99")  # created in the shop; no webhook arrived
    outcome = await engine.reconcile(EntityType.PRODUCT)

    assert outcome.repaired == 1
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 4


async def test_reconcile_removes_what_the_shop_no_longer_has() -> None:
    """The failure that shows: an agent recommending a deleted product."""
    shop = FakeShop(products=3)
    engine, entities = engine_for(shop)
    await engine.backfill(EntityType.PRODUCT)

    shop.delete_product("1")
    outcome = await engine.reconcile(EntityType.PRODUCT)

    assert outcome.removed == 1
    assert not outcome.in_sync
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 2


async def test_reconcile_catches_an_edit_that_never_reached_us() -> None:
    shop = FakeShop(products=3)
    engine, entities = engine_for(shop)
    await engine.backfill(EntityType.PRODUCT)

    shop.edit_product("2", title="Changed Behind Our Back")
    outcome = await engine.reconcile(EntityType.PRODUCT)

    assert outcome.drifted == 1
    assert outcome.repaired == 1
    stored = await entities.get(EntityKey(TENANT, "acme", EntityType.PRODUCT, "2"))
    assert stored is not None
    assert stored.title == "Changed Behind Our Back"


# ── Rate limiting ────────────────────────────────────────────────────────────


async def test_a_rate_limited_shop_is_retried_not_abandoned() -> None:
    """We must never be the reason a merchant's shop falls over — and equally,
    one 429 must not abandon a sync."""
    shop = FakeShop(products=4)
    shop.rate_limit_once = True
    engine, entities = engine_for(shop)

    outcome = await engine.backfill(EntityType.PRODUCT)

    assert outcome.completed
    assert await entities.count(TENANT, "acme", EntityType.PRODUCT) == 4


async def test_the_rate_limiter_paces_requests() -> None:
    import time

    from neura_commerce.sync import RateLimiter

    limiter = RateLimiter(rate_per_second=50, burst=2)
    started = time.monotonic()

    for _ in range(5):
        await limiter.acquire()

    # Two came free from the burst; the remaining three had to wait for tokens.
    assert time.monotonic() - started >= 3 / 50


async def test_retry_after_is_honoured() -> None:
    import time

    from neura_commerce.sync import RateLimiter

    limiter = RateLimiter(rate_per_second=1000, burst=100)
    limiter.pause(0.05)

    started = time.monotonic()
    await limiter.acquire()

    assert time.monotonic() - started >= 0.04


def test_a_rate_limiter_must_have_a_positive_rate() -> None:
    from neura_commerce.sync import RateLimiter

    with pytest.raises(ValueError):
        RateLimiter(rate_per_second=0)


# ── Fingerprints ─────────────────────────────────────────────────────────────


def test_a_fingerprint_ignores_when_we_looked() -> None:
    """Otherwise every reconcile reports drift on every row, every night."""
    shop = FakeShop()
    first = shop._product("1")
    second = first.model_copy(update={"synced_at": NOW + timedelta(days=30)})

    assert fingerprint(first) == fingerprint(second)


def test_a_fingerprint_notices_a_real_edit() -> None:
    shop = FakeShop()
    before = shop._product("1")
    after = before.model_copy(update={"title": "Something Else"})

    assert fingerprint(before) != fingerprint(after)


def test_a_fingerprint_ignores_the_platforms_own_payload() -> None:
    """`raw` changes when a shop upgrades its software. Re-embedding an entire
    catalogue for that is an expensive way to achieve nothing."""
    shop = FakeShop()
    before = shop._product("1")
    after = before.model_copy(update={"raw": {"vendor_internal": "changed"}})

    assert fingerprint(before) == fingerprint(after)


# ── Orders are deliberately not synced ───────────────────────────────────────


async def test_orders_are_not_part_of_a_routine_sync() -> None:
    """Order status changes fast, and a stale "out for delivery" is worse than
    a slow answer. Orders are read live through the adapter instead (§6.1)."""
    engine, _ = engine_for(FakeShop())

    outcomes = await engine.sync_all()

    assert {o.entity_type for o in outcomes} == {
        EntityType.PRODUCT,
        EntityType.CATEGORY,
        EntityType.POLICY,
    }


# ── Health ───────────────────────────────────────────────────────────────────


async def test_health_reports_what_a_merchant_would_ask_about() -> None:
    engine, _ = engine_for(FakeShop(products=3))
    await engine.backfill(EntityType.PRODUCT)

    health = await engine.health()
    streams = {s["entity_type"]: s for s in health["streams"]}  # type: ignore[union-attr]

    assert streams["product"]["count"] == 3
    assert streams["product"]["last_completed"] is not None
    assert streams["product"]["backfill_in_progress"] is False
    assert streams["policy"]["last_completed"] is None


async def test_a_checkpoint_survives_the_run_that_wrote_it() -> None:
    state = InMemorySyncStateStore()
    shop = FakeShop(products=4)
    engine = SyncEngine(
        shop,  # type: ignore[arg-type]
        tenant_id=TENANT,
        entities=InMemoryEntityStore(),
        state=state,
        page_size=2,
    )

    await engine.backfill(EntityType.PRODUCT)
    checkpoint = await state.load(SyncKey(TENANT, "acme", EntityType.PRODUCT))

    assert checkpoint is not None
    assert checkpoint.has_completed_backfill
    assert not checkpoint.is_backfilling
    assert checkpoint.updated_through is not None


# ── Identity survives an edit ────────────────────────────────────────────────


async def test_a_stored_neura_id_survives_a_content_change() -> None:
    """An adapter mints a fresh ``neura_id`` on every fetch.

    Writing the incoming one would give a product a new permanent identity each
    time a merchant edits its title, which is the exact opposite of what
    ``identity.py`` exists for — and it only becomes visible once the store is
    durable, because in memory nobody outlives the process that holds the ids.
    """
    shop = FakeShop()
    store = InMemoryEntityStore()
    key = EntityKey(TENANT, shop.platform, EntityType.PRODUCT, "1")

    await store.upsert([shop._product("1")])
    original = await store.get(key)
    assert original is not None

    edited = shop._product("1", title="A New Title").model_copy(
        update={"neura_id": "ent_freshly_minted"}
    )
    result = await store.upsert([edited])

    assert result.updated == 1
    after = await store.get(key)
    assert after is not None
    assert after.title == "A New Title"
    # Both the row's id and the entity inside it, or a reader gets two answers.
    assert after.neura_id == original.neura_id
    assert store._rows[key.as_tuple()].neura_id == original.neura_id


# ── What a stored document deserialises to ───────────────────────────────────


def test_every_synced_entity_type_maps_to_a_canonical_model() -> None:
    """Both directions of the map live in one module so a new entity type
    cannot be added to one and forgotten in the other."""
    from neura_commerce.sync import model_for

    for entity_type in (
        EntityType.PRODUCT,
        EntityType.CATEGORY,
        EntityType.POLICY,
        EntityType.ORDER,
        EntityType.CUSTOMER,
    ):
        assert issubclass(model_for(entity_type), CanonicalEntity)


def test_a_variant_is_not_a_stored_entity() -> None:
    """A variant is a field of a Product, not an entity with provenance of its
    own. A store asked for one should say so rather than guess."""
    from neura_commerce.sync import model_for

    with pytest.raises(ValueError, match="variant"):
        model_for(EntityType.VARIANT)


# ── The schema, as a contract ────────────────────────────────────────────────


def test_the_entity_primary_key_is_exactly_an_entity_key() -> None:
    """A surrogate id would permit two rows for one entity — the single failure
    the store contract says must be structurally impossible."""
    from neura_commerce.sync import synced_entities

    assert [c.name for c in synced_entities.primary_key.columns] == [
        "tenant_id",
        "platform",
        "entity_type",
        "external_id",
    ]


def test_the_checkpoint_primary_key_is_exactly_a_sync_key() -> None:
    from neura_commerce.sync import sync_checkpoints

    assert [c.name for c in sync_checkpoints.primary_key.columns] == [
        "tenant_id",
        "platform",
        "entity_type",
    ]


def test_both_sync_tables_carry_a_tenant_id() -> None:
    """Which is what puts them in reach of the ADR-0008 protection test — the
    integration suite finds tenant-scoped tables by this column, so a table
    without one is a table nothing checks for a policy."""
    from neura_commerce.sync import sync_checkpoints, synced_entities

    for table in (synced_entities, sync_checkpoints):
        assert "tenant_id" in table.c


def test_an_entity_is_stored_as_a_document_not_as_a_second_schema() -> None:
    """ADR-0021. If this fails, someone has started defining the canonical
    model in PostgreSQL as well as in neura-domain — which is a superseding
    ADR, not a column."""
    from neura_commerce.sync import synced_entities

    assert set(synced_entities.c.keys()) == {
        "tenant_id",
        "platform",
        "entity_type",
        "external_id",
        "neura_id",
        "fingerprint",
        "document",
        "created_at",
        "updated_at",
    }
