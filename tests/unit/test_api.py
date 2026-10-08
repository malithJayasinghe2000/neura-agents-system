"""API contract tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neura_api.errors import register_error_handlers
from neura_api.main import create_app
from neura_core.observation import ObservedEvent


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A client that actually runs the app's lifespan.

    `TestClient(app)` without the context manager skips startup and shutdown
    entirely — so agent discovery and config validation would go untested, and
    the connection pool opened by the readiness probe would never be closed,
    leaving live sockets attached to a finished event loop.
    """
    with TestClient(create_app()) as test_client:
        yield test_client


class TestHealth:
    def test_liveness(self, client: TestClient) -> None:
        response = client.get("/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_readiness_reports_components(self, client: TestClient) -> None:
        body = client.get("/v1/health/ready").json()
        names = {c["name"] for c in body["components"]}
        assert {"postgres", "redis"} <= names

    def test_postgres_is_really_checked(self, client: TestClient) -> None:
        """It must report what it found — `ok` or `down` — never `not_implemented`.

        The database exists as of milestone 1.9. A readiness probe still
        answering "not wired up yet" would be reporting the codebase of a
        previous milestone, and readiness that is stale is readiness that lies.
        """
        body = client.get("/v1/health/ready").json()
        postgres = next(c for c in body["components"] if c["name"] == "postgres")
        assert postgres["status"] in {"ok", "down"}

    def test_request_id_header_is_always_present(self, client: TestClient) -> None:
        """Clients quote this when reporting a problem, so it must never be absent."""
        assert client.get("/v1/health").headers.get("X-Request-Id")


class TestAgentDiscovery:
    def test_care_is_discovered_via_entry_points(self, client: TestClient) -> None:
        """Agents self-register; there is no central list to edit."""
        installed = client.get("/v1/agents").json()["data"]["installed"]
        care = next(a for a in installed if a["key"] == "care")
        assert care["name"] == "NEURA-CARE"
        assert care["route_prefix"] == "/v1/care"

    def test_manifest_declares_required_capabilities(self, client: TestClient) -> None:
        """These drive tool filtering and give a connection-time compatibility check."""
        installed = client.get("/v1/agents").json()["data"]["installed"]
        care = next(a for a in installed if a["key"] == "care")
        assert set(care["requires_capabilities"]) == {
            "order.read",
            "policy.read",
            "product.search",
        }


class TestErrorContract:
    def test_unknown_route_uses_the_standard_shape(self, client: TestClient) -> None:
        body = client.get("/v1/does-not-exist").json()
        assert set(body) == {"error"}
        error = body["error"]
        # `code` is machine-readable and stable — clients branch on it.
        assert error["code"] == "NOT_FOUND"
        assert error["type"] == "invalid_request"
        assert error["request_id"]
        # G62, ADR-0056: no link until a page exists to link to. Every error
        # pointed at docs.fiveneurals.com, which has no address at all.
        assert "docs_url" not in error

    def test_no_error_links_to_a_page_that_does_not_exist(self) -> None:
        """Every builder of an error: our own errors, and the 400 and 500 handlers."""
        from neura_core import NotFoundError

        assert "docs_url" not in NotFoundError("gone").to_dict(request_id="req_1")["error"]
        root = Path(__file__).resolve().parents[2]
        source = (root / "apps/neura-api/src/neura_api/errors.py").read_text()
        assert "docs.fiveneurals.com" not in source

    def test_error_request_id_matches_the_header(self, client: TestClient) -> None:
        response = client.get("/v1/does-not-exist")
        assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]


#: A correct product view, for G64's tests.
_VIEW: dict[str, Any] = {
    "event_id": "ev_0123456789abcdef",
    "session_id": "s_0123456789abcdef",
    "type": "product.viewed",
    "product_id": "1042",
    "occurred_at": "2026-10-01T09:30:00Z",
    "in_stock": False,
}


class TestAWrongFieldIsAlwaysA400:
    """G64: a check of our own (a pydantic validator) carries the Python
    exception, and sometimes the date it refused, inside its error. The 400
    handler put those into the answer as they were, could not turn them into
    JSON, and the developer got a 500 "internal error" for one wrong field.

    The product view is the case that found it: its model has three such checks.
    """

    @pytest.fixture
    def events(self) -> Iterator[TestClient]:
        app = FastAPI()
        register_error_handlers(app)

        @app.post("/events")
        async def record(event: ObservedEvent) -> dict[str, str]:
            return {"event_id": event.event_id}

        # As a real client sees it: a crash in the handler is a 500, not a
        # Python exception raised into the test.
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client

    def test_a_correct_view_passes(self, events: TestClient) -> None:
        assert events.post("/events", json=_VIEW).status_code == 200

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            pytest.param(
                {k: v for k, v in _VIEW.items() if k != "in_stock"},
                "in_stock",
                id="a view without in_stock",
            ),
            pytest.param(
                {**_VIEW, "type": "cart.added", "in_stock": True},
                "in_stock",
                id="a basket add with in_stock",
            ),
            pytest.param(
                {**_VIEW, "occurred_at": "2026-10-01T09:30:00"},
                "occurred_at",
                id="a time with no time zone",
            ),
        ],
    )
    def test_our_own_checks_answer_400_naming_the_field(
        self, events: TestClient, body: dict[str, Any], field: str
    ) -> None:
        response = events.post("/events", json=body)

        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "INVALID_REQUEST"
        problems = error["details"]["errors"]
        assert any(field in p["msg"] or field in p["loc"] for p in problems)


