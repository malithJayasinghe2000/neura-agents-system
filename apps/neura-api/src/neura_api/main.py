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

from neura_api.errors import register_error_handlers
from neura_api.idempotency import Idempotency
from neura_api.jobs import (
    SYNC_STORE,
    WEBHOOK_DRAIN,
    JobRunner,
    SyncStoreHandler,
    WebhookDrainHandler,
)
from neura_api.middleware.cors import TenantCorsMiddleware
from neura_api.middleware.request_context import RequestContextMiddleware
from neura_api.ratelimit import RateLimiter
from neura_api.registry import discover_agent_routes, discover_agents, discover_runners
from neura_api.routes import agent as agent_routes
from neura_api.routes import console, console_review, health, stores, webhooks, widget
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
    app.state.jobs = _job_runner(database, app.state.stores, app.state.drainer)
    app.state.turns = TurnService(database, _llm(), app.state.stores)

    # Agents are mounted here rather than in `create_app`, because discovery is
    # a startup activity and a route table built from an empty registry would
    # silently serve 404s for every agent.
    _mount_agents(app)
    app.state.jobs.start()

    log.info(
        "api_started",
        environment=settings.env.value,
        role_map=settings.role_map,
        agents=sorted(app.state.agents),
        runners=sorted(app.state.runners),
        job_kinds=sorted(app.state.jobs.kinds),
    )
    try:
        yield
    finally:
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


def _job_runner(database: Database, stores: StoreDirectory, drainer: WebhookDrainer) -> JobRunner:
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
    app.include_router(health.router, prefix="/v1")
    app.include_router(widget.router, prefix="/v1")
    app.include_router(stores.router, prefix="/v1")
    app.include_router(webhooks.router, prefix="/v1")

    return app


app = create_app()
