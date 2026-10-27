"""ADR-0058 §1, §2 and §9 over HTTP and against real RLS: each role is refused, or let in.

What these tests hold the build to:

* **every** dashboard route that names a shop, called by each role: a member
  whose role does not include the route's permission gets **403**
  ``ROLE_NOT_ALLOWED``, and one whose role does is not turned away at the door
  (what the route then answers is its own business: a 404 for a made-up id, a
  422 for a made-up body);
* the 403 comes **before** the body is read, so a refused member learns nothing
  from a validation error and nothing is written;
* a person with no membership in the shop gets **404** ``No such shop.`` on
  every route, never 403, even when they own another shop (ADR-0026: a 403 would
  say the shop exists);
* the database refuses a role the code does not know, and a membership made
  without a role is still an Owner (existing members stay owners).

The routes and who may open them are ``tests/console_permissions.py``, written
from the ADR rather than from the code's map.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import memberships, users
from neura_core.tenancy import TenantConfig, TenantRepository, TurnMode
from neura_core.tenancy.schema import customer_secrets, tenants
from tests.console_permissions import DEVELOPER, OWNER, ROLES, ROUTES, SUPPORT, WHO
from tests.integration.console_fixtures import Shop, drop_shop, make_shop

pytestmark = pytest.mark.integration

#: What fills every path parameter but the shop: an id nothing has, so a route
#: that lets the person in answers its own 404 and changes nothing.
MADE_UP = "probe-not-there"


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


@dataclass
class Team:
    """One shop with an Owner, a Support person and a Developer, and a stranger
    who owns a different shop."""

    shop: Shop
    people: dict[str, str] = field(default_factory=dict)
    memberships: list[str] = field(default_factory=list)
    stranger: str = ""
    elsewhere: str = ""
    elsewhere_membership: str = ""

    @property
    def tenant(self) -> str:
        return self.shop.tenant


@pytest.fixture
async def team(db: Database):
    shop = await make_shop(db)
    made = Team(shop=shop, people={OWNER: shop.user})
    async with db.tenant_session(shop.tenant) as session:
        # A real tenants row with both assistants, so SELL's Suggestions answers
        # as it would for a real shop rather than "this shop does not have it";
        # in practice mode, so *Go live* would be a change.
        await TenantRepository(session).create(
            tenant_id=shop.tenant,
            name="Roles Test Shop",
            enabled_agents=["care", "sell"],
            config=TenantConfig(mode=TurnMode.SHADOW),
        )
    for role in (SUPPORT, DEVELOPER):
        user = ids.new_id(ids.USER)
        membership = ids.new_id(ids.MEMBERSHIP)
        async with db.identity_session() as session:
            await session.execute(
                users.insert().values(id=user, email=f"{user}@example.com", name=role)
            )
        async with db.tenant_session(shop.tenant) as session:
            await session.execute(
                memberships.insert().values(
                    id=membership, tenant_id=shop.tenant, user_id=user, role=role
                )
            )
        made.people[role] = user
        made.memberships.append(membership)

    made.stranger = ids.new_id(ids.USER)
    made.elsewhere = ids.new_id(ids.TENANT)
    made.elsewhere_membership = ids.new_id(ids.MEMBERSHIP)
    async with db.identity_session() as session:
        await session.execute(
            users.insert().values(id=made.stranger, email=f"{made.stranger}@example.com")
        )
    async with db.tenant_session(made.elsewhere) as session:
        await session.execute(
            memberships.insert().values(
                id=made.elsewhere_membership,
                tenant_id=made.elsewhere,
                user_id=made.stranger,
                role=OWNER,
            )
        )

    yield made

    async with db.tenant_session(shop.tenant) as session:
        await session.execute(delete(memberships).where(memberships.c.id.in_(made.memberships)))
        await session.execute(
            delete(customer_secrets).where(customer_secrets.c.tenant_id == shop.tenant)
        )
        await session.execute(delete(tenants).where(tenants.c.tenant_id == shop.tenant))
    async with db.tenant_session(made.elsewhere) as session:
        await session.execute(
            delete(memberships).where(memberships.c.id == made.elsewhere_membership)
        )
    await drop_shop(db, shop)
    async with db.identity_session() as session:
        await session.execute(
            delete(users).where(
                users.c.id.in_([made.people[SUPPORT], made.people[DEVELOPER], made.stranger])
            )
        )
    # The application role may not delete audit entries; only the operator's may.
    engine = create_async_engine(str(get_settings().database_migration_url))
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM audit_log WHERE tenant_id = :t"), {"t": shop.tenant}
            )
    finally:
        await engine.dispose()


def signed_in(user: str) -> dict[str, str]:
    return {COOKIE_NAME: issue(user, get_settings().secret_key)}


def call(client: TestClient, method: str, template: str, tenant: str, user: str) -> Response:
    """One route, for one shop, as one person. A body that is not an object, so
    a route that lets them in refuses the body and writes nothing."""
    path = re.sub(r"\{[a-z_]+\}", MADE_UP, template.replace("{tenant_id}", tenant))
    body = [] if method in {"POST", "PUT", "DELETE"} else None
    return client.request(method, path, json=body, cookies=signed_in(user))


def turned_away(response: Response) -> str:
    """Why the door refused, or ``""`` when it did not."""
    error = response.json().get("error") or {}
    if response.status_code == 403 and error.get("code") == "ROLE_NOT_ALLOWED":
        return "role"
    if response.status_code == 404 and error.get("message") == "No such shop.":
        return "stranger"
    if response.status_code == 401:
        return "signed out"
    return ""


class TestEachRoleOnEveryRoute:
    @pytest.mark.parametrize("role", ROLES)
    async def test_each_role_is_refused_exactly_what_it_does_not_include(
        self, client: TestClient, team: Team, role: str
    ) -> None:
        wrong = []
        for (method, template), permission in sorted(ROUTES.items()):
            response = call(client, method, template, team.tenant, team.people[role])
            refused = turned_away(response)
            if role in WHO[permission] and refused:
                wrong.append(f"{method} {template}: refused ({refused}), the role includes it")
            elif role not in WHO[permission] and refused != "role":
                wrong.append(
                    f"{method} {template}: answered {response.status_code}, "
                    f"expected 403 ROLE_NOT_ALLOWED ({permission})"
                )
        assert not wrong, f"{role}:\n" + "\n".join(wrong)

    async def test_a_stranger_gets_404_on_every_route_never_403(
        self, client: TestClient, team: Team
    ) -> None:
        wrong = [
            f"{method} {template}: {response.status_code}"
            for method, template in sorted(ROUTES)
            if turned_away(response := call(client, method, template, team.tenant, team.stranger))
            != "stranger"
        ]
        assert not wrong, "\n".join(wrong)


class TestTheRefusal:
    async def test_it_says_the_role_and_what_the_role_does_not_include(
        self, client: TestClient, team: Team
    ) -> None:
        response = client.get(
            f"/v1/console/shops/{team.tenant}/usage", cookies=signed_in(team.people[SUPPORT])
        )
        assert response.status_code == 403
        error = response.json()["error"]
        assert error["code"] == "ROLE_NOT_ALLOWED"
        assert error["details"] == {"role": "support", "permission": "usage:cost:read"}
        assert "ask the shop's owner" in error["message"]

    async def test_a_refused_member_changes_nothing(
        self, client: TestClient, db: Database, team: Team
    ) -> None:
        """A whole, valid request from Support: *Go live*, and a new sign-in secret.
        Both refused, and both still as they were."""
        cookies = signed_in(team.people[SUPPORT])
        base = f"/v1/console/shops/{team.tenant}"

        assert client.put(f"{base}/mode", json={"mode": "live"}, cookies=cookies).status_code == 403
        assert client.post(f"{base}/customer-secret", cookies=cookies).status_code == 403

        async with db.tenant_session(team.tenant) as session:
            tenant = await TenantRepository(session).get(team.tenant)
            secret = await session.scalar(
                select(customer_secrets.c.tenant_id).where(
                    customer_secrets.c.tenant_id == team.tenant
                )
            )
        assert tenant is not None
        assert tenant.config.mode is TurnMode.SHADOW
        assert secret is None

    async def test_the_developer_may_make_the_shops_secrets(
        self, client: TestClient, team: Team
    ) -> None:
        """R10: the Developer makes the sign-in secret and puts it straight into the
        shop's settings, so it never travels by email or chat."""
        made = client.post(
            f"/v1/console/shops/{team.tenant}/customer-secret",
            cookies=signed_in(team.people[DEVELOPER]),
        )
        assert made.status_code == 200
        assert made.json()["data"]["secret"]