class TestNoSecretKeyInAnAddress:
    """G34: an address is written down by things we do not control, so only a
    public key may travel in one. A server sends a secret key in a header."""

    class _Request:
        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

    def test_a_secret_key_in_the_address_is_refused_before_any_lookup(self) -> None:
        import asyncio

        from neura_api.dependencies import authenticate_request
        from neura_core import AuthenticationError
        from neura_core.tenancy.keys import ApiKeyKind, generate

        secret = generate(ApiKeyKind.SECRET).token
        with pytest.raises(AuthenticationError, match="Authorization header"):
            # No database is configured here, so reaching the lookup would fail
            # differently: the refusal has to come first.
            asyncio.run(authenticate_request(self._Request(), token=secret))  # type: ignore[arg-type]

    def test_a_public_key_in_the_address_is_not_refused_for_being_there(self) -> None:
        import asyncio

        from neura_api.dependencies import authenticate_request
        from neura_core.tenancy.keys import ApiKeyKind, generate

        public = generate(ApiKeyKind.PUBLIC).token
        with pytest.raises(Exception) as raised:
            asyncio.run(authenticate_request(self._Request(), token=public))  # type: ignore[arg-type]
        assert "Authorization header" not in str(raised.value)


class TestNoSecretKeyInAPage:
    """G55: a browser marks every request a page makes with ``Origin``; a
    server's HTTP client does not. A secret key arriving with one was put in a
    web page, where anyone can read it, and it used to work there."""

    class _Request:
        def __init__(self, key: str, origin: str | None) -> None:
            self.headers = {"authorization": f"Bearer {key}"}
            if origin:
                self.headers["origin"] = origin
            self.state = type("State", (), {})()

    @staticmethod
    def _authenticate(request: Any) -> BaseException:
        import asyncio

        from neura_api.dependencies import authenticate_request

        # No database is configured here, so every call ends in an exception:
        # the question is only which one.
        with pytest.raises(Exception) as raised:
            asyncio.run(authenticate_request(request))
        return raised.value

    def test_a_secret_key_from_a_web_page_is_refused_before_any_lookup(self) -> None:
        from neura_api.dependencies import SECRET_KEY_IN_PAGE
        from neura_core import AuthenticationError
        from neura_core.tenancy.keys import ApiKeyKind, generate

        request = self._Request(generate(ApiKeyKind.SECRET).token, "https://shop.example")
        refused = self._authenticate(request)
        assert isinstance(refused, AuthenticationError)
        assert refused.code == SECRET_KEY_IN_PAGE
        # The mark that lets the page read this one refusal (middleware/cors.py).
        assert request.state.secret_key_in_page is True

    def test_a_secret_key_from_a_server_is_not_refused_for_it(self) -> None:
        from neura_api.dependencies import SECRET_KEY_IN_PAGE
        from neura_core.tenancy.keys import ApiKeyKind, generate

        request = self._Request(generate(ApiKeyKind.SECRET).token, None)
        assert getattr(self._authenticate(request), "code", None) != SECRET_KEY_IN_PAGE
        assert not hasattr(request.state, "secret_key_in_page")

    def test_a_public_key_from_a_web_page_is_not_refused_for_it(self) -> None:
        from neura_api.dependencies import SECRET_KEY_IN_PAGE
        from neura_core.tenancy.keys import ApiKeyKind, generate

        request = self._Request(generate(ApiKeyKind.PUBLIC).token, "https://shop.example")
        assert getattr(self._authenticate(request), "code", None) != SECRET_KEY_IN_PAGE


class TestNoShopTokenInAPage:
    """G57: the shop token (``fn_st_``) is the bridge's password. Pasted into the
    chat box line by mistake it was refused as an unknown key the page could not
    read, so the chat box could only say it could not reach the assistant, while
    the token sat in the page for anyone to copy."""

    _Request = TestNoSecretKeyInAPage._Request
    _authenticate = staticmethod(TestNoSecretKeyInAPage._authenticate)

    def test_a_shop_token_from_a_web_page_is_refused_before_any_lookup(self) -> None:
        from neura_api.dependencies import SHOP_TOKEN_IN_PAGE
        from neura_core import AuthenticationError
        from neura_core.tenancy import new_shop_token

        request = self._Request(new_shop_token(), "https://shop.example")
        refused = self._authenticate(request)
        assert isinstance(refused, AuthenticationError)
        assert refused.code == SHOP_TOKEN_IN_PAGE
        assert "shop token" in str(refused)
        assert "fn_pk_" in str(refused)
        # The same mark as G55: the page may read this refusal (middleware/cors.py).
        assert request.state.secret_key_in_page is True

    def test_a_shop_token_in_the_chat_sockets_address_is_refused_the_same_way(self) -> None:
        import asyncio

        from neura_api.dependencies import SHOP_TOKEN_IN_PAGE, authenticate_request
        from neura_core.tenancy import new_shop_token

        request = self._Request("", "https://shop.example")
        request.headers.pop("authorization")
        with pytest.raises(Exception) as raised:
            asyncio.run(authenticate_request(request, token=new_shop_token()))
        assert getattr(raised.value, "code", None) == SHOP_TOKEN_IN_PAGE

    def test_a_shop_token_from_a_server_is_not_refused_for_it(self) -> None:
        from neura_api.dependencies import SHOP_TOKEN_IN_PAGE
        from neura_core.tenancy import new_shop_token

        request = self._Request(new_shop_token(), None)
        assert getattr(self._authenticate(request), "code", None) != SHOP_TOKEN_IN_PAGE
        assert not hasattr(request.state, "secret_key_in_page")
