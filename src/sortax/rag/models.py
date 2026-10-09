from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass(frozen=True, slots=True)
class CitationCandidate:
    document_id: str
    chunk_id: str
    title: str
    source_url: str
    tax_year: str
    score: float
    content_hash: str
    chunk_ids: tuple[str, ...]
    accessed_at: date
    section: str | None = None


@dataclass(frozen=True, slots=True)
class GroundingContext:
    claim_type: str
    tax_year: str
    evidence: tuple[str, ...]
    citations: tuple[CitationCandidate, ...]
    candidate_count: int = 0
    selected_count: int = 0


@dataclass(frozen=True, slots=True)
class ClarificationRequired:
    missing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RetrievalPlan:
    intent: str
    claim_type: str
    tax_year: str
    minimized_query: str


@dataclass(frozen=True, slots=True)
class ChecklistTopicPlan:
    claim_type: str
    source_option_codes: tuple[str, ...]
    retrieval_plan: RetrievalPlan


@dataclass(frozen=True, slots=True)
class ChecklistRetrievalPlan:
    intent: str
    tax_year: str
    topics: tuple[ChecklistTopicPlan, ...]

    @property
    def claim_types(self) -> tuple[str, ...]:
        return tuple(topic.claim_type for topic in self.topics)


@dataclass(frozen=True, slots=True)
class ChecklistGroundingItem:
    claim_type: str
    source_option_codes: tuple[str, ...]
    evidence: tuple[str, ...]
    citation_ordinals: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ChecklistGroundingContext:
    tax_year: str
    claim_types: tuple[str, ...]
    items: tuple[ChecklistGroundingItem, ...]
    citations: tuple[CitationCandidate, ...]
    candidate_count: int = 0
    selected_count: int = 0


@dataclass(frozen=True, slots=True)
class RetrievalHistoryMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class VectorSearchHit:
    chunk_id: str
    document_id: str
    content_hash: str
    text: str
    title: str
    source_url: str
    claim_type: str
    tax_year: str
    accessed_at: str
    score: float
    section_path: str | None = None
