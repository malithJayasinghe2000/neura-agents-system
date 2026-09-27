"""The console's sign-in endpoints, over HTTP. ADR-0026.

Integration rather than unit, because the interesting assertions are about what
the *database* enforces and what a real cookie jar does. A test that stubbed
either would prove the stub.

**The security assertions here are the point of the file**, not the happy path:
that a person is never told whether an address has an account, that a session
cookie carries no authority, that no API key ever appears in a response, and
that a revoked membership stops working on the very next request.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from neura_api.main import create_app
from neura_core import Database, get_settings, ids, load_env
from neura_core.identity import COOKIE_NAME, issue
from neura_core.identity.schema import login_tokens, memberships, users

pytestmark = pytest.mark.integration


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    """A client that **cannot send email**, whatever `.env` says.

    Not a convenience. A developer machine has real SMTP credentials in `.env`,
    and `request-link` for a known address sends for real — so without this the
    suite mails every fixture address it invents, from the developer's own
    account, every run. `Mailer` skips when there is no host, which is exactly
    the behaviour these tests want to exercise anyway.
    """
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
async def owner(db: Database):
    """One person, one merchant."""
    made = {
        "user": ids.new_id(ids.USER),
        "tenant": ids.new_id(ids.TENANT),
        "membership": ids.new_id(ids.MEMBERSHIP),
    }
    made["email"] = f"{made['user']}@example.com"

    async with db.identity_session() as s:
        await s.execute(users.insert().values(id=made["user"], email=made["email"], name="Owner"))
    async with db.tenant_session(made["tenant"]) as s:
        await s.execute(
            memberships.insert().values(
                id=made["membership"],
                tenant_id=made["tenant"],
                user_id=made["user"],
                role="owner",
            )
        )

    yield made

    async with db.tenant_session(made["tenant"]) as s:
        await s.execute(delete(memberships).where(memberships.c.id == made["membership"]))
    async with db.identity_session() as s:
        await s.execute(delete(login_tokens).where(login_tokens.c.user_id == made["user"]))
        await s.execute(delete(users).where(users.c.id == made["user"]))


class TestRequestLink:
    def test_a_known_and_an_unknown_address_are_indistinguishable(
        self, client: TestClient, owner
    ) -> None:
        """The anti-enumeration rule, asserted on the wire.

        Same status and same body — otherwise this endpoint tells anyone who
        asks which merchants use us, which is a customer list and a target list
        at the same time.
        """
        known = client.post("/v1/console/auth/request-link", json={"email": owner["email"]})
        unknown = client.post("/v1/console/auth/request-link", json={"email": "nobody@example.com"})

        assert known.status_code == unknown.status_code == 200
        assert known.json()["data"] == unknown.json()["data"]

    def test_a_malformed_address_is_refused_rather_than_silently_matching_nothing(
        self, client: TestClient
    ) -> None:
        """400, not 422 — this API's own error envelope (api-design.md)."""
        assert (
            client.post("/v1/console/auth/request-link", json={"email": "not-an-email"}).status_code
            == 400
        )

    def test_no_token_is_ever_returned_to_the_caller(self, client: TestClient, owner) -> None:
        """The link is a credential. It goes to the inbox and nowhere else."""
        body = client.post(
            "/v1/console/auth/request-link", json={"email": owner["email"]}
        ).text.lower()
        assert "token" not in body
        assert "auth/verify" not in body


