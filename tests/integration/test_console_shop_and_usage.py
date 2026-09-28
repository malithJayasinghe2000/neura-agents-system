"""Console screens 4 (Shop) and 5 (Usage), over HTTP and against real RLS.

The `console.md §6` bar again, on two more sets of routes — because the bar is
per screen and "the other file tests it" has never been true of the route
somebody added last.

Then the two things these screens are specifically able to get wrong:

**Screen 4 can leak a credential.** §3.4 says the console never displays a stored
credential, not even masked, because a field that can be revealed gets revealed
in a screen-share. The fixture writes recognisable placeholders into
`credentials` and `wrapped_dek` so that "no secret is returned" is an assertion
about strings that are actually there, not a hopeful check against a column that
happened to be empty.

**Screen 5 can invent a measurement.** `console.md §5` calls a dashboard the
place this project's honesty about unmeasured numbers usually dies, so the tests
here assert the *absence* of things: no rate, no cost figure that means nothing,
and no silent period.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from neura_api.main import create_app
from neura_core import Database, get_settings, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.tenancy.usage import UsageDelta, UsageMeter, today
from tests.integration.console_fixtures import PLATFORM, Shop, drop_shop, make_shop

pytestmark = pytest.mark.integration


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def db():
    load_env()
    database = Database.from_settings()
    if not await database.ping():
        pytest.skip("no database reachable at DATABASE_URL — run `make up`")
    yield database
    await database.dispose()


@pytest.fixture
async def shop(db: Database):
    made = await make_shop(db)
    yield made
    await drop_shop(db, made)


@pytest.fixture
async def other_shop(db: Database):
    """The second populated tenant `console.md §6.4` requires."""
    made = await make_shop(db)
    yield made
    await drop_shop(db, made)


def cookie_for(user_id: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user_id, get_settings().secret_key)}


def store_view(client: TestClient, shop: Shop) -> dict:
    response = client.get(f"/v1/console/shops/{shop.tenant}/store", cookies=cookie_for(shop.user))
    assert response.status_code == 200, response.text
    return response.json()["data"]


def usage_of(client: TestClient, shop: Shop, *, period: str = "30d") -> dict:
    response = client.get(
        f"/v1/console/shops/{shop.tenant}/usage?period={period}", cookies=cookie_for(shop.user)
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


class TestTheBarHoldsOnBothScreens:
    """`console.md §6.1`, §6.2, §6.4 — re-asserted per screen, not assumed."""

    @pytest.mark.parametrize("path", ["store", "usage"])
    def test_a_person_reaches_their_own_shop(self, client: TestClient, shop, path: str) -> None:
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/{path}", cookies=cookie_for(shop.user)
        )
        assert response.status_code == 200

    @pytest.mark.parametrize("path", ["store", "usage"])
    def test_another_persons_shop_is_not_reachable(
        self, client: TestClient, shop, other_shop, path: str
    ) -> None:
        response = client.get(
            f"/v1/console/shops/{other_shop.tenant}/{path}", cookies=cookie_for(shop.user)
        )
        assert response.status_code == 404

    @pytest.mark.parametrize("path", ["store", "usage"])
    def test_no_session_reaches_nothing(self, client: TestClient, shop, path: str) -> None:
        assert client.get(f"/v1/console/shops/{shop.tenant}/{path}").status_code == 401

    @pytest.mark.parametrize("path", ["store", "usage"])
    def test_a_forged_cookie_reaches_nothing(self, client: TestClient, shop, path: str) -> None:
        forged = issue(shop.user, "not-the-servers-secret")
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/{path}", cookies={COOKIE_NAME: forged}
        )
        assert response.status_code == 401

    @pytest.mark.parametrize("path", ["store", "usage"])
    async def test_a_revoked_membership_reaches_nothing_immediately(
        self, client: TestClient, db: Database, shop, path: str
    ) -> None:
        from datetime import UTC, datetime

        from neura_core.identity.schema import memberships

        async with db.tenant_session(shop.tenant) as session:
            await session.execute(
                memberships.update()
                .where(memberships.c.id == shop.membership)
                .values(revoked_at=datetime.now(UTC))
            )

        response = client.get(
            f"/v1/console/shops/{shop.tenant}/{path}", cookies=cookie_for(shop.user)
        )
        assert response.status_code == 404


class TestTheShopScreenNeverShowsACredential:
    """`console.md §6.6` and §3.4 — the assertion this screen exists to survive."""

    def test_the_stored_credential_never_appears_in_any_form(
        self, client: TestClient, shop
    ) -> None:
        """The fixture writes recognisable placeholders into `credentials` and
        `wrapped_dek`. This asserts about strings that are really in the row —
        not against a column that happened to be empty."""
        body = client.get(
            f"/v1/console/shops/{shop.tenant}/store", cookies=cookie_for(shop.user)
        ).text
        assert "MUST-NEVER-BE-RETURNED" not in body
        assert "credentials" not in body
        assert "wrapped_dek" not in body

    def test_no_api_key_appears_either(self, client: TestClient, shop) -> None:
        body = client.get(
            f"/v1/console/shops/{shop.tenant}/store", cookies=cookie_for(shop.user)
        ).text
        assert "fn_sk_" not in body
        assert "fn_pk_" not in body

    def test_another_tenants_store_is_not_in_the_body(
        self, client: TestClient, shop, other_shop
    ) -> None:
        body = client.get(
            f"/v1/console/shops/{shop.tenant}/store", cookies=cookie_for(shop.user)
        ).text
        assert other_shop.store not in body
        assert other_shop.tenant not in body


class TestTheShopScreenReportsWhatWasRecorded:
    def test_the_connection_is_listed_without_its_secret(self, client: TestClient, shop) -> None:
        view = store_view(client, shop)
        assert view["connected"] is True
        [store] = view["stores"]
        assert store["id"] == shop.store
        assert store["platform"] == PLATFORM
        assert set(store) == {
            "id",
            "platform",
            "base_url",
            "status",
            "catalogue",
            "syncs",
            "index",
            "sync_asked",
            "notes",
        }

    def test_the_last_sync_is_reported_per_entity_type(self, client: TestClient, shop) -> None:
        [store] = store_view(client, shop)["stores"]
        [sync] = store["syncs"]
        assert sync["entity_type"] == "product"
        assert sync["last_run_count"] == 42
        assert sync["completed_at"] is not None

    def test_the_opaque_cursor_is_never_returned(self, client: TestClient, shop) -> None:
        """A cursor is opaque by design (api-design.md §5) and a merchant can do
        nothing with it but paste it somewhere it will go stale. Whether a crawl
        is mid-flight is the fact they need; the value is not."""
        body = client.get(
            f"/v1/console/shops/{shop.tenant}/store", cookies=cookie_for(shop.user)
        ).text
        assert "eyJwYWdlIjozfQ" not in body, "the encoded cursor must not travel to the browser"
        [store] = store_view(client, shop)["stores"]
        assert store["syncs"][0]["in_progress"] is True

    def test_the_health_probe_is_a_separate_call(self, client: TestClient, shop) -> None:
        """The main screen must not reach out to the merchant's own server. If it
        did, this fixture — whose `base_url` points nowhere — would make the
        screen slow or failing rather than instant."""
        assert store_view(client, shop)["connected"] is True

    def test_an_unknown_store_id_is_404_on_the_probe(self, client: TestClient, shop) -> None:
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/store/st_nope/health",
            cookies=cookie_for(shop.user),
        )
        assert response.status_code == 404


class TestTheShopConnectionChecklist:
    """The 2026-09-28 redesign (`console.md §3.4`): a *Get set up* checklist read
    from our own tables, *Sync now*, and the index line.

    The chat-box tick is the one that could leak: it reads `api_keys`. So a
    real public key is issued here, used, and then looked for in the body by
    every part of it the screen must never show."""

    @pytest.fixture
    async def dressed(self, db: Database, shop):
        """The shop, with a tenant row, an agreement, a used chat box key, a
        revoked key used later, a product view, and a half-indexed catalogue."""
        from datetime import UTC, datetime

        from sqlalchemy import insert

        from neura_agent_core.rag.schema import document_chunks
        from neura_commerce.sync.schema import synced_entities
        from neura_core import ids
        from neura_core.observation import (
            ObservedEvent,
            ObservedEventRepository,
            ObservedEventType,
        )
        from neura_core.tenancy import ApiKeyKind, ApiKeyRepository, TenantRepository

        now = datetime.now(UTC)
        made: dict[str, str] = {}
        async with db.tenant_session(shop.tenant) as session:
            tenants = TenantRepository(session)
            await tenants.create(tenant_id=shop.tenant, name="Checklist Shop")
            await tenants.set_dpa_signed_at(shop.tenant, now - timedelta(days=2))

            keys = ApiKeyRepository(session)
            used, issued = await keys.issue(
                shop.tenant,
                kind=ApiKeyKind.PUBLIC,
                scopes=["care:chat:write"],
                name="widget",
                allowed_origins=["https://shop.example.com"],
            )
            await keys.touch(used.id, at=now - timedelta(hours=1))
            made["token"] = issued.token
            made["prefix"] = used.token_prefix
            # Revoked, and used more recently: it must not be the one reported.
            revoked, _ = await keys.issue(
                shop.tenant,
                kind=ApiKeyKind.PUBLIC,
                scopes=["care:chat:write"],
                allowed_origins=["https://old.example.com"],
            )
            await keys.touch(revoked.id, at=now)
            await keys.revoke(revoked.id)

            await ObservedEventRepository(session).record(
                shop.tenant,
                ObservedEvent.model_construct(
                    event_id=ids.new_id("obs"),
                    session_id="checklistsession" * 4,
                    type=ObservedEventType.PRODUCT_VIEWED,
                    product_id="501",
                    occurred_at=now - timedelta(hours=1),
                    in_stock=True,
                ),
            )

            # Four products synced, two of them indexed — one of those twice,
            # in two chunks, which must still count once.
            for product in ("501", "502", "503", "504"):
                await session.execute(
                    insert(synced_entities).values(
                        tenant_id=shop.tenant,
                        platform=PLATFORM,
                        entity_type="product",
                        external_id=product,
                        neura_id=ids.new_id(ids.NEURA_ENTITY),
                        fingerprint="console-checklist",
                        document={"title": f"Product {product}"},
                    )
                )
            for product, chunk in (("501", 0), ("501", 1), ("502", 0), ("999", 0)):
                await session.execute(
                    insert(document_chunks).values(
                        id=ids.new_id(ids.CHUNK),
                        tenant_id=shop.tenant,
                        embedding_model="console-checklist",
                        dimensions=3,
                        embedding="[0,0,0]",
                        content=f"product {product}",
                        content_hash="console-checklist",
                        source_type="product",
                        source_id=product,
                        chunk_index=chunk,
                    )
                )
        yield made
        await _undress(db, shop)

    def test_every_setup_fact_is_reported(self, client: TestClient, shop, dressed) -> None:
        setup = store_view(client, shop)["setup"]
        assert setup["agreement_since"] is not None
        assert setup["receiving"] is True
        assert setup["window_days"] == 7
        # The used, live key — not the revoked one used later.
        assert setup["chat_box"]["origins"] == ["https://shop.example.com"]
        assert setup["chat_box"]["last_used_at"] is not None
        assert set(setup["chat_box"]) == {"last_used_at", "origins"}

    def test_no_part_of_the_chat_box_key_is_ever_returned(
        self, client: TestClient, shop, dressed
    ) -> None:
        body = client.get(
            f"/v1/console/shops/{shop.tenant}/store", cookies=cookie_for(shop.user)
        ).text
        assert dressed["token"] not in body
        assert dressed["prefix"] not in body
        assert "fn_pk_" not in body
        assert "care:chat:write" not in body, "a key's scopes are not the screen's business"
        assert "token_hash" not in body

    def test_a_shop_with_nothing_set_up_says_so(self, client: TestClient, shop) -> None:
        """No tenant row, no key, no agreement, no views — each a plain no."""
        setup = store_view(client, shop)["setup"]
        assert setup == {
            "chat_box": None,
            "agreement_since": None,
            "receiving": False,
            "window_days": 7,
        }

    def test_the_index_counts_synced_products_it_can_find(
        self, client: TestClient, shop, dressed
    ) -> None:
        """Two of four: a product in two chunks counts once, and an indexed
        product the catalogue no longer has does not count at all."""
        [store] = store_view(client, shop)["stores"]
        assert store["index"] == {"products": 4, "searchable": 2}
        notes = {note["key"]: note["text"] for note in store["notes"]}
        assert notes["index"] == (
            "Search by meaning covers 2 of 4 products — the other 2 are not in it yet, "
            "so the AI can't find them that way."
        )

    def test_it_says_nothing_syncs_by_itself(self, client: TestClient, shop) -> None:
        [store] = store_view(client, shop)["stores"]
        assert store["notes"][0]["key"] == "no_schedule"
        assert "nothing syncs by itself yet" in store["notes"][0]["text"]
        # No products synced, so no index sentence to say anything about.
        assert [note["key"] for note in store["notes"]] == ["no_schedule"]

    def test_variants_are_not_counted(self, client: TestClient, shop) -> None:
        [store] = store_view(client, shop)["stores"]
        assert set(store["catalogue"]) == {"product", "category", "policy"}


class TestSyncNow:
    """The console's third write — and it writes only our copy (`console.md §3.4`)."""

    @pytest.fixture
    async def jobs(self, db: Database, shop):
        yield
        from sqlalchemy import delete

        from neura_core.jobs import job_queue

        async with db.tenant_session(shop.tenant) as session:
            await session.execute(delete(job_queue).where(job_queue.c.tenant_id == shop.tenant))

    def _sync(self, client: TestClient, shop, *, store: str | None = None, user: str | None = None):
        return client.post(
            f"/v1/console/shops/{shop.tenant}/store/{store or shop.store}/sync",
            cookies=cookie_for(user or shop.user),
        )

    async def test_it_queues_a_full_read_of_the_shop(
        self, client: TestClient, db: Database, shop, jobs
    ) -> None:
        """Full, not incremental: a shop's *changed since* filter follows a
        product's own edits, and a sale that lowers stock is not one."""
        from neura_core.jobs import JobQueue

        response = self._sync(client, shop)
        assert response.status_code == 202
        asked = response.json()["data"]["sync_asked"]
        assert asked["status"] in {"pending", "running"}

        async with db.tenant_session(shop.tenant) as session:
            [job] = await JobQueue(session).list_for(shop.tenant)
        assert job.kind == "sync.store"
        assert job.payload == {"store_id": shop.store, "incremental": False}

    async def test_pressing_it_twice_is_one_sync(
        self, client: TestClient, db: Database, shop, jobs
    ) -> None:
        from neura_core.jobs import JobQueue

        assert self._sync(client, shop).status_code == 202
        assert self._sync(client, shop).status_code == 202
        async with db.tenant_session(shop.tenant) as session:
            assert len(await JobQueue(session).list_for(shop.tenant)) == 1

    def test_the_screen_shows_a_sync_that_has_not_finished(
        self, client: TestClient, shop, jobs
    ) -> None:
        [before] = store_view(client, shop)["stores"]
        assert before["sync_asked"] is None
        self._sync(client, shop)
        [after] = store_view(client, shop)["stores"]
        assert after["sync_asked"]["status"] in {"pending", "running"}
        assert set(after["sync_asked"]) == {"status", "queued_at"}

    async def test_an_unknown_store_is_a_404_and_queues_nothing(
        self, client: TestClient, db: Database, shop, jobs
    ) -> None:
        from neura_core.jobs import JobQueue

        assert self._sync(client, shop, store="st_nope").status_code == 404
        async with db.tenant_session(shop.tenant) as session:
            assert await JobQueue(session).list_for(shop.tenant) == []

    async def test_another_shops_store_cannot_be_synced(
        self, client: TestClient, db: Database, shop, other_shop, jobs
    ) -> None:
        """Both ways round: another shop's store id under my shop, and my
        person under another shop."""
        from neura_core.jobs import JobQueue

        assert self._sync(client, shop, store=other_shop.store).status_code == 404
        response = client.post(
            f"/v1/console/shops/{other_shop.tenant}/store/{other_shop.store}/sync",
            cookies=cookie_for(shop.user),
        )
        assert response.status_code == 404
        async with db.tenant_session(other_shop.tenant) as session:
            assert await JobQueue(session).list_for(other_shop.tenant) == []

    def test_no_session_syncs_nothing(self, client: TestClient, shop, jobs) -> None:
        response = client.post(f"/v1/console/shops/{shop.tenant}/store/{shop.store}/sync")
        assert response.status_code == 401