class TestTheDatabase:
    async def test_it_refuses_a_role_the_code_does_not_know(self, db: Database, team: Team) -> None:
        user = ids.new_id(ids.USER)
        membership = ids.new_id(ids.MEMBERSHIP)
        async with db.identity_session() as session:
            await session.execute(users.insert().values(id=user, email=f"{user}@example.com"))
        try:
            with pytest.raises(IntegrityError, match="ck_memberships_role"):
                async with db.tenant_session(team.tenant) as session:
                    await session.execute(
                        memberships.insert().values(
                            id=membership, tenant_id=team.tenant, user_id=user, role="admin"
                        )
                    )
        finally:
            async with db.tenant_session(team.tenant) as session:
                await session.execute(delete(memberships).where(memberships.c.id == membership))
            async with db.identity_session() as session:
                await session.execute(delete(users).where(users.c.id == user))

    async def test_a_membership_made_without_a_role_is_an_owner(
        self, db: Database, team: Team
    ) -> None:
        user = ids.new_id(ids.USER)
        membership = ids.new_id(ids.MEMBERSHIP)
        async with db.identity_session() as session:
            await session.execute(users.insert().values(id=user, email=f"{user}@example.com"))
        try:
            async with db.tenant_session(team.tenant) as session:
                await session.execute(
                    memberships.insert().values(id=membership, tenant_id=team.tenant, user_id=user)
                )
                role = await session.scalar(
                    select(memberships.c.role).where(memberships.c.id == membership)
                )
            assert role == OWNER
        finally:
            async with db.tenant_session(team.tenant) as session:
                await session.execute(delete(memberships).where(memberships.c.id == membership))
            async with db.identity_session() as session:
                await session.execute(delete(users).where(users.c.id == user))
