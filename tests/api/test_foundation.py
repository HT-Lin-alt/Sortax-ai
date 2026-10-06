import json
import logging
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from sortax.config import Settings
from sortax.infrastructure.milvus import VectorStoreUnavailable
from sortax.infrastructure.persistence import Database
from sortax.infrastructure.redis_health import RedisHealthProbe
from sortax.main import _missing_configuration_app, create_app
from sortax.observability.logging import JsonFormatter, request_id_context


@pytest.mark.asyncio
async def test_health_endpoints_report_application_state(client: httpx.AsyncClient) -> None:
    live_response = await client.get("/health/live")
    ready_response = await client.get("/health/ready")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "ok", "checks": {}}
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ok", "checks": {"application": "ok"}}


@pytest.mark.asyncio
async def test_request_id_is_generated_and_returned(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")

    assert UUID(response.headers["x-request-id"])


@pytest.mark.asyncio
async def test_valid_request_id_is_preserved(client: httpx.AsyncClient) -> None:
    request_id = str(uuid4())

    response = await client.get("/health/live", headers={"X-Request-ID": request_id})

    assert response.headers["x-request-id"] == request_id


@pytest.mark.asyncio
async def test_invalid_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "not-a-uuid"})

    assert response.headers["x-request-id"] != "not-a-uuid"
    assert UUID(response.headers["x-request-id"])


@pytest.mark.asyncio
async def test_unknown_route_uses_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "Not Found",
            "request_id": response.headers["x-request-id"],
            "retryable": False,
            "details": {},
        }
    }


@pytest.mark.asyncio
async def test_validation_error_does_not_echo_input(client: httpx.AsyncClient) -> None:
    sensitive_value = "must-not-appear-in-error-response"

    response = await client.post(
        "/api/v1/dev/token",
        json={"user_id": sensitive_value, "tenant_id": sensitive_value},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert sensitive_value not in response.text


def test_json_formatter_adds_request_context_without_body_content() -> None:
    formatter = JsonFormatter()
    token = request_id_context.set("00000000-0000-0000-0000-000000000001")
    try:
        record = logging.LogRecord(
            name="sortax.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="request_completed",
            args=(),
            exc_info=None,
        )
        record.method = "GET"
        record.path = "/health/live"
        record.status_code = 200
        formatted = json.loads(formatter.format(record))
    finally:
        request_id_context.reset(token)

    assert formatted["request_id"] == "00000000-0000-0000-0000-000000000001"
    assert formatted["method"] == "GET"
    assert formatted["path"] == "/health/live"
    assert formatted["status_code"] == 200


@pytest.mark.asyncio
async def test_unhandled_error_is_sanitized(settings: Settings) -> None:
    app = create_app(settings)

    @app.get("/test-only/boom")
    async def boom() -> None:
        raise RuntimeError("sensitive internal detail")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/test-only/boom")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "sensitive internal detail" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


@pytest.mark.asyncio
async def test_invalid_configuration_is_live_but_not_ready() -> None:
    with pytest.raises(ValidationError) as captured_error:
        Settings(app_env="test", jwt_secret=SecretStr("too-short"))
    app = _missing_configuration_app(captured_error.value)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        live_response = await client.get("/health/live")
        ready_response = await client.get("/health/ready")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "ok", "checks": {}}
    assert ready_response.status_code == 503
    assert ready_response.json()["error"]["code"] == "configuration_error"


class UnavailableVectorStore:
    async def connect(self) -> None:
        raise VectorStoreUnavailable("normalized failure")

    async def healthcheck(self) -> bool:
        return False

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_milvus_failure_keeps_api_live_but_not_ready(settings: Settings) -> None:
    milvus_settings = settings.model_copy(update={"milvus_enabled": True})
    app = create_app(milvus_settings, vector_store=UnavailableVectorStore())
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            live_response = await client.get("/health/live")
            ready_response = await client.get("/health/ready")

    assert live_response.status_code == 200
    assert ready_response.status_code == 503
    assert ready_response.json() == {
        "status": "unavailable",
        "checks": {"application": "ok", "milvus": "unavailable"},
    }


class AvailableRedisProbe(RedisHealthProbe):
    def __init__(self) -> None:
        pass

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_database_and_redis_are_reported_by_readiness(settings: Settings) -> None:
    dependency_settings = settings.model_copy(
        update={"database_enabled": True, "redis_enabled": True}
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    app = create_app(
        dependency_settings,
        database=database,
        redis_probe=AvailableRedisProbe(),
    )
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ready_response = await client.get("/health/ready")

    assert ready_response.status_code == 200
    assert ready_response.json() == {
        "status": "ok",
        "checks": {"application": "ok", "postgresql": "ok", "redis": "ok"},
    }
