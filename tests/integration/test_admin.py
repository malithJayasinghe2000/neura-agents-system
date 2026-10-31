"""ADR-0061 over HTTP and against real RLS: the FiveNeurals admin dashboard.

What these tests hold the build to:

* **the door**: signed out, 401; not on the admin list, 404 *No such page.* on
  every admin route; an admin signed in more than 12 hours ago, 401
  ``ADMIN_SIGN_IN_AGAIN``; a removed admin is refused on the next request; an
  admin who is not a member of a shop gets 404 on every shop route (§4, §5);
* **the database keeps shoppers out** (§1, §6): the two functions answer nothing
  to a transaction that names no admin, a non-admin or a removed admin; their
  role can read no table outside §1; no admin answer carries a shopper's words;
* **Shops**: waiting shops first, each shop's facts and its last 7 days;
* **approve and refuse** (§7): only a waiting shop; the assistants named, CARE
  when none; the approval or refusal email to its Owner; the admin in the shop's
  record; refusal removes the shop and keeps the person's account;
* **AI use and cost**: today, 7 days, 30 days; the rows add up to the totals;
* **removing a shop** reaches every table that holds a shop's rows, without
  naming an agent, the audit log excepted (S10);
* **a switch per feature** (ADR-0065): a shop's switches come from its
  assistants' manifests; only an admin changes one, for an assistant the shop
  has; a change is in the shop's record with the admin, a no-op records nothing;
* **the code from the admin's phone** (ADR-0067): an admin with no code must set
  it up first (``ADMIN_CODE_SETUP``), a new sign-in must type it
  (``ADMIN_CODE_NEEDED``); a code works once; 5 wrong codes stop it for 15
  minutes; the key is never returned after setup; ``make admin-reset-code``
  clears it and nothing else; a shop's own routes never ask;
* ``/me`` says who is an admin; ``make admin-add`` and ``admin-remove`` change
  the list and nothing else.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from neura_agent_core.shadow_evidence import shadow_evidence
from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.email import Mailer, SendResult
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.admin_codes import CodeResult, confirm_setup, start_setup
from neura_core.identity.admins import add_admin, admin_shops, admin_usage, is_admin
from neura_core.identity.schema import login_tokens, memberships, platform_admins, users
from neura_core.identity.sign_up import confirm_sign_up, request_sign_up
from neura_core.identity.totp import STEP_SECONDS, code_at
from neura_core.jobs.schema import job_queue
from neura_core.tenancy import TenantRepository, TenantStatus, TurnMode
from neura_core.tenancy.removal import remove_tenant
from neura_core.tenancy.schema import tenants
from neura_core.tenancy.switches import SwitchRepository
from tests.console_permissions import ADMIN_ROUTES, ROUTES
from tests.integration.console_fixtures import QUESTION, REPLY, Shop, drop_shop, make_shop

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import console_admin

pytestmark = pytest.mark.integration

MADE_UP = "probe-not-there"

#: The only tables the admin functions' role may read anything of (§1).
ALLOWED = {"tenants", "tenant_stores", "tenant_usage", "memberships", "users", "platform_admins"}


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
def mail(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    sent: list[dict[str, str]] = []

    def send(self: Mailer, *, to: str, subject: str, body: str) -> SendResult:
        sent.append({"to": to, "subject": subject, "body": body})
        return SendResult(sent=True)

    monkeypatch.setattr(Mailer, "send", send)
    return sent


async def _as_operator(statement: str, **params: object) -> None:
    """For what the application role may not do: delete audit entries and admins."""
    engine = create_async_engine(str(get_settings().database_migration_url))
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement), params)
    finally:
        await engine.dispose()


@dataclass
class Made:
    users: list[str] = field(default_factory=list)
    shops: list[str] = field(default_factory=list)


@pytest.fixture
async def made(db: Database):
    record = Made()
    yield record
    for tenant_id in set(record.shops):
        async with db.tenant_session(tenant_id) as session:
            await remove_tenant(session, tenant_id)
        await _as_operator("DELETE FROM audit_log WHERE tenant_id = :t", t=tenant_id)
    for user_id in record.users:
        await _as_operator("DELETE FROM platform_admins WHERE user_id = :u", u=user_id)
    async with db.identity_session() as session:
        await session.execute(delete(login_tokens).where(login_tokens.c.user_id.in_(record.users)))
        await session.execute(delete(users).where(users.c.id.in_(record.users)))


async def _person(db: Database, made: Made, label: str = "person") -> tuple[str, str]:
    user = ids.new_id(ids.USER)
    email = f"{label}-{user.lower()}@example.com"
    async with db.identity_session() as session:
        await session.execute(users.insert().values(id=user, email=email, name=label))
    made.users.append(user)
    return user, email


async def _admin(db: Database, made: Made, *, code: bool = True) -> str:
    """An admin; with ``code``, one whose phone is already set up (ADR-0067)."""
    user, email = await _person(db, made, "admin")
    async with db.identity_session() as session:
        await add_admin(session, email=email)
    if code:
        kek = get_settings().kek
        async with db.identity_session(user) as session:
            secret = await start_setup(session, user, kek=kek)
            done = await confirm_setup(session, user, _code(secret, -1), kek=kek)
        assert done is CodeResult.OK
    return user


def _code(secret: str, offset: int = 0) -> str:
    """The code an authenticator app shows now, or ``offset`` steps from now."""
    return code_at(secret, int(datetime.now(UTC).timestamp()) // STEP_SECONDS + offset)


async def _waiting_shop(
    db: Database, made: Made, name: str = "Lanka Spice Test"
) -> tuple[str, str]:
    """A shop that signed up, as the link makes one: (shop id, owner email)."""
    email = f"owner-{ids.new_id(ids.USER).lower()}@example.com"
    async with db.identity_session() as session:
        link = await request_sign_up(
            session,
            email=email,
            name=name,
            website="lankaspice.example.com",
            console_base_url="http://console.test",
        )
    tenant_id = ids.new_id(ids.TENANT)
    async with db.tenant_session(tenant_id) as session:
        signed = await confirm_sign_up(session, tenant_id=tenant_id, token=link.token)
    assert signed is not None
    made.shops.append(tenant_id)
    made.users.append(signed.user_id)
    return tenant_id, email


@pytest.fixture
async def populated(db: Database):
    """An ordinary shop with chats, a held reply with its evidence, and a day of usage."""
    shop = await make_shop(db)
    async with db.tenant_session(shop.tenant) as session:
        await TenantRepository(session).create(
            tenant_id=shop.tenant, name="Admin Test Shop", enabled_agents=["care"]
        )
    yield shop
    async with db.tenant_session(shop.tenant) as session:
        await session.execute(delete(tenants).where(tenants.c.tenant_id == shop.tenant))
    await drop_shop(db, shop)


def cookie(user: str, *, age: timedelta = timedelta(0), code: bool = True) -> dict[str, str]:
    """A sign-in ``age`` old; with ``code``, one in which the phone's code was typed."""
    signed_in = datetime.now(UTC) - age
    return {
        COOKIE_NAME: issue(
            user, get_settings().secret_key, now=signed_in, code_at=signed_in if code else None
        )
    }


