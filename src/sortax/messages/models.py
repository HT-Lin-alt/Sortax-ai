from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

MessageRole = Literal["user", "assistant", "system"]
RunStatus = Literal["pending", "streaming", "completed", "failed", "cancelled"]
CompletionKind = Literal["answer", "clarification", "general_chat"]


@dataclass(frozen=True, slots=True)
class Message:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    author_user_id: UUID
    role: MessageRole
    content: str
    status: RunStatus
    client_message_id: UUID | None
    parent_message_id: UUID | None
    retry_of_message_id: UUID | None
    model_provider: str | None
    model_name: str | None
    prompt_version: str | None
    error_code: str | None
    retrieval_run_id: UUID | None
    completion_kind: CompletionKind | None
    grounded: bool
    citation_count: int
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class GenerationRun:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    retrieval_run_id: UUID | None
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class RetrievalRun:
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID | None
    status: RunStatus
    intent: str
    claim_type: str | None
    tax_year: str | None
    query_hash: str
    embedding_provider: str
    embedding_model: str
    retrieval_config_version: str
    collection_name: str
    top_k: int
    score_threshold: Decimal
    candidate_count: int
    selected_count: int
    started_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class CitationSnapshot:
    id: UUID
    tenant_id: UUID
    message_id: UUID
    retrieval_run_id: UUID
    ordinal: int
    document_id: str
    content_hash: str
    chunk_ids: tuple[str, ...]
    title: str
    url: str
    section: str | None
    tax_years: tuple[str, ...]
    source_accessed_at: date
