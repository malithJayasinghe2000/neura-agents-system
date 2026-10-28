"""FastAPI application factory.

One deployable process (ADR-0002). Agents are discovered at startup via entry
points and mounted at their declared prefixes; there is no central list to edit.

**Everything expensive is built once, at startup, and lives on ``app.state``.**
The LLM client holds provider connections, an agent runner holds a compiled
graph, the store directory holds a capability cache, and the rate limiter holds a
Redis pool. Building any of them per request would put process setup inside a
shopper's latency — and, for the graph, would measure graph construction as if it
were agent latency, which is the mistake the eval target's docstring warns about.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from neura_api import developer_mcp
from neura_api.dependencies import declared_permissions
from neura_api.errors import register_error_handlers
from neura_api.idempotency import Idempotency
from neura_api.jobs import (
    RETENTION_SWEEP,
    SHOP_CHECK,
    SYNC_STORE,
    WEBHOOK_DRAIN,
    JobRunner,
    RetentionSweepHandler,
    ShopCheckHandler,
    SyncStoreHandler,
    WebhookDrainHandler,
)
from neura_api.middleware.cors import TenantCorsMiddleware
from neura_api.middleware.request_context import RequestContextMiddleware
from neura_api.ratelimit import RateLimiter
from neura_api.registry import (
    discover_agent_routes,
    discover_agents,
    discover_job_handlers,
    discover_runners,
)
from neura_api.routes import (
    admin,
    admin_code,
    console,
    console_connect,
    console_contact,
    console_conversations,
    console_customer_secret,
    console_gaps,
    console_handover,
    console_home,
    console_mode,
    console_people,
    console_review,
    console_shop,
    console_sign_up,
    console_sold_out,
    console_usage,
    dispatch,
    handover_email,
    health,
    observe,
    stores,
    webhooks,
    widget,
)
from neura_api.routes import agent as agent_routes
from neura_api.stores import StoreDirectory
from neura_api.turns import TurnService
from neura_api.webhooks import WebhookDrainer
from neura_core import (
    Database,
    Environment,
    configure_logging,
    configure_telemetry,
    get_database,
    get_logger,
    get_settings,
    load_env,
)

log = get_logger(__name__)

DESCRIPTION = """
Platform-agnostic AI agents for commerce.

