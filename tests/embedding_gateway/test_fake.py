import math

import pytest

from sortax.embedding_gateway import EmbeddingProviderError, FakeEmbeddingProvider


@pytest.mark.asyncio
async def test_fake_embeddings_are_deterministic_normalized_and_sized() -> None:
    provider = FakeEmbeddingProvider(dimensions=8)

    first = await provider.embed_query("ATO working from home")
    second = await provider.embed_query("ATO working from home")
    different = await provider.embed_query("ATO car expenses")

    assert first == second
    assert first != different
    assert len(first) == 8
    assert math.isclose(math.sqrt(sum(value * value for value in first)), 1.0)


@pytest.mark.asyncio
async def test_fake_document_embeddings_preserve_input_order() -> None:
    provider = FakeEmbeddingProvider(dimensions=4)

    vectors = await provider.embed_documents(["first", "second"])

    assert vectors == [await provider.embed_query("first"), await provider.embed_query("second")]


@pytest.mark.asyncio
async def test_fake_embedding_rejects_empty_input() -> None:
    provider = FakeEmbeddingProvider()

    with pytest.raises(EmbeddingProviderError):
        await provider.embed_query("  ")


@pytest.mark.asyncio
async def test_fake_embeddings_rank_lexical_topic_overlap() -> None:
    provider = FakeEmbeddingProvider(dimensions=64)
    query = await provider.embed_query("ATO work related car record requirements")
    related = await provider.embed_query("Keep car logbook records for work travel")
    unrelated = await provider.embed_query("Self education course tuition receipt")

    related_score = sum(left * right for left, right in zip(query, related, strict=True))
    unrelated_score = sum(left * right for left, right in zip(query, unrelated, strict=True))

    assert related_score > unrelated_score
