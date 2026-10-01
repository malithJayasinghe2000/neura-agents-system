"""``POST /v1/developers/mcp``: the teacher, served (ADR-0053 §2, §3, §5).

Driven by **the MCP project's own client**, over an in-process transport, in
both eras the library speaks: the 2025 handshake and 2026-07-28's
self-contained requests. A server that only our own tests can talk to is the
failure ADR-0053 §5 names ("nothing shows that SELL's MCP server was ever tried
this way"); this is the cheapest real client there is, and it costs no model.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
import structlog.testing
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.routing import Mount

from neura_adapters.generic import teacher
from neura_adapters.generic.wire import SPEC_VERSION
from neura_api import developer_mcp
from neura_api.ratelimit import Verdict

BASE = "http://localhost:8010"
URL = f"{BASE}{developer_mcp.MOUNT}{developer_mcp.ENDPOINT}"
TOOLS = {"list_addresses", "get_address", "get_rules", "get_openapi"}


class _Limiter:
    """Records what it was asked, and allows or refuses everything."""

    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.subjects: list[Any] = []

    async def check(self, subjects: Any) -> Verdict:
        self.subjects.extend(subjects)
        limit = subjects[0].limit
        return Verdict(
            allowed=self.allow,
            limit=limit,
            remaining=limit - 1 if self.allow else 0,
            reset=1_900_000_000,
            subject=subjects[0].kind,
        )


@asynccontextmanager
async def _served(limiter: _Limiter | None = None) -> AsyncIterator[tuple[Starlette, _Limiter]]:
    """The route as `create_app` mounts it, without a database."""
    limiter = limiter or _Limiter()
    server = developer_mcp.build_server()
    inner = developer_mcp.build_app(server)
    app = Starlette(
        routes=[Mount(developer_mcp.MOUNT, app=developer_mcp.Limited(inner, lambda: limiter))]
    )
    async with server.session_manager.run():
        yield app, limiter


def _http(app: Starlette, **headers: str) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url=BASE, headers=headers
    )


@asynccontextmanager
async def _connected(
    mode: str = "legacy", limiter: _Limiter | None = None
) -> AsyncIterator[tuple[Client, _Limiter]]:
    """The official MCP client, connected to the route."""
    async with (
        _served(limiter) as (app, used),
        _http(app) as http,
        Client(streamable_http_client(URL, http_client=http), mode=mode) as client,
    ):
        yield client, used


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_the_official_client_sees_four_read_only_tools(mode: str) -> None:
    async with _connected(mode) as (client, _):
        tools = (await client.list_tools()).tools

    assert {tool.name for tool in tools} == TOOLS
    for tool in tools:
        labels = tool.annotations
        assert labels is not None, tool.name
        assert labels.read_only_hint is True
        assert labels.destructive_hint is False
        assert labels.idempotent_hint is True
        assert labels.open_world_hint is False
        assert tool.output_schema, f"{tool.name} declares no output format"


@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_it_teaches_the_nine_addresses_with_their_format_version(mode: str) -> None:
    async with _connected(mode) as (client, _):
        result = await client.call_tool("list_addresses", {})

    assert not result.is_error
    answer = result.structured_content
    assert answer is not None
    assert answer["format_version"] == SPEC_VERSION
    paths = {a["path"] for group in answer["groups"] for a in group["addresses"]}
    assert paths == {address.path for address in teacher.ADDRESSES}


async def test_one_address_comes_with_its_sample_answer() -> None:
    async with _connected() as (client, _):
        result = await client.call_tool("get_address", {"path": "/products/{id}"})

    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["sample_answer"] == teacher.SAMPLE_PRODUCT


async def test_an_unknown_address_is_an_error_that_names_the_nine() -> None:
    async with _connected() as (client, _):
        result = await client.call_tool("get_address", {"path": "/carts"})

    assert result.is_error
    text = " ".join(getattr(part, "text", "") for part in result.content)
    assert "/health" in text and "/customers/{id}" in text


async def test_it_needs_no_account_and_no_token() -> None:
    """ADR-0053 §3: it holds nothing worth protecting. The client above sends no
    Authorization header; this says so on purpose."""
    async with _connected() as (client, _):
        result = await client.call_tool("get_rules", {"topic": "customers"})

    assert not result.is_error


async def test_it_keeps_no_session() -> None:
    """Stateless: any copy of NEURA's API can answer any question."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    async with (
        _served() as (app, _),
        _http(app, Accept="application/json, text/event-stream") as http,
    ):
        response = await http.post(URL, json=body)

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers
    assert response.headers["content-type"].startswith("application/json")


async def test_a_request_from_a_web_page_is_refused() -> None:
    """The MCP standard's DNS-rebinding guard: a browser marks a page's request
    with `Origin`, and no web page is meant to call this."""
    async with _served() as (app, _), _http(app, Origin="https://evil.example") as http:
        response = await http.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 403


async def test_a_host_that_is_not_neuras_is_refused() -> None:
    async with _served() as (app, _), _http(app, Host="attacker.example") as http:
        response = await http.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 421


async def test_each_client_address_is_limited_and_never_stored_as_it_is() -> None:
    async with _connected() as (client, limiter):
        await client.call_tool("get_rules", {})

    assert limiter.subjects
    subject = limiter.subjects[0]
    assert subject.kind == developer_mcp.LIMIT_SUBJECT
    # A keyed hash, never the address itself (ADR-0017).
    assert "127.0.0.1" not in subject.identity
    assert len(subject.identity) == 32


async def test_over_the_limit_is_a_429_that_says_when_to_retry() -> None:
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    async with _served(_Limiter(allow=False)) as (app, _), _http(app) as http:
        response = await http.post(URL, json=body)

    assert response.status_code == 429
    assert response.headers["retry-after"]
    assert response.json()["error"]["code"] == "RATE_LIMITED"


async def test_each_call_is_counted_by_tool_never_by_what_was_asked() -> None:
    async with _connected() as (client, _):
        with structlog.testing.capture_logs() as logs:
            await client.call_tool("get_address", {"path": "/orders/{id}"})

    counted = [entry for entry in logs if entry["event"] == "developer_mcp_tool_called"]
    assert counted == [
        {
            "event": "developer_mcp_tool_called",
            "log_level": "info",
            "tool": "get_address",
            "format_version": SPEC_VERSION,
        }
    ]


def test_create_app_mounts_it_at_its_address() -> None:
    from neura_api.main import create_app

    mounts = {getattr(route, "path", None) for route in create_app().routes}
    assert developer_mcp.MOUNT in mounts
