from collections.abc import Callable

from sortax.llm_gateway.openai import (
    AsyncOpenAIClientLike,
    OpenAILLMProvider,
    _default_client_factory,
)


class QwenLLMProvider(OpenAILLMProvider):
    """Qwen adapter using the platform's OpenAI-compatible Responses API."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        base_url: str,
        request_timeout_seconds: float = 60.0,
        max_output_tokens: int = 1024,
        client_factory: Callable[..., AsyncOpenAIClientLike] = _default_client_factory,
    ) -> None:
        super().__init__(
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
            provider_name="qwen",
            request_timeout_seconds=request_timeout_seconds,
            max_output_tokens=max_output_tokens,
            client_factory=client_factory,
        )
