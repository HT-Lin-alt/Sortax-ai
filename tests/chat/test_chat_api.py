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
from sortax.llm_gateway import LLMProviderError, LLMStreamChunk
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

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        if False:
            yield LLMStreamChunk()
        raise LLMProviderError("internal provider detail")


class MustNotRunLLM:
    @property
    def provider_name(self) -> str:
        return "must-not-run"

    @property
    def model_name(self) -> str:
        return "must-not-run-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        raise AssertionError("LLM must not run when a tax summary is declined")
        yield LLMStreamChunk()  # pragma: no cover


@pytest.mark.asyncio
async def test_general_chat_skips_retrieval_persists_kind_and_replays_idempotently(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = chat_client
    conversation = await client.post("/api/v1/conversations", headers=headers, json={})
    conversation_id = conversation.json()["id"]
    payload = {"client_message_id": str(uuid4()), "content": "Hello"}

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json=payload,
    )

    events = _events(response)
    event_names = [name for name, _data in events]
    assert "retrieval.started" not in event_names
    assert "retrieval.completed" not in event_names
    assert events[-1][0] == "message.completed"
    assert events[-1][1]["completion_kind"] == "general_chat"
    assert events[-1][1]["grounded"] is False
    assert events[-1][1]["citations"] == []
    message_id = events[-1][1]["message_id"]

    replay = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json=payload,
    )
    replay_completed = _events(replay)[-1][1]
    assert replay_completed["message_id"] == message_id
    assert replay_completed["completion_kind"] == "general_chat"

    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()["items"]
    assistant = next(item for item in messages if item["role"] == "assistant")
    assert assistant["completion_kind"] == "general_chat"
    assert assistant["retrieval_run_id"] is None
    assert assistant["grounded"] is False
    assert assistant["citations"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected_kind"),
    [
        ("Can you help with my tax return?", "questionnaire"),
        ("How is crypto taxed?", "clarification"),
    ],
)
async def test_non_document_tax_routes_clarify_without_retrieval(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
    content: str,
    expected_kind: str,
) -> None:
    client, headers = chat_client
    conversation = await client.post("/api/v1/conversations", headers=headers, json={})
    conversation_id = conversation.json()["id"]

    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"client_message_id": str(uuid4()), "content": content},
    )

    events = _events(response)
    event_names = [name for name, _data in events]
    assert "retrieval.started" not in event_names
    assert events[-1][0] == "message.completed"
    assert events[-1][1]["completion_kind"] == expected_kind
    assert events[-1][1]["grounded"] is False


