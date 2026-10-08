import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from sortax.api.errors import NotFoundError
from sortax.chat import ChatCoordinator, InMemoryCancellationStore
from sortax.infrastructure.persistence import Base, PersistenceUnitOfWork
from sortax.infrastructure.persistence.models import GenerationRunRecord, MessageRecord
from sortax.intent import FakeIntentClassifier
from sortax.llm_gateway import FakeLLMProvider, LLMStreamChunk
from sortax.prompting import LLMRequest
from sortax.rag import FakeRetriever, GroundingContext, RetrievalPlan


class PausingLLM:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    @property
    def provider_name(self) -> str:
        return "fake-pausing"

    @property
    def model_name(self) -> str:
        return "fake-pausing-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        yield LLMStreamChunk(delta="partial")
        await self.release.wait()
        yield LLMStreamChunk(delta=" remainder")


class DelayedFirstTokenLLM:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    @property
    def provider_name(self) -> str:
        return "fake-delayed"

    @property
    def model_name(self) -> str:
        return "fake-delayed-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        await asyncio.sleep(self.delay)
        yield LLMStreamChunk(delta="hello")


class BlockingRetriever(FakeRetriever):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def retrieve(self, plan: RetrievalPlan) -> GroundingContext:
        del plan
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("unreachable")


class CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def provider_name(self) -> str:
        return "fake-counting"

    @property
    def model_name(self) -> str:
        return "fake-counting-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        self.calls += 1
        yield LLMStreamChunk(delta="must not run")


class MetadataLLM:
    @property
    def provider_name(self) -> str:
        return "fake-metadata"

    @property
    def model_name(self) -> str:
        return "fake-metadata-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        yield LLMStreamChunk(delta="hello")
        yield LLMStreamChunk(
            provider_request_id="provider-request-1",
            input_tokens=7,
            output_tokens=1,
        )


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
    coordinator = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=FakeRetriever(),
        llm=llm,
    )
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
    coordinator = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=FakeRetriever(),
        llm=llm,
    )
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


@pytest.mark.asyncio
async def test_heartbeat_is_emitted_while_waiting_for_first_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        await uow.commit()
    coordinator = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=FakeRetriever(),
        llm=DelayedFirstTokenLLM(0.06),
        first_token_timeout_seconds=0.2,
        heartbeat_seconds=0.02,
        max_duration_seconds=1,
        cancellation_poll_seconds=0.005,
    )
    session = await coordinator.prepare(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation.id,
        client_message_id=uuid4(),
        content="Hello",
    )

    events = [event async for event in coordinator.stream(session, request_id=str(uuid4()))]

    assert any("event: heartbeat" in event for event in events)
    assert any("event: message.delta" in event for event in events)
    assert "event: message.completed" in events[-1]


@pytest.mark.asyncio
async def test_first_token_timeout_fails_and_settles_persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        await uow.commit()
    coordinator = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=FakeRetriever(),
        llm=DelayedFirstTokenLLM(1),
        first_token_timeout_seconds=0.04,
        heartbeat_seconds=0.01,
        max_duration_seconds=0.2,
        cancellation_poll_seconds=0.005,
    )
    session = await coordinator.prepare(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation.id,
        client_message_id=uuid4(),
        content="Hello",
    )

    events = [event async for event in coordinator.stream(session, request_id=str(uuid4()))]

    assert "event: message.failed" in events[-1]
    assert '"code":"provider_timeout"' in events[-1]
    generation = await coordinator.get_generation(
        session.generation.id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
    )
    assert generation.status == "failed"


@pytest.mark.asyncio
async def test_total_timeout_preserves_partial_content(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        await uow.commit()
    coordinator = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=FakeRetriever(),
        llm=PausingLLM(),
        first_token_timeout_seconds=0.02,
        heartbeat_seconds=0.01,
        max_duration_seconds=0.06,
        cancellation_poll_seconds=0.005,
    )
    session = await coordinator.prepare(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation.id,
        client_message_id=uuid4(),
        content="Hello",
    )

    events = [event async for event in coordinator.stream(session, request_id=str(uuid4()))]

    assert '"code":"provider_timeout"' in events[-1]
    async with PersistenceUnitOfWork(session_factory) as uow:
        messages = await uow.messages.list_owned(
            conversation.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
    assistant = next(message for message in messages if message.role == "assistant")
    assert assistant.status == "failed"
    assert assistant.content == "partial"


@pytest.mark.asyncio
async def test_shared_cancellation_stops_retrieval_before_llm(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        await uow.commit()
    store = InMemoryCancellationStore()
    retriever = BlockingRetriever()
    llm = CountingLLM()
    coordinator_a = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=retriever,
        llm=llm,
        cancellation_store=store,
        cancellation_poll_seconds=0.005,
    )
    coordinator_b = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=FakeRetriever(),
        llm=FakeLLMProvider(),
        cancellation_store=store,
    )
    session = await coordinator_a.prepare(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation.id,
        client_message_id=uuid4(),
        content="What car records are needed for 2025-26?",
    )
    streamed: list[str] = []

    async def consume() -> None:
        async for streamed_event in coordinator_a.stream(session, request_id=str(uuid4())):
            streamed.append(streamed_event)

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(retriever.started.wait(), timeout=1)
    await coordinator_b.cancel(
        session.generation.id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
    )
    await asyncio.wait_for(consumer, timeout=1)

    assert retriever.cancelled.is_set()
    assert llm.calls == 0
    assert not any("event: message.completed" in event for event in streamed)
    generation = await coordinator_a.get_generation(
        session.generation.id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
    )
    assert generation.status == "cancelled"


@pytest.mark.asyncio
async def test_unauthorized_cancel_does_not_publish_shared_signal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        await uow.commit()
    store = InMemoryCancellationStore()
    coordinator = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=FakeRetriever(),
        llm=FakeLLMProvider(),
        cancellation_store=store,
    )
    session = await coordinator.prepare(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation.id,
        client_message_id=uuid4(),
        content="hello",
    )

    with pytest.raises(NotFoundError):
        await coordinator.cancel(
            session.generation.id,
            tenant_id=tenant_id,
            owner_user_id=uuid4(),
        )

    assert not await store.is_requested(session.generation.id)


@pytest.mark.asyncio
async def test_provider_usage_and_first_token_metadata_are_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        await uow.commit()
    coordinator = ChatCoordinator(
        session_factory,
        intent_classifier=FakeIntentClassifier(),
        retriever=FakeRetriever(),
        llm=MetadataLLM(),
    )
    chat_session = await coordinator.prepare(
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        conversation_id=conversation.id,
        client_message_id=uuid4(),
        content="hello",
    )

    _events = [item async for item in coordinator.stream(chat_session, request_id=str(uuid4()))]

    async with session_factory() as database_session:
        message = await database_session.scalar(
            select(MessageRecord).where(MessageRecord.id == chat_session.assistant_message.id)
        )
        generation = await database_session.scalar(
            select(GenerationRunRecord).where(GenerationRunRecord.id == chat_session.generation.id)
        )
    assert message is not None
    assert message.input_tokens == 7
    assert message.output_tokens == 1
    assert generation is not None
    assert generation.provider_request_id == "provider-request-1"
    assert generation.first_token_at is not None
