from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DevelopmentTokenRequest(BaseModel):
    """Identity selected by a developer for local-only token issuance."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    tenant_id: UUID


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class IdentityContext(BaseModel):
    """Trusted identity created only from a verified access token."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    tenant_id: UUID
    role: Literal["user"]
    token_id: UUID
    issued_at: datetime
    expires_at: datetime


class CurrentIdentityResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    role: Literal["user"]


class AccessTokenClaims(BaseModel):
    """Claims accepted after signature and registered-claim verification."""

    model_config = ConfigDict(extra="ignore")

    sub: UUID
    tenant_id: UUID
    role: Literal["user"]
    iss: str
    aud: str
    iat: datetime
    exp: datetime
    jti: UUID
