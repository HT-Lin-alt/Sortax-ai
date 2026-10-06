from types import SimpleNamespace
from typing import Any

import pytest

from sortax.embedding_gateway import EmbeddingProviderError, OpenAIEmbeddingProvider


class FakeEmbeddingsEndpoint:
    def __init__(self, *, dimensions: int = 3, fail: bool = False) -> None:
        self.dimensions = dimensions
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("secret provider detail")
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[float(index + 1)] * self.dimensions)
                for index, _text in reversed(list(enumerate(kwargs["input"])))
            ]
        )


class FakeOpenAIClient:
    def __init__(self, endpoint: FakeEmbeddingsEndpoint) -> None:
        self.embeddings = endpoint


@pytest.mark.asyncio
async def test_openai_embeddings_batch_and_restore_provider_order() -> None:
    endpoint = FakeEmbeddingsEndpoint()
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        model_name="text-embedding-3-small",
        dimensions=3,
        batch_size=2,
        client_factory=lambda **_kwargs: FakeOpenAIClient(endpoint),
    )

    vectors = await provider.embed_documents(["one", "two", "three"])

    assert len(endpoint.calls) == 2
    assert endpoint.calls[0] == {
        "input": ["one", "two"],
        "model": "text-embedding-3-small",
        "dimensions": 3,
        "encoding_format": "float",
    }
    assert vectors == [[1.0, 1.0, 1.0], [2.0, 2.0, 2.0], [1.0, 1.0, 1.0]]


@pytest.mark.asyncio
async def test_openai_embedding_normalizes_provider_failure() -> None:
    endpoint = FakeEmbeddingsEndpoint(fail=True)
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        dimensions=3,
        client_factory=lambda **_kwargs: FakeOpenAIClient(endpoint),
    )

    with pytest.raises(EmbeddingProviderError, match="embedding provider request failed") as error:
        await provider.embed_query("ATO source")

    assert "secret provider detail" not in str(error.value)


@pytest.mark.asyncio
async def test_openai_embedding_rejects_wrong_dimension() -> None:
    endpoint = FakeEmbeddingsEndpoint(dimensions=2)
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        dimensions=3,
        client_factory=lambda **_kwargs: FakeOpenAIClient(endpoint),
    )

    with pytest.raises(EmbeddingProviderError, match="unexpected dimension"):
        await provider.embed_query("ATO source")