def call(client: TestClient, method: str, template: str, tenant: str, cookies: dict[str, str]):
    path = re.sub(r"\{[a-z_]+\}", MADE_UP, template.replace("{tenant_id}", tenant))
    body = {"on": True} if method == "PUT" else {} if method == "POST" else None
    return client.request(method, path, json=body, cookies=cookies)


class TestTheDoor:
    def test_signed_out_is_401_on_every_admin_route(self, client: TestClient) -> None:
        wrong = [
            f"{m} {t}: {r.status_code}"
            for m, t in sorted(ADMIN_ROUTES)
            if (r := call(client, m, t, MADE_UP, {})).status_code != 401
        ]
        assert not wrong, "\n".join(wrong)

    async def test_someone_not_on_the_list_gets_no_such_page(
        self, client: TestClient, db: Database, made: Made, populated: Shop
    ) -> None:
        wrong = []
        for method, template in sorted(ADMIN_ROUTES):
            response = call(client, method, template, populated.tenant, cookie(populated.user))
            error = response.json().get("error") or {}
            if response.status_code != 404 or error.get("message") != "No such page.":
                wrong.append(f"{method} {template}: {response.status_code} {error}")
        assert not wrong, "\n".join(wrong)

    async def test_an_admin_signed_in_long_ago_must_sign_in_again(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made)
        old = client.get("/v1/admin/shops", cookies=cookie(admin, age=timedelta(hours=13)))
        assert old.status_code == 401
        assert old.json()["error"]["code"] == "ADMIN_SIGN_IN_AGAIN"
        fresh = client.get("/v1/admin/shops", cookies=cookie(admin, age=timedelta(hours=11)))
        assert fresh.status_code == 200

    async def test_a_removed_admin_is_refused_on_the_next_request(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made)
        assert client.get("/v1/admin/shops", cookies=cookie(admin)).status_code == 200
        async with db.identity_session() as session:
            email = await session.scalar(select(users.c.email).where(users.c.id == admin))
        assert await console_admin.admin_remove(str(email)) == 0
        assert client.get("/v1/admin/shops", cookies=cookie(admin)).status_code == 404

    async def test_an_admin_opens_no_shop_they_are_not_in(
        self, client: TestClient, db: Database, made: Made, populated: Shop
    ) -> None:
        admin = await _admin(db, made)
        wrong = []
        for method, template in sorted(ROUTES):
            response = call(client, method, template, populated.tenant, cookie(admin))
            error = response.json().get("error") or {}
            if response.status_code != 404 or error.get("message") != "No such shop.":
                wrong.append(f"{method} {template}: {response.status_code}")
        assert not wrong, "\n".join(wrong)


