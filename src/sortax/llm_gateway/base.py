from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from sortax.prompting import LLMRequest


class LLMProviderError(RuntimeError):
    """Normalized language-model failure without vendor details."""


class LLMProviderUnavailable(LLMProviderError):
    """The configured provider cannot currently accept the request."""


class LLMProviderTimeout(LLMProviderError):
    """The configured provider exceeded a request deadline."""


class LLMProviderRateLimited(LLMProviderError):
    """The configured provider rejected the request due to rate limits."""


@dataclass(frozen=True, slots=True)
class LLMStreamChunk:
    delta: str = ""
    provider_request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]: ...
