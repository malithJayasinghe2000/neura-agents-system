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

from fastapi import APIRouter, Response
from pydantic import BaseModel

from neura_core import get_settings

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
async def readiness(response: Response) -> ReadinessResponse:
    components: list[ComponentStatus] = [
        # Real checks land with milestone 1.13 (Postgres) and the Redis-backed
        # session/rate-limit work. Reported explicitly rather than omitted, so
        # readiness never looks green for a reason that does not exist yet.
        ComponentStatus(
            name="postgres",
            status="not_implemented",
            detail="Wired in Phase 1 milestone 1.13",
        ),
        ComponentStatus(
            name="redis",
            status="not_implemented",
            detail="Wired in Phase 1 milestone 1.13",
        ),
    ]

    failed = [c for c in components if c.status == "down"]
    if failed:
        response.status_code = 503

    return ReadinessResponse(
        status="not_ready" if failed else "ready",
        components=components,
        timestamp=datetime.now(UTC),
    )


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