class TestTheDatabaseKeepsShoppersOut:
    async def test_the_functions_answer_only_a_live_admin(
        self, db: Database, made: Made, populated: Shop
    ) -> None:
        nobody_user, _ = await _person(db, made)
        admin = await _admin(db, made)
        today = datetime.now(UTC).date()

        async with db.identity_session() as session:
            assert await admin_shops(session) == []
            assert await admin_usage(session, since=today, until=today) == []
        async with db.identity_session(nobody_user) as session:
            assert await admin_shops(session) == []
            assert await admin_usage(session, since=today, until=today) == []
        async with db.identity_session(admin) as session:
            shops = await admin_shops(session)
            usage = await admin_usage(session, since=today, until=today)
        assert populated.tenant in {s.tenant_id for s in shops}
        assert populated.tenant in {u.tenant_id for u in usage}

        await _as_operator(
            "UPDATE platform_admins SET removed_at = now() WHERE user_id = :u", u=admin
        )
        async with db.identity_session(admin) as session:
            assert await admin_shops(session) == []

    async def test_their_role_can_read_nothing_outside_shop_facts(self) -> None:
        engine = create_async_engine(str(get_settings().database_migration_url))
        try:
            async with engine.connect() as conn:
                columns = (
                    await conn.execute(
                        text(
                            "SELECT table_name, column_name FROM information_schema.column_privileges "
                            "WHERE grantee = 'neura_admin_reader' AND privilege_type = 'SELECT'"
                        )
                    )
                ).all()
                whole = (
                    await conn.execute(
                        text(
                            "SELECT table_name, privilege_type FROM information_schema.table_privileges "
                            "WHERE grantee = 'neura_admin_reader'"
                        )
                    )
                ).all()
        finally:
            await engine.dispose()
        assert columns, "the role should exist and read some columns"
        assert {t for t, _ in columns} <= ALLOWED
        assert whole == []
        assert ("users", "email") in set(columns)
        assert ("users", "name") not in set(columns)

    async def test_no_admin_answer_carries_a_shoppers_words(
        self, client: TestClient, db: Database, made: Made, populated: Shop
    ) -> None:
        admin = await _admin(db, made)
        for method, template in sorted(ADMIN_ROUTES):
            if method != "GET":
                continue
            response = call(client, method, template, populated.tenant, cookie(admin))
            assert QUESTION not in response.text
            assert REPLY not in response.text
            assert "conversation_id" not in response.text


class TestShops:
    async def test_waiting_shops_come_first_with_their_facts(
        self, client: TestClient, db: Database, made: Made, populated: Shop
    ) -> None:
        admin = await _admin(db, made)
        waiting, owner = await _waiting_shop(db, made)
        data = client.get("/v1/admin/shops", cookies=cookie(admin)).json()["data"]
        shops = data["shops"]
        statuses = [s["status"] for s in shops]
        assert statuses == sorted(statuses, key=lambda s: s != "waiting")
        assert data["waiting"] == statuses.count("waiting") >= 1
        first = next(s for s in shops if s["tenant_id"] == waiting)
        assert first["name"] == "Lanka Spice Test"
        assert first["website"] == "https://lankaspice.example.com"
        assert first["owners"] == [owner]
        assert first["assistants"] == []
        assert first["mode"] == "practice"
        assert first["connected"] is False
        ordinary = next(s for s in shops if s["tenant_id"] == populated.tenant)
        assert ordinary["status"] == "active"
        assert ordinary["connected"] is True
        assert ordinary["chats_7d"] == 3
        assert ordinary["ai_calls_7d"] == 9
        assert ordinary["cost_7d"] == {"usd": "0.000000", "measured": False}

    async def test_one_shop_and_an_unknown_one(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made)
        waiting, _ = await _waiting_shop(db, made)
        one = client.get(f"/v1/admin/shops/{waiting}", cookies=cookie(admin))
        assert one.status_code == 200
        assert one.json()["data"]["shop"]["tenant_id"] == waiting
        missing = client.get(f"/v1/admin/shops/{MADE_UP}", cookies=cookie(admin))
        assert missing.status_code == 404
        assert missing.json()["error"]["message"] == "No such shop."


