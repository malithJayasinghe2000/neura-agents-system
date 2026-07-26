"""FastAPI application factory.

One deployable process (ADR-0002). Agents are discovered at startup via entry
points and mounted at their declared prefixes; there is no central list to edit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from neura_api.errors import register_error_handlers
from neura_api.middleware.request_context import RequestContextMiddleware
from neura_api.registry import discover_agents
from neura_api.routes import health
from neura_core import (
    Environment,
    configure_logging,
    configure_telemetry,
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Refuse to serve real traffic with placeholder secrets.
    settings.validate_for_runtime()

    app.state.agents = discover_agents()
    log.info(
        "api_started",
        environment=settings.env.value,
        role_map=settings.role_map,
        agents=sorted(app.state.agents),
    )
    yield
    log.info("api_stopped")


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
    app.add_middleware(
        CORSMiddleware,
        # Never "*": fn_pk_ keys are, by definition, exposed in the browser.
        allow_origins=settings.widget_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["X-Request-Id", "X-RateLimit-Remaining", "Retry-After"],
    )

    register_error_handlers(app)
    app.include_router(health.router, prefix="/v1")

    return app


app = create_app()