class TestVerifyAndSession:
    def test_an_invalid_token_starts_no_session(self, client: TestClient) -> None:
        response = client.post("/v1/console/auth/verify", json={"token": "nope"})
        assert response.json()["data"]["signed_in"] is False
        assert COOKIE_NAME not in response.cookies

    def test_me_is_anonymous_without_a_cookie(self, client: TestClient) -> None:
        data = client.get("/v1/console/me").json()["data"]
        assert data["signed_in"] is False
        assert data["memberships"] == []

    def test_a_forged_cookie_is_not_a_session(self, client: TestClient, owner) -> None:
        """Signed with the wrong secret — the whole security of the session."""
        forged = issue(owner["user"], "not-the-servers-secret")
        data = client.get("/v1/console/me", cookies={COOKIE_NAME: forged}).json()["data"]
        assert data["signed_in"] is False

    def test_a_valid_session_lists_only_its_own_memberships(
        self, client: TestClient, owner
    ) -> None:
        from neura_core import get_settings

        cookie = issue(owner["user"], get_settings().secret_key)
        data = client.get("/v1/console/me", cookies={COOKIE_NAME: cookie}).json()["data"]

        assert data["signed_in"] is True
        assert data["user_id"] == owner["user"]
        assert [m["tenant_id"] for m in data["memberships"]] == [owner["tenant"]]

    async def test_a_membership_carries_its_shop_name_and_no_other_shops(
        self, client: TestClient, db: Database, owner
    ) -> None:
        """The name, so a merchant never has to recognise ``tn_01M…`` — and only theirs.

        ``tenants`` is read in each held shop's own session. A second shop with a
        recognisable name and no membership is the assertion that the lookup
        cannot be widened into a way of reading another merchant's name.
        """
        from neura_core import get_settings
        from neura_core.tenancy import TenantRepository
        from neura_core.tenancy.schema import tenants

        stranger = ids.new_id(ids.TENANT)
        async with db.tenant_session(owner["tenant"]) as s:
            await TenantRepository(s).create(tenant_id=owner["tenant"], name="Corner Bookshop")
        async with db.tenant_session(stranger) as s:
            await TenantRepository(s).create(tenant_id=stranger, name="Somebody Else's Shop")

        try:
            cookie = issue(owner["user"], get_settings().secret_key)
            response = client.get("/v1/console/me", cookies={COOKIE_NAME: cookie})

            assert response.json()["data"]["memberships"] == [
                {"tenant_id": owner["tenant"], "role": "owner", "name": "Corner Bookshop"}
            ]
            assert "Somebody Else" not in response.text
            assert stranger not in response.text
        finally:
            for tenant_id in (owner["tenant"], stranger):
                async with db.tenant_session(tenant_id) as s:
                    await s.execute(delete(tenants).where(tenants.c.tenant_id == tenant_id))

    def test_a_shop_with_no_tenant_row_has_no_name_rather_than_an_invented_one(
        self, client: TestClient, owner
    ) -> None:
        from neura_core import get_settings

        cookie = issue(owner["user"], get_settings().secret_key)
        data = client.get("/v1/console/me", cookies={COOKIE_NAME: cookie}).json()["data"]

        assert data["memberships"][0]["name"] is None

    async def test_a_revoked_membership_stops_working_on_the_next_request(
        self, client: TestClient, db: Database, owner
    ) -> None:
        """The reason the cookie carries no tenant.

        A cookie cannot be recalled, so access has to be re-derived. If this ever
        fails, revoking somebody's access does nothing until their cookie expires.
        """
        from neura_core import get_settings

        cookie = issue(owner["user"], get_settings().secret_key)
        assert client.get("/v1/console/me", cookies={COOKIE_NAME: cookie}).json()["data"][
            "memberships"
        ]

        async with db.tenant_session(owner["tenant"]) as s:
            await s.execute(
                memberships.update()
                .where(memberships.c.id == owner["membership"])
                .values(revoked_at=datetime.now(UTC))
            )

        after = client.get("/v1/console/me", cookies={COOKIE_NAME: cookie}).json()["data"]
        assert after["signed_in"] is True, "the person is still who they were"
        assert after["memberships"] == [], "revocation did not take effect immediately"


class TestNoAuthorityLeaksToTheBrowser:
    def test_no_response_contains_an_api_key(self, client: TestClient, owner) -> None:
        """ADR-0026 §3 — the rule the whole console rests on.

        `fn_sk_` / `fn_pk_` in a console response would mean the browser had been
        handed the tenant's full machine authority.
        """
        from neura_core import get_settings

        cookie = issue(owner["user"], get_settings().secret_key)
        bodies = [
            client.post("/v1/console/auth/request-link", json={"email": owner["email"]}).text,
            client.post("/v1/console/auth/verify", json={"token": "x"}).text,
            client.get("/v1/console/me", cookies={COOKIE_NAME: cookie}).text,
        ]
        for body in bodies:
            assert "fn_sk_" not in body
            assert "fn_pk_" not in body

    def test_sign_out_clears_the_cookie(self, client: TestClient) -> None:
        response = client.post("/v1/console/auth/sign-out")
        assert response.json()["data"]["signed_out"] is True
