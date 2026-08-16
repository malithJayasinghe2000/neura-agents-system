"""The PostgreSQL sync stores, against a real PostgreSQL.

These cannot be unit tests, and a fake would defeat their purpose. Everything
here is a property of *PostgreSQL* rather than of our code:

* Row-Level Security actually filtering a catalogue, which is the ADR-0008
  argument applied to the two tables that hold a merchant's products. A fake
  store "proving" isolation proves only that the fake filters.
* ``ON CONFLICT`` on the natural key making a re-run an upsert rather than an
  append, across processes rather than within one.
* **A restart.** The whole point of this milestone is that the synced catalogue
  outlives the process that fetched it, and no in-memory double can be wrong
  about that in the right direction.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).

**The cross-tenant tests here are the ones to keep working.** They only mean
anything because the application connects as a role RLS applies to — if that
regresses to the owner or a superuser they all pass while isolating nothing, so
``ping()`` is asserted first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from neura_commerce import Cursor, EntityKey, EntityType, Page, SyncQuery
from neura_commerce.sync import (
    CrossTenantWriteError,
    PostgresEntityStore,
    PostgresSyncStateStore,
    StoredEntityInvalidError,
    SyncCheckpoint,
    SyncEngine,
    SyncKey,
    fingerprint,
)
from neura_commerce.sync.postgres import DatabaseEntityStore, DatabaseSyncStateStore
from neura_core import Database
from neura_domain import (
    Capability,
    Category,
    Money,
    Policy,
    PolicyKind,
    Product,
    ProductStatus,
)

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 16, tzinfo=UTC)
TENANT_A = "tn_isync_a"
TENANT_B = "tn_isync_b"

# Named for a fictional platform. Test data naming a real one quietly re-couples
# the core to whichever platform was implemented first.
PLATFORM = "acme"


def product(
    tenant: str,
    external_id: str,
    *,
    title: str = "Cast Iron Skillet",
    neura_id: str | None = None,
) -> Product:
    return Product(
        neura_id=neura_id or f"ent_p{external_id}",
        tenant_id=tenant,
        external_id=external_id,
        platform=PLATFORM,
        synced_at=NOW,
        title=title,
        description="Pre-seasoned, oven safe to 260°C.",
        status=ProductStatus.ACTIVE,
        price_range_min=Money(amount=Decimal("49.00"), currency="GBP"),
        price_range_max=Money(amount=Decimal("89.50"), currency="GBP"),
        image_urls=["https://example.test/skillet.jpg"],
        category_ids=["cookware"],
        updated_at=NOW,
        raw={"vendor_internal": {"warehouse": "B2"}},
    )


def key(tenant: str, external_id: str, entity_type: EntityType = EntityType.PRODUCT) -> EntityKey:
    return EntityKey(tenant, PLATFORM, entity_type, external_id)


@pytest.fixture
async def db():
    database = Database.from_settings()

    # A database that is not running is a skip: not everyone has Docker up.
    # A database connected as a role RLS does not apply to is a FAILURE and
    # deliberately not a skip — skipping it is how a suite reports green while
    # the isolation it claims to prove was never in effect.
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")

    yield database

    for tenant in (TENANT_A, TENANT_B):
        async with database.tenant_session(tenant) as session:
            await session.execute(
                text("DELETE FROM synced_entities WHERE tenant_id = :t"), {"t": tenant}
            )
            await session.execute(
                text("DELETE FROM sync_checkpoints WHERE tenant_id = :t"), {"t": tenant}
            )
    await database.dispose()


class TestTenantIsolation:
    """ADR-0008's own acceptance criterion, applied to a merchant's catalogue."""

    async def test_the_connected_role_is_subject_to_rls(self, db: Database) -> None:
        """Everything below is meaningless if this is false."""
        await db.assert_isolation_applies()

    async def test_a_tenant_cannot_read_another_tenants_catalogue(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "1")])

        async with db.tenant_session(TENANT_B) as session:
            store = PostgresEntityStore(session)
            assert await store.get(key(TENANT_A, "1")) is None
            assert await store.count(TENANT_A, PLATFORM, EntityType.PRODUCT) == 0
            assert await store.external_ids(TENANT_A, PLATFORM, EntityType.PRODUCT) == set()
            assert await store.fingerprints(TENANT_A, PLATFORM, EntityType.PRODUCT) == {}

    async def test_a_tenant_cannot_read_another_tenants_checkpoints(self, db: Database) -> None:
        sync_key = SyncKey(TENANT_A, PLATFORM, EntityType.PRODUCT)

        async with db.tenant_session(TENANT_A) as session:
            await PostgresSyncStateStore(session).save(
                SyncCheckpoint(key=sync_key, completed_at=NOW, last_run_count=29)
            )

        async with db.tenant_session(TENANT_B) as session:
            store = PostgresSyncStateStore(session)
            assert await store.load(sync_key) is None
            assert await store.all_for_tenant(TENANT_A) == []

    async def test_a_tenant_cannot_delete_another_tenants_entity(self, db: Database) -> None:
        """A silent no-op, not an error — under RLS the row does not exist.

        The row still being there afterwards is the assertion that matters; a
        ``False`` return alone would also be produced by a delete that worked.
        """
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "1")])

        async with db.tenant_session(TENANT_B) as session:
            assert await PostgresEntityStore(session).delete(key(TENANT_A, "1")) is False

        async with db.tenant_session(TENANT_A) as session:
            assert await PostgresEntityStore(session).get(key(TENANT_A, "1")) is not None

    async def test_writing_another_tenants_entity_is_refused(self, db: Database) -> None:
        """The ``WITH CHECK`` half of the policy.

        Reading being filtered is not enough: without this, a bug that resolved
        the tenant inconsistently would write one merchant's products into
        another's catalogue and every read would then correctly show them.
        """
        async with db.tenant_session(TENANT_B) as session:
            with pytest.raises(CrossTenantWriteError):
                await PostgresEntityStore(session).upsert([product(TENANT_A, "1")])


class TestTheUpsertIsIdempotent:
    """Webhooks arrive twice, backfills overlap incrementals, reconciles rewrite."""

    async def test_the_same_batch_twice_writes_nothing_the_second_time(self, db: Database) -> None:
        batch = [product(TENANT_A, str(i)) for i in range(1, 4)]

        async with db.tenant_session(TENANT_A) as session:
            first = await PostgresEntityStore(session).upsert(batch)
        async with db.tenant_session(TENANT_A) as session:
            store = PostgresEntityStore(session)
            second = await store.upsert(batch)
            total = await store.count(TENANT_A, PLATFORM, EntityType.PRODUCT)

        assert (first.created, first.updated, first.unchanged) == (3, 0, 0)
        assert (second.created, second.updated, second.unchanged) == (0, 0, 3)
        # The claim `unchanged` makes is only true if no row was appended.
        assert total == 3
        assert second.seen == 3
        assert sorted(second.external_ids) == ["1", "2", "3"]

    async def test_an_unchanged_row_does_not_move_its_updated_at(self, db: Database) -> None:
        """``updated_at`` must answer "when did this change", not "when did a
        job run" — otherwise a nightly reconcile makes the whole catalogue look
        freshly edited every morning."""
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "1")])

        before = await _updated_at(db, TENANT_A, "1")

        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "1")])

        assert await _updated_at(db, TENANT_A, "1") == before

    async def test_a_real_edit_does_move_its_updated_at(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "1")])

        before = await _updated_at(db, TENANT_A, "1")

        async with db.tenant_session(TENANT_A) as session:
            result = await PostgresEntityStore(session).upsert(
                [product(TENANT_A, "1", title="Enamelled Skillet")]
            )

        assert result.updated == 1
        assert await _updated_at(db, TENANT_A, "1") > before

    async def test_the_platforms_own_payload_changing_is_not_an_edit(self, db: Database) -> None:
        """``raw`` is outside the fingerprint, so a shop upgrading its software
        must not re-embed a whole catalogue. The stored document keeps the old
        payload as a consequence, which is the accepted cost."""
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "1")])

        noisy = product(TENANT_A, "1").model_copy(update={"raw": {"vendor_internal": "rewritten"}})

        async with db.tenant_session(TENANT_A) as session:
            result = await PostgresEntityStore(session).upsert([noisy])

        assert (result.created, result.updated, result.unchanged) == (0, 0, 1)


class TestIdentityIsStable:
    async def test_a_neura_id_survives_an_edit(self, db: Database) -> None:
        """The adapter mints a fresh id on every fetch. Storing the incoming
        one would give a product a new permanent identity each time a merchant
        edits its title — which only becomes a real defect now that the id
        outlives the process."""
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert(
                [product(TENANT_A, "1", neura_id="ent_original")]
            )

        async with db.tenant_session(TENANT_A) as session:
            store = PostgresEntityStore(session)
            await store.upsert(
                [product(TENANT_A, "1", title="Edited", neura_id="ent_freshly_minted")]
            )
            stored = await store.stored(key(TENANT_A, "1"))

        assert stored is not None
        assert stored.neura_id == "ent_original"
        # The row and the document inside it must not disagree.
        assert stored.entity.neura_id == "ent_original"
        assert stored.entity.title == "Edited"  # type: ignore[attr-defined]


class TestTheDocumentRoundTrips:
    async def test_a_product_survives_the_round_trip_intact(self, db: Database) -> None:
        """ADR-0021's central claim: the canonical model is the only definition,
        and PostgreSQL gives back exactly what it was handed. Money is the part
        to watch — a Decimal that came back as a float would be a wrong price."""
        original = product(TENANT_A, "1")

        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([original])
        async with db.tenant_session(TENANT_A) as session:
            recovered = await PostgresEntityStore(session).get(key(TENANT_A, "1"))

        assert recovered == original
        assert isinstance(recovered, Product)
        assert recovered.price_range_min is not None
        assert recovered.price_range_min.amount == Decimal("49.00")
        assert recovered.raw == {"vendor_internal": {"warehouse": "B2"}}
        # The fingerprint is what reconcile compares, so it has to survive too.
        assert fingerprint(recovered) == fingerprint(original)

    async def test_the_other_synced_types_round_trip_too(self, db: Database) -> None:
        policy = Policy(
            neura_id="ent_returns",
            tenant_id=TENANT_A,
            external_id="returns",
            platform=PLATFORM,
            synced_at=NOW,
            kind=PolicyKind.RETURNS,
            title="Returns",
            body="You may return most items within 30 days of delivery.",
        )
        category = Category(
            neura_id="ent_cookware",
            tenant_id=TENANT_A,
            external_id="cookware",
            platform=PLATFORM,
            synced_at=NOW,
            name="Cookware",
        )

        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([policy, category])
        async with db.tenant_session(TENANT_A) as session:
            store = PostgresEntityStore(session)
            assert await store.get(key(TENANT_A, "returns", EntityType.POLICY)) == policy
            assert await store.get(key(TENANT_A, "cookware", EntityType.CATEGORY)) == category

    async def test_a_corrupted_document_is_an_error_and_not_a_missing_product(
        self, db: Database
    ) -> None:
        """The stated cost of a jsonb column, and the reason it is not silent.

        A store that skipped rows it could not parse would report a shrinking
        catalogue, and "the agent stopped knowing about twelve products" is a
        bug found by a shopper rather than by a test.
        """
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "1")])

        async with db.tenant_session(TENANT_A) as session:
            await session.execute(
                text(
                    "UPDATE synced_entities SET document = document - 'title' "
                    "WHERE tenant_id = :t AND external_id = '1'"
                ),
                {"t": TENANT_A},
            )

        async with db.tenant_session(TENANT_A) as session:
            with pytest.raises(StoredEntityInvalidError):
                await PostgresEntityStore(session).get(key(TENANT_A, "1"))


class TestCheckpoints:
    async def test_a_checkpoint_round_trips_including_its_cursor(self, db: Database) -> None:
        """The cursor is what makes an interrupted crawl of 40,000 products
        resume rather than restart, so it has to survive as a cursor and not as
        an opaque string that no longer decodes."""
        sync_key = SyncKey(TENANT_A, PLATFORM, EntityType.PRODUCT)
        checkpoint = SyncCheckpoint(
            key=sync_key,
            cursor=Cursor(state={"after": "page-7", "seen": 700}),
            updated_through=NOW - timedelta(days=1),
            completed_at=NOW,
            last_run_count=29,
        )

        async with db.tenant_session(TENANT_A) as session:
            await PostgresSyncStateStore(session).save(checkpoint)
        async with db.tenant_session(TENANT_A) as session:
            recovered = await PostgresSyncStateStore(session).load(sync_key)

        assert recovered == checkpoint
        assert recovered is not None
        assert recovered.is_backfilling
        assert recovered.cursor is not None
        assert recovered.cursor.state == {"after": "page-7", "seen": 700}

    async def test_a_finished_crawl_clears_the_cursor(self, db: Database) -> None:
        """Saving twice must overwrite one row, and ``None`` must be written as
        ``None`` rather than left at the previous value — otherwise a completed
        backfill reads as still in progress for ever."""
        sync_key = SyncKey(TENANT_A, PLATFORM, EntityType.PRODUCT)

        async with db.tenant_session(TENANT_A) as session:
            store = PostgresSyncStateStore(session)
            await store.save(SyncCheckpoint(key=sync_key, cursor=Cursor(state={"after": "p1"})))
            await store.save(
                SyncCheckpoint(key=sync_key).finished(at=NOW, count=29, high_water=NOW)
            )

        async with db.tenant_session(TENANT_A) as session:
            recovered = await PostgresSyncStateStore(session).load(sync_key)
            everything = await PostgresSyncStateStore(session).all_for_tenant(TENANT_A)

        assert recovered is not None
        assert recovered.cursor is None
        assert recovered.has_completed_backfill
        assert len(everything) == 1

    async def test_all_for_tenant_returns_every_stream(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            store = PostgresSyncStateStore(session)
            for entity_type in (EntityType.PRODUCT, EntityType.CATEGORY, EntityType.POLICY):
                await store.save(
                    SyncCheckpoint(key=SyncKey(TENANT_A, PLATFORM, entity_type), last_run_count=1)
                )

        async with db.tenant_session(TENANT_A) as session:
            streams = await PostgresSyncStateStore(session).all_for_tenant(TENANT_A)

        assert {c.key.entity_type for c in streams} == {
            EntityType.PRODUCT,
            EntityType.CATEGORY,
            EntityType.POLICY,
        }


class TestTheCatalogueSurvivesARestart:
    """The milestone, stated as a test.

    Everything else here could pass with the in-memory store still in place.
    This is the one that cannot: the second engine shares no object with the
    first, exactly as a redeployed worker shares none with the process it
    replaced.
    """

    async def test_a_second_engine_finds_nothing_to_download(self, db: Database) -> None:
        shop = _Shop(products=6)

        first = await _engine(db, shop).sync_all(incremental=False)
        assert [o.created for o in first] == [6, 1, 1]
        assert all(o.error is None for o in first)
        calls_after_first = shop.calls

        # A different engine, different stores, nothing shared but PostgreSQL.
        second = await _engine(db, shop).sync_all(incremental=True)

        assert [o.created for o in second] == [0, 0, 0]
        assert [o.updated for o in second] == [0, 0, 0]
        assert sum(o.unchanged for o in second) > 0
        # The shop was still asked — an incremental pass that skips the network
        # would also report nothing, and would be wrong for a different reason.
        assert shop.calls > calls_after_first

    async def test_a_restarted_engine_notices_a_real_edit(self, db: Database) -> None:
        """The other half. A run that reports nothing changed is only good news
        if it would have reported a change that happened."""
        shop = _Shop(products=3)
        await _engine(db, shop).sync_all(incremental=False)

        shop.edit("2", "A Different Skillet")
        outcomes = {o.entity_type: o for o in await _engine(db, shop).sync_all(incremental=True)}

        assert outcomes[EntityType.PRODUCT].updated == 1
        assert outcomes[EntityType.PRODUCT].created == 0

        async with db.tenant_session(TENANT_A) as session:
            recovered = await PostgresEntityStore(session).get(key(TENANT_A, "2"))
        assert recovered is not None
        assert recovered.title == "A Different Skillet"  # type: ignore[attr-defined]

    async def test_a_completed_backfill_is_remembered_across_the_restart(
        self, db: Database
    ) -> None:
        """Without this the second run does a *full* backfill and calls it an
        incremental: ``incremental()`` falls back when no crawl has completed,
        and a checkpoint that did not survive looks exactly like one that never
        finished."""
        shop = _Shop(products=3)
        await _engine(db, shop).sync_all(incremental=False)

        async with db.tenant_session(TENANT_A) as session:
            checkpoint = await PostgresSyncStateStore(session).load(
                SyncKey(TENANT_A, PLATFORM, EntityType.PRODUCT)
            )

        assert checkpoint is not None
        assert checkpoint.has_completed_backfill
        assert not checkpoint.is_backfilling

        outcome = await _engine(db, shop).incremental(EntityType.PRODUCT)
        assert outcome.mode == "incremental"
        assert outcome.notes == []


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _updated_at(db: Database, tenant: str, external_id: str) -> datetime:
    async with db.tenant_session(tenant) as session:
        return (
            await session.execute(
                text(
                    "SELECT updated_at FROM synced_entities "
                    "WHERE tenant_id = :t AND external_id = :e"
                ),
                {"t": tenant, "e": external_id},
            )
        ).scalar_one()


def _engine(db: Database, shop: _Shop) -> SyncEngine:
    """A fresh engine over fresh stores — what a restarted worker builds."""
    return SyncEngine(
        shop,  # type: ignore[arg-type]
        tenant_id=TENANT_A,
        entities=DatabaseEntityStore(db, TENANT_A),
        state=DatabaseSyncStateStore(db, TENANT_A),
        page_size=2,
    )


class _Shop:
    """A shop that can be edited between runs.

    Deliberately not the ``FakeShop`` from the unit suite: this one counts
    calls, so a test can tell "nothing changed" apart from "nothing was asked".
    """

    platform = PLATFORM
    capabilities = frozenset(
        {
            Capability.PRODUCT_READ,
            Capability.CATEGORY_READ,
            Capability.POLICY_READ,
            Capability.INCREMENTAL_SYNC,
        }
    )

    def __init__(self, *, products: int) -> None:
        self.calls = 0
        self._products = {
            str(i): product(TENANT_A, str(i), title=f"Cast Iron Skillet {i}")
            for i in range(1, products + 1)
        }

    def edit(self, external_id: str, title: str) -> None:
        self._products[external_id] = product(TENANT_A, external_id, title=title)

    async def list_products(self, query: SyncQuery, cursor: Cursor | None = None) -> Page[Product]:
        self.calls += 1
        items = sorted(self._products.values(), key=lambda p: int(p.external_id))
        offset = int((cursor.state if cursor else {}).get("offset", 0))
        window = items[offset : offset + query.limit]
        following = offset + len(window)
        return Page(
            items=window,
            next_cursor=(Cursor(state={"offset": following}) if following < len(items) else None),
        )

    async def list_categories(self) -> list[Category]:
        self.calls += 1
        return [
            Category(
                neura_id="ent_cookware",
                tenant_id=TENANT_A,
                external_id="cookware",
                platform=PLATFORM,
                synced_at=NOW,
                name="Cookware",
            )
        ]

    async def get_policies(self) -> list[Policy]:
        self.calls += 1
        return [
            Policy(
                neura_id="ent_returns",
                tenant_id=TENANT_A,
                external_id="returns",
                platform=PLATFORM,
                synced_at=NOW,
                kind=PolicyKind.RETURNS,
                title="Returns",
                body="Thirty days.",
            )
        ]
