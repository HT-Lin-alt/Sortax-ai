from typing import cast

import pytest

from sortax.embedding_gateway import FakeEmbeddingProvider
from sortax.rag import (
    ChecklistGroundingContext,
    ClarificationRequired,
    FakeRetriever,
    MilvusRetriever,
    RetrievalHistoryMessage,
    RetrievalPlan,
    RetrievalUnavailableError,
    VectorSearchHit,
    VectorStore,
)
from sortax.tax_intake import UnsupportedQuestionnaireOptionError


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


class ClaimSearchStore:
    def __init__(self, hits_by_claim: dict[str, list[VectorSearchHit]]) -> None:
        self.hits_by_claim = hits_by_claim
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
        assert collection_name == "ato_knowledge_demo"
        assert vector
        self.calls.append((claim_type, tax_year, limit))
        return self.hits_by_claim.get(claim_type, [])


def _hit(
    claim_type: str,
    *,
    document_id: str | None = None,
    chunk_id: str | None = None,
    tax_year: str = "2025-26",
    score: float = 0.9,
) -> VectorSearchHit:
    resolved_document_id = document_id or f"ato-{claim_type}"
    return VectorSearchHit(
        chunk_id=chunk_id or f"{resolved_document_id}:00000",
        document_id=resolved_document_id,
        content_hash=f"sha256:{resolved_document_id}",
        text=f"Reviewed evidence for {claim_type}.",
        title=claim_type.replace("_", " ").title(),
        source_url=f"https://www.ato.gov.au/{resolved_document_id}",
        claim_type=claim_type,
        tax_year=tax_year,
        accessed_at="2026-10-09",
        score=score,
        section_path="Records to keep",
    )


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
@pytest.mark.parametrize(
    ("query", "expected_claim"),
    [
        ("PAYG income statement documents for 2025-26", "salary_wages"),
        ("工资收入 2025-26 要保留哪些文件", "salary_wages"),
        ("Rental property records for 2025-26", "residential_rental_property"),
        ("出租物业 2025-26 需要哪些记录", "residential_rental_property"),
        ("Bank interest documents for 2025-26", "australian_bank_interest"),
        ("银行利息 2025-26 需要哪些证明", "australian_bank_interest"),
        (
            "Records for rental properties and holiday homes in 2025-26",
            "residential_rental_property",
        ),
        ("australian_bank_interest 2025-26", "australian_bank_interest"),
    ],
)
async def test_phase_4b_plan_parses_new_claim_types(query: str, expected_claim: str) -> None:
    plan = await FakeRetriever().plan(query)

    assert isinstance(plan, RetrievalPlan)
    assert plan.claim_type == expected_claim
    assert plan.tax_year == "2025-26"


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


@pytest.mark.asyncio
async def test_checklist_plan_maps_options_and_rejects_unsupported_scope() -> None:
    retriever = FakeRetriever()

    plan = await retriever.plan_checklist(
        ("salary_wages", "working_from_home", "salary_wages"),
        "2025-26",
    )

    assert plan.claim_types == ("salary_wages", "working_from_home")
    assert plan.topics[0].source_option_codes == ("salary_wages",)
    assert plan.topics[0].retrieval_plan.minimized_query == (
        "ATO document record requirements salary_wages 2025-26"
    )

    with pytest.raises(RetrievalUnavailableError, match="unsupported tax year"):
        await retriever.plan_checklist(("salary_wages",), "2024-25")
    with pytest.raises(UnsupportedQuestionnaireOptionError, match="overseas_income"):
        await retriever.plan_checklist(("overseas_income",), "2025-26")


@pytest.mark.asyncio
async def test_multi_topic_retrieval_keeps_topic_citation_closure_and_deduplicates_chunks() -> None:
    salary_hit = _hit("salary_wages")
    duplicate_salary_hit = _hit("salary_wages", score=0.8)
    rental_hit = _hit("residential_rental_property")
    store = ClaimSearchStore(
        {
            "salary_wages": [salary_hit, duplicate_salary_hit],
            "residential_rental_property": [rental_hit],
        }
    )
    retriever = MilvusRetriever(
        provider=FakeEmbeddingProvider(dimensions=8),
        store=cast(VectorStore, store),
        collection_name="ato_knowledge_demo",
        top_k=5,
        score_threshold=0.5,
    )
    plan = await retriever.plan_checklist(
        ("salary_wages", "residential_rental_property"),
        "2025-26",
    )

    grounding = await retriever.retrieve_checklist(plan)

    assert isinstance(grounding, ChecklistGroundingContext)
    assert grounding.claim_types == ("salary_wages", "residential_rental_property")
    assert grounding.candidate_count == 3
    assert grounding.selected_count == 2
    assert len(grounding.citations) == 2
    assert grounding.items[0].claim_type == "salary_wages"
    assert grounding.items[0].citation_ordinals == (1,)
    assert grounding.items[1].claim_type == "residential_rental_property"
    assert grounding.items[1].citation_ordinals == (2,)
    assert store.calls == [
        ("salary_wages", "2025-26", 5),
        ("residential_rental_property", "2025-26", 5),
    ]


@pytest.mark.asyncio
async def test_multi_topic_retrieval_fails_closed_when_any_topic_has_no_evidence() -> None:
    store = ClaimSearchStore({"salary_wages": [_hit("salary_wages")]})
    retriever = MilvusRetriever(
        provider=FakeEmbeddingProvider(dimensions=8),
        store=cast(VectorStore, store),
        collection_name="ato_knowledge_demo",
        score_threshold=0.5,
    )
    plan = await retriever.plan_checklist(
        ("salary_wages", "australian_bank_interest"),
        "2025-26",
    )

    with pytest.raises(RetrievalUnavailableError, match="insufficient evidence"):
        await retriever.retrieve_checklist(plan)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_hit",
    [
        _hit("work_related_car", tax_year="2024-25"),
        _hit("working_from_home"),
    ],
)
async def test_multi_topic_retrieval_rejects_wrong_year_or_claim_type(
    bad_hit: VectorSearchHit,
) -> None:
    store = ClaimSearchStore({"work_related_car": [bad_hit]})
    retriever = MilvusRetriever(
        provider=FakeEmbeddingProvider(dimensions=8),
        store=cast(VectorStore, store),
        collection_name="ato_knowledge_demo",
        score_threshold=0.5,
    )
    plan = await retriever.plan_checklist(("work_related_car",), "2025-26")

    with pytest.raises(RetrievalUnavailableError, match="insufficient evidence"):
        await retriever.retrieve_checklist(plan)
