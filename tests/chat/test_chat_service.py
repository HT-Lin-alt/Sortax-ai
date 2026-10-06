import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from sortax.chat import ChatCoordinator
from sortax.infrastructure.persistence import Base, PersistenceUnitOfWork
from sortax.prompting import LLMRequest
from sortax.rag import FakeRetriever


class PausingLLM:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    @property
    def provider_name(self) -> str:
        return "fake-pausing"

    @property
    def model_name(self) -> str:
        return "fake-pausing-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        del request
        yield "partial"
        await self.release.wait()
        yield " remainder"


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
async def test_explicit_cancel_persists_partial_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        await uow.commit()
    llm = PausingLLM()
    coordinator = ChatCoordinator(session_factory, retriever=FakeRetriever(), llm=llm)
    session = await coordinator.prepare(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation.id,
        client_message_id=uuid4(),
        content="What car records do I need?",
    )
    delta_seen = asyncio.Event()
    streamed: list[str] = []

    async def consume() -> None:
        async for event_text in coordinator.stream(session, request_id=str(uuid4())):
            streamed.append(event_text)
            if "event: message.delta" in event_text:
                delta_seen.set()

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(delta_seen.wait(), timeout=2)
    cancelled = await coordinator.cancel(
        session.generation.id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
    )
    llm.release.set()
    await asyncio.wait_for(consumer, timeout=2)

    assert cancelled.status == "cancelled"
    assert not any("event: message.completed" in item for item in streamed)
    async with PersistenceUnitOfWork(session_factory) as uow:
        messages = await uow.messages.list_owned(
            conversation.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
    assistant = next(message for message in messages if message.role == "assistant")
    assert assistant.status == "cancelled"
    assert assistant.content == "partial"


@pytest.mark.asyncio
async def test_stream_disconnect_marks_generation_cancelled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        await uow.commit()
    llm = PausingLLM()
    coordinator = ChatCoordinator(session_factory, retriever=FakeRetriever(), llm=llm)
    session = await coordinator.prepare(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation.id,
        client_message_id=uuid4(),
        content="What car records do I need?",
    )
    delta_seen = asyncio.Event()

    async def consume() -> None:
        async for event_text in coordinator.stream(session, request_id=str(uuid4())):
            if "event: message.delta" in event_text:
                delta_seen.set()

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(delta_seen.wait(), timeout=2)
    consumer.cancel()
    with suppress(asyncio.CancelledError):
        await consumer

    generation = await coordinator.get_generation(
        session.generation.id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
    )
    assert generation.status == "cancelled"
