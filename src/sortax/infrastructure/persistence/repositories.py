from datetime import date, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from sortax.conversations import Conversation, ConversationStatus
from sortax.infrastructure.persistence.models import (
    ConversationRecord,
    GenerationRunRecord,
    MessageCitationRecord,
    MessageRecord,
    RetrievalRunRecord,
    utc_now,
)
from sortax.messages import (
    CitationSnapshot,
    GenerationRun,
    Message,
    MessageRole,
    RetrievalRun,
    RunStatus,
)


class IdempotencyConflictError(RuntimeError):
    pass


def _conversation(record: ConversationRecord) -> Conversation:
    return Conversation(
        id=record.id,
        tenant_id=record.tenant_id,
        owner_user_id=record.owner_user_id,
        title=record.title,
        status=cast(ConversationStatus, record.status),
        last_message_at=record.last_message_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        expires_at=record.expires_at,
        version=record.version,
    )


def _message(record: MessageRecord) -> Message:
    return Message(
        id=record.id,
        tenant_id=record.tenant_id,
        conversation_id=record.conversation_id,
        author_user_id=record.author_user_id,
        role=cast(MessageRole, record.role),
        content=record.content,
        status=cast(RunStatus, record.status),
        client_message_id=record.client_message_id,
        parent_message_id=record.parent_message_id,
        retry_of_message_id=record.retry_of_message_id,
        model_provider=record.model_provider,
        model_name=record.model_name,
        prompt_version=record.prompt_version,
        error_code=record.error_code,
        retrieval_run_id=record.retrieval_run_id,
        grounded=record.grounded,
        citation_count=record.citation_count,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )


