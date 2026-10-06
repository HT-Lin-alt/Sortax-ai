from typing import cast

import pytest

from sortax.embedding_gateway import FakeEmbeddingProvider
from sortax.rag import (
    ClarificationRequired,
    FakeRetriever,
    MilvusRetriever,
    RetrievalHistoryMessage,
    RetrievalPlan,
    RetrievalUnavailableError,
    VectorSearchHit,
    VectorStore,
)


class SearchStore:
    def __init__(self, hits: list[VectorSearchHit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, str, int]] = []

    async def search(
        self,
        collection_name: str,
        vector: list[float],
        *,
        claim_type: str,
        tax_year: str,
        limit: int,
    ) -> list[VectorSearchHit]:
        assert vector
        self.calls.append((claim_type, tax_year, limit))
        return self.hits


@pytest.mark.asyncio
async def test_plan_prefers_current_fields_and_inherits_only_missing_history_field() -> None:
    retriever = FakeRetriever()
    history = (
        RetrievalHistoryMessage(role="user", content="Car records for 2024-25"),
        RetrievalHistoryMessage(role="assistant", content="Which year?"),
    )

    plan = await retriever.plan("2025-26", history)

    assert isinstance(plan, RetrievalPlan)
    assert plan.claim_type == "work_related_car"
    assert plan.tax_year == "2025-26"
    assert plan.minimized_query == ("ATO document record requirements work_related_car 2025-26")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "history", "expected_claim", "expected_year"),
    [
        ("Car records for 2025-26", (), "work_related_car", "2025-26"),
        (
            "What car records are needed?",
            (RetrievalHistoryMessage(role="user", content="For 2025-26"),),
            "work_related_car",
            "2025-26",
        ),
        (
            "2025-26",
            (RetrievalHistoryMessage(role="user", content="Working from home records"),),
            "working_from_home",
            "2025-26",
        ),
    ],
)
async def test_plan_field_combinations(
    query: str,
    history: tuple[RetrievalHistoryMessage, ...],
    expected_claim: str,
    expected_year: str,
) -> None:
    plan = await FakeRetriever().plan(query, history)

    assert isinstance(plan, RetrievalPlan)
    assert plan.claim_type == expected_claim
    assert plan.tax_year == expected_year


@pytest.mark.asyncio
async def test_plan_does_not_inherit_when_current_message_has_no_supported_field() -> None:
    result = await FakeRetriever().plan(
        "Thanks",
        (RetrievalHistoryMessage(role="user", content="Car records for 2025-26"),),
    )

    assert isinstance(result, ClarificationRequired)
    assert result.missing_fields == ("claim_type", "tax_year")


@pytest.mark.asyncio
async def test_milvus_retriever_filters_low_scores_and_groups_document_citations() -> None:
    common = {
        "document_id": "car-records",
        "content_hash": "sha256:reviewed",
        "title": "Car expenses records",
        "source_url": "https://www.ato.gov.au/car-expenses",
        "claim_type": "work_related_car",
        "tax_year": "2025-26",
        "accessed_at": "2026-10-04",
        "section_path": "Records to keep",
    }
    hits = [
        VectorSearchHit(chunk_id="car:00000", text="Keep written evidence.", score=0.92, **common),
        VectorSearchHit(chunk_id="car:00001", text="Keep a logbook.", score=0.81, **common),
        VectorSearchHit(chunk_id="car:00002", text="Weak match.", score=0.2, **common),
    ]
    store = SearchStore(hits)
    retriever = MilvusRetriever(
        provider=FakeEmbeddingProvider(dimensions=8),
        store=cast(VectorStore, store),
        collection_name="ato_knowledge_demo",
        top_k=5,
        score_threshold=0.5,
    )
    plan = cast(RetrievalPlan, await retriever.plan("Car records for 2025-26"))

    grounding = await retriever.retrieve(plan)

    assert grounding.evidence == ("Keep written evidence.", "Keep a logbook.")
    assert len(grounding.citations) == 1
    assert grounding.citations[0].chunk_ids == ("car:00000", "car:00001")
    assert store.calls == [("work_related_car", "2025-26", 5)]


@pytest.mark.asyncio
async def test_milvus_retriever_fails_closed_when_no_hit_meets_threshold() -> None:
    hit = VectorSearchHit(
        chunk_id="car:00000",
        document_id="car",
        content_hash="sha256:hash",
        text="Low confidence",
        title="Car records",
        source_url="https://www.ato.gov.au/car",
        claim_type="work_related_car",
        tax_year="2025-26",
        accessed_at="2026-10-04",
        score=0.1,
    )
    retriever = MilvusRetriever(
        provider=FakeEmbeddingProvider(dimensions=8),
        store=cast(VectorStore, SearchStore([hit])),
        collection_name="ato_knowledge_demo",
        score_threshold=0.5,
    )
    plan = cast(RetrievalPlan, await retriever.plan("Car records for 2025-26"))

    with pytest.raises(RetrievalUnavailableError, match="insufficient evidence"):
        await retriever.retrieve(plan)
