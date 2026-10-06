import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from pydantic import SecretStr

from sortax.config import Settings
from sortax.infrastructure.persistence import Base, Database
from sortax.llm_gateway import LLMProviderError
from sortax.main import create_app
from sortax.prompting import LLMRequest


def _events(response: httpx.Response) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event_name: str | None = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            event_name = line.removeprefix("event: ")
        elif line.startswith("data: ") and event_name is not None:
            events.append((event_name, json.loads(line.removeprefix("data: "))))
            event_name = None
    return events


class FailingLLM:
    @property
    def provider_name(self) -> str:
        return "fake-failing"

    @property
    def model_name(self) -> str:
        return "fake-failing-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        del request
        if False:
            yield ""
        raise LLMProviderError("internal provider detail")


@pytest_asyncio.fixture
async def chat_client() -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    settings = Settings(
        app_env="test",
        jwt_secret=SecretStr("test-secret-that-is-at-least-32-characters-long"),
        database_enabled=True,
        redis_enabled=False,
        milvus_enabled=False,
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app = create_app(settings, database=database)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            token_response = await client.post(
                "/api/v1/dev/token",
                json={"user_id": str(uuid4()), "tenant_id": str(uuid4())},
            )
            token = token_response.json()["access_token"]
            yield client, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_grounded_fake_chat_stream_persists_snapshot_and_replays_idempotently(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = chat_client
    conversation_response = await client.post(
        "/api/v1/conversations",
        headers=headers,
        json={"title": "ATO car records"},
    )
    assert conversation_response.status_code == 201
    conversation_id = conversation_response.json()["id"]
    client_message_id = str(uuid4())
    payload = {
        "client_message_id": client_message_id,
        "content": "What car records are needed for 2025-26?",
    }

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json=payload,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    event_names = [name for name, _data in events]
    assert event_names[0] == "generation.started"
    assert "retrieval.started" in event_names
    assert "retrieval.completed" in event_names
    assert "message.delta" in event_names
    assert event_names[-1] == "message.completed"
    completed = events[-1][1]
    assert completed["completion_kind"] == "answer"
    assert completed["grounded"] is True
    assert len(completed["citations"]) == 1
    message_id = completed["message_id"]

    replay = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json=payload,
    )
    replay_events = _events(replay)
    assert replay_events[-1][1]["message_id"] == message_id

    messages_response = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
    )
    messages = messages_response.json()["items"]
    assert len(messages) == 2
    assistant = next(item for item in messages if item["role"] == "assistant")
    assert assistant["status"] == "completed"
    assert assistant["grounded"] is True
    assert assistant["citation_count"] == 1
    assert len(assistant["citations"]) == 1


@pytest.mark.asyncio
async def test_missing_tax_year_returns_clarification_without_fake_citation(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = chat_client
    conversation = await client.post("/api/v1/conversations", headers=headers, json={})
    conversation_id = conversation.json()["id"]

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"client_message_id": str(uuid4()), "content": "What car records do I need?"},
    )

    events = _events(response)
    event_names = [name for name, _data in events]
    assert "retrieval.started" not in event_names
    assert events[-1][0] == "message.completed"
    assert events[-1][1]["completion_kind"] == "clarification"
    assert events[-1][1]["grounded"] is False
    assert events[-1][1]["citations"] == []


@pytest.mark.asyncio
async def test_follow_up_year_inherits_claim_type_from_completed_history(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = chat_client
    conversation = await client.post("/api/v1/conversations", headers=headers, json={})
    conversation_id = conversation.json()["id"]
    first = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={
            "client_message_id": str(uuid4()),
            "content": "What car records do I need?",
        },
    )
    assert _events(first)[-1][1]["completion_kind"] == "clarification"

    follow_up = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"client_message_id": str(uuid4()), "content": "2025-26"},
    )

    events = _events(follow_up)
    assert "retrieval.started" in [name for name, _data in events]
    assert events[-1][0] == "message.completed"
    assert events[-1][1]["completion_kind"] == "answer"
    assert events[-1][1]["grounded"] is True


@pytest.mark.asyncio
async def test_retry_preserves_original_and_completes_new_generation(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = chat_client
    conversation = await client.post("/api/v1/conversations", headers=headers, json={})
    conversation_id = conversation.json()["id"]
    first = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={
            "client_message_id": str(uuid4()),
            "content": "What car records are needed for 2025-26?",
        },
    )
    original_message_id = _events(first)[-1][1]["message_id"]

    retry = await client.post(
        f"/api/v1/messages/{original_message_id}/retry",
        headers=headers,
        json={"client_message_id": str(uuid4())},
    )

    assert retry.status_code == 202
    assert retry.json()["status"] == "completed"
    assert retry.json()["assistant_message_id"] != original_message_id
    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()["items"]
    assert len(messages) == 3
    retried = next(item for item in messages if item["id"] == retry.json()["assistant_message_id"])
    assert retried["retry_of_message_id"] == original_message_id


@pytest.mark.asyncio
async def test_provider_failure_emits_safe_event_and_persists_failed_snapshot() -> None:
    settings = Settings(
        app_env="test",
        jwt_secret=SecretStr("test-secret-that-is-at-least-32-characters-long"),
        database_enabled=True,
        redis_enabled=False,
        milvus_enabled=False,
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app = create_app(settings, database=database, llm_provider=FailingLLM())
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            token_response = await client.post(
                "/api/v1/dev/token",
                json={"user_id": str(uuid4()), "tenant_id": str(uuid4())},
            )
            headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}
            conversation = await client.post("/api/v1/conversations", headers=headers, json={})
            conversation_id = conversation.json()["id"]
            response = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers=headers,
                json={
                    "client_message_id": str(uuid4()),
                    "content": "What car records are needed for 2025-26?",
                },
            )
            events = _events(response)
            assert events[-1][0] == "message.failed"
            assert events[-1][1]["error"]["code"] == "provider_error"
            assert "internal provider detail" not in response.text
            messages = (
                await client.get(
                    f"/api/v1/conversations/{conversation_id}/messages", headers=headers
                )
            ).json()["items"]
            assistant = next(item for item in messages if item["role"] == "assistant")
            assert assistant["status"] == "failed"


@pytest.mark.asyncio
async def test_conversation_is_not_visible_to_another_identity(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = chat_client
    conversation = await client.post("/api/v1/conversations", headers=headers, json={})
    conversation_id = conversation.json()["id"]
    other_token = await client.post(
        "/api/v1/dev/token",
        json={"user_id": str(uuid4()), "tenant_id": str(uuid4())},
    )
    other_headers = {"Authorization": f"Bearer {other_token.json()['access_token']}"}

    response = await client.get(f"/api/v1/conversations/{conversation_id}", headers=other_headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert UUID(response.json()["error"]["request_id"])
