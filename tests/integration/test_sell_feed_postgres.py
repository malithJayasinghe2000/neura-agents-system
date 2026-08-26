"""The product feed, against a real PostgreSQL.

None of this can be a unit test, because every property below belongs to the
database rather than to our code:

* **The token resolves through the ADR-0014 bootstrap.** `credential_session`
  sets `app.api_key_hash` and no `app.tenant_id`, and the policy on `sell_feeds`
  is what turns that into exactly one readable row. A fake would prove only that
  the fake filtered.
* **One tenant's feed cannot reach another tenant's catalogue.** This is the
  single worst thing this surface could do: the feed is the only unauthenticated
  endpoint in the system, so if the token ever named the wrong tenant, one
  merchant's whole catalogue is published at another merchant's public URL.
* **A rotated token stops resolving**, which is the entire revocation story
  (ADR-0024) and lives in a `WHERE rotated_at IS NULL` that only a real query
  runs.

Run with ``make test-integration`` (needs ``make up`` and ``make migrate``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, text, update

from neura_agent_sell.feed import build, canonical, jsonld, publishable
from neura_agent_sell.feed import tokens as feed_tokens
from neura_agent_sell.feed.schema import sell_feeds
from neura_commerce import EntityType
from neura_commerce.sync import DatabaseEntityStore, PostgresEntityStore
from neura_core import Database
from neura_domain import Money, Product, ProductStatus, ProductVariant

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 20, 9, 30, tzinfo=UTC)
TENANT_A = "tn_ifeed_a"
TENANT_B = "tn_ifeed_b"
STORE_A = "st_ifeed_a"
STORE_B = "st_ifeed_b"

#: A fictional platform, for the reason test_sync_postgres.py gives: test data
#: naming a real one quietly re-couples the core to whichever was built first.
PLATFORM = "acme"


def product(tenant: str, external_id: str, *, title: str = "Cast Iron Skillet") -> Product:
    """A product as the sync engine stores it — provenance and `raw` included."""
    return Product(
        neura_id=f"prd_{tenant}_{external_id}",
        tenant_id=tenant,
        external_id=external_id,
        platform=PLATFORM,
        synced_at=NOW,
        raw={"cost_price": "12.00", "supplier": "Northwind Ltd"},
        title=title,
        status=ProductStatus.ACTIVE,
        price_range_min=Money(amount="24.00", currency="GBP"),
        price_range_max=Money(amount="24.00", currency="GBP"),
        variants=[
            ProductVariant(
                external_id=f"{external_id}-v1",
                sku=f"SKU-{external_id}",
                price=Money(amount="24.00", currency="GBP"),
                in_stock=True,
            )
        ],
    )


@pytest.fixture
async def db():
    database = Database.from_settings()

    # Not running is a skip. Connected as a role RLS does not apply to is a
    # FAILURE — skipping that is how a suite reports green while the isolation
    # it claims to prove was never in effect.
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")

    yield database

    for tenant in (TENANT_A, TENANT_B):
        async with database.tenant_session(tenant) as session:
            await session.execute(
                text("DELETE FROM synced_entities WHERE tenant_id = :t"), {"t": tenant}
            )
            await session.execute(
                text("DELETE FROM sell_feeds WHERE tenant_id = :t"), {"t": tenant}
            )
    await database.dispose()


async def publish(db: Database, tenant: str, store: str, *, feed_id: str) -> str:
    """Turn publication on for a store and return the plaintext token."""
    issued = feed_tokens.generate()
    async with db.tenant_session(tenant) as session:
        await session.execute(
            insert(sell_feeds).values(
                id=feed_id,
                tenant_id=tenant,
                store_id=store,
                token_prefix=issued.token_prefix,
                token_hash=issued.token_hash,
            )
        )
    return issued.token


class TestTheTokenResolves:
    async def test_the_connected_role_is_subject_to_rls(self, db: Database) -> None:
        """Everything below is meaningless if this is false."""
        await db.assert_isolation_applies()

    async def test_a_published_token_names_its_own_tenant(self, db: Database) -> None:
        token = await publish(db, TENANT_A, STORE_A, feed_id="feed_a1")

        resolved = await feed_tokens.resolve(db, token)

        assert resolved is not None
        assert resolved.tenant_id == TENANT_A
        assert resolved.store_id == STORE_A

    async def test_an_unknown_token_resolves_to_nothing(self, db: Database) -> None:
        assert await feed_tokens.resolve(db, feed_tokens.generate().token) is None

    async def test_a_malformed_token_never_reaches_the_database(self, db: Database) -> None:
        """A public URL is scanned constantly.

        `/v1/sell/feed/wp-admin/products.json` must cost a regex, not a
        connection from the pool.
        """
        assert not feed_tokens.is_well_formed("wp-admin")
        assert await feed_tokens.resolve(db, "wp-admin") is None

    async def test_a_rotated_token_stops_resolving(self, db: Database) -> None:
        """The whole revocation story (ADR-0024)."""
        token = await publish(db, TENANT_A, STORE_A, feed_id="feed_a2")
        assert await feed_tokens.resolve(db, token) is not None

        async with db.tenant_session(TENANT_A) as session:
            await session.execute(
                update(sell_feeds)
                .where(sell_feeds.c.id == "feed_a2")
                .values(rotated_at=datetime.now(UTC))
            )

        assert await feed_tokens.resolve(db, token) is None


class TestOneTenantsFeedCannotReachAnother:
    """The worst thing this surface could do, tested directly."""

    async def test_a_feed_row_is_invisible_to_another_tenant(self, db: Database) -> None:
        await publish(db, TENANT_A, STORE_A, feed_id="feed_a3")

        async with db.tenant_session(TENANT_B) as session:
            rows = (
                await session.execute(text("SELECT id FROM sell_feeds WHERE id = 'feed_a3'"))
            ).all()

        assert rows == []

    async def test_a_token_never_names_the_other_tenants_catalogue(self, db: Database) -> None:
        """The end-to-end version, and the one that matters.

        Both tenants publish. Each token is resolved and its catalogue read
        through the tenant the token named — which is exactly what the route
        does. If the token ever named the wrong tenant, one merchant's whole
        catalogue appears at another merchant's public URL.
        """
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert(
                [product(TENANT_A, "a1", title="Tenant A Skillet")]
            )
        async with db.tenant_session(TENANT_B) as session:
            await PostgresEntityStore(session).upsert(
                [product(TENANT_B, "b1", title="Tenant B Kettle")]
            )

        token_a = await publish(db, TENANT_A, STORE_A, feed_id="feed_a4")
        token_b = await publish(db, TENANT_B, STORE_B, feed_id="feed_b4")

        titles_a = await _titles_via(db, token_a)
        titles_b = await _titles_via(db, token_b)

        assert titles_a == ["Tenant A Skillet"]
        assert titles_b == ["Tenant B Kettle"]


class TestTheServedDocument:
    async def test_it_publishes_the_catalogue_and_none_of_its_provenance(
        self, db: Database
    ) -> None:
        """The allowlist, proved on data that made a real round trip.

        The unit tests assert this on constructed objects. This one asserts it
        on a document that went through `jsonb`, came back out and was
        re-validated — which is where a `model_dump()` would have quietly
        reappeared.
        """
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "a5")])

        token = await publish(db, TENANT_A, STORE_A, feed_id="feed_a5")
        rendered = await _render_via(db, token)

        assert "Cast Iron Skillet" in rendered
        for private in ("cost_price", "Northwind", PLATFORM, TENANT_A, "prd_"):
            assert private not in rendered, private

    async def test_a_price_survives_the_round_trip_exactly(self, db: Database) -> None:
        """`24.00` through jsonb and back is still `24.00`, not `24.0`."""
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "a6")])

        token = await publish(db, TENANT_A, STORE_A, feed_id="feed_a6")
        document = await _document_via(db, token)
        offer = jsonld.render(document)["itemListElement"][0]["item"]["offers"]

        assert offer["price"] == "24.00"
        assert isinstance(offer["price"], str)

    async def test_the_timestamp_is_the_syncs_not_the_serves(self, db: Database) -> None:
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert([product(TENANT_A, "a7")])

        token = await publish(db, TENANT_A, STORE_A, feed_id="feed_a7")
        document = await _document_via(db, token)

        assert document.synced_at == NOW
        assert canonical.render(document)["synced_at"] == NOW.isoformat()

    async def test_a_page_resumes_where_the_last_one_stopped(self, db: Database) -> None:
        """Keyset pagination over a real index, not an OFFSET."""
        async with db.tenant_session(TENANT_A) as session:
            await PostgresEntityStore(session).upsert(
                [product(TENANT_A, f"p{i:03d}") for i in range(5)]
            )

        store = DatabaseEntityStore(db, TENANT_A)
        first = await store.page(TENANT_A, PLATFORM, EntityType.PRODUCT, limit=2)
        second = await store.page(
            TENANT_A, PLATFORM, EntityType.PRODUCT, limit=2, after=first.next_after
        )
        last = await store.page(
            TENANT_A, PLATFORM, EntityType.PRODUCT, limit=10, after=second.next_after
        )

        assert [e.external_id for e in first.entities] == ["p000", "p001"]
        assert [e.external_id for e in second.entities] == ["p002", "p003"]
        assert [e.external_id for e in last.entities] == ["p004"]
        # The last page says so, rather than leaving a caller to infer it from a
        # short result — a short page and a final page are different things the
        # moment a limit and a catalogue size coincide.
        assert last.next_after is None


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _document_via(db: Database, token: str):
    """Exactly what the route does: resolve the token, then read as that tenant."""
    feed = await feed_tokens.resolve(db, token)
    assert feed is not None

    page = await DatabaseEntityStore(db, feed.tenant_id).page(
        feed.tenant_id, PLATFORM, EntityType.PRODUCT, limit=500
    )
    return build(
        publishable(list(page.entities), may_assert_availability=True),
        availability_asserted=True,
    )


async def _titles_via(db: Database, token: str) -> list[str]:
    return [p.title for p in (await _document_via(db, token)).products]


async def _render_via(db: Database, token: str) -> str:
    document = await _document_via(db, token)
    return json.dumps(canonical.render(document)) + json.dumps(jsonld.render(document))
