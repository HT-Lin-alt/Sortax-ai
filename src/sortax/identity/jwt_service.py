from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pydantic import ValidationError

from sortax.config import Settings
from sortax.identity.errors import InvalidAccessTokenError
from sortax.identity.models import AccessTokenClaims, IdentityContext

JWT_ALGORITHM = "HS256"


class JwtService:
    """Issues local development tokens and verifies bearer tokens."""

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret.get_secret_value()
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._ttl_seconds = settings.jwt_ttl_seconds

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def issue_development_token(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        now: datetime | None = None,
    ) -> str:
        issued_at = now or datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=self._ttl_seconds)
        claims = {
            "sub": str(user_id),
            "tenant_id": str(tenant_id),
            "role": "user",
            "iss": self._issuer,
            "aud": self._audience,
            "iat": issued_at,
            "exp": expires_at,
            "jti": str(uuid4()),
        }
        return jwt.encode(claims, self._secret, algorithm=JWT_ALGORITHM)

    def verify(self, token: str) -> IdentityContext:
        try:
            raw_claims = jwt.decode(
                token,
                self._secret,
                algorithms=[JWT_ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": ["sub", "tenant_id", "role", "iss", "aud", "iat", "exp", "jti"]
                },
            )
            claims = AccessTokenClaims.model_validate(raw_claims)
        except (jwt.PyJWTError, ValidationError, ValueError, TypeError) as exc:
            raise InvalidAccessTokenError from exc

        return IdentityContext(
            user_id=claims.sub,
            tenant_id=claims.tenant_id,
            role=claims.role,
            token_id=claims.jti,
            issued_at=claims.iat,
            expires_at=claims.exp,
        )