async def _audit(tenant_id: str) -> list[tuple[str, str, str]]:
    engine = create_async_engine(str(get_settings().database_migration_url))
    try:
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT event_type, actor, outcome FROM audit_log "
                        "WHERE tenant_id = :t ORDER BY sequence"
                    ),
                    {"t": tenant_id},
                )
            ).all()
    finally:
        await engine.dispose()
    return [(r.event_type, r.actor, r.outcome) for r in rows]


class TestApproveAndRefuse:
    async def test_approval_makes_an_ordinary_shop_and_says_who(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        admin = await _admin(db, made)
        waiting, owner = await _waiting_shop(db, made)
        response = client.post(
            f"/v1/admin/shops/{waiting}/approve",
            json={"agents": ["care", "sell"]},
            cookies=cookie(admin),
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["approved"] is True and data["emailed"] is True
        async with db.tenant_session(waiting) as session:
            shop = await TenantRepository(session).require(waiting)
        assert shop.status is TenantStatus.ACTIVE
        assert shop.enabled_agents == frozenset({"care", "sell"})
        assert shop.config.mode is TurnMode.SHADOW
        assert mail[-1]["to"] == owner
        assert mail[-1]["subject"] == "Lanka Spice Test is ready on FiveNeurals"
        assert ("config.change", admin, "shop.approved") in await _audit(waiting)

        again = client.post(
            f"/v1/admin/shops/{waiting}/approve", json={"agents": ["care"]}, cookies=cookie(admin)
        )
        assert again.status_code == 409
        assert again.json()["error"]["code"] == "NOT_WAITING"

    async def test_approving_a_shop_with_grow_books_its_night_run(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        """ADR-0072 §8: the Marketing calendar needs the night run before any chat."""
        admin = await _admin(db, made)
        waiting, _ = await _waiting_shop(db, made)
        response = client.post(
            f"/v1/admin/shops/{waiting}/approve",
            json={"agents": ["care", "grow"]},
            cookies=cookie(admin),
        )
        assert response.status_code == 200
        async with db.tenant_session(waiting) as session:
            kinds = (await session.execute(select(job_queue.c.kind))).scalars().all()
        assert kinds == ["grow.gaps.scan"]

    async def test_an_assistant_must_be_chosen_and_a_typo_is_refused(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        """The API names no agent (AGENTS.md), so it has no default: the dashboard
        ticks CARE (R14), and the API asks for at least one."""
        admin = await _admin(db, made)
        waiting, _ = await _waiting_shop(db, made)
        typo = client.post(
            f"/v1/admin/shops/{waiting}/approve", json={"agents": ["cre"]}, cookies=cookie(admin)
        )
        assert typo.status_code == 400
        async with db.tenant_session(waiting) as session:
            assert (await TenantRepository(session).require(waiting)).status is TenantStatus.WAITING
        none = client.post(
            f"/v1/admin/shops/{waiting}/approve", json={"agents": []}, cookies=cookie(admin)
        )
        assert none.status_code == 400
        assert none.json()["error"]["code"] == "NO_ASSISTANT"
        async with db.tenant_session(waiting) as session:
            assert (await TenantRepository(session).require(waiting)).status is TenantStatus.WAITING
        assert mail == []

    async def test_refusal_removes_the_shop_keeps_the_person_and_says_who(
        self, client: TestClient, db: Database, made: Made, mail: list[dict[str, str]]
    ) -> None:
        admin = await _admin(db, made)
        waiting, owner = await _waiting_shop(db, made, name="Refused Test Shop")
        response = client.post(f"/v1/admin/shops/{waiting}/refuse", cookies=cookie(admin))
        assert response.status_code == 200
        assert response.json()["data"]["refused"] is True
        async with db.tenant_session(waiting) as session:
            assert await TenantRepository(session).get(waiting) is None
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(memberships)
                    .where(memberships.c.tenant_id == waiting)
                )
                == 0
            )
        async with db.identity_session() as session:
            assert (
                await session.scalar(select(users.c.id).where(users.c.email == owner)) is not None
            )
        assert mail[-1]["to"] == owner
        assert mail[-1]["subject"] == "Your FiveNeurals sign-up for Refused Test Shop"
        assert ("config.change", admin, "shop.refused") in await _audit(waiting)

    async def test_an_ordinary_shop_cannot_be_approved_or_refused(
        self,
        client: TestClient,
        db: Database,
        made: Made,
        populated: Shop,
        mail: list[dict[str, str]],
    ) -> None:
        admin = await _admin(db, made)
        for action in ("approve", "refuse"):
            # A request that is otherwise right: only the shop's state refuses it.
            body = {"agents": ["care"]} if action == "approve" else None
            response = client.post(
                f"/v1/admin/shops/{populated.tenant}/{action}", json=body, cookies=cookie(admin)
            )
            assert response.status_code == 409, action
        async with db.tenant_session(populated.tenant) as session:
            assert await TenantRepository(session).get(populated.tenant) is not None
        assert mail == []


class TestUsage:
    async def test_the_rows_add_up_to_the_totals(
        self, client: TestClient, db: Database, made: Made, populated: Shop
    ) -> None:
        admin = await _admin(db, made)
        for period, days in (("today", 1), ("7d", 7), ("30d", 30)):
            data = client.get(f"/v1/admin/usage?period={period}", cookies=cookie(admin)).json()[
                "data"
            ]
            assert data["period"]["days"] == days
            totals = data["totals"]
            for key in ("conversations", "turns", "escalations", "llm_calls", "total_tokens"):
                assert sum(row[key] for row in data["by_shop"]) == totals[key], (period, key)
                assert sum(row[key] for row in data["by_assistant"]) == totals[key], (period, key)
            mine = next(row for row in data["by_shop"] if row["tenant_id"] == populated.tenant)
            assert mine["conversations"] == 3 and mine["name"] == "Admin Test Shop"
            assert Decimal(totals["cost"]["usd"]) >= 0

    async def test_an_unknown_period_is_refused(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made)
        assert client.get("/v1/admin/usage?period=1y", cookies=cookie(admin)).status_code == 400


class TestRemovingAShop:
    async def test_it_reaches_every_table_but_the_audit_log(
        self, db: Database, populated: Shop
    ) -> None:
        async with db.tenant_session(populated.tenant) as session:
            await session.execute(
                shadow_evidence.insert().values(
                    tenant_id=populated.tenant,
                    shadow_turn_id=populated.answered_turn,
                    store_id=populated.store,
                    content_hash="removal-test",
                    bundle={},
                )
            )
            removed = await remove_tenant(session, populated.tenant)
        assert "audit_log" not in removed
        assert removed["tenants"] == 1 and removed["shadow_evidence"] == 1
        async with db.tenant_session(populated.tenant) as session:
            tables = (
                await session.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND column_name = 'tenant_id' "
                        "AND table_name <> 'audit_log'"
                    )
                )
            ).scalars()
            for table in tables:
                left = await session.scalar(
                    text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :t'),  # noqa: S608
                    {"t": populated.tenant},
                )
                assert left == 0, table