async def _undress(db: Database, shop: Shop) -> None:
    """Remove what `dressed` made. A test tenant's own rows, so by tenant is safe."""
    from sqlalchemy import delete

    from neura_agent_core.rag.schema import document_chunks
    from neura_commerce.sync.schema import synced_entities
    from neura_core.observation import observed_events
    from neura_core.tenancy.schema import api_keys, tenants

    async with db.tenant_session(shop.tenant) as session:
        await session.execute(delete(api_keys).where(api_keys.c.tenant_id == shop.tenant))
        await session.execute(
            delete(observed_events).where(observed_events.c.tenant_id == shop.tenant)
        )
        await session.execute(
            delete(synced_entities)
            .where(synced_entities.c.tenant_id == shop.tenant)
            .where(synced_entities.c.fingerprint == "console-checklist")
        )
        await session.execute(
            delete(document_chunks)
            .where(document_chunks.c.tenant_id == shop.tenant)
            .where(document_chunks.c.embedding_model == "console-checklist")
        )
        await session.execute(delete(tenants).where(tenants.c.tenant_id == shop.tenant))


class TestTheUsageScreenInventsNothing:
    """`console.md §5` and `CLAUDE.md §4`. Mostly assertions of absence."""

    def test_no_field_anywhere_in_the_payload_is_a_rate(self, client: TestClient, shop) -> None:
        """Escalations over conversations is arithmetic this data supports;
        *deflection* is a business claim it does not, and `CLAUDE.md §4` lists
        deflection rate under unknown. The screen shows "1 of 3", which a
        merchant can check.

        Asserted over the **field names**, not over the response text: the
        caveats deliberately contain the word "deflection", in the sentence that
        refuses it. Searching the body for the word would fail on the disclaimer
        and pass on a field called `deflectionRate`.
        """
        payload = usage_of(client, shop)

        def keys(node: object) -> list[str]:
            if isinstance(node, dict):
                return [k for key, value in node.items() for k in [key, *keys(value)]]
            if isinstance(node, list):
                return [k for item in node for k in keys(item)]
            return []

        for name in keys(payload):
            lowered = name.lower()
            assert not lowered.endswith("_rate"), name
            assert "deflect" not in lowered, name
            assert "percent" not in lowered, name

    def test_a_zero_cost_is_flagged_as_unmeasured(self, client: TestClient, shop) -> None:
        """A local model records zero and an unpriced hosted model records zero.
        The figure cannot tell a merchant which, so it says so."""
        assert usage_of(client, shop)["totals"]["cost"]["measured"] is False

    def test_the_zero_cost_carries_a_sentence_explaining_it(self, client: TestClient, shop) -> None:
        caveats = " ".join(c["text"] for c in usage_of(client, shop)["caveats"])
        assert "own hardware" in caveats and "no price" in caveats

    def test_the_escalation_count_arrives_with_its_denominator(
        self, client: TestClient, shop
    ) -> None:
        usage = usage_of(client, shop)
        assert usage["totals"]["conversations"] == 3
        assert usage["totals"]["escalations"] == 1
        assert "of 3 conversations" in " ".join(c["text"] for c in usage["caveats"])

    def test_the_caveat_refuses_the_word_it_would_be_mistaken_for(
        self, client: TestClient, shop
    ) -> None:
        """The count is stated *and* disclaimed in the same sentence, because a
        merchant reading "1 of 3 escalated" will otherwise do the division
        themselves and call the answer a deflection rate."""
        assert "not a deflection rate" in " ".join(
            c["text"] for c in usage_of(client, shop)["caveats"]
        )

    def test_every_total_names_its_period(self, client: TestClient, shop) -> None:
        """ "142 turns" says nothing without "since when"."""
        usage = usage_of(client, shop, period="7d")
        assert usage["period"]["key"] == "7d"
        assert usage["period"]["days"] == 7
        assert usage["period"]["since"] is not None

    def test_everything_ever_recorded_has_no_day_count(self, client: TestClient, shop) -> None:
        """`null`, not a number. "All time" is not a number of days and must not
        be rendered as one."""
        usage = usage_of(client, shop, period="all")
        assert usage["period"]["days"] is None
        assert usage["period"]["since"] is None

    def test_an_unknown_period_is_refused_rather_than_defaulted(
        self, client: TestClient, shop
    ) -> None:
        """A silently corrected period returns a different window than was asked
        for while looking like the one that was asked for — a wrong number, not
        a wrong parameter."""
        response = client.get(
            f"/v1/console/shops/{shop.tenant}/usage?period=lastyear",
            cookies=cookie_for(shop.user),
        )
        assert response.status_code == 400

    async def test_the_split_by_agent_covers_the_period_chosen(
        self, client: TestClient, db: Database, shop
    ) -> None:
        """Today-only until 2026-09-28. The rollup is one row per (day, agent),
        so a period's per-agent figure is a sum of recorded rows like the total
        is — and the agents' rows add up to the total."""
        async with db.tenant_session(shop.tenant) as session:
            await UsageMeter(session).record(
                shop.tenant,
                "sell",
                UsageDelta(conversations=2, turns=3, llm_calls=5),
                on=today() - timedelta(days=10),
            )

        month = usage_of(client, shop, period="30d")
        assert set(month["by_agent"]) == {"care", "sell"}
        assert month["by_agent"]["sell"]["turns"] == 3
        for counter in ("conversations", "turns", "llm_calls", "total_tokens"):
            assert (
                sum(agent[counter] for agent in month["by_agent"].values())
                == month["totals"][counter]
            )
        # Ten days ago is outside a week: the split follows the period.
        assert set(usage_of(client, shop, period="7d")["by_agent"]) == {"care"}

    async def test_ai_work_without_a_conversation_is_explained_only_when_it_happened(
        self, client: TestClient, db: Database, shop
    ) -> None:
        """Model calls with no turn — a pairing computed in the background — read
        as a broken assistant unless the screen says why."""
        assert not any(c["key"] == "background_ai" for c in usage_of(client, shop)["caveats"])

        async with db.tenant_session(shop.tenant) as session:
            await UsageMeter(session).record(
                shop.tenant, "sell", UsageDelta(llm_calls=7, prompt_tokens=3000)
            )
        caveats = {c["key"]: c["text"] for c in usage_of(client, shop)["caveats"]}
        assert "without a conversation" in caveats["background_ai"]

    def test_everything_says_where_it_starts(self, client: TestClient, shop) -> None:
        assert usage_of(client, shop, period="all")["period"]["first_recorded"] == str(today())

    def test_another_tenants_usage_is_not_counted(
        self, client: TestClient, shop, other_shop
    ) -> None:
        """Both shops recorded identical usage. If isolation failed here, the
        counts would simply double — silently, and plausibly."""
        assert usage_of(client, shop)["totals"]["turns"] == 4


