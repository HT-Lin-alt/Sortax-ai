import asyncio
import hashlib
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from typing import Protocol

from sortax.embedding_gateway import EmbeddingProvider, EmbeddingProviderError
from sortax.rag.models import (
    ChecklistGroundingContext,
    ChecklistGroundingItem,
    ChecklistRetrievalPlan,
    ChecklistTopicPlan,
    CitationCandidate,
    ClarificationRequired,
    GroundingContext,
    RetrievalHistoryMessage,
    RetrievalPlan,
    VectorSearchHit,
)
from sortax.rag.ports import VectorStore
from sortax.tax_intake import SUPPORTED_TAX_YEAR, map_questionnaire_options


class RetrievalUnavailableError(RuntimeError):
    """The configured retrieval dependency cannot safely answer the query."""


class Retriever(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def embedding_model(self) -> str: ...

    @property
    def collection_name(self) -> str: ...

    @property
    def top_k(self) -> int: ...

    @property
    def score_threshold(self) -> float: ...

    @property
    def config_version(self) -> str: ...

    async def plan(
        self,
        query: str,
        history: Sequence[RetrievalHistoryMessage] = (),
    ) -> RetrievalPlan | ClarificationRequired: ...

    async def retrieve(self, plan: RetrievalPlan) -> GroundingContext: ...

    async def plan_checklist(
        self,
        option_codes: Sequence[str],
        tax_year: str,
    ) -> ChecklistRetrievalPlan: ...

    async def retrieve_checklist(
        self,
        plan: ChecklistRetrievalPlan,
    ) -> ChecklistGroundingContext: ...


class FakeRetriever:
    """Deterministic Phase 5A retriever; never reads Milvus or external content."""

    _claim_terms = {
        "salary_wages": (
            "salary",
            "wages",
            "payg",
            "income statement",
            "工资",
            "薪资",
            "工资收入",
        ),
        "working_from_home": (
            "working from home",
            "work from home",
            "home office",
            "wfh",
            "在家办公",
            "居家办公",
            "居家工作",
        ),
        "self_education": ("education", "course", "training", "学习", "课程", "培训"),
        "work_related_car": ("car", "vehicle", "mileage", "汽车", "车辆", "里程"),
        "residential_rental_property": (
            "rental property",
            "rental properties",
            "rental income",
            "investment property",
            "holiday homes",
            "landlord",
            "出租房",
            "出租物业",
            "租金收入",
            "投资房",
        ),
        "australian_bank_interest": (
            "bank interest",
            "interest income",
            "income bond",
            "bank account interest",
            "银行利息",
            "存款利息",
            "利息收入",
        ),
    }
    _tax_year_pattern = re.compile(r"\b(20\d{2})[-–/](\d{2}|20\d{2})\b")

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def embedding_model(self) -> str:
        return "fake-embedding-v1"

    @property
    def collection_name(self) -> str:
        return "ato_knowledge_demo"

    @property
    def top_k(self) -> int:
        return 5

    @property
    def score_threshold(self) -> float:
        return 0.5

    @property
    def config_version(self) -> str:
        return "phase-4b-fake-v1"

    async def plan(
        self,
        query: str,
        history: Sequence[RetrievalHistoryMessage] = (),
    ) -> RetrievalPlan | ClarificationRequired:
        claim_type, tax_year = _parse_fields(query, self._claim_terms, self._tax_year_pattern)
        if claim_type is not None or tax_year is not None:
            for message in reversed(history):
                if message.role != "user":
                    continue
                historical_claim, historical_year = _parse_fields(
                    message.content, self._claim_terms, self._tax_year_pattern
                )
                claim_type = claim_type or historical_claim
                tax_year = tax_year or historical_year
                if claim_type is not None and tax_year is not None:
                    break
        missing: list[str] = []
        if claim_type is None:
            missing.append("claim_type")
        if tax_year is None:
            missing.append("tax_year")
        if missing:
            return ClarificationRequired(missing_fields=tuple(missing))

        if claim_type is None or tax_year is None:
            raise RetrievalUnavailableError("fake retrieval planning failed")
        return RetrievalPlan(
            intent="ato_document_requirements",
            claim_type=claim_type,
            tax_year=tax_year,
            minimized_query=_minimized_query(claim_type, tax_year),
        )

    async def retrieve(self, plan: RetrievalPlan) -> GroundingContext:
        document_id = f"fake-{plan.claim_type}"
        digest = hashlib.sha256(
            f"{document_id}:{plan.tax_year}:phase-5a".encode(), usedforsecurity=False
        ).hexdigest()
        title = plan.claim_type.replace("_", " ").title()
        citation = CitationCandidate(
            document_id=document_id,
            chunk_id=f"{document_id}:{digest[:20]}:00000",
            title=f"{title} (Phase 5A fake evidence)",
            source_url="https://www.ato.gov.au/",
            tax_year=plan.tax_year,
            score=1.0,
            content_hash=f"sha256:{digest}",
            chunk_ids=(f"{document_id}:{digest[:20]}:00000",),
            accessed_at=date(2026, 10, 6),
            section="Phase 5A fake evidence",
            claim_type=plan.claim_type,
        )
        evidence = (
            "This is deterministic Phase 5A fake evidence used only to test chat "
            "orchestration. It is not an ATO factual answer.",
        )
        return GroundingContext(
            claim_type=plan.claim_type,
            tax_year=plan.tax_year,
            evidence=evidence,
            citations=(citation,),
            candidate_count=1,
            selected_count=1,
        )

    async def plan_checklist(
        self,
        option_codes: Sequence[str],
        tax_year: str,
    ) -> ChecklistRetrievalPlan:
        if tax_year != SUPPORTED_TAX_YEAR:
            raise RetrievalUnavailableError("unsupported tax year")
        claim_types = map_questionnaire_options(option_codes)
        if not claim_types:
            raise RetrievalUnavailableError("no supported claim types selected")
        topics = tuple(
            ChecklistTopicPlan(
                claim_type=claim_type,
                source_option_codes=tuple(
                    dict.fromkeys(
                        option_code
                        for option_code in option_codes
                        if map_questionnaire_options((option_code,)) == (claim_type,)
                    )
                ),
                retrieval_plan=RetrievalPlan(
                    intent="tax_assistance",
                    claim_type=claim_type,
                    tax_year=tax_year,
                    minimized_query=_minimized_query(claim_type, tax_year),
                ),
            )
            for claim_type in claim_types
        )
        return ChecklistRetrievalPlan(
            intent="tax_assistance",
            tax_year=tax_year,
            topics=topics,
        )

    async def retrieve_checklist(
        self,
        plan: ChecklistRetrievalPlan,
    ) -> ChecklistGroundingContext:
        if plan.tax_year != SUPPORTED_TAX_YEAR or not plan.topics:
            raise RetrievalUnavailableError("invalid checklist retrieval plan")
        contexts = await asyncio.gather(
            *(self.retrieve(topic.retrieval_plan) for topic in plan.topics)
        )
        return _merge_checklist_grounding(plan, contexts)


class MilvusRetriever(FakeRetriever):
    """Online retriever over reviewed ATO chunks stored in Milvus."""

    def __init__(
        self,
        *,
        provider: EmbeddingProvider,
        store: VectorStore,
        collection_name: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not 0 <= score_threshold <= 1:
            raise ValueError("score_threshold must be between zero and one")
        self._provider = provider
        self._store = store
        self._collection_name = collection_name
        self._top_k = top_k
        self._score_threshold = score_threshold

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def embedding_model(self) -> str:
        return self._provider.model_name

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def top_k(self) -> int:
        return self._top_k

    @property
    def score_threshold(self) -> float:
        return self._score_threshold

    @property
    def config_version(self) -> str:
        return "phase-4b-dense-v1"

    async def retrieve(self, plan: RetrievalPlan) -> GroundingContext:
        try:
            vector = await self._provider.embed_query(plan.minimized_query)
            if len(vector) != self._provider.dimensions:
                raise RetrievalUnavailableError("query embedding has an invalid dimension")
            raw_hits = await self._store.search(
                self._collection_name,
                vector,
                claim_type=plan.claim_type,
                tax_year=plan.tax_year,
                limit=self._top_k,
            )
        except RetrievalUnavailableError:
            raise
        except (EmbeddingProviderError, RuntimeError) as exc:
            raise RetrievalUnavailableError("retrieval dependency is unavailable") from exc

        hits = [
            hit
            for hit in raw_hits
            if hit.score >= self._score_threshold
            and hit.claim_type == plan.claim_type
            and hit.tax_year == plan.tax_year
            and hit.text.strip()
        ]
        if not hits:
            raise RetrievalUnavailableError("insufficient evidence")
        return _grounding_from_hits(plan, hits, candidate_count=len(raw_hits))


def _parse_fields(
    text: str,
    claim_terms: dict[str, tuple[str, ...]],
    tax_year_pattern: re.Pattern[str],
) -> tuple[str | None, str | None]:
    normalized = " ".join(text.lower().split())
    claim_type = next(
        (
            candidate
            for candidate, terms in claim_terms.items()
            if candidate in normalized or any(term in normalized for term in terms)
        ),
        None,
    )
    match = tax_year_pattern.search(normalized)
    if match is None:
        return claim_type, None
    start_year = match.group(1)
    end_year = match.group(2)[-2:]
    return claim_type, f"{start_year}-{end_year}"


def _minimized_query(claim_type: str, tax_year: str) -> str:
    return f"ATO document record requirements {claim_type} {tax_year}"


def _grounding_from_hits(
    plan: RetrievalPlan, hits: list[VectorSearchHit], *, candidate_count: int
) -> GroundingContext:
    unique_hits: dict[tuple[str, str, str], VectorSearchHit] = {}
    for hit in hits:
        key = (hit.document_id, hit.content_hash, hit.chunk_id)
        existing = unique_hits.get(key)
        if existing is None or hit.score > existing.score:
            unique_hits[key] = hit
    hits = list(unique_hits.values())
    citations: list[CitationCandidate] = []
    grouped: dict[tuple[str, str], list[VectorSearchHit]] = {}
    for hit in hits:
        grouped.setdefault((hit.document_id, hit.content_hash), []).append(hit)
    for document_hits in grouped.values():
        first = document_hits[0]
        try:
            accessed_at = date.fromisoformat(first.accessed_at)
        except ValueError as exc:
            raise RetrievalUnavailableError("retrieved citation metadata is invalid") from exc
        citations.append(
            CitationCandidate(
                document_id=first.document_id,
                chunk_id=first.chunk_id,
                title=first.title,
                source_url=first.source_url,
                tax_year=first.tax_year,
                score=max(hit.score for hit in document_hits),
                content_hash=first.content_hash,
                chunk_ids=tuple(hit.chunk_id for hit in document_hits),
                accessed_at=accessed_at,
                section=first.section_path,
                claim_type=first.claim_type,
            )
        )
    return GroundingContext(
        claim_type=plan.claim_type,
        tax_year=plan.tax_year,
        evidence=tuple(hit.text for hit in hits),
        citations=tuple(citations),
        candidate_count=candidate_count,
        selected_count=len(hits),
    )


def _merge_checklist_grounding(
    plan: ChecklistRetrievalPlan,
    contexts: Sequence[GroundingContext],
) -> ChecklistGroundingContext:
    if len(contexts) != len(plan.topics):
        raise RetrievalUnavailableError("checklist retrieval result count is invalid")

    citations: list[CitationCandidate] = []
    citation_positions: dict[tuple[str, str], int] = {}
    citation_owners: dict[tuple[str, str], str] = {}
    items: list[ChecklistGroundingItem] = []
    selected_chunks: set[tuple[str, str, str]] = set()
    candidate_count = 0

    for topic, context in zip(plan.topics, contexts, strict=True):
        if (
            context.claim_type != topic.claim_type
            or context.tax_year != plan.tax_year
            or not context.evidence
            or not context.citations
        ):
            raise RetrievalUnavailableError("checklist evidence scope is invalid")
        candidate_count += context.candidate_count
        ordinals: list[int] = []
        for citation in context.citations:
            if citation.tax_year != plan.tax_year or not citation.chunk_ids:
                raise RetrievalUnavailableError("checklist citation metadata is invalid")
            key = (citation.document_id, citation.content_hash)
            owner = citation_owners.get(key)
            if owner is not None and owner != topic.claim_type:
                raise RetrievalUnavailableError("citation cannot support multiple claim types")
            citation_owners[key] = topic.claim_type
            position = citation_positions.get(key)
            if position is None:
                position = len(citations)
                citation_positions[key] = position
                citations.append(citation)
            else:
                existing = citations[position]
                merged_chunk_ids = tuple(dict.fromkeys((*existing.chunk_ids, *citation.chunk_ids)))
                citations[position] = replace(
                    existing,
                    score=max(existing.score, citation.score),
                    chunk_ids=merged_chunk_ids,
                )
            ordinal = position + 1
            if ordinal not in ordinals:
                ordinals.append(ordinal)
            for chunk_id in citation.chunk_ids:
                selected_chunks.add((citation.document_id, citation.content_hash, chunk_id))
        if not ordinals:
            raise RetrievalUnavailableError("checklist item has no citation")
        items.append(
            ChecklistGroundingItem(
                claim_type=topic.claim_type,
                source_option_codes=topic.source_option_codes,
                evidence=tuple(dict.fromkeys(context.evidence)),
                citation_ordinals=tuple(ordinals),
            )
        )

    if len(items) != len(plan.topics):
        raise RetrievalUnavailableError("checklist evidence is incomplete")
    return ChecklistGroundingContext(
        tax_year=plan.tax_year,
        claim_types=plan.claim_types,
        items=tuple(items),
        citations=tuple(citations),
        candidate_count=candidate_count,
        selected_count=len(selected_chunks),
    )
