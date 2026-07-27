"""API contract tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from neura_api.main import create_app


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
        # docs_url is what turns a 404 into a self-service fix.
        assert error["docs_url"].endswith("/NOT_FOUND")

    def test_error_request_id_matches_the_header(self, client: TestClient) -> None:
        response = client.get("/v1/does-not-exist")
        assert response.json()["error"]["request_id"] == response.headers["X-Request-Id"]