class TestShadowModeIsStatedNotImplied:
    """The most misleading page this console could produce is built entirely from
    true numbers: work done in shadow mode, reported without saying so."""

    def test_a_live_shop_says_nothing_about_withholding(self, client: TestClient, shop) -> None:
        """The fixture's tenant has no `tenants` row, so the mode is unknown
        rather than `shadow` — and an unknown mode must not claim either."""
        usage = usage_of(client, shop)
        assert usage["withheld"] is False
        assert not any(caveat["key"] == "practice_mode" for caveat in usage["caveats"])

    async def test_a_shadow_shop_says_so_before_any_figure(
        self, client: TestClient, db: Database, shop
    ) -> None:
        from neura_core.tenancy import TenantRepository
        from neura_core.tenancy.models import TenantConfig
        from neura_core.tenancy.modes import TurnMode

        async with db.tenant_session(shop.tenant) as session:
            await TenantRepository(session).create(
                tenant_id=shop.tenant,
                name="Fixture Shop",
                enabled_agents=["care"],
                config=TenantConfig(mode=TurnMode.SHADOW),
            )

        try:
            usage = usage_of(client, shop)
            assert usage["mode"] == "shadow"
            assert usage["withheld"] is True
            # First in the list, so a screen rendering them in order leads with it.
            assert usage["caveats"][0]["key"] == "practice_mode"
            assert "practice mode" in usage["caveats"][0]["text"]
            assert "no shopper was shown any of it" in usage["caveats"][0]["text"]
        finally:
            from sqlalchemy import delete

            from neura_core.tenancy.schema import tenants

            async with db.tenant_session(shop.tenant) as session:
                await session.execute(delete(tenants).where(tenants.c.tenant_id == shop.tenant))
