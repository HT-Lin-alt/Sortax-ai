import math
from collections.abc import Callable
from typing import Any, Protocol, cast

from sortax.embedding_gateway.base import EmbeddingProviderError


class EmbeddingsEndpointLike(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class AsyncOpenAIClientLike(Protocol):
    embeddings: EmbeddingsEndpointLike


OpenAIClientFactory = Callable[..., AsyncOpenAIClientLike]


def _default_client_factory(**kwargs: Any) -> AsyncOpenAIClientLike:
    from openai import AsyncOpenAI

    return cast(AsyncOpenAIClientLike, AsyncOpenAI(**kwargs))


class OpenAIEmbeddingProvider:
    """OpenAI embeddings adapter with batching and strict response validation."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str = "text-embedding-3-small",
        dimensions: int = 1536,
        batch_size: int = 64,
        client_factory: OpenAIClientFactory = _default_client_factory,
    ) -> None:
        if not api_key:
            raise ValueError("api_key must not be empty")
        if dimensions <= 1:
            raise ValueError("dimensions must be greater than one")
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        self._model_name = model_name
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._client = client_factory(api_key=api_key)

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise EmbeddingProviderError("embedding input must not be empty")

        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self._batch_size):
                response = await self._client.embeddings.create(
                    input=texts[start : start + self._batch_size],
                    model=self._model_name,
                    dimensions=self._dimensions,
                    encoding_format="float",
                )
                ordered = sorted(response.data, key=lambda item: item.index)
                batch_vectors = [list(item.embedding) for item in ordered]
                self._validate_batch(batch_vectors, len(ordered))
                vectors.extend(batch_vectors)
        except EmbeddingProviderError:
            raise
        except Exception as exc:
            raise EmbeddingProviderError("embedding provider request failed") from exc
        if len(vectors) != len(texts):
            raise EmbeddingProviderError("embedding provider returned an unexpected item count")
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]

    def _validate_batch(self, vectors: list[list[float]], expected_count: int) -> None:
        if len(vectors) != expected_count:
            raise EmbeddingProviderError("embedding provider returned an unexpected item count")
        if any(len(vector) != self._dimensions for vector in vectors):
            raise EmbeddingProviderError("embedding provider returned an unexpected dimension")
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise EmbeddingProviderError("embedding provider returned a non-finite value")
