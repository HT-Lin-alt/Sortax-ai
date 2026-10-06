from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from sortax.api.errors import NotFoundError
from sortax.identity.dependencies import CurrentIdentity, get_jwt_service
from sortax.identity.jwt_service import JwtService
from sortax.identity.models import (
    CurrentIdentityResponse,
    DevelopmentTokenRequest,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["identity"])
development_router = APIRouter(prefix="/dev", tags=["development"])


@router.get("/me", response_model=CurrentIdentityResponse)
async def read_current_identity(identity: CurrentIdentity) -> CurrentIdentityResponse:
    return CurrentIdentityResponse(
        user_id=identity.user_id,
        tenant_id=identity.tenant_id,
        role=identity.role,
    )


@development_router.post(
    "/token",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_development_token(
    payload: DevelopmentTokenRequest,
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)],
    request: Request,
) -> TokenResponse:
    # The router is only mounted in development/test. Keep a runtime assertion as
    # defense in depth in case application composition changes later.
    if not request.app.state.settings.development_token_enabled:
        raise NotFoundError
    token = jwt_service.issue_development_token(
        user_id=payload.user_id,
        tenant_id=payload.tenant_id,
    )
    return TokenResponse(access_token=token, expires_in=jwt_service.ttl_seconds)
