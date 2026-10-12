from collections.abc import Mapping
from typing import Literal, Protocol, cast

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from sortax.api.models import HealthStatus

router = APIRouter(tags=["health"])


class HealthProbe(Protocol):
    async def healthcheck(self) -> bool: ...


@router.get("/health/live", response_model=HealthStatus)
async def health_live() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get("/health/ready", response_model=HealthStatus)
async def health_ready(request: Request) -> HealthStatus | JSONResponse:
    application_ready = bool(getattr(request.app.state, "ready", False))
    probes = cast(
        Mapping[str, HealthProbe],
        getattr(request.app.state, "readiness_probes", {}),
    )
    checks: dict[str, Literal["ok", "unavailable"]] = {
        "application": "ok" if application_ready else "unavailable"
    }
    for name, probe in probes.items():
        try:
            available = await probe.healthcheck()
        except Exception:  # pragma: no cover - probes fail closed at this boundary
            available = False
        checks[name] = "ok" if available else "unavailable"

    request.app.state.readiness_checks = checks
    ready = application_ready and all(result == "ok" for result in checks.values())
    body = HealthStatus(
        status="ok" if ready else "unavailable",
        checks=checks,
    )
    if ready:
        return body
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body.model_dump())
