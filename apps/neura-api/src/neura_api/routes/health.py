"""Health endpoints.

Two, deliberately distinct:

* ``/v1/health``       liveness — is the process up? Never touches a dependency,
                       so a database blip does not cause an orchestrator to
                       restart a perfectly healthy process.
* ``/v1/health/ready`` readiness — can it actually serve? Checks dependencies and
                       returns 503 when it cannot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from neura_core import ConfigurationError, get_database, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    environment: str
    timestamp: datetime


class ComponentStatus(BaseModel):
    name: str
    status: Literal["ok", "degraded", "down", "not_implemented"]
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    components: list[ComponentStatus]
    timestamp: datetime


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="neura-api",
        version="0.1.0",
        environment=settings.env.value,
        timestamp=datetime.now(UTC),
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    responses={503: {"description": "One or more dependencies unavailable"}},
)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    components: list[ComponentStatus] = [
        await _postgres_status(),
        await _redis_status(request),
    ]

    failed = [c for c in components if c.status == "down"]
    if failed:
        response.status_code = 503

    return ReadinessResponse(
        status="not_ready" if failed else "ready",
        components=components,
        timestamp=datetime.now(UTC),
    )


async def _redis_status(request: Request) -> ComponentStatus:
    """Reachable? Reported as **degraded**, never ``down``, when it is not.

    Redis backs rate limiting, and since 2026-08-26 nothing else — the webhook
    drainer's tenant index moved into PostgreSQL (ADR-0022). Rate limiting fails
    open by design (ADR-0017 §3) — a rate limiter is not an access control, and
    the *cost* ceiling is a PostgreSQL rollup that is unaffected. So a Redis
    outage must not take a healthy process out of rotation and deny every
    merchant service to defend against unmetered request pacing.

    It is still *reported*, at the one place an operator looks, because a
    control that has silently stopped working looks exactly like one that is on.
    """
    client = getattr(request.app.state, "redis", None)
    if client is None:
        return ComponentStatus(
            name="redis",
            status="degraded",
            detail="not configured — rate limits are not enforced",
        )
    try:
        await client.ping()
    except Exception as exc:  # any client failure is the same operational fact
        return ComponentStatus(name="redis", status="degraded", detail=str(exc)[:200])
    return ComponentStatus(name="redis", status="ok")


async def _postgres_status() -> ComponentStatus:
    """Reachable, and — just as important — connected as a role RLS applies to.

    A misconfigured role is reported as ``down`` rather than raised. A 503 with
    a readable reason is what an orchestrator and an on-call engineer can both
    act on; a 500 with a stack trace is neither. And serving traffic with tenant
    isolation silently switched off is worse than not serving traffic at all
    (docs/architecture/adr/0008-multi-tenancy-rls.md).
    """
    try:
        if await get_database().ping():
            return ComponentStatus(name="postgres", status="ok")
        return ComponentStatus(name="postgres", status="down", detail="unreachable")
    except ConfigurationError as exc:
        return ComponentStatus(name="postgres", status="down", detail=exc.message)


@router.get("/agents", summary="Agents installed in this deployment")
async def installed_agents() -> dict[str, Any]:
    """What this deployment *has*, not what any tenant may *use*.

    Entitlement is a per-tenant decision made per request
    (docs/architecture/tenancy-and-packaging.md §3).
    """
    from neura_api.registry import discover_agents

    agents = discover_agents()
    return {
        "data": {
            "installed": [
                {
                    "key": a.key,
                    "name": a.name,
                    "version": a.version,
                    "route_prefix": a.route_prefix,
                    "requires_capabilities": sorted(
                        c.value for c in a.manifest.requires_capabilities
                    ),
                }
                for a in agents.values()
            ]
        },
        "meta": {"timestamp": datetime.now(UTC).isoformat()},
    }
