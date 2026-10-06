from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from sortax.api.models import HealthStatus

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthStatus)
async def health_live() -> HealthStatus:
    return HealthStatus(status="ok")


@router.get("/health/ready", response_model=HealthStatus)
async def health_ready(request: Request) -> HealthStatus | JSONResponse:
    application_ready = bool(getattr(request.app.state, "ready", False))
    checks = getattr(
        request.app.state,
        "readiness_checks",
        {"application": "ok" if application_ready else "unavailable"},
    )
    body = HealthStatus(
        status="ok" if application_ready else "unavailable",
        checks=checks,
    )
    if application_ready:
        return body
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=body.model_dump())
