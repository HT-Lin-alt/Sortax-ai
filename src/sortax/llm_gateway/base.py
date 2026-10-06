from collections.abc import AsyncIterator
from typing import Protocol

from sortax.prompting import LLMRequest


class LLMProviderError(RuntimeError):
    """Normalized language-model failure without vendor details."""


class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[str]: ...
