"""
CS2 Instant Alert — Health Check Endpoints.

Provides /health and /ready endpoints for Docker healthcheck
and load balancer probes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: str
    version: str = "0.1.0"
    service: str = "cs2-instant-alert"


class ReadinessResponse(BaseModel):
    """Readiness check response with component status."""

    status: str
    timestamp: str
    components: dict[str, str]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """
    Liveness probe.

    Returns 200 if the application process is running.
    Used by Docker HEALTHCHECK and Kubernetes liveness probes.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(
    request: Request,
) -> ReadinessResponse | JSONResponse:
    """
    Readiness probe.

    Checks that all critical dependencies (DB, Redis) are accessible.
    Returns 200 only when the service is ready to handle requests.
    """
    container = request.app.container
    health = await container.health_service().check_all()
    components = {
        name: "ok" if healthy else "error"
        for name, healthy in health.items()
        if name != "overall"
    }
    response = ReadinessResponse(
        status="ready" if health["overall"] else "not_ready",
        timestamp=datetime.now(UTC).isoformat(),
        components=components,
    )
    if not health["overall"]:
        return JSONResponse(status_code=503, content=response.model_dump())
    return response
