from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from sortax.config import Settings
from sortax.llm_gateway import LLMProviderError, LLMProviderTimeout, OpenAILLMProvider
from sortax.prompting import HistoryMessage, LLMRequest


class FakeResponseStream:
    def __init__(self, events: list[Any]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> "FakeResponseStream":
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeResponsesEndpoint:
    def __init__(self, *, events: list[Any] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeResponseStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return FakeResponseStream(self.events)


class FakeOpenAIClient:
    def __init__(self, endpoint: FakeResponsesEndpoint) -> None:
        self.responses = endpoint


def _request() -> LLMRequest:
    return LLMRequest(
        system_instruction="system boundary",
        user_content="What car records are needed?",
        history=(HistoryMessage(role="user", content="For work expenses"),),
        evidence=("Keep a logbook.",),
        completion_kind="answer",
    )


@pytest.mark.asyncio
async def test_openai_provider_streams_text_and_normalizes_usage() -> None:
    endpoint = FakeResponsesEndpoint(
        events=[
            SimpleNamespace(type="response.output_text.delta", delta="Keep "),
            SimpleNamespace(type="response.output_text.delta", delta="records."),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    id="resp_123",
                    usage=SimpleNamespace(input_tokens=12, output_tokens=3),
                ),
            ),
        ]
    )
    client_options: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeOpenAIClient:
        client_options.update(kwargs)
        return FakeOpenAIClient(endpoint)

    provider = OpenAILLMProvider(
        api_key="test-key",
        model_name="test-model",
        request_timeout_seconds=12,
        max_output_tokens=400,
        client_factory=factory,
    )

    chunks = [chunk async for chunk in provider.stream(_request())]

    assert client_options == {"api_key": "test-key", "timeout": 12, "max_retries": 2}
    assert "".join(chunk.delta for chunk in chunks) == "Keep records."
    assert chunks[-1].provider_request_id == "resp_123"
    assert chunks[-1].input_tokens == 12
    assert chunks[-1].output_tokens == 3
    call = endpoint.calls[0]
    assert call["model"] == "test-model"
    assert call["instructions"] == "system boundary"
    assert call["store"] is False
    assert call["stream"] is True
    assert call["timeout"] == 12
    assert call["input"][0] == {"role": "user", "content": "For work expenses"}
    assert call["input"][1]["content"] == "What car records are needed?"
    assert "[EVIDENCE 1]" in call["input"][2]["content"]


@pytest.mark.asyncio
async def test_openai_provider_normalizes_timeout_without_leaking_details() -> None:
    endpoint = FakeResponsesEndpoint(error=TimeoutError("secret provider detail"))
    provider = OpenAILLMProvider(
        api_key="test-key",
        model_name="test-model",
        client_factory=lambda **_kwargs: FakeOpenAIClient(endpoint),
    )

    with pytest.raises(LLMProviderTimeout, match="timed out") as error:
        _ = [chunk async for chunk in provider.stream(_request())]

    assert "secret provider detail" not in str(error.value)


@pytest.mark.asyncio
async def test_openai_provider_normalizes_unknown_failure() -> None:
    endpoint = FakeResponsesEndpoint(error=RuntimeError("secret provider detail"))
    provider = OpenAILLMProvider(
        api_key="test-key",
        model_name="test-model",
        client_factory=lambda **_kwargs: FakeOpenAIClient(endpoint),
    )

    with pytest.raises(LLMProviderError, match="request failed") as error:
        _ = [chunk async for chunk in provider.stream(_request())]

    assert "secret provider detail" not in str(error.value)


def test_openai_llm_configuration_requires_explicit_key_and_real_model() -> None:
    with pytest.raises(ValidationError, match="SORTAX_LLM_API_KEY"):
        Settings(
            app_env="development",
            jwt_secret=SecretStr("test-secret-that-is-at-least-32-characters-long"),
            llm_provider="openai",
            llm_model="test-model",
            llm_api_key=None,
        )

    with pytest.raises(ValidationError, match="real LLM model"):
        Settings(
            app_env="development",
            jwt_secret=SecretStr("test-secret-that-is-at-least-32-characters-long"),
            llm_provider="openai",
            llm_model="fake-chat-v1",
            llm_api_key=SecretStr("test-key"),
        )