@pytest.mark.asyncio
async def test_phase5d_questionnaire_resume_and_grounded_checklist(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = chat_client
    conversation = await client.post("/api/v1/conversations", headers=headers, json={})
    conversation_id = conversation.json()["id"]
    questionnaire_response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json={"client_message_id": str(uuid4()), "content": "Help me prepare my tax return"},
    )
    questionnaire_event = _events(questionnaire_response)[-1][1]
    assert questionnaire_event["completion_kind"] == "questionnaire"
    assert questionnaire_event["content_type"] == "questionnaire"
    structured = questionnaire_event["structured_content"]
    assert structured["type"] == "questionnaire"
    intake = structured["tax_intake"]
    intake_id = intake["id"]
    assert intake["template_version"] == "limited-tax-2025-26-v1"
    assert intake["version"] == 1
    assert len(intake["questions"]) == 3

    other_token = await client.post(
        "/api/v1/dev/token",
        json={"user_id": str(uuid4()), "tenant_id": str(uuid4())},
    )
    other_headers = {"Authorization": f"Bearer {other_token.json()['access_token']}"}
    assert (
        await client.get(f"/api/v1/tax-intakes/{intake_id}", headers=other_headers)
    ).status_code == 404
    identity = await client.get("/api/v1/auth/me", headers=headers)
    same_tenant_token = await client.post(
        "/api/v1/dev/token",
        json={"user_id": str(uuid4()), "tenant_id": identity.json()["tenant_id"]},
    )
    same_tenant_headers = {"Authorization": f"Bearer {same_tenant_token.json()['access_token']}"}
    assert (
        await client.get(f"/api/v1/tax-intakes/{intake_id}", headers=same_tenant_headers)
    ).status_code == 404

    invalid_answer = await client.put(
        f"/api/v1/tax-intakes/{intake_id}/answers/work_expenses",
        headers=headers,
        json={"selected_options": ["none", "working_from_home"], "version": 1},
    )
    assert invalid_answer.status_code == 422

    answers = {
        "first_tax_return": ["yes"],
        "work_expenses": ["working_from_home", "work_related_car"],
        "income_sources": ["salary_wages"],
    }
    version = 1
    for question_key, option_codes in answers.items():
        response = await client.put(
            f"/api/v1/tax-intakes/{intake_id}/answers/{question_key}",
            headers=headers,
            json={"selected_options": option_codes, "version": version},
        )
        assert response.status_code == 200
        version = response.json()["version"]

    stale_answer = await client.put(
        f"/api/v1/tax-intakes/{intake_id}/answers/first_tax_return",
        headers=headers,
        json={"selected_options": ["no"], "version": 1},
    )
    assert stale_answer.status_code == 409
    assert stale_answer.json()["error"]["code"] == "version_conflict"

    restored = await client.get(f"/api/v1/tax-intakes/{intake_id}", headers=headers)
    assert restored.status_code == 200
    assert restored.json()["current_step"] == 3
    assert {
        item["question_key"]: item["selected_options"] for item in restored.json()["answers"]
    } == answers
    assert restored.json()["version"] == 4

    complete_payload = {"client_request_id": str(uuid4()), "version": version}
    completed = await client.post(
        f"/api/v1/tax-intakes/{intake_id}/complete",
        headers=headers,
        json=complete_payload,
    )
    events = _events(completed)
    event_names = [name for name, _data in events]
    assert "retrieval.started" in event_names
    assert "retrieval.completed" in event_names
    completed_events = [data for name, data in events if name == "message.completed"]
    assert [event["completion_kind"] for event in completed_events] == [
        "document_checklist",
        "summary_confirmation",
    ]
    checklist = completed_events[0]
    assert checklist["grounded"] is True
    assert checklist["structured_content"]["type"] == "document_checklist"
    assert checklist["structured_content"]["summary_confirmation"]["type"] == (
        "summary_confirmation"
    )
    assert len(checklist["structured_content"]["items"]) == 3
    citation_ordinals = set(range(1, len(checklist["citations"]) + 1))
    assert citation_ordinals
    for item in checklist["structured_content"]["items"]:
        assert item["id"]
        assert item["citation_ordinals"]
        assert set(item["citation_ordinals"]) <= citation_ordinals
    assert all(citation["claim_type"] for citation in checklist["citations"])

    completed_intake = await client.get(f"/api/v1/tax-intakes/{intake_id}", headers=headers)
    completed_version = completed_intake.json()["version"]
    assert completed_intake.json()["status"] == "awaiting_summary_confirmation"
    stale_complete = await client.post(
        f"/api/v1/tax-intakes/{intake_id}/complete",
        headers=headers,
        json={"client_request_id": str(uuid4()), "version": version},
    )
    assert stale_complete.status_code == 409

    locked_answer = await client.put(
        f"/api/v1/tax-intakes/{intake_id}/answers/first_tax_return",
        headers=headers,
        json={"selected_options": ["no"], "version": completed_version},
    )
    assert locked_answer.status_code == 409

    replay = await client.post(
        f"/api/v1/tax-intakes/{intake_id}/complete",
        headers=headers,
        json=complete_payload,
    )
    replay_completed = [data for name, data in _events(replay) if name == "message.completed"]
    assert replay_completed[0]["message_id"] == checklist["message_id"]

    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()["items"]
    assert any(item["content_type"] == "document_checklist" for item in messages)
    assert any(item["content_type"] == "summary_confirmation" for item in messages)

    summary_payload = {
        "client_request_id": str(uuid4()),
        "requested": True,
        "version": completed_version,
    }
    summary_response = await client.post(
        f"/api/v1/tax-intakes/{intake_id}/summary",
        headers=headers,
        json=summary_payload,
    )
    summary_completed = [
        data for name, data in _events(summary_response) if name == "message.completed"
    ][-1]
    assert summary_completed["completion_kind"] == "tax_summary"
    assert summary_completed["content_type"] == "tax_summary"
    assert summary_completed["grounded"] is True
    assert summary_completed["citations"] == checklist["citations"]
    assert summary_completed["structured_content"]["type"] == "tax_summary"
    assert summary_completed["structured_content"]["sections"]
    assert summary_completed["structured_content"]["sections"][0]["citation_ordinals"]
    final_intake = await client.get(f"/api/v1/tax-intakes/{intake_id}", headers=headers)
    assert final_intake.json()["status"] == "summary_completed"

    summary_replay = await client.post(
        f"/api/v1/tax-intakes/{intake_id}/summary",
        headers=headers,
        json=summary_payload,
    )
    replay_summary = [
        data for name, data in _events(summary_replay) if name == "message.completed"
    ][-1]
    assert replay_summary["message_id"] == summary_completed["message_id"]


