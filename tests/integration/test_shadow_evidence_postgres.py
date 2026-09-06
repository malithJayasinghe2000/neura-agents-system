"""Captured evidence against real PostgreSQL — [ADR-0034] §3, §4, §7.

Integration rather than unit for the reason the other files here give: the
interesting assertions are about what the *database* enforces, and a test that
stubbed it would prove the stub.

Three properties, and each one fails silently if it is wrong:

1. **Isolation.** An evidence row holds a merchant's catalogue. RLS is the
   control, and a policy that was never created looks identical to one that
   works until two tenants exist.
2. **Store scoping.** The data model permits several stores per tenant and two
   of them may use the same ``external_id`` for different products — so a bundle
   that could not say which store it came from would replay the wrong catalogue,
   quietly.
3. **Immutability, and the transaction.** Evidence that could be replaced would
   change what an already-promoted case replays; evidence written outside the
   turn's transaction would leave a turn that is promotable or not depending on
   nothing anybody can see.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select, text

from neura_agent_core.evidence import (
    EvidenceBundle,
    EvidenceError,
    RecordedCall,
    call_key,
)
from neura_agent_core.shadow import ShadowRepository, ShadowTurn
from neura_agent_core.shadow_evidence import ShadowEvidenceRepository, shadow_evidence
from neura_core import Database, load_env

pytestmark = pytest.mark.integration

TENANT = "tn_evidence_a"
OTHER = "tn_evidence_b"


@pytest.fixture
async def db():
    load_env()
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    yield database
    for tenant in (TENANT, OTHER):
        async with database.tenant_session(tenant) as session:
            await session.execute(
                delete(shadow_evidence).where(shadow_evidence.c.tenant_id == tenant)
            )
    await database.dispose()


def _bundle(*, store_id: str = "st_one", title: str = "Lightweight Rain Shell") -> EvidenceBundle:
    """One captured turn. ``external_id`` is the same in both stores on purpose."""
    arguments = {"external_id": "1315"}
    return EvidenceBundle(
        store_id=store_id,
        captured_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        calls=[
            RecordedCall(
                method="get_product",
                key=call_key("get_product", arguments),
                arguments=arguments,
                result={"external_id": "1315", "title": title},
            )
        ],
        tools=["get_product_details"],
        entities={"products": [{"external_id": "1315", "title": title}]},
    )


async def _turn(session, tenant: str) -> str:
    return await ShadowRepository(session).record(
        ShadowTurn(
            tenant_id=tenant,
            conversation_id="cnv_evidence",
            message_id="msg_evidence",
            agent_key="care",
            mode="shadow",
            state="answered",
            draft="Most items may be returned within 30 days.",
        )
    )


class TestItIsWrittenWithTheTurn:
    async def test_a_turn_and_its_evidence_commit_together(self, db: Database) -> None:
        """[ADR-0034] §3."""
        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)
            await ShadowEvidenceRepository(session).record(TENANT, turn_id, _bundle())

        async with db.tenant_session(TENANT) as session:
            stored = await ShadowEvidenceRepository(session).get(TENANT, turn_id)

        assert stored is not None
        assert stored.calls[0].result["title"] == "Lightweight Rain Shell"

    async def test_a_rolled_back_turn_leaves_no_evidence(self, db: Database) -> None:
        """The other half of "cannot come apart"."""
        with pytest.raises(RuntimeError):
            async with db.tenant_session(TENANT) as session:
                turn_id = await _turn(session, TENANT)
                await ShadowEvidenceRepository(session).record(TENANT, turn_id, _bundle())
                raise RuntimeError("the turn failed after both writes")

        async with db.tenant_session(TENANT) as session:
            rows = (
                await session.execute(
                    select(shadow_evidence).where(shadow_evidence.c.tenant_id == TENANT)
                )
            ).all()

        assert rows == []

    async def test_a_turn_with_no_evidence_reads_back_as_none(self, db: Database) -> None:
        """Every turn graded before 2026-09-06 is this, and promotion turns it
        into a refusal rather than reconstructing anything."""
        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)

        async with db.tenant_session(TENANT) as session:
            assert await ShadowEvidenceRepository(session).get(TENANT, turn_id) is None


class TestItIsImmutable:
    async def test_a_second_capture_is_refused(self, db: Database) -> None:
        """[ADR-0034] §4. Replacing it would change what a promoted case replays."""
        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)
            repository = ShadowEvidenceRepository(session)
            await repository.record(TENANT, turn_id, _bundle())

            with pytest.raises(EvidenceError, match="immutable"):
                await repository.record(TENANT, turn_id, _bundle(title="Something Else"))

    async def test_the_repository_offers_no_update(self) -> None:
        """Asserted as an absence, because the absence is the design."""
        assert not hasattr(ShadowEvidenceRepository, "update")
        assert not hasattr(ShadowEvidenceRepository, "replace")

    async def test_the_content_hash_is_stored_beside_the_bundle(self, db: Database) -> None:
        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)
            written = await ShadowEvidenceRepository(session).record(TENANT, turn_id, _bundle())

        async with db.tenant_session(TENANT) as session:
            row = (
                await session.execute(
                    select(shadow_evidence.c.content_hash).where(
                        shadow_evidence.c.shadow_turn_id == turn_id
                    )
                )
            ).scalar_one()

        assert row == written == _bundle().content_hash()


class TestTenantIsolation:
    async def test_one_tenant_cannot_read_anothers_evidence(self, db: Database) -> None:
        """The row holds a merchant's catalogue. RLS is the control."""
        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)
            await ShadowEvidenceRepository(session).record(TENANT, turn_id, _bundle())

        async with db.tenant_session(OTHER) as session:
            assert await ShadowEvidenceRepository(session).get(TENANT, turn_id) is None
            rows = (await session.execute(select(shadow_evidence))).all()

        assert rows == [], "another tenant's evidence was visible"

    async def test_the_policy_exists_and_is_forced(self, db: Database) -> None:
        """A policy that was never created looks exactly like one that works,
        until two tenants exist. `test_migrations.py` makes the same argument."""
        async with db.tenant_session(TENANT) as session:
            enabled = (
                await session.execute(
                    text(
                        "SELECT relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE relname = 'shadow_evidence'"
                    )
                )
            ).one()
            policies = (
                (
                    await session.execute(
                        text(
                            "SELECT policyname FROM pg_policies WHERE tablename = 'shadow_evidence'"
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert enabled == (True, True)
        assert "tenant_isolation" in policies


class TestStoreScoping:
    async def test_two_stores_may_use_the_same_external_id(self, db: Database) -> None:
        """[ADR-0034] §7, and the reason `store_id` is a column.

        A tenant with two shops can legitimately have a product `1315` in each,
        and they are different products. Evidence that could not say which store
        it came from would replay one shop's catalogue for the other's turn.
        """
        async with db.tenant_session(TENANT) as session:
            first = await _turn(session, TENANT)
            second = await _turn(session, TENANT)
            repository = ShadowEvidenceRepository(session)
            await repository.record(
                TENANT, first, _bundle(store_id="st_one", title="Rain Shell (shop one)")
            )
            await repository.record(
                TENANT, second, _bundle(store_id="st_two", title="Rain Shell (shop two)")
            )

        async with db.tenant_session(TENANT) as session:
            repository = ShadowEvidenceRepository(session)
            one = await repository.get(TENANT, first)
            two = await repository.get(TENANT, second)

        assert one is not None and two is not None
        assert one.store_id == "st_one" and two.store_id == "st_two"
        assert one.calls[0].result["title"] != two.calls[0].result["title"]
        assert one.content_hash() != two.content_hash(), (
            "two stores' captures must be different artefacts"
        )


class TestReplayDoesNotDependOnPresentState:
    async def test_changing_the_synced_catalogue_does_not_change_a_replay(
        self, db: Database
    ) -> None:
        """The whole argument for capturing at turn time, asserted end to end.

        The rejected design rebuilt a case's store from `synced_entities`. Under
        it, editing a product would silently change what an already-promoted case
        asserts against. Under this one it cannot, because the replay never reads
        that table.
        """
        from neura_agent_core.evidence import ReplayAdapter

        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)
            await ShadowEvidenceRepository(session).record(
                TENANT, turn_id, _bundle(title="Lightweight Rain Shell")
            )

        # The shop moves on: a re-sync, a renamed product, a new price. Nothing
        # here touches `shadow_evidence`, and that is the point.
        async with db.tenant_session(TENANT) as session:
            await session.execute(
                text(
                    "INSERT INTO synced_entities "
                    "(tenant_id, platform, entity_type, external_id, neura_id, "
                    " fingerprint, document) "
                    "VALUES (:t, 'fixture', 'product', '1315', 'ne_x', 'ffff', "
                    ' \'{"title": "Renamed Since"}\'::jsonb) '
                    "ON CONFLICT (tenant_id, platform, entity_type, external_id) "
                    "DO UPDATE SET document = EXCLUDED.document"
                ),
                {"t": TENANT},
            )

        async with db.tenant_session(TENANT) as session:
            stored = await ShadowEvidenceRepository(session).get(TENANT, turn_id)
            await session.execute(
                text("DELETE FROM synced_entities WHERE tenant_id = :t"), {"t": TENANT}
            )

        assert stored is not None
        product = await ReplayAdapter(stored, tenant_id=TENANT).get_product("1315")
        assert product.title == "Lightweight Rain Shell", (
            "the replay read present state instead of what the turn captured"
        )


class TestTheDatabaseEnforcesImmutability:
    """[ADR-0034] §4 — and it is the *database* that must, not a method.

    Before 2026-09-06 immutability was `record` refusing a second bundle. That
    stops one caller. It does not stop a second connection, a psql session, or
    the next repository method somebody adds — and an evidence row changed
    underneath an already-promoted case changes what a `synthetic: false`
    assertion rests on.
    """

    async def test_the_app_role_has_no_update_privilege(self, db: Database) -> None:
        async with db.tenant_session(TENANT) as session:
            granted = set(
                (
                    await session.execute(
                        text(
                            "SELECT privilege_type FROM information_schema.role_table_grants "
                            "WHERE table_name = 'shadow_evidence' AND grantee = 'neura_app'"
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert "UPDATE" not in granted, "the app role can still rewrite evidence"
        assert {"SELECT", "INSERT", "DELETE"} <= granted, (
            "capture, promotion and retention all still need their privilege"
        )

    async def test_a_direct_update_is_refused(self, db: Database) -> None:
        """The assertion that matters: not "no method does it", but "it cannot be done"."""
        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)
            await ShadowEvidenceRepository(session).record(TENANT, turn_id, _bundle())

        with pytest.raises(Exception) as caught:
            async with db.tenant_session(TENANT) as session:
                await session.execute(
                    text(
                        "UPDATE shadow_evidence SET content_hash = 'tampered' WHERE tenant_id = :t"
                    ),
                    {"t": TENANT},
                )

        assert "permission denied" in str(caught.value).lower()

    async def test_the_row_is_unchanged_after_the_refused_update(self, db: Database) -> None:
        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)
            written = await ShadowEvidenceRepository(session).record(TENANT, turn_id, _bundle())

        with contextlib.suppress(Exception):
            async with db.tenant_session(TENANT) as session:
                await session.execute(text("UPDATE shadow_evidence SET content_hash = 'tampered'"))

        async with db.tenant_session(TENANT) as session:
            stored = (
                await session.execute(
                    select(shadow_evidence.c.content_hash).where(
                        shadow_evidence.c.shadow_turn_id == turn_id
                    )
                )
            ).scalar_one()

        assert stored == written


class TestEvidenceLivesAndDiesWithItsTurn:
    """[ADR-0034] §3 — the lifecycle, enforced by a cascade rather than by memory."""

    async def test_deleting_the_turn_deletes_its_evidence(self, db: Database) -> None:
        """A merchant's catalogue must not outlive the turn it was captured for.

        A retention sweep that has to *remember* a second table is one that
        eventually forgets — which is open question S10's shape, and the reason
        this is a foreign key rather than a line in a runbook.
        """
        async with db.tenant_session(TENANT) as session:
            turn_id = await _turn(session, TENANT)
            await ShadowEvidenceRepository(session).record(TENANT, turn_id, _bundle())

        async with db.tenant_session(TENANT) as session:
            await session.execute(
                text("DELETE FROM shadow_turns WHERE tenant_id = :t AND id = :i"),
                {"t": TENANT, "i": turn_id},
            )

        async with db.tenant_session(TENANT) as session:
            rows = (
                await session.execute(
                    select(shadow_evidence).where(shadow_evidence.c.shadow_turn_id == turn_id)
                )
            ).all()

        assert rows == [], "the merchant's catalogue outlived the turn it belonged to"

    async def test_evidence_cannot_be_orphaned(self, db: Database) -> None:
        """A row referencing no turn is unpromotable and outside the cascade that
        is supposed to be its lifecycle — so it must not be insertable at all."""
        with pytest.raises(Exception) as caught:
            async with db.tenant_session(TENANT) as session:
                await ShadowEvidenceRepository(session).record(
                    TENANT, "msg_no_such_turn", _bundle()
                )

        assert "foreign key" in str(caught.value).lower()

    async def test_it_cannot_hang_off_another_tenants_turn(self, db: Database) -> None:
        """Why the key is composite. A single-column reference would permit this."""
        async with db.tenant_session(OTHER) as session:
            other_turn = await _turn(session, OTHER)

        with pytest.raises(Exception) as caught:
            async with db.tenant_session(TENANT) as session:
                await ShadowEvidenceRepository(session).record(TENANT, other_turn, _bundle())

        assert "foreign key" in str(caught.value).lower()


def _promote_module() -> Any:
    """`scripts/promote_turn.py`, loaded by path — it is a script, not a package."""
    spec = importlib.util.spec_from_file_location(
        "promote_turn", Path(__file__).resolve().parents[2] / "scripts/promote_turn.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _connect_store(session: Any, tenant: str, store_id: str, platform: str) -> None:
    """A store row, written directly.

    The real connect path encrypts credentials against the KEK, and none of that
    is what these tests are about — they are about whether `synced_entities` can
    be attributed to a store, which is decided by `(id, platform)` alone.
    """
    await session.execute(
        text(
            "INSERT INTO tenant_stores "
            "(id, tenant_id, platform, base_url, credentials, wrapped_dek) "
            "VALUES (:i, :t, :p, :u, 'x', 'x') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        # Unique per store: `tenant_stores` is unique on
        # (tenant_id, platform, base_url), so two shops on one platform are
        # only legal at different URLs — which is exactly the real case.
        {"i": store_id, "t": tenant, "p": platform, "u": f"https://{store_id}.test"},
    )


class TestStalenessKnowsWhichStoreItIsCheckingAgainst:
    """Fix 4 — and the gap it refuses around is recorded as open question C5.

    `synced_entities` is keyed `(tenant_id, platform, entity_type, external_id)`
    and has **no `store_id`**, while `tenant_stores` has always allowed several
    stores per tenant. Scoping by platform is exact when a tenant's shops run
    different software and impossible when they do not, and every case it cannot
    answer **refuses** — because a staleness check that compares against the
    wrong shop and reports "unchanged" is worse than no staleness check.
    """

    @pytest.fixture(autouse=True)
    async def _clean_stores(self, db: Database):
        yield
        async with db.tenant_session(TENANT) as session:
            await session.execute(
                text("DELETE FROM tenant_stores WHERE tenant_id = :t"), {"t": TENANT}
            )

    async def test_one_store_resolves_to_its_platform(self, db: Database) -> None:
        module = _promote_module()
        async with db.tenant_session(TENANT) as session:
            await _connect_store(session, TENANT, "st_one", "generic")

            platform, refusal = await module.store_scope(session, TENANT, "st_one")

        assert (platform, refusal) == ("generic", None)

    async def test_two_stores_on_different_platforms_still_resolve(self, db: Database) -> None:
        """Platform is real data from `tenant_stores`, not an invented mapping,
        and it is exact in this case."""
        module = _promote_module()
        async with db.tenant_session(TENANT) as session:
            await _connect_store(session, TENANT, "st_one", "generic")
            await _connect_store(session, TENANT, "st_two", "fixture")

            platform, refusal = await module.store_scope(session, TENANT, "st_two")

        assert (platform, refusal) == ("fixture", None)

    async def test_two_stores_on_one_platform_refuse(self, db: Database) -> None:
        """The gap. `synced_entities` cannot say which shop a product came from,
        so nothing here pretends to know (C5)."""
        module = _promote_module()
        async with db.tenant_session(TENANT) as session:
            await _connect_store(session, TENANT, "st_one", "generic")
            await _connect_store(session, TENANT, "st_two", "generic")

            platform, refusal = await module.store_scope(session, TENANT, "st_one")

        assert platform is None
        assert refusal and "no store_id column" in refusal

    async def test_a_tenant_with_no_store_refuses(self, db: Database) -> None:
        module = _promote_module()
        async with db.tenant_session(TENANT) as session:
            platform, refusal = await module.store_scope(session, TENANT, "st_one")

        assert platform is None
        assert refusal and "no connected store" in refusal

    async def test_evidence_from_a_disconnected_store_refuses(self, db: Database) -> None:
        module = _promote_module()
        async with db.tenant_session(TENANT) as session:
            await _connect_store(session, TENANT, "st_one", "generic")

            platform, refusal = await module.store_scope(session, TENANT, "st_gone")

        assert platform is None
        assert refusal and "no longer connected" in refusal

    async def test_stale_entities_compares_against_the_right_store(self, db: Database) -> None:
        """The behaviour all of the above exists to protect.

        Two shops, two platforms, each with a product `1315`. The other shop's
        row must not answer for this one — under a tenant-wide scan it would,
        and the answer would be "this entity changed" for a shop that did not.
        """
        module = _promote_module()
        bundle = _bundle(store_id="st_one", title="Rain Shell")
        captured = module.fingerprint({"external_id": "1315", "title": "Rain Shell"})
        bundle = bundle.model_copy(update={"source_fingerprints": {"products:1315": captured}})

        async with db.tenant_session(TENANT) as session:
            await _connect_store(session, TENANT, "st_one", "generic")
            await _connect_store(session, TENANT, "st_two", "fixture")
            for platform, title in (("generic", "Rain Shell"), ("fixture", "A Different Product")):
                await session.execute(
                    text(
                        "INSERT INTO synced_entities (tenant_id, platform, entity_type, "
                        "external_id, neura_id, fingerprint, document) VALUES "
                        "(:t, :p, 'product', '1315', :n, 'ffff', CAST(:d AS jsonb)) "
                        "ON CONFLICT (tenant_id, platform, entity_type, external_id) "
                        "DO UPDATE SET document = EXCLUDED.document"
                    ),
                    {
                        "t": TENANT,
                        "p": platform,
                        "n": f"ne_{platform}",
                        "d": json.dumps({"external_id": "1315", "title": title}),
                    },
                )

            moved, refusal = await module.stale_entities(session, TENANT, bundle)
            await session.execute(
                text("DELETE FROM synced_entities WHERE tenant_id = :t"), {"t": TENANT}
            )

        assert refusal is None
        assert moved == [], "the other store's product was compared against this one's evidence"
