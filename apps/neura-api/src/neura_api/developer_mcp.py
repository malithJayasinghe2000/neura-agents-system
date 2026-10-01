"""``POST /v1/developers/mcp``: a developer's AI tool asks how to build a bridge (ADR-0053).

**It teaches, and only teaches.** Four read-only tools over
``neura_adapters.generic.teacher``: the nine addresses, one address with its
format and a sample answer, the rules, and the OpenAPI file. Nothing here calls
a shop, reads a tenant or touches the database, which is why it answers anyone,
with no account and no token (§3), and why it is not one of SELL's surfaces: it
knows no shop at all. SELL's own MCP server (ADR-0023) is a different thing.

**Built on the MCP project's own library** (§2), not on hand-made protocol code:
the library follows each revision of the standard (it speaks the 2025
handshake and 2026-07-28's self-contained requests) and does the transport
checks the standard requires of a server. What is ours is in this file: the
tools, their labels, the limit and the count.

**Stateless, in plain JSON.** No session and nothing kept between questions, so
any copy of the API can answer any question; the only shared thing is the
limiter's counters in Redis.

**Three things it refuses, each in code (AGENTS.md rule 3):**

1. **A web page.** The standard's DNS-rebinding guard: a request with an
   ``Origin`` header is a browser's, and no page is meant to call this (403).
2. **A host that is not NEURA's** (421).
3. **Too many questions from one address** (429, ADR-0017's limiter, failing
   open like the rest). The address is fingerprinted, never stored.

**Counted, never read** (§5): one log line per tool call with the tool and the
format version. Never the arguments, never who asked.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import entry_points
from types import ModuleType
from typing import Annotated, Any
from urllib.parse import urlsplit

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from neura_api.dependencies import client_address
from neura_api.ratelimit import Verdict, anonymous_client, enforce
from neura_core import RateLimitError, Settings, get_logger, get_settings

log = get_logger(__name__)

#: Where `create_app` mounts it, and the path inside the mount.
MOUNT = "/v1/developers"
ENDPOINT = "/mcp"

#: The limiter subject: a client address, for a caller with no key.
LIMIT_SUBJECT = "developer-mcp-client"

#: Where the teacher is found. NEURA's API may not import the adapter package
#: (pyproject's import contracts, Rule 1), so it is discovered, exactly as
#: adapters are (``neura_commerce.registry``). Its content is platform-neutral
#: and tested so (``tests/unit/test_developer_teacher.py``).
TEACHER_ENTRY_POINT = "neura.bridge_teacher"

#: The MCP standard's labels (§4). Hints, as the standard says, but true ones:
#: every tool only reads our own fixed content.
READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

INSTRUCTIONS = (
    "NEURA teaches how to build a bridge: the nine read-only web addresses a shop answers so "
    "NEURA's assistants can read it. Start with list_addresses, build the first three, then use "
    "get_address for each address you build and get_rules for the rules bridges get wrong. "
    "This server never calls a shop and needs no token."
)

Version = Annotated[
    str | None,
    Field(description="The bridge format version to teach. Leave out for the current one."),
]


# ── The answers' declared formats (structured output, §4) ────────────────────


class AddressSummary(BaseModel):
    path: str
    answers: str
    capabilities: list[str]
    sample_request: str


class AddressGroup(BaseModel):
    group: str
    title: str
    note: str
    addresses: list[AddressSummary]


class AddressList(BaseModel):
    format_version: str
    how_to_start: str
    groups: list[AddressGroup]
    optional_capabilities: list[str]
    leave_out: list[str]


class RuleText(BaseModel):
    topic: str
    title: str
    text: str


class AddressDetail(BaseModel):
    format_version: str
    path: str
    answers: str
    group: str
    capabilities: list[str]
    request: dict[str, Any]
    schemas: dict[str, Any]
    sample_request: str
    #: One object (a product, an order, /health) or a list of them (categories,
    #: stock, policies): every sample the teacher has is one of the two.
    sample_answer: dict[str, Any] | list[dict[str, Any]]
    rules: list[RuleText]


class Rules(BaseModel):
    format_version: str
    rules: list[RuleText]


class OpenAPIDocument(BaseModel):
    format_version: str
    openapi: dict[str, Any]


def load_teacher() -> ModuleType:
    """The one registered teacher. None, or two, is a broken install, and the
    process should say so at start-up rather than answer with the wrong one."""
    found = list(entry_points(group=TEACHER_ENTRY_POINT))
    if len(found) != 1:
        raise RuntimeError(f"expected one {TEACHER_ENTRY_POINT!r} entry point, found {len(found)}")
    teacher: ModuleType = found[0].load()
    return teacher


def _answer[M: BaseModel](
    teacher: ModuleType, tool: str, ask: Callable[[], dict[str, Any]], model: type[M]
) -> M:
    """One tool call: ask the teacher, count it, and shape the answer."""
    try:
        answer = ask()
    except teacher.TeacherError as exc:
        # The teacher's message names what it does know, so an AI tool can
        # correct itself rather than guess again.
        raise ToolError(str(exc)) from exc
    log.info("developer_mcp_tool_called", tool=tool, format_version=answer["format_version"])
    return model.model_validate(answer)


def build_server(teacher: ModuleType | None = None) -> MCPServer:
    teacher = teacher or load_teacher()
    server = MCPServer(
        name="neura-bridge",
        title="NEURA: build a bridge",
        instructions=INSTRUCTIONS,
    )

    @server.tool(
        title="The nine addresses",
        description="The nine addresses a bridge answers, in the order to build them, with the "
        "/health word each needs and a sample request.",
        annotations=READ_ONLY,
    )
    def list_addresses(version: Version = None) -> AddressList:
        return _answer(
            teacher, "list_addresses", lambda: teacher.list_addresses(version), AddressList
        )

    @server.tool(
        title="One address",
        description="One address: its request and parameters, the format of its answer, a sample "
        "answer that NEURA reads correctly, and the rules for it.",
        annotations=READ_ONLY,
    )
    def get_address(
        path: Annotated[
            str, Field(description="The address as list_addresses names it, e.g. /products/{id}.")
        ],
        version: Version = None,
    ) -> AddressDetail:
        return _answer(
            teacher, "get_address", lambda: teacher.get_address(path, version), AddressDetail
        )

    @server.tool(
        title="The rules",
        description="The rules bridges get wrong: the token, /health, paging, statuses, prices, "
        "customers only, and what to leave out. All of them, or one topic.",
        annotations=READ_ONLY,
    )
    def get_rules(
        topic: Annotated[
            str | None, Field(description="One topic, e.g. products. Leave out for all.")
        ] = None,
        version: Version = None,
    ) -> Rules:
        return _answer(teacher, "get_rules", lambda: teacher.get_rules(topic, version), Rules)

    @server.tool(
        title="The OpenAPI file",
        description="The whole OpenAPI file of the bridge format, for a code generator.",
        annotations=READ_ONLY,
    )
    def get_openapi(version: Version = None) -> OpenAPIDocument:
        return _answer(
            teacher, "get_openapi", lambda: teacher.get_openapi(version), OpenAPIDocument
        )

    return server


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """NEURA's own host only, and no web page (`Origin` is never allowed)."""
    hosts = {urlsplit(settings.public_base_url).netloc}
    if not settings.is_production:
        hosts |= {"localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"}
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(hosts),
        allowed_origins=[],
    )