@pytest.mark.asyncio
async def test_conversation_start_is_idempotent(
    chat_client: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    client, headers = chat_client
    conversation = await client.post("/api/v1/conversations", headers=headers, json={})
    conversation_id = conversation.json()["id"]
    payload = {"client_request_id": str(uuid4())}

    first = await client.post(
        f"/api/v1/conversations/{conversation_id}/start", headers=headers, json=payload
    )
    first_completed = _events(first)[-1][1]
    assert first_completed["completion_kind"] == "general_chat"

    replay = await client.post(
        f"/api/v1/conversations/{conversation_id}/start", headers=headers, json=payload
    )
    assert _events(replay)[-1][1]["message_id"] == first_completed["message_id"]

    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()["items"]
    assert [item["role"] for item in messages] == ["system", "assistant"]


@pytest.mark.asyncio
async def test_declining_summary_does_not_call_llm() -> None:
    settings = Settings(
        app_env="test",
        jwt_secret=SecretStr("test-secret-that-is-at-least-32-characters-long"),
        database_enabled=True,
        redis_enabled=False,
        milvus_enabled=False,
        llm_provider="fake",
        llm_model="fake-chat-v1",
        intent_classifier_provider="fake",
        classifier_model="fake-intent-v1",
    )
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app = create_app(settings, database=database, llm_provider=MustNotRunLLM())
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            token = await client.post(
                "/api/v1/dev/token",
                json={"user_id": str(uuid4()), "tenant_id": str(uuid4())},
            )
            headers = {"Authorization": f"Bearer {token.json()['access_token']}"}
            conversation = await client.post("/api/v1/conversations", headers=headers, json={})
            conversation_id = conversation.json()["id"]
            questionnaire = await client.post(
                f"/api/v1/conversations/{conversation_id}/messages",
                headers=headers,
                json={"client_message_id": str(uuid4()), "content": "Help with my tax return"},
            )
            intake = _events(questionnaire)[-1][1]["structured_content"]["tax_intake"]
            intake_id = intake["id"]
            version = intake["version"]
            for key, options in {
                "first_tax_return": ["no"],
                "work_expenses": ["none"],
                "income_sources": ["salary_wages"],
            }.items():
                saved = await client.put(
                    f"/api/v1/tax-intakes/{intake_id}/answers/{key}",
                    headers=headers,
                    json={"selected_options": options, "version": version},
                )
                assert saved.status_code == 200
                version = saved.json()["version"]
            checklist = await client.post(
                f"/api/v1/tax-intakes/{intake_id}/complete",
                headers=headers,
                json={"client_request_id": str(uuid4()), "version": version},
            )
            assert checklist.status_code == 200
            current = await client.get(f"/api/v1/tax-intakes/{intake_id}", headers=headers)
            declined = await client.post(
                f"/api/v1/tax-intakes/{intake_id}/summary",
                headers=headers,
                json={
                    "client_request_id": str(uuid4()),
                    "requested": False,
                    "version": current.json()["version"],
                },
            )
            assert declined.status_code == 200
            assert _events(declined)[-1][1]["completion_kind"] == "clarification"
            intake = await client.get(f"/api/v1/tax-intakes/{intake_id}", headers=headers)
            assert intake.json()["status"] == "summary_declined"


@pytest_asyncio.fixture
async def chat_client() -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    settings = Settings(
        app_env="test",
        jwt_secret=SecretStr("test-secret-that-is-at-least-32-characters-long"),
        database_enabled=True,
        redis_enabled=False,
        milvus_enabled=False,
        llm_provider="fake",
        llm_model="fake-chat-v1",
        intent_classifier_provider="fake",
        classifier_model="fake-intent-v1",
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
    assert assistant["completion_kind"] == "answer"
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

    payload = {
        "client_message_id": str(uuid4()),
        "content": "What car records do I need?",
    }
    response = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json=payload,
    )

    events = _events(response)
    event_names = [name for name, _data in events]
    assert "retrieval.started" not in event_names
    assert events[-1][0] == "message.completed"
    assert events[-1][1]["completion_kind"] == "clarification"
    assert events[-1][1]["grounded"] is False
    assert events[-1][1]["citations"] == []

    messages = (
        await client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=headers)
    ).json()["items"]
    assistant = next(item for item in messages if item["role"] == "assistant")
    assert assistant["completion_kind"] == "clarification"
    assert assistant["retrieval_run_id"] is None

    replay = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=headers,
        json=payload,
    )
    replay_completed = _events(replay)[-1][1]
    assert replay_completed["message_id"] == events[-1][1]["message_id"]
    assert replay_completed["completion_kind"] == "clarification"


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
        llm_provider="fake",
        llm_model="fake-chat-v1",
        intent_classifier_provider="fake",
        classifier_model="fake-intent-v1",
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
