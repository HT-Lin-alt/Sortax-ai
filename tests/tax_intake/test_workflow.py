import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from sortax.chat import InMemoryCancellationStore
from sortax.infrastructure.persistence import Base, PersistenceUnitOfWork
from sortax.infrastructure.persistence.repositories import OptimisticLockError
from sortax.llm_gateway import FakeLLMProvider, LLMStreamChunk
from sortax.prompting import LLMRequest
from sortax.rag import ChecklistGroundingContext, ChecklistRetrievalPlan, FakeRetriever
from sortax.tax_intake.questionnaire import current_step
from sortax.tax_intake.service import TaxWorkflowCoordinator


class CancellableChecklistRetriever(FakeRetriever):
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def retrieve_checklist(self, plan: ChecklistRetrievalPlan) -> ChecklistGroundingContext:
        self.calls += 1
        if self.calls > 1:
            return await super().retrieve_checklist(plan)
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        raise AssertionError("unreachable")


class PausingSummaryLLM:
    def __init__(self) -> None:
        self.first_chunk = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def provider_name(self) -> str:
        return "fake-pausing-summary"

    @property
    def model_name(self) -> str:
        return "fake-pausing-summary-v1"

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        del request
        yield LLMStreamChunk(delta="Partial tax summary")
        self.first_chunk.set()
        await self.release.wait()
        yield LLMStreamChunk(delta=" completed.")


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


async def _seed_completed_questionnaire(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID, UUID, int]:
    tenant_id, owner_user_id = uuid4(), uuid4()
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=tenant_id, owner_user_id=owner_user_id
        )
        result = await uow.tax_intakes.create_or_get(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation.id,
            template_version="limited-tax-2025-26-v1",
            tax_year="2025-26",
        )
        assert result is not None
        intake, _created = result
        answers: dict[str, list[str]] = {}
        version = intake.version
        for question_key, selected_options in {
            "first_tax_return": ["no"],
            "work_expenses": ["working_from_home"],
            "income_sources": ["salary_wages"],
        }.items():
            answers[question_key] = selected_options
            updated = await uow.tax_intakes.save_answer(
                intake.id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                question_key=question_key,
                option_codes=selected_options,
                current_step=current_step(answers),
                expected_version=version,
            )
            assert updated is not None
            version = updated.version
        await uow.commit()
    return intake.id, tenant_id, owner_user_id, version


async def _consume(stream: AsyncIterator[str]) -> list[str]:
    return [event async for event in stream]