GAPS = "grow.gaps"


async def _growing_shop(
    db: Database, made: Made, agents: tuple[str, ...] = ("care", "grow")
) -> str:
    tenant_id = ids.new_id(ids.TENANT)
    async with db.tenant_session(tenant_id) as session:
        await TenantRepository(session).create(
            tenant_id=tenant_id, name="Switch Test Shop", enabled_agents=list(agents)
        )
    made.shops.append(tenant_id)
    return tenant_id


class TestSwitches:
    async def test_a_shop_lists_the_switches_of_its_assistants(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made)
        growing = await _growing_shop(db, made)
        caring = await _growing_shop(db, made, ("care",))
        shop = client.get(f"/v1/admin/shops/{growing}", cookies=cookie(admin)).json()["data"][
            "shop"
        ]
        # Sorted by key: the calendar's own switch (ADR-0072 §5), then the night check.
        assert [s["key"] for s in shop["switches"]] == ["grow.calendar", GAPS]
        switch = shop["switches"][1]
        assert switch["key"] == GAPS
        assert switch["assistant"] == "grow"
        assert switch["on"] is True
        assert switch["name"] and switch["text"]
        assert switch["changed_at"] is None
        other = client.get(f"/v1/admin/shops/{caring}", cookies=cookie(admin)).json()["data"][
            "shop"
        ]
        assert other["switches"] == []

    async def test_turning_off_and_on_says_who_and_a_no_op_records_nothing(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made)
        tenant = await _growing_shop(db, made)
        path = f"/v1/admin/shops/{tenant}/switches/{GAPS}"

        off = client.put(path, json={"on": False}, cookies=cookie(admin))
        assert off.status_code == 200, off.text
        switch = off.json()["data"]["switch"]
        assert (switch["on"], switch["changed_by_you"]) == (False, True)
        assert switch["changed_at"]
        async with db.tenant_session(tenant) as session:
            assert not await SwitchRepository(session).is_on(tenant, GAPS)

        again = client.put(path, json={"on": False}, cookies=cookie(admin))
        assert again.status_code == 200
        assert again.json()["data"]["changed"] is False

        assert client.put(path, json={"on": True}, cookies=cookie(admin)).status_code == 200
        async with db.tenant_session(tenant) as session:
            assert await SwitchRepository(session).is_on(tenant, GAPS)

        assert [a for a in await _audit(tenant) if a[2].startswith("switch.")] == [
            ("config.change", admin, "switch.off"),
            ("config.change", admin, "switch.on"),
        ]

    async def test_an_unknown_key_or_an_assistant_the_shop_lacks_is_refused(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made)
        caring = await _growing_shop(db, made, ("care",))
        unknown = client.put(
            f"/v1/admin/shops/{caring}/switches/care.nothing",
            json={"on": False},
            cookies=cookie(admin),
        )
        assert unknown.status_code == 400
        assert unknown.json()["error"]["code"] == "UNKNOWN_SWITCH"
        lacking = client.put(
            f"/v1/admin/shops/{caring}/switches/{GAPS}", json={"on": False}, cookies=cookie(admin)
        )
        assert lacking.status_code == 400
        assert lacking.json()["error"]["code"] == "NOT_THIS_SHOPS_ASSISTANT"
        missing = client.put(
            f"/v1/admin/shops/{MADE_UP}/switches/{GAPS}", json={"on": False}, cookies=cookie(admin)
        )
        assert missing.status_code == 404
        async with db.tenant_session(caring) as session:
            assert await SwitchRepository(session).all(caring) == {}


