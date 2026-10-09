from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr, ValidationError

from sortax.config import Settings
from sortax.llm_gateway import QwenLLMProvider
from sortax.prompting import LLMRequest


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
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> FakeResponseStream:
        self.calls.append(kwargs)
        return FakeResponseStream(
            [
                SimpleNamespace(type="response.output_text.delta", delta="sortax-ok"),
                SimpleNamespace(
                    type="response.completed",
                    response=SimpleNamespace(
                        id="resp_qwen_123",
                        usage=SimpleNamespace(input_tokens=8, output_tokens=2),
                    ),
                ),
            ]
        )


class FakeOpenAIClient:
    def __init__(self, endpoint: FakeResponsesEndpoint) -> None:
        self.responses = endpoint


@pytest.mark.asyncio
async def test_qwen_provider_uses_compatible_base_url_and_reports_qwen() -> None:
    endpoint = FakeResponsesEndpoint()
    client_options: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakeOpenAIClient:
        client_options.update(kwargs)
        return FakeOpenAIClient(endpoint)

    provider = QwenLLMProvider(
        api_key="test-key",
        model_name="qwen3.7-flash",
        base_url="https://maas.qianwenaiapi.com/compatible-mode/v1",
        request_timeout_seconds=12,
        max_output_tokens=32,
        client_factory=factory,
    )

    chunks = [
        chunk
        async for chunk in provider.stream(
            LLMRequest(
                system_instruction="Reply briefly.",
                user_content="Connectivity check.",
                history=(),
                evidence=(),
                completion_kind="general_chat",
            )
        )
    ]

    assert provider.provider_name == "qwen"
    assert client_options == {
        "api_key": "test-key",
        "base_url": "https://maas.qianwenaiapi.com/compatible-mode/v1",
        "timeout": 12,
        "max_retries": 2,
    }
    assert "".join(chunk.delta for chunk in chunks) == "sortax-ok"
    assert chunks[-1].provider_request_id == "resp_qwen_123"


def test_qwen_configuration_requires_key_real_model_and_https() -> None:
    common = {
        "app_env": "development",
        "jwt_secret": SecretStr("test-secret-that-is-at-least-32-characters-long"),
        "llm_provider": "qwen",
    }

    with pytest.raises(ValidationError, match="SORTAX_QWEN_API_KEY"):
        Settings(**common, llm_model="qwen3.7-flash", qwen_api_key=None)

    with pytest.raises(ValidationError, match="real LLM model"):
        Settings(**common, llm_model="fake-chat-v1", qwen_api_key=SecretStr("test-key"))

    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            **common,
            llm_model="qwen3.7-flash",
            qwen_api_key=SecretStr("test-key"),
            qwen_base_url="http://example.test/compatible-mode/v1",
        )

    with pytest.raises(ValidationError, match="must be at least 16"):
        Settings(
            **common,
            llm_model="qwen3.7-flash",
            qwen_api_key=SecretStr("test-key"),
            llm_max_output_tokens=15,
        )
