from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sortax.messages import CitationSnapshot, GenerationRun, Message
from sortax.prompting import HistoryMessage


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)


class UpdateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "archived"] | None = None
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateConversationRequest":
        if self.title is None and self.status is None:
            raise ValueError("title or status is required")
        return self


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: UUID
    content: str = Field(min_length=1, max_length=16_384)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class RetryMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_message_id: UUID


class CitationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    url: str
    document_id: str
    content_hash: str
    chunk_ids: list[str]
    tax_year: str
    accessed_at: date


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str
    status: Literal["active", "archived"]
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    version: int


class ConversationPageResponse(BaseModel):
    items: list[ConversationResponse]
    next_cursor: str | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    status: Literal["pending", "streaming", "completed", "failed", "cancelled"]
    parent_message_id: UUID | None = None
    retry_of_message_id: UUID | None = None
    model_provider: str | None = None
    model_name: str | None = None
    retrieval_run_id: UUID | None = None
    grounded: bool
    citation_count: int
    citations: list[CitationResponse]
    created_at: datetime
    completed_at: datetime | None = None


class MessagePageResponse(BaseModel):
    items: list[MessageResponse]
    next_cursor: str | None = None


class GenerationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    assistant_message_id: UUID
    status: Literal["pending", "streaming", "completed", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class ChatSession:
    tenant_id: UUID
    owner_user_id: UUID
    conversation_id: UUID
    user_message: Message
    assistant_message: Message
    generation: GenerationRun
    user_content: str
    history: tuple[HistoryMessage, ...]
    replay: bool = False
    replay_citations: tuple[CitationSnapshot, ...] = ()


def generation_response(run: GenerationRun) -> GenerationResponse:
    return GenerationResponse(
        id=run.id,
        conversation_id=run.conversation_id,
        assistant_message_id=run.assistant_message_id,
        status=run.status,
    )