class TestTheCode:
    async def test_an_admin_with_no_code_must_set_it_up_first(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made, code=False)
        refused = client.get("/v1/admin/shops", cookies=cookie(admin, code=False))
        assert refused.status_code == 401
        assert refused.json()["error"]["code"] == "ADMIN_CODE_SETUP"

    async def test_setting_it_up_opens_the_admin_area(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made, code=False)
        jar = cookie(admin, code=False)
        started = client.post("/v1/admin/code/setup", cookies=jar)
        assert started.status_code == 200, started.text
        data = started.json()["data"]
        key = data["key"].replace(" ", "")
        assert data["uri"].startswith("otpauth://totp/FiveNeurals:")
        assert data["qr_svg"].startswith("data:image/svg+xml;base64,")

        wrong = client.post("/v1/admin/code/setup/confirm", json={"code": "000000"}, cookies=jar)
        assert wrong.status_code == 400
        assert wrong.json()["error"]["code"] == "WRONG_CODE"

        right = client.post("/v1/admin/code/setup/confirm", json={"code": _code(key)}, cookies=jar)
        assert right.status_code == 200, right.text
        signed = {COOKIE_NAME: right.cookies[COOKIE_NAME]}
        assert client.get("/v1/admin/shops", cookies=signed).status_code == 200

        again = client.post("/v1/admin/code/setup", cookies=signed)
        assert again.status_code == 409, "the key is never shown twice"
        assert key not in again.text

    async def test_asking_twice_before_setup_is_finished_gives_the_same_key(
        self, db: Database, made: Made
    ) -> None:
        """G116: the setup page opened twice at once showed one key and stored
        another. Until setup is finished, every request gets the same key,
        even two at the same moment."""
        import asyncio

        admin = await _admin(db, made, code=False)
        kek = get_settings().kek

        async def ask() -> str:
            async with db.identity_session(admin) as session:
                return await start_setup(session, admin, kek=kek)

        first, second = await asyncio.gather(ask(), ask())
        assert first == second
        assert await ask() == first

    async def test_a_new_sign_in_must_type_the_code_and_a_code_works_once(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made, code=False)
        kek = get_settings().kek
        async with db.identity_session(admin) as session:
            secret = await start_setup(session, admin, kek=kek)
            assert await confirm_setup(session, admin, _code(secret, -1), kek=kek) is CodeResult.OK

        fresh = cookie(admin, code=False)
        needed = client.get("/v1/admin/shops", cookies=fresh)
        assert needed.status_code == 401
        assert needed.json()["error"]["code"] == "ADMIN_CODE_NEEDED"

        typed = client.post("/v1/admin/code", json={"code": _code(secret)}, cookies=fresh)
        assert typed.status_code == 200, typed.text
        signed = {COOKIE_NAME: typed.cookies[COOKIE_NAME]}
        assert client.get("/v1/admin/shops", cookies=signed).status_code == 200

        reused = client.post("/v1/admin/code", json={"code": _code(secret)}, cookies=fresh)
        assert reused.status_code == 400
        assert reused.json()["error"]["code"] == "WRONG_CODE"

    async def test_five_wrong_codes_stop_it_for_fifteen_minutes(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made, code=False)
        kek = get_settings().kek
        async with db.identity_session(admin) as session:
            secret = await start_setup(session, admin, kek=kek)
            assert await confirm_setup(session, admin, _code(secret, -1), kek=kek) is CodeResult.OK
        fresh = cookie(admin, code=False)
        answers = [
            client.post("/v1/admin/code", json={"code": "000000"}, cookies=fresh) for _ in range(5)
        ]
        assert [a.status_code for a in answers] == [400, 400, 400, 400, 429]
        assert answers[-1].json()["error"]["code"] == "TOO_MANY_CODES"
        right = client.post("/v1/admin/code", json={"code": _code(secret)}, cookies=fresh)
        assert right.status_code == 429, "even the right code waits"

    async def test_the_reset_command_clears_the_code_and_nothing_else(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made)
        async with db.identity_session() as session:
            email = await session.scalar(select(users.c.email).where(users.c.id == admin))
        assert await console_admin.admin_reset_code(str(email)) == 0
        after = client.get("/v1/admin/shops", cookies=cookie(admin))
        assert after.json()["error"]["code"] == "ADMIN_CODE_SETUP"
        async with db.identity_session() as session:
            assert await is_admin(session, admin), "still an admin"

    async def test_a_shops_own_routes_never_ask(
        self, client: TestClient, db: Database, made: Made
    ) -> None:
        admin = await _admin(db, made, code=False)
        me = client.get("/v1/console/me", cookies=cookie(admin, code=False))
        assert me.status_code == 200
        assert me.json()["data"]["is_admin"] is True


