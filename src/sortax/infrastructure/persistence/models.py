from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ConversationRecord(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="ck_conversations_status"),
        Index(
            "ix_conversations_owner_last_message",
            "tenant_id",
            "owner_user_id",
            "last_message_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="ck_messages_role"),
        CheckConstraint(
            "status IN ('pending', 'streaming', 'completed', 'failed', 'cancelled')",
            name="ck_messages_status",
        ),
        UniqueConstraint(
            "tenant_id",
            "author_user_id",
            "client_message_id",
            name="uq_messages_idempotency",
        ),
        Index(
            "ix_messages_conversation_created",
            "tenant_id",
            "conversation_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    client_message_id: Mapped[UUID | None] = mapped_column(Uuid)
    parent_message_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="SET NULL"),
    )
    retry_of_message_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="SET NULL"),
    )
    model_provider: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    retrieval_run_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    completion_kind: Mapped[str | None] = mapped_column(String(32))
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetrievalRunRecord(Base):
    __tablename__ = "retrieval_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'streaming', 'completed', 'failed', 'cancelled')",
            name="ck_retrieval_runs_status",
        ),
        Index("ix_retrieval_runs_conversation", "tenant_id", "conversation_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_message_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="SET NULL"),
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    intent: Mapped[str] = mapped_column(String(100), nullable=False)
    claim_type: Mapped[str | None] = mapped_column(String(100))
    tax_year: Mapped[str | None] = mapped_column(String(7))
    query_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    retrieval_config_version: Mapped[str] = mapped_column(String(100), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(200), nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    score_threshold: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(200))


class GenerationRunRecord(Base):
    __tablename__ = "generation_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'streaming', 'completed', 'failed', 'cancelled')",
            name="ck_generation_runs_status",
        ),
        Index("ix_generation_runs_conversation", "tenant_id", "conversation_id", "started_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_message_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    assistant_message_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    retrieval_run_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("retrieval_runs.id", ondelete="SET NULL"),
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    first_token_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(200))


class MessageCitationRecord(Base):
    __tablename__ = "message_citations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", "ordinal", name="uq_message_citations_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    message_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    retrieval_run_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("retrieval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    document_id: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    url_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    section_snapshot: Mapped[str | None] = mapped_column(String(500))
    tax_years_snapshot: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_accessed_at: Mapped[date] = mapped_column(Date, nullable=False)