def build_app(server: MCPServer, settings: Settings | None = None) -> ASGIApp:
    """The server's HTTP app: stateless, plain JSON. Its session manager must be
    running (``server.session_manager.run()``) before it answers."""
    return server.streamable_http_app(
        streamable_http_path=ENDPOINT,
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(settings or get_settings()),
    )


class Limited:
    """The limit per client address, in front of the MCP app.

    Here rather than in a FastAPI dependency because the MCP app is mounted, and
    a mounted app runs no dependencies. ``limiter`` is read per request, because
    the limiter is built in the lifespan, after the app is mounted.
    """

    def __init__(self, app: ASGIApp, limiter: Callable[[], Any]) -> None:
        self._app = app
        self._limiter = limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        subject = anonymous_client(
            LIMIT_SUBJECT,
            client_address(Request(scope)),
            get_settings().rate_limit_developer_mcp,
        )
        verdict: Verdict = await self._limiter().check([subject])
        try:
            enforce(verdict)
        except RateLimitError as exc:
            refusal = JSONResponse(
                exc.to_dict(None), status_code=exc.http_status, headers=verdict.headers()
            )
            await refusal(scope, receive, send)
            return

        async def with_limit_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [(k.lower().encode(), v.encode()) for k, v in verdict.headers().items()]
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, with_limit_headers)


__all__ = [
    "ENDPOINT",
    "LIMIT_SUBJECT",
    "MOUNT",
    "READ_ONLY",
    "TEACHER_ENTRY_POINT",
    "Limited",
    "build_app",
    "build_server",
    "load_teacher",
    "transport_security",
]