class TestWhoIsAnAdmin:
    async def test_me_says_so(self, client: TestClient, db: Database, made: Made) -> None:
        admin = await _admin(db, made)
        person, _ = await _person(db, made)
        assert (
            client.get("/v1/console/me", cookies=cookie(admin)).json()["data"]["is_admin"] is True
        )
        assert (
            client.get("/v1/console/me", cookies=cookie(person)).json()["data"]["is_admin"] is False
        )

    async def test_the_commands_change_the_list_and_nothing_else(
        self, db: Database, made: Made
    ) -> None:
        email = f"new-admin-{ids.new_id(ids.USER).lower()}@example.com"
        assert await console_admin.admin_add(email) == 0
        async with db.identity_session() as session:
            user = str(await session.scalar(select(users.c.id).where(users.c.email == email)))
        made.users.append(user)
        async with db.identity_session() as session:
            assert await is_admin(session, user)
        assert await console_admin.admin_add(email) == 0
        async with db.identity_session() as session:
            rows = await session.scalar(
                select(func.count())
                .select_from(platform_admins)
                .where(platform_admins.c.user_id == user)
            )
        assert rows == 1
        assert await console_admin.admin_list() == 0
        assert await console_admin.admin_remove(email) == 0
        async with db.identity_session() as session:
            assert not await is_admin(session, user)
        assert await console_admin.admin_remove(email) == 1
