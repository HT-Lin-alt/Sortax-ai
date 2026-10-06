from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sortax.api.errors import AuthenticationError
from sortax.identity.errors import InvalidAccessTokenError
from sortax.identity.jwt_service import JwtService
from sortax.identity.models import IdentityContext

bearer_scheme = HTTPBearer(auto_error=False)


def get_jwt_service(request: Request) -> JwtService:
    return request.app.state.jwt_service  # type: ignore[no-any-return]


def authentication_error(detail: str = "Invalid or missing access token") -> AuthenticationError:
    return AuthenticationError(detail)


async def get_current_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    jwt_service: Annotated[JwtService, Depends(get_jwt_service)],
) -> IdentityContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise authentication_error()

    try:
        return jwt_service.verify(credentials.credentials)
    except InvalidAccessTokenError as exc:
        raise authentication_error() from exc


CurrentIdentity = Annotated[IdentityContext, Depends(get_current_identity)]
