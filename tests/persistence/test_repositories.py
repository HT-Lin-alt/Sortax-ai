from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from sortax.infrastructure.persistence import Base, PersistenceUnitOfWork
from sortax.infrastructure.persistence.models import (
    ConversationRecord,
    GenerationRunRecord,
    MessageCitationRecord,
    MessageRecord,
    RetrievalRunRecord,
)
from sortax.infrastructure.persistence.repositories import IdempotencyConflictError


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_persistence_flow_enforces_ownership_idempotency_and_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    owner_user_id = uuid4()
    other_user_id = uuid4()
    client_message_id = uuid4()

    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            title="ATO records",
        )
        created_result = await uow.messages.create_user_message(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            client_message_id=client_message_id,
            content="What records do I need?",
        )
        assert created_result is not None
        user_message, created = created_result
        assert created is True

        replay_result = await uow.messages.create_user_message(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            client_message_id=client_message_id,
            content="What records do I need?",
        )
        assert replay_result is not None
        replayed_message, replay_created = replay_result
        assert replayed_message.id == user_message.id
        assert replay_created is False

        with pytest.raises(IdempotencyConflictError):
            await uow.messages.create_user_message(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation.id,
                client_message_id=client_message_id,
                content="Different payload",
            )

        assistant_message = await uow.messages.create_assistant_message(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            parent_message_id=user_message.id,
            content="Keep the relevant records.",
            status="completed",
        )
        assert assistant_message is not None
        retrieval_run = await uow.retrieval_runs.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            intent="ato_document_requirements",
            claim_type="working_from_home",
            tax_year="2025-26",
            query_hash="sha256:query",
            embedding_provider="fake",
            embedding_model="fake-embedding-v1",
            retrieval_config_version="demo-v1",
            collection_name="ato_knowledge_demo",
            top_k=5,
            score_threshold=Decimal("0.500000"),
        )
        assert retrieval_run is not None
        generation_run = await uow.generation_runs.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            retrieval_run_id=retrieval_run.id,
        )
        assert generation_run is not None
        citation = await uow.citations.add(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            message_id=assistant_message.id,
            retrieval_run_id=retrieval_run.id,
            ordinal=1,
            document_id="ato-working-from-home-expenses",
            content_hash="sha256:" + "a" * 64,
            chunk_ids=["chunk-1", "chunk-2"],
            title="Working from home expenses",
            url="https://www.ato.gov.au/example",
            section="Records",
            tax_years=["2025-26"],
            source_accessed_at=date(2026, 10, 4),
        )
        assert citation is not None
        await uow.commit()

    async with PersistenceUnitOfWork(session_factory) as uow:
        assert (
            await uow.conversations.get_owned(
                conversation.id,
                tenant_id=tenant_id,
                owner_user_id=other_user_id,
            )
            is None
        )
        assert (
            await uow.messages.list_owned(
                conversation.id,
                tenant_id=tenant_id,
                owner_user_id=other_user_id,
            )
            == []
        )
        assert (
            await uow.citations.list_for_message(
                assistant_message.id,
                tenant_id=tenant_id,
                owner_user_id=other_user_id,
            )
            == []
        )

        messages = await uow.messages.list_owned(
            conversation.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        snapshots = await uow.citations.list_for_message(
            assistant_message.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        assert {message.role for message in messages} == {"user", "assistant"}
        assert snapshots == [citation]


@pytest.mark.asyncio
async def test_explicit_retry_preserves_original_and_creates_new_generation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        user_result = await uow.messages.create_user_message(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            client_message_id=uuid4(),
            content="Question",
        )
        assert user_result is not None
        user_message, _ = user_result
        original = await uow.messages.create_assistant_message(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            parent_message_id=user_message.id,
            content="Original answer",
            status="completed",
        )
        assert original is not None
        retry = await uow.messages.create_assistant_message(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            parent_message_id=user_message.id,
            retry_of_message_id=original.id,
        )
        assert retry is not None
        run = await uow.generation_runs.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=retry.id,
        )
        assert run is not None
        await uow.commit()

    async with PersistenceUnitOfWork(session_factory) as uow:
        messages = await uow.messages.list_owned(
            conversation.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        assert {message.content for message in messages} == {"Question", "Original answer", ""}
        retry_message = next(message for message in messages if message.content == "")
        assert retry_message.retry_of_message_id == original.id


@pytest.mark.asyncio
async def test_owned_conversation_delete_cascades_all_chat_records(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id, other_user_id = uuid4(), uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        user_result = await uow.messages.create_user_message(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            client_message_id=uuid4(),
            content="Question",
        )
        assert user_result is not None
        user_message, _ = user_result
        assistant = await uow.messages.create_assistant_message(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            parent_message_id=user_message.id,
        )
        assert assistant is not None
        retrieval = await uow.retrieval_runs.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant.id,
            intent="ato_document_requirements",
            claim_type="working_from_home",
            tax_year="2025-26",
            query_hash="hash",
            embedding_provider="fake",
            embedding_model="fake-embedding-v1",
            retrieval_config_version="demo-v1",
            collection_name="ato_knowledge_demo",
            top_k=5,
            score_threshold=Decimal("0.5"),
        )
        assert retrieval is not None
        await uow.generation_runs.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant.id,
            retrieval_run_id=retrieval.id,
        )
        await uow.citations.add(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            message_id=assistant.id,
            retrieval_run_id=retrieval.id,
            ordinal=1,
            document_id="doc",
            content_hash="hash",
            chunk_ids=["chunk"],
            title="Title",
            url="https://www.ato.gov.au/example",
            section=None,
            tax_years=["2025-26"],
            source_accessed_at=date(2026, 10, 4),
        )
        await uow.commit()

    async with PersistenceUnitOfWork(session_factory) as uow:
        unauthorized_delete = await uow.conversations.delete_owned(
            conversation.id,
            tenant_id=tenant_id,
            owner_user_id=other_user_id,
        )
        assert unauthorized_delete is False
        deleted = await uow.conversations.delete_owned(
            conversation.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        assert deleted is True
        await uow.commit()

    async with session_factory() as session:
        for record_type in (
            ConversationRecord,
            MessageRecord,
            RetrievalRunRecord,
            GenerationRunRecord,
            MessageCitationRecord,
        ):
            count = await session.scalar(select(func.count()).select_from(record_type))
            assert count == 0