@pytest.mark.asyncio
async def test_concurrent_complete_claim_uses_intake_version(tmp_path: Path) -> None:
    database_path = (tmp_path / "phase5d-concurrency.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        intake_id, tenant_id, owner_user_id, version = await _seed_completed_questionnaire(factory)

        async def claim() -> str:
            try:
                async with PersistenceUnitOfWork(factory) as uow:
                    updated = await uow.tax_intakes.transition(
                        intake_id,
                        tenant_id=tenant_id,
                        owner_user_id=owner_user_id,
                        expected={"questionnaire_active", "questionnaire_completed"},
                        status="questionnaire_completed",
                        expected_version=version,
                    )
                    assert updated is not None
                    await uow.commit()
                return "claimed"
            except OptimisticLockError:
                return "conflict"

        results = await asyncio.gather(claim(), claim())
        assert sorted(results) == ["claimed", "conflict"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cancelled_checklist_can_retry_with_structured_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    intake_id, tenant_id, owner_user_id, version = await _seed_completed_questionnaire(
        session_factory
    )
    store = InMemoryCancellationStore()
    retriever = CancellableChecklistRetriever()
    coordinator = TaxWorkflowCoordinator(
        session_factory,
        retriever=retriever,
        llm=FakeLLMProvider(),
        cancellation_store=store,
        cancellation_poll_seconds=0.005,
    )
    session, intake = await coordinator.prepare_complete(
        intake_id=intake_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        client_request_id=uuid4(),
        expected_version=version,
    )
    task = asyncio.create_task(
        _consume(coordinator.stream_complete(session, intake, request_id="cancel-checklist"))
    )
    await asyncio.wait_for(retriever.started.wait(), timeout=1)
    await store.request(session.generation.id)
    streamed = await asyncio.wait_for(task, timeout=1)

    assert retriever.cancelled.is_set()
    assert not any("event: message.completed" in event for event in streamed)
    async with PersistenceUnitOfWork(session_factory) as uow:
        cancelled_message = await uow.messages.get_owned(
            session.assistant_message.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        restored = await uow.tax_intakes.get_owned(
            intake_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
    assert cancelled_message is not None
    assert cancelled_message.status == "cancelled"
    assert cancelled_message.content_type == "document_checklist"
    assert restored is not None
    assert restored.workflow_status == "questionnaire_completed"

    retry_session, retry_intake = await coordinator.prepare_complete(
        intake_id=intake_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        client_request_id=uuid4(),
        expected_version=restored.version,
        retry_of_message_id=cancelled_message.id,
    )
    retried = await _consume(
        coordinator.stream_complete(retry_session, retry_intake, request_id="retry-checklist")
    )
    assert any('"content_type":"document_checklist"' in event for event in retried)
    async with PersistenceUnitOfWork(session_factory) as uow:
        retry_message = await uow.messages.get_owned(
            retry_session.assistant_message.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
    assert retry_message is not None
    assert retry_message.status == "completed"
    assert retry_message.retry_of_message_id == cancelled_message.id
    assert retry_message.structured_content is not None


@pytest.mark.asyncio
async def test_cancelled_tax_summary_can_retry_and_reuse_citations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    intake_id, tenant_id, owner_user_id, version = await _seed_completed_questionnaire(
        session_factory
    )
    store = InMemoryCancellationStore()
    llm = PausingSummaryLLM()
    coordinator = TaxWorkflowCoordinator(
        session_factory,
        retriever=FakeRetriever(),
        llm=llm,
        cancellation_store=store,
        cancellation_poll_seconds=0.005,
    )
    checklist_session, checklist_intake = await coordinator.prepare_complete(
        intake_id=intake_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        client_request_id=uuid4(),
        expected_version=version,
    )
    await _consume(
        coordinator.stream_complete(
            checklist_session, checklist_intake, request_id="prepare-summary"
        )
    )
    async with PersistenceUnitOfWork(session_factory) as uow:
        ready = await uow.tax_intakes.get_owned(
            intake_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
    assert ready is not None
    summary_session, summary_intake = await coordinator.prepare_summary(
        intake_id=intake_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        client_request_id=uuid4(),
        requested=True,
        expected_version=ready.version,
    )
    task = asyncio.create_task(
        _consume(
            coordinator.stream_summary(
                summary_session,
                summary_intake,
                requested=True,
                request_id="cancel-summary",
            )
        )
    )
    await asyncio.wait_for(llm.first_chunk.wait(), timeout=1)
    await store.request(summary_session.generation.id)
    cancelled_events = await asyncio.wait_for(task, timeout=1)
    assert not any("event: message.completed" in event for event in cancelled_events)

    async with PersistenceUnitOfWork(session_factory) as uow:
        cancelled_message = await uow.messages.get_owned(
            summary_session.assistant_message.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        restored = await uow.tax_intakes.get_owned(
            intake_id, tenant_id=tenant_id, owner_user_id=owner_user_id
        )
    assert cancelled_message is not None
    assert cancelled_message.status == "cancelled"
    assert cancelled_message.content == "Partial tax summary"
    assert cancelled_message.content_type == "tax_summary"
    assert restored is not None
    assert restored.workflow_status == "awaiting_summary_confirmation"

    llm.release.set()
    retry_session, retry_intake = await coordinator.prepare_summary(
        intake_id=intake_id,
        tenant_id=tenant_id,
        owner_user_id=owner_user_id,
        client_request_id=uuid4(),
        requested=True,
        expected_version=restored.version,
        retry_of_message_id=cancelled_message.id,
    )
    retried = await _consume(
        coordinator.stream_summary(
            retry_session,
            retry_intake,
            requested=True,
            request_id="retry-summary",
        )
    )
    assert any('"content_type":"tax_summary"' in event for event in retried)
    async with PersistenceUnitOfWork(session_factory) as uow:
        retry_message = await uow.messages.get_owned(
            retry_session.assistant_message.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        checklist_citations = await uow.citations.list_for_message(
            checklist_session.assistant_message.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        summary_citations = await uow.citations.list_for_message(
            retry_session.assistant_message.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
    assert retry_message is not None
    assert retry_message.status == "completed"
    assert retry_message.retry_of_message_id == cancelled_message.id
    assert [(item.document_id, item.content_hash) for item in summary_citations] == [
        (item.document_id, item.content_hash) for item in checklist_citations
    ]
