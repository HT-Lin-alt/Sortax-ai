import json
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sortax.messages import CompletionKind


class CitationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    document_id: str
    content_hash: str
    chunk_ids: list[str]
    tax_year: str
    accessed_at: date


class GenerationStartedEvent(BaseModel):
    generation_id: UUID
    message_id: UUID


class RetrievalStartedEvent(BaseModel):
    retrieval_run_id: UUID
    claim_type: str
    tax_year: str


class RetrievalCompletedEvent(BaseModel):
    retrieval_run_id: UUID
    status: Literal["completed", "insufficient_evidence", "failed", "cancelled"]
    collection_name: str
    retrieval_config_version: str
    candidate_count: int
    selected_count: int


class MessageDeltaEvent(BaseModel):
    generation_id: UUID
    message_id: UUID
    seq: int
    delta: str


class HeartbeatEvent(BaseModel):
    generation_id: UUID
    emitted_at: datetime


class MessageCompletedEvent(BaseModel):
    generation_id: UUID
    message_id: UUID
    completion_kind: CompletionKind
    grounded: bool
    citations: list[CitationEvent]


class StreamError(BaseModel):
    code: str
    message: str
    request_id: str
    retryable: bool
    retry_after_seconds: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class MessageFailedEvent(BaseModel):
    generation_id: UUID
    message_id: UUID
    error: StreamError


def encode_sse(event_id: int, event: str, payload: BaseModel) -> str:
    data = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\nid: {event_id}\ndata: {data}\n\n"