def _retrieval_run(record: RetrievalRunRecord) -> RetrievalRun:
    return RetrievalRun(
        id=record.id,
        tenant_id=record.tenant_id,
        owner_user_id=record.owner_user_id,
        conversation_id=record.conversation_id,
        user_message_id=record.user_message_id,
        assistant_message_id=record.assistant_message_id,
        status=cast(RunStatus, record.status),
        intent=record.intent,
        claim_type=record.claim_type,
        tax_year=record.tax_year,
        query_hash=record.query_hash,
        embedding_provider=record.embedding_provider,
        embedding_model=record.embedding_model,
        retrieval_config_version=record.retrieval_config_version,
        collection_name=record.collection_name,
        top_k=record.top_k,
        score_threshold=record.score_threshold,
        candidate_count=record.candidate_count,
        selected_count=record.selected_count,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _generation_run(record: GenerationRunRecord) -> GenerationRun:
    return GenerationRun(
        id=record.id,
        tenant_id=record.tenant_id,
        conversation_id=record.conversation_id,
        user_message_id=record.user_message_id,
        assistant_message_id=record.assistant_message_id,
        retrieval_run_id=record.retrieval_run_id,
        status=cast(RunStatus, record.status),
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _citation(record: MessageCitationRecord) -> CitationSnapshot:
    return CitationSnapshot(
        id=record.id,
        tenant_id=record.tenant_id,
        message_id=record.message_id,
        retrieval_run_id=record.retrieval_run_id,
        ordinal=record.ordinal,
        document_id=record.document_id,
        content_hash=record.content_hash,
        chunk_ids=tuple(record.chunk_ids),
        title=record.title_snapshot,
        url=record.url_snapshot,
        section=record.section_snapshot,
        tax_years=tuple(record.tax_years_snapshot),
        source_accessed_at=record.source_accessed_at,
    )


class SQLAlchemyConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        title: str = "New conversation",
        conversation_id: UUID | None = None,
    ) -> Conversation:
        now = utc_now()
        record = ConversationRecord(
            id=conversation_id or uuid4(),
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            title=title,
            status="active",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(days=180),
            version=1,
        )
        self._session.add(record)
        await self._session.flush()
        return _conversation(record)

    async def get_owned(
        self, conversation_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> Conversation | None:
        record = await self._session.scalar(
            select(ConversationRecord).where(
                ConversationRecord.id == conversation_id,
                ConversationRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )
        return _conversation(record) if record else None

    async def list_owned(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        status: ConversationStatus | None = None,
        limit: int = 30,
    ) -> list[Conversation]:
        statement = select(ConversationRecord).where(
            ConversationRecord.tenant_id == tenant_id,
            ConversationRecord.owner_user_id == owner_user_id,
        )
        if status is not None:
            statement = statement.where(ConversationRecord.status == status)
        records = (
            await self._session.scalars(
                statement.order_by(
                    ConversationRecord.last_message_at.desc(),
                    ConversationRecord.created_at.desc(),
                    ConversationRecord.id,
                ).limit(limit)
            )
        ).all()
        return [_conversation(record) for record in records]

    async def update_owned(
        self,
        conversation_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        expected_version: int,
        title: str | None = None,
        status: ConversationStatus | None = None,
    ) -> Conversation | None:
        record = await self._session.scalar(
            select(ConversationRecord).where(
                ConversationRecord.id == conversation_id,
                ConversationRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )
        if record is None:
            return None
        if record.version != expected_version:
            raise IdempotencyConflictError("conversation version differs")
        if title is not None:
            record.title = title
        if status is not None:
            record.status = status
        record.version += 1
        record.updated_at = utc_now()
        await self._session.flush()
        return _conversation(record)

    async def delete_owned(
        self, conversation_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> bool:
        result = await self._session.execute(
            delete(ConversationRecord).where(
                ConversationRecord.id == conversation_id,
                ConversationRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )
        return bool(cast(CursorResult[Any], result).rowcount)


class SQLAlchemyMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user_message(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        conversation_id: UUID,
        client_message_id: UUID,
        content: str,
    ) -> tuple[Message, bool] | None:
        existing = await self._session.scalar(
            select(MessageRecord).where(
                MessageRecord.tenant_id == tenant_id,
                MessageRecord.author_user_id == owner_user_id,
                MessageRecord.client_message_id == client_message_id,
            )
        )
        if existing:
            if existing.conversation_id != conversation_id or existing.content != content:
                raise IdempotencyConflictError("idempotency key payload differs")
            return _message(existing), False

        conversation = await self._owned_conversation(
            conversation_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        if conversation is None:
            return None

        now = utc_now()
        record = MessageRecord(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            author_user_id=owner_user_id,
            role="user",
            content=content,
            status="completed",
            client_message_id=client_message_id,
            grounded=False,
            citation_count=0,
            created_at=now,
            completed_at=now,
        )
        conversation.last_message_at = now
        conversation.updated_at = now
        self._session.add(record)
        await self._session.flush()
        return _message(record), True

    async def create_assistant_message(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        conversation_id: UUID,
        parent_message_id: UUID,
        retry_of_message_id: UUID | None = None,
        client_message_id: UUID | None = None,
        content: str = "",
        status: RunStatus = "pending",
    ) -> Message | None:
        conversation = await self._owned_conversation(
            conversation_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        if conversation is None:
            return None
        parent_exists = await self._session.scalar(
            select(MessageRecord.id).where(
                MessageRecord.id == parent_message_id,
                MessageRecord.tenant_id == tenant_id,
                MessageRecord.conversation_id == conversation_id,
            )
        )
        if parent_exists is None:
            return None
        if retry_of_message_id is not None:
            retry_target_exists = await self._session.scalar(
                select(MessageRecord.id).where(
                    MessageRecord.id == retry_of_message_id,
                    MessageRecord.tenant_id == tenant_id,
                    MessageRecord.conversation_id == conversation_id,
                    MessageRecord.role == "assistant",
                )
            )
            if retry_target_exists is None:
                return None

        now = utc_now()
        record = MessageRecord(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            author_user_id=owner_user_id,
            role="assistant",
            content=content,
            status=status,
            parent_message_id=parent_message_id,
            retry_of_message_id=retry_of_message_id,
            client_message_id=client_message_id,
            grounded=False,
            citation_count=0,
            created_at=now,
            completed_at=now if status == "completed" else None,
        )
        conversation.last_message_at = now
        conversation.updated_at = now
        self._session.add(record)
        await self._session.flush()
        return _message(record)

    async def list_owned(
        self, conversation_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> list[Message]:
        records = (
            await self._session.scalars(
                select(MessageRecord)
                .join(
                    ConversationRecord,
                    ConversationRecord.id == MessageRecord.conversation_id,
                )
                .where(
                    MessageRecord.conversation_id == conversation_id,
                    MessageRecord.tenant_id == tenant_id,
                    ConversationRecord.tenant_id == tenant_id,
                    ConversationRecord.owner_user_id == owner_user_id,
                )
                .order_by(MessageRecord.created_at, MessageRecord.id)
            )
        ).all()
        return [_message(record) for record in records]

    async def get_owned(
        self, message_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> Message | None:
        record = await self._owned_message_record(
            message_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        return _message(record) if record else None

    async def get_by_client_message_id(
        self,
        client_message_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
    ) -> Message | None:
        record = await self._session.scalar(
            select(MessageRecord)
            .join(ConversationRecord, ConversationRecord.id == MessageRecord.conversation_id)
            .where(
                MessageRecord.client_message_id == client_message_id,
                MessageRecord.tenant_id == tenant_id,
                MessageRecord.author_user_id == owner_user_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )
        return _message(record) if record else None

    async def set_assistant_state(
        self,
        message_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        status: RunStatus,
        content: str,
        model_provider: str,
        model_name: str,
        prompt_version: str,
        retrieval_run_id: UUID | None = None,
        error_code: str | None = None,
    ) -> Message | None:
        record = await self._owned_message_record(
            message_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        if record is None or record.role != "assistant":
            return None
        record.status = status
        record.content = content
        record.model_provider = model_provider
        record.model_name = model_name
        record.prompt_version = prompt_version
        record.retrieval_run_id = retrieval_run_id
        record.error_code = error_code
        record.completed_at = utc_now() if status in {"completed", "failed", "cancelled"} else None
        await self._session.flush()
        return _message(record)

    async def _owned_message_record(
        self, message_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> MessageRecord | None:
        return await self._session.scalar(
            select(MessageRecord)
            .join(ConversationRecord, ConversationRecord.id == MessageRecord.conversation_id)
            .where(
                MessageRecord.id == message_id,
                MessageRecord.tenant_id == tenant_id,
                ConversationRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )

    async def _owned_conversation(
        self, conversation_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> ConversationRecord | None:
        return await self._session.scalar(
            select(ConversationRecord).where(
                ConversationRecord.id == conversation_id,
                ConversationRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )


class SQLAlchemyRetrievalRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        conversation_id: UUID,
        user_message_id: UUID,
        assistant_message_id: UUID | None,
        intent: str,
        claim_type: str | None,
        tax_year: str | None,
        query_hash: str,
        embedding_provider: str,
        embedding_model: str,
        retrieval_config_version: str,
        collection_name: str,
        top_k: int,
        score_threshold: Decimal,
    ) -> RetrievalRun | None:
        owned = await self._session.scalar(
            select(ConversationRecord.id).where(
                ConversationRecord.id == conversation_id,
                ConversationRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )
        if owned is None:
            return None
        message_ids = {user_message_id}
        if assistant_message_id is not None:
            message_ids.add(assistant_message_id)
        owned_message_count = len(
            (
                await self._session.scalars(
                    select(MessageRecord.id).where(
                        MessageRecord.id.in_(message_ids),
                        MessageRecord.tenant_id == tenant_id,
                        MessageRecord.conversation_id == conversation_id,
                    )
                )
            ).all()
        )
        if owned_message_count != len(message_ids):
            return None
        record = RetrievalRunRecord(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            status="pending",
            intent=intent,
            claim_type=claim_type,
            tax_year=tax_year,
            query_hash=query_hash,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            retrieval_config_version=retrieval_config_version,
            collection_name=collection_name,
            top_k=top_k,
            score_threshold=score_threshold,
            candidate_count=0,
            selected_count=0,
        )
        self._session.add(record)
        await self._session.flush()
        return _retrieval_run(record)

    async def finish(
        self,
        retrieval_run_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        status: RunStatus,
        candidate_count: int,
        selected_count: int,
        failure_reason: str | None = None,
    ) -> RetrievalRun | None:
        record = await self._session.scalar(
            select(RetrievalRunRecord).where(
                RetrievalRunRecord.id == retrieval_run_id,
                RetrievalRunRecord.tenant_id == tenant_id,
                RetrievalRunRecord.owner_user_id == owner_user_id,
            )
        )
        if record is None:
            return None
        record.status = status
        record.candidate_count = candidate_count
        record.selected_count = selected_count
        record.failure_reason = failure_reason
        record.finished_at = utc_now()
        await self._session.flush()
        return _retrieval_run(record)


class SQLAlchemyGenerationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        conversation_id: UUID,
        user_message_id: UUID,
        assistant_message_id: UUID,
        retrieval_run_id: UUID | None = None,
    ) -> GenerationRun | None:
        owned = await self._session.scalar(
            select(ConversationRecord.id).where(
                ConversationRecord.id == conversation_id,
                ConversationRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )
        message_ids = {user_message_id, assistant_message_id}
        owned_message_count = len(
            (
                await self._session.scalars(
                    select(MessageRecord.id).where(
                        MessageRecord.id.in_(message_ids),
                        MessageRecord.tenant_id == tenant_id,
                        MessageRecord.conversation_id == conversation_id,
                    )
                )
            ).all()
        )
        if owned is None or owned_message_count != len(message_ids):
            return None
        if retrieval_run_id is not None:
            retrieval_exists = await self._session.scalar(
                select(RetrievalRunRecord.id).where(
                    RetrievalRunRecord.id == retrieval_run_id,
                    RetrievalRunRecord.tenant_id == tenant_id,
                    RetrievalRunRecord.conversation_id == conversation_id,
                )
            )
            if retrieval_exists is None:
                return None
        record = GenerationRunRecord(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            retrieval_run_id=retrieval_run_id,
            status="pending",
        )
        self._session.add(record)
        await self._session.flush()
        return _generation_run(record)

    async def find_for_user_message(
        self,
        user_message_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
    ) -> GenerationRun | None:
        record = await self._session.scalar(
            select(GenerationRunRecord)
            .join(ConversationRecord, ConversationRecord.id == GenerationRunRecord.conversation_id)
            .where(
                GenerationRunRecord.user_message_id == user_message_id,
                GenerationRunRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
            .order_by(GenerationRunRecord.started_at.desc())
        )
        return _generation_run(record) if record else None

    async def find_for_assistant_message(
        self,
        assistant_message_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
    ) -> GenerationRun | None:
        record = await self._session.scalar(
            select(GenerationRunRecord)
            .join(ConversationRecord, ConversationRecord.id == GenerationRunRecord.conversation_id)
            .where(
                GenerationRunRecord.assistant_message_id == assistant_message_id,
                GenerationRunRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )
        return _generation_run(record) if record else None

    async def get_owned(
        self,
        generation_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
    ) -> GenerationRun | None:
        record = await self._owned_record(
            generation_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        return _generation_run(record) if record else None

    async def find_active_for_conversation(
        self,
        conversation_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
    ) -> GenerationRun | None:
        record = await self._session.scalar(
            select(GenerationRunRecord)
            .join(ConversationRecord, ConversationRecord.id == GenerationRunRecord.conversation_id)
            .where(
                GenerationRunRecord.conversation_id == conversation_id,
                GenerationRunRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
                GenerationRunRecord.status.in_(("pending", "streaming")),
            )
            .order_by(GenerationRunRecord.started_at.desc())
        )
        return _generation_run(record) if record else None

    async def attach_retrieval(
        self,
        generation_id: UUID,
        retrieval_run_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
    ) -> GenerationRun | None:
        record = await self._owned_record(
            generation_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        if record is None:
            return None
        retrieval_exists = await self._session.scalar(
            select(RetrievalRunRecord.id).where(
                RetrievalRunRecord.id == retrieval_run_id,
                RetrievalRunRecord.tenant_id == tenant_id,
                RetrievalRunRecord.owner_user_id == owner_user_id,
                RetrievalRunRecord.conversation_id == record.conversation_id,
            )
        )
        if retrieval_exists is None:
            return None
        record.retrieval_run_id = retrieval_run_id
        await self._session.flush()
        return _generation_run(record)

    async def set_status(
        self,
        generation_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        status: RunStatus,
        failure_reason: str | None = None,
        cancel_requested: bool = False,
    ) -> GenerationRun | None:
        record = await self._owned_record(
            generation_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        if record is None:
            return None
        now = utc_now()
        record.status = status
        if status == "streaming" and record.first_token_at is None:
            record.first_token_at = now
        if status in {"completed", "failed", "cancelled"}:
            record.finished_at = now
        if cancel_requested:
            record.cancel_requested_at = now
        record.failure_reason = failure_reason
        await self._session.flush()
        return _generation_run(record)

    async def _owned_record(
        self,
        generation_id: UUID,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
    ) -> GenerationRunRecord | None:
        return await self._session.scalar(
            select(GenerationRunRecord)
            .join(ConversationRecord, ConversationRecord.id == GenerationRunRecord.conversation_id)
            .where(
                GenerationRunRecord.id == generation_id,
                GenerationRunRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )


class SQLAlchemyCitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        message_id: UUID,
        retrieval_run_id: UUID,
        ordinal: int,
        document_id: str,
        content_hash: str,
        chunk_ids: list[str],
        title: str,
        url: str,
        section: str | None,
        tax_years: list[str],
        source_accessed_at: date,
    ) -> CitationSnapshot | None:
        message = await self._session.scalar(
            select(MessageRecord)
            .join(ConversationRecord, ConversationRecord.id == MessageRecord.conversation_id)
            .where(
                MessageRecord.id == message_id,
                MessageRecord.tenant_id == tenant_id,
                ConversationRecord.tenant_id == tenant_id,
                ConversationRecord.owner_user_id == owner_user_id,
            )
        )
        if message is None:
            return None
        retrieval_exists = await self._session.scalar(
            select(RetrievalRunRecord.id).where(
                RetrievalRunRecord.id == retrieval_run_id,
                RetrievalRunRecord.tenant_id == tenant_id,
                RetrievalRunRecord.owner_user_id == owner_user_id,
                RetrievalRunRecord.conversation_id == message.conversation_id,
            )
        )
        if retrieval_exists is None:
            return None
        record = MessageCitationRecord(
            tenant_id=tenant_id,
            message_id=message_id,
            retrieval_run_id=retrieval_run_id,
            ordinal=ordinal,
            document_id=document_id,
            content_hash=content_hash,
            chunk_ids=chunk_ids,
            title_snapshot=title,
            url_snapshot=url,
            section_snapshot=section,
            tax_years_snapshot=tax_years,
            source_accessed_at=source_accessed_at,
        )
        self._session.add(record)
        message.citation_count += 1
        message.grounded = True
        message.retrieval_run_id = retrieval_run_id
        await self._session.flush()
        return _citation(record)

    async def list_for_message(
        self, message_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> list[CitationSnapshot]:
        records = (
            await self._session.scalars(
                select(MessageCitationRecord)
                .join(MessageRecord, MessageRecord.id == MessageCitationRecord.message_id)
                .join(ConversationRecord, ConversationRecord.id == MessageRecord.conversation_id)
                .where(
                    MessageCitationRecord.message_id == message_id,
                    MessageCitationRecord.tenant_id == tenant_id,
                    ConversationRecord.tenant_id == tenant_id,
                    ConversationRecord.owner_user_id == owner_user_id,
                )
                .order_by(MessageCitationRecord.ordinal)
            )
        ).all()
        return [_citation(record) for record in records]
