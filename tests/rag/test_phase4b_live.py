import os

import pytest

from sortax.embedding_gateway import FakeEmbeddingProvider
from sortax.infrastructure.milvus import MilvusVectorStore
from sortax.rag import MilvusRetriever
from sortax.tax_intake import SUPPORTED_CLAIM_TYPES

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_explicit_phase4b_multi_topic_milvus_smoke() -> None:
    if os.getenv("SORTAX_RUN_MILVUS_SMOKE") != "1":
        pytest.skip("set SORTAX_RUN_MILVUS_SMOKE=1 to use the local Milvus collection")

    store = MilvusVectorStore(
        uri=os.getenv("SORTAX_MILVUS_URI", "http://localhost:19530"),
        database=os.getenv("SORTAX_MILVUS_DATABASE", "default"),
    )
    await store.connect()
    try:
        retriever = MilvusRetriever(
            provider=FakeEmbeddingProvider(dimensions=64),
            store=store,
            collection_name=os.getenv("SORTAX_MILVUS_COLLECTION", "ato_knowledge_demo"),
            top_k=3,
            score_threshold=0,
        )
        plan = await retriever.plan_checklist(SUPPORTED_CLAIM_TYPES, "2025-26")

        grounding = await retriever.retrieve_checklist(plan)

        assert grounding.claim_types == SUPPORTED_CLAIM_TYPES
        assert len(grounding.items) == len(SUPPORTED_CLAIM_TYPES)
        assert all(item.citation_ordinals for item in grounding.items)
        assert all(
            grounding.citations[ordinal - 1].tax_year == "2025-26"
            for item in grounding.items
            for ordinal in item.citation_ordinals
        )
    finally:
        await store.close()