The API speaks one canonical vocabulary regardless of the merchant's commerce
platform. See https://docs.fiveneurals.com for integration guides.
""".strip()


def _redis() -> Any | None:
    """A Redis client, or ``None`` if the package or the server is missing.

    ``None`` is a working state, not a failure: rate limiting fails **open** and
    says so on every request (ADR-0017 §3). That is now the *only* thing Redis
    backs — the webhook drainer's tenant index moved into PostgreSQL on
    2026-08-26 (ADR-0022), so a deployment without Redis still delivers every
    webhook it queued.
    """
    try:
        import redis.asyncio as redis
    except ImportError:  # pragma: no cover — redis is a declared dependency
        log.error("redis_unavailable", detail="package not installed")
        return None

    try:
        return redis.from_url(str(get_settings().redis_url))
    except Exception as exc:  # a bad URL must not stop the process booting
        log.error("redis_unavailable", error=str(exc))
        return None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Refuse to serve real traffic with placeholder secrets.
    settings.validate_for_runtime()

    database = get_database()
    app.state.database = database
    app.state.agents = discover_agents()
    app.state.runners = discover_runners()
    app.state.redis = _redis()
    app.state.limiter = RateLimiter(app.state.redis)
    app.state.idempotency = Idempotency(database)
    app.state.stores = StoreDirectory(database)
    app.state.drainer = WebhookDrainer(database)
    # One client, shared. The dispatcher ([ADR-0031]) calls a model *before* any
    # turn exists, so it cannot borrow the per-turn `MeteredLLM` the turn
    # service wraps around this — and building a second client would open a
    # second HTTP connection pool per process for one extra call per message.
    #
    # Built before the job runner, which is new: a background handler may need a
    # model too ([ADR-0045]), and a second client for the worker would double
    # the connection pools to save moving one line.
    app.state.llm = _llm()
    app.state.jobs = _job_runner(database, app.state.stores, app.state.drainer, app.state.llm)
    app.state.turns = TurnService(database, app.state.llm, app.state.stores)

    # Agents are mounted here rather than in `create_app`, because discovery is
    # a startup activity and a route table built from an empty registry would
    # silently serve 404s for every agent.
    _mount_agents(app)
    # After every route, an agent's too, is mounted: what `/me` reports each
    # role may open is drawn from what the routes declare (ADR-0058 §1).
    app.state.permissions = declared_permissions(app.routes)
    app.state.jobs.start()

    log.info(
        "api_started",
        environment=settings.env.value,
        role_map=settings.role_map,
        agents=sorted(app.state.agents),
        runners=sorted(app.state.runners),
        job_kinds=sorted(app.state.jobs.kinds),
    )
    # The developer MCP server's manager (ADR-0053). A mounted app's own
    # lifespan never runs, so it is started here, for the life of the process.
    async with app.state.developer_mcp.session_manager.run():
        try:
            yield
        finally:
            await _shutdown(app)


async def _shutdown(app: FastAPI) -> None:
    """What the lifespan closes, in order, once the process stops serving."""
    await app.state.jobs.stop()
    await app.state.drainer.aclose()
    if app.state.redis is not None:
        await app.state.redis.aclose()
    # The connection pool is process-wide and lazily created, so it outlives
    # any single request. Closing it here means a shutdown returns its
    # connections rather than leaving PostgreSQL to time them out — and, in
    # tests, that an event loop does not end with live sockets attached to
    # it. `get_database` is cached, so a restart simply builds a new pool.
    await get_database().dispose()
    get_database.cache_clear()
    log.info("api_stopped")


def _job_runner(
    database: Database, stores: StoreDirectory, drainer: WebhookDrainer, llm: Any
) -> JobRunner:
    """The worker loop, with its handlers attached.

    Handlers are registered here rather than discovered, because the queue must
    not import the things it runs — a queue that knew about syncing would be a
    queue that changes every time a new kind of work appears (ADR-0022).

    **This is now the only background loop in the process.** The webhook drainer
    had its own five-second poll over a Redis set until 2026-08-26; it is a
    handler here instead, and there is one clock rather than two.

    It runs inside the API process. ADR-0002 says one deployable, and a second
    container to run a five-second poll would be a microservice bought for the
    price of a `create_task`. The day a sync starves a shopper's turn of a
    connection, that is a measured reason to split it out and this function is
    what moves.
    """
    runner = JobRunner(database)
    runner.register(SYNC_STORE, SyncStoreHandler(stores))
    runner.register(WEBHOOK_DRAIN, WebhookDrainHandler(drainer))
    # The deletions ADR-0042 §3 requires to *run*. Registered here, not by an
    # agent: conversations and observed events belong to no one agent.
    runner.register(RETENTION_SWEEP, RetentionSweepHandler(get_settings()))
    # The dashboard's full check of a shop's bridge (ADR-0052 §4).
    runner.register(SHOP_CHECK, ShopCheckHandler(production=get_settings().is_production))

    # ...plus whatever the installed agents own. Discovered rather than named
    # here, for the reason the other four seams are ([ADR-0045]): background
    # work belongs to the agent that needs it, and this file must not learn
    # which agents exist in order to run theirs.
    for kind, handler in discover_job_handlers(db=database, stores=stores, llm=llm).items():
        runner.register(kind, handler)

    return runner


def _llm() -> Any:
    """The process-wide model client, resolved from the configured role map.

    One per process, wrapped per turn by ``MeteredLLM`` so the counters belong
    to one conversation. Building a client per request would open a new HTTP
    connection pool per shopper.
    """
    from neura_llm import LLMClient

    return LLMClient.from_role_map_name(get_settings().role_map)


def _mount_agents(app: FastAPI) -> None:
    """Give every installed agent its routes, under its own declared prefix.

    ``/v1/care/chat`` exists because CARE's manifest says so, not because
    anything here knows the word "care". An agent that is installed but has no
    runner is still mounted: the route then answers ``AGENT_NOT_RUNNABLE``,
    which tells an operator "we have it and it is broken" rather than pretending
    the deployment does not have it.
    """
    own_routes = discover_agent_routes()

    for key, discovered in sorted(app.state.agents.items()):
        # An agent no shopper talks to (GROW, ADR-0064) gets no chat, no
        # conversations and no shadow queue: they could only ever answer
        # AGENT_NOT_RUNNABLE. Its own surface, if any, is still mounted below.
        if getattr(discovered.manifest, "chat", True) is not False:
            app.include_router(agent_routes.build_router(key), prefix=discovered.route_prefix)
            log.info("agent_mounted", agent=key, prefix=discovered.route_prefix)

        # An agent's own surface, if it has one, under the same prefix. Mounted
        # after the generic routes so a path an agent invents can never shadow
        # `/chat` or `/conversations` — an agent that captured those would be
        # answering questions the API is responsible for.
        if build := own_routes.get(key):
            app.include_router(build(key), prefix=discovered.route_prefix)
            log.info("agent_routes_mounted", agent=key, prefix=discovered.route_prefix)

    # Rebuilt so the agent routes appear in `/openapi.json`, which FastAPI
    # otherwise caches from before the mount.
    app.openapi_schema = None


def create_app() -> FastAPI:
    # First, before anything reads configuration. Settings loads .env itself via
    # pydantic-settings, but role maps and pricing use os.getenv and would
    # otherwise never see the file.
    load_env()

    settings = get_settings()

    configure_logging(
        level=settings.log_level,
        json_output=settings.env is not Environment.DEVELOPMENT,
    )
    configure_telemetry(
        service_name=settings.otel_service_name,
        endpoint=settings.otel_endpoint,
        enabled=settings.otel_enabled,
    )

    app = FastAPI(
        title="Neura Agents API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs are part of the five-minute integration target
        # (docs/architecture/api-design.md §10), but not exposed in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    app.add_middleware(RequestContextMiddleware)
    # Not Starlette's CORSMiddleware, and not a deployment-wide origin list.
    # A widget key belongs to one merchant, so the allowlist that decides is
    # that key's own (ADR-0014 §3, ADR-0019 §3) — which also means onboarding a
    # merchant's domain is a key issue rather than a redeploy. The reason this
    # cannot be resolved at preflight instead is P7, and it is written out in
    # `middleware/cors.py`.
    app.add_middleware(TenantCorsMiddleware)

    register_error_handlers(app)
    app.include_router(console.router, prefix="/v1")
    app.include_router(console_review.router, prefix="/v1")
    app.include_router(console_conversations.router, prefix="/v1")
    app.include_router(console_handover.router, prefix="/v1")
    app.include_router(console_shop.router, prefix="/v1")
    app.include_router(console_connect.router, prefix="/v1")
    app.include_router(console_usage.router, prefix="/v1")
    app.include_router(console_mode.router, prefix="/v1")
    app.include_router(console_contact.router, prefix="/v1")
    app.include_router(console_customer_secret.router, prefix="/v1")
    app.include_router(console_sold_out.router, prefix="/v1")
    app.include_router(console_gaps.router, prefix="/v1")
    app.include_router(console_home.router, prefix="/v1")
    app.include_router(console_people.router, prefix="/v1")
    app.include_router(console_sign_up.router, prefix="/v1")
    # FiveNeurals' own area (ADR-0061): every route behind `AdminOnly`.
    app.include_router(admin.router, prefix="/v1")
    app.include_router(admin_code.router, prefix="/v1")
    # Mounted once, and it names no agent — that is the whole point
    # ([ADR-0031]). It sits beside the per-agent routes rather than
    # replacing them: `/v1/care/chat` is still CARE's own declared prefix.
    app.include_router(dispatch.router, prefix="/v1")
    # A handed-over shopper's address (ADR-0062). Mounted once, naming no agent,
    # like the dispatched chat: the agent comes from the conversation.
    app.include_router(handover_email.router, prefix="/v1")
    app.include_router(health.router, prefix="/v1")
    app.include_router(widget.router, prefix="/v1")
    app.include_router(stores.router, prefix="/v1")
    app.include_router(webhooks.router, prefix="/v1")
    # ADR-0044 phase 1. Mounted for every deployment; what gates it is the key's
    # scope and the tenant's agreement, never whether this line is here.
    app.include_router(observe.router, prefix="/v1")
    # ADR-0053: teaches a developer's AI tool how to build a bridge. Public, no
    # key; it reads nothing but our own fixed content. The limiter is built in
    # the lifespan, so it is looked up per request.
    app.state.developer_mcp = developer_mcp.build_server()
    app.mount(
        developer_mcp.MOUNT,
        developer_mcp.Limited(
            developer_mcp.build_app(app.state.developer_mcp, settings),
            lambda: app.state.limiter,
        ),
    )

    return app


app = create_app()
