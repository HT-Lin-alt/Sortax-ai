from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from sortax.config import Settings
from sortax.main import create_app


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        jwt_secret=SecretStr("test-secret-that-is-at-least-32-characters-long"),
        jwt_issuer="sortax-test",
        jwt_audience="sortax-test-api",
        jwt_ttl_seconds=3600,
        database_enabled=False,
        redis_enabled=False,
        milvus_enabled=False,
    )


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
            yield test_client
