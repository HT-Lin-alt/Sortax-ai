from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import jwt
import pytest
from pydantic import SecretStr

from sortax.config import Settings
from sortax.identity.jwt_service import JWT_ALGORITHM
from sortax.main import create_app


@pytest.mark.asyncio
async def test_development_token_authenticates_current_identity(
    client: httpx.AsyncClient,
) -> None:
    user_id = uuid4()
    tenant_id = uuid4()

    token_response = await client.post(
        "/api/v1/dev/token",
        json={"user_id": str(user_id), "tenant_id": str(tenant_id)},
    )

    assert token_response.status_code == 201
    token_body = token_response.json()
    assert token_body["token_type"] == "bearer"
    assert token_body["expires_in"] == 3600

    me_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_body['access_token']}"},
    )

    assert me_response.status_code == 200
    assert me_response.json() == {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "role": "user",
    }


@pytest.mark.asyncio
async def test_missing_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_tampered_token_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer header.payload.invalid-signature"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_is_rejected(
    client: httpx.AsyncClient,
    settings: Settings,
) -> None:
    now = datetime.now(UTC)
    expired_token = jwt.encode(
        {
            "sub": str(uuid4()),
            "tenant_id": str(uuid4()),
            "role": "user",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
            "jti": str(uuid4()),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )

    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_client_cannot_select_a_role(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/dev/token",
        json={
            "user_id": str(uuid4()),
            "tenant_id": str(uuid4()),
            "role": "tenant_admin",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_development_token_route_is_absent_in_production() -> None:
    production_settings = Settings(
        app_env="production",
        jwt_secret=SecretStr("production-secret-that-is-at-least-32-characters"),
    )
    app = create_app(production_settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/dev/token",
                json={"user_id": str(uuid4()), "tenant_id": str(uuid4())},
            )

    assert response.status_code == 404
