import asyncio
import hashlib
from collections.abc import AsyncIterator, Awaitable
from contextlib import suppress
from decimal import Decimal
from typing import TypeVar
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sortax.api.errors import ConflictError, NotFoundError, ServiceUnavailableError
from sortax.chat.cancellation import CancellationStore, InMemoryCancellationStore
from sortax.chat.events import (
    CitationEvent,
    GenerationStartedEvent,
    MessageCompletedEvent,
    MessageDeltaEvent,
    RetrievalCompletedEvent,
    RetrievalStartedEvent,
    encode_sse,
)
from sortax.chat.models import ChatSession
from sortax.infrastructure.persistence import PersistenceUnitOfWork
from sortax.infrastructure.persistence.repositories import (
    IdempotencyConflictError,
    OptimisticLockError,
)
from sortax.llm_gateway import LLMProvider, LLMProviderError
from sortax.messages import CitationSnapshot
from sortax.prompting import build_tax_summary_request
from sortax.rag import ChecklistGroundingContext, RetrievalUnavailableError, Retriever
from sortax.tax_intake.models import (
    ChecklistItemContent,
    DocumentChecklistContent,
    SummaryConfirmationContent,
    TaxIntakeSession,
    TaxSummaryContent,
    TaxSummarySection,
)
from sortax.tax_intake.questionnaire import require_complete, selected_claim_types

CHECKLIST_VERSION = "phase-5d-checklist-v1"
T = TypeVar("T")


class TaxGenerationCancelled(RuntimeError):
    pass


class TaxWorkflowCoordinator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retriever: Retriever,
        llm: LLMProvider,
        cancellation_store: CancellationStore | None = None,
        cancellation_poll_seconds: float = 0.5,
    ) -> None:
        self._session_factory = session_factory
        self._retriever = retriever
        self._llm = llm
        self._cancellation_store = cancellation_store or InMemoryCancellationStore()
        self._cancellation_poll_seconds = cancellation_poll_seconds

    async def prepare_summary(
        self,
        *,
        intake_id: UUID,
        tenant_id: UUID,
        owner_user_id: UUID,
        client_request_id: UUID,
        requested: bool,
        expected_version: int,
        retry_of_message_id: UUID | None = None,
    ) -> tuple[ChatSession, TaxIntakeSession]:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            intake = await uow.tax_intakes.get_owned(
                intake_id, tenant_id=tenant_id, owner_user_id=owner_user_id
            )
            if intake is None:
                raise NotFoundError()
            trigger_content = f"tax-summary:{intake.id}:requested={str(requested).lower()}"
            existing = await uow.messages.get_by_client_message_id(
                client_request_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if existing is None and intake.workflow_status != "awaiting_summary_confirmation":
                raise ConflictError(
                    "invalid_workflow_state", "The intake is not awaiting summary confirmation"
                )
            if existing is None and intake.version != expected_version:
                raise ConflictError(
                    "version_conflict", "The tax intake version is stale; reload and retry"
                )
            try:
                trigger_result = await uow.messages.create_system_trigger(
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    conversation_id=intake.conversation_id,
                    client_message_id=client_request_id,
                    content=trigger_content,
                )
            except IdempotencyConflictError as exc:
                raise ConflictError(
                    "idempotency_conflict", "The idempotency key payload differs"
                ) from exc
            if trigger_result is None:
                raise NotFoundError()
            trigger, created = trigger_result
            if not created:
                generation = await uow.generation_runs.find_for_user_message(
                    trigger.id, tenant_id=tenant_id, owner_user_id=owner_user_id
                )
                if generation is None:
                    raise ConflictError("conversation_busy", "Previous summary is incomplete")
                assistant = await uow.messages.get_owned(
                    generation.assistant_message_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                )
                if assistant is None:
                    raise ConflictError("conversation_busy", "Previous summary is incomplete")
                citations = await uow.citations.list_for_message(
                    assistant.id, tenant_id=tenant_id, owner_user_id=owner_user_id
                )
                return (
                    ChatSession(
                        tenant_id=tenant_id,
                        owner_user_id=owner_user_id,
                        conversation_id=intake.conversation_id,
                        user_message=trigger,
                        assistant_message=assistant,
                        generation=generation,
                        user_content=trigger_content,
                        history=(),
                        replay=True,
                        replay_citations=tuple(citations),
                    ),
                    intake,
                )
            active = await uow.generation_runs.find_active_for_conversation(
                intake.conversation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if active is not None:
                raise ConflictError(
                    "conversation_busy", "The conversation has an active generation"
                )
            assistant = await uow.messages.create_assistant_message(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=intake.conversation_id,
                parent_message_id=trigger.id,
                retry_of_message_id=retry_of_message_id,
            )
            if assistant is None:
                raise NotFoundError()
            generation = await uow.generation_runs.create(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=intake.conversation_id,
                user_message_id=trigger.id,
                assistant_message_id=assistant.id,
            )
            if generation is None:
                raise NotFoundError()
            try:
                claimed = await uow.tax_intakes.transition(
                    intake.id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    expected={"awaiting_summary_confirmation"},
                    status="generating_summary" if requested else "summary_declined",
                    summary_requested=requested,
                    expected_version=expected_version,
                )
            except OptimisticLockError as exc:
                raise ConflictError(
                    "version_conflict", "The tax intake version is stale; reload and retry"
                ) from exc
            except IdempotencyConflictError as exc:
                raise ConflictError(
                    "invalid_workflow_state", "The intake summary decision is no longer current"
                ) from exc
            if claimed is None:
                raise NotFoundError()
            intake = claimed
            await uow.commit()
        return (
            ChatSession(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=intake.conversation_id,
                user_message=trigger,
                assistant_message=assistant,
                generation=generation,
                user_content=trigger_content,
                history=(),
            ),
            intake,
        )

    async def stream_summary(
        self,
        session: ChatSession,
        intake: TaxIntakeSession,
        *,
        requested: bool,
        request_id: str,
    ) -> AsyncIterator[str]:
        del request_id
        event_id = 1
        yield encode_sse(
            event_id,
            "generation.started",
            GenerationStartedEvent(
                generation_id=session.generation.id,
                message_id=session.assistant_message.id,
            ),
        )
        if session.replay:
            async for event in self._replay(session, start_event_id=event_id + 1):
                yield event
            return
        if not requested:
            content = "No tax summary was generated. You can return to ordinary chat."
            await self._persist_declined_summary(session, intake, content)
            yield encode_sse(
                2,
                "message.delta",
                MessageDeltaEvent(
                    generation_id=session.generation.id,
                    message_id=session.assistant_message.id,
                    seq=1,
                    delta=content,
                ),
            )
            yield encode_sse(
                3,
                "message.completed",
                MessageCompletedEvent(
                    generation_id=session.generation.id,
                    message_id=session.assistant_message.id,
                    completion_kind="clarification",
                    grounded=False,
                    citations=[],
                ),
            )
            return

        facts, requirements, citation_snapshots = await self._summary_inputs(session, intake)
        request = build_tax_summary_request(
            user_facts=tuple(facts), document_requirements=tuple(requirements)
        )
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="streaming",
            )
            await uow.commit()
        content = ""
        seq = 0
        try:
            iterator = self._llm.stream(request).__aiter__()
            while True:
                try:
                    chunk = await self._await_cancellable(
                        anext(iterator), generation_id=session.generation.id
                    )
                except StopAsyncIteration:
                    break
                if not chunk.delta:
                    continue
                content += chunk.delta
                seq += 1
                event_id += 1
                yield encode_sse(
                    event_id,
                    "message.delta",
                    MessageDeltaEvent(
                        generation_id=session.generation.id,
                        message_id=session.assistant_message.id,
                        seq=seq,
                        delta=chunk.delta,
                    ),
                )
            if not content:
                raise LLMProviderError("language model returned no text")
            summary = TaxSummaryContent(
                type="tax_summary",
                tax_intake_id=intake.id,
                tax_year=intake.tax_year,
                sections=[
                    TaxSummarySection(
                        heading="Tax preparation overview",
                        plain_language_text=content,
                        citation_ordinals=[item.ordinal for item in citation_snapshots],
                    )
                ],
                disclaimer=(
                    "This is preparation information, not tax advice or a lodged tax return."
                ),
            )
            citation_events = await self._persist_generated_summary(
                session, intake, content, summary, citation_snapshots
            )
        except TaxGenerationCancelled:
            await self._cancel_summary(session, intake, content)
            return
        except asyncio.CancelledError:
            await self._cancel_summary(session, intake, content)
            raise
        except LLMProviderError:
            await self._fail_summary(session, intake, content)
            raise ServiceUnavailableError(
                "llm_unavailable", "Tax summary generation failed"
            ) from None
        finally:
            await self._cancellation_store.clear(session.generation.id)
        event_id += 1
        yield encode_sse(
            event_id,
            "message.completed",
            MessageCompletedEvent(
                generation_id=session.generation.id,
                message_id=session.assistant_message.id,
                completion_kind="tax_summary",
                content_type="tax_summary",
                structured_content=summary.model_dump(mode="json"),
                grounded=True,
                citations=citation_events,
            ),
        )

    async def prepare_complete(
        self,
        *,
        intake_id: UUID,
        tenant_id: UUID,
        owner_user_id: UUID,
        client_request_id: UUID,
        expected_version: int,
        retry_of_message_id: UUID | None = None,
    ) -> tuple[ChatSession, TaxIntakeSession]:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            intake = await uow.tax_intakes.get_owned(
                intake_id, tenant_id=tenant_id, owner_user_id=owner_user_id
            )
            if intake is None:
                raise NotFoundError()
            require_complete(intake.answers)
            existing = await uow.messages.get_by_client_message_id(
                client_request_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if existing is None and intake.workflow_status not in {
                "questionnaire_active",
                "questionnaire_completed",
            }:
                raise ConflictError(
                    "invalid_workflow_state", "The questionnaire cannot be completed in this state"
                )
            if existing is None and intake.version != expected_version:
                raise ConflictError(
                    "version_conflict", "The tax intake version is stale; reload and retry"
                )
            trigger_content = f"complete-tax-intake:{intake.id}"
            try:
                trigger_result = await uow.messages.create_system_trigger(
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    conversation_id=intake.conversation_id,
                    client_message_id=client_request_id,
                    content=trigger_content,
                )
            except IdempotencyConflictError as exc:
                raise ConflictError(
                    "idempotency_conflict", "The idempotency key payload differs"
                ) from exc
            if trigger_result is None:
                raise NotFoundError()
            trigger, created = trigger_result
            if not created:
                generation = await uow.generation_runs.find_for_user_message(
                    trigger.id, tenant_id=tenant_id, owner_user_id=owner_user_id
                )
                if generation is None:
                    raise ConflictError("conversation_busy", "Previous completion is incomplete")
                assistant = await uow.messages.get_owned(
                    generation.assistant_message_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                )
                if assistant is None:
                    raise ConflictError("conversation_busy", "Previous completion is incomplete")
                citations = await uow.citations.list_for_message(
                    assistant.id, tenant_id=tenant_id, owner_user_id=owner_user_id
                )
                return (
                    ChatSession(
                        tenant_id=tenant_id,
                        owner_user_id=owner_user_id,
                        conversation_id=intake.conversation_id,
                        user_message=trigger,
                        assistant_message=assistant,
                        generation=generation,
                        user_content=trigger_content,
                        history=(),
                        replay=True,
                        replay_citations=tuple(citations),
                    ),
                    intake,
                )
            active = await uow.generation_runs.find_active_for_conversation(
                intake.conversation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if active is not None:
                raise ConflictError(
                    "conversation_busy", "The conversation has an active generation"
                )
            assistant = await uow.messages.create_assistant_message(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=intake.conversation_id,
                parent_message_id=trigger.id,
                retry_of_message_id=retry_of_message_id,
            )
            if assistant is None:
                raise NotFoundError()
            generation = await uow.generation_runs.create(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=intake.conversation_id,
                user_message_id=trigger.id,
                assistant_message_id=assistant.id,
            )
            if generation is None:
                raise NotFoundError()
            try:
                claimed = await uow.tax_intakes.transition(
                    intake.id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    expected={"questionnaire_active", "questionnaire_completed"},
                    status="questionnaire_completed",
                    expected_version=expected_version,
                )
            except OptimisticLockError as exc:
                raise ConflictError(
                    "version_conflict", "The tax intake version is stale; reload and retry"
                ) from exc
            except IdempotencyConflictError as exc:
                raise ConflictError(
                    "invalid_workflow_state", "The questionnaire cannot be completed in this state"
                ) from exc
            if claimed is None:
                raise NotFoundError()
            intake = claimed
            await uow.commit()
        return (
            ChatSession(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=intake.conversation_id,
                user_message=trigger,
                assistant_message=assistant,
                generation=generation,
                user_content=trigger_content,
                history=(),
            ),
            intake,
        )

    async def stream_complete(
        self,
        session: ChatSession,
        intake: TaxIntakeSession,
        *,
        request_id: str,
    ) -> AsyncIterator[str]:
        del request_id  # Errors are normalized before this deterministic stream is opened.
        event_id = 1
        yield encode_sse(
            event_id,
            "generation.started",
            GenerationStartedEvent(
                generation_id=session.generation.id,
                message_id=session.assistant_message.id,
            ),
        )
        if session.replay:
            async for event in self._replay(session, start_event_id=event_id + 1):
                yield event
            return
        claim_types = selected_claim_types(intake.answers)
        if not claim_types:
            async for event in self._complete_without_topics(
                session, intake, start_event_id=event_id + 1
            ):
                yield event
            return
        try:
            plan = await self._await_cancellable(
                self._retriever.plan_checklist(claim_types, intake.tax_year),
                generation_id=session.generation.id,
            )
        except TaxGenerationCancelled:
            await self._cancel_checklist(session, intake, None)
            return
        except asyncio.CancelledError:
            await self._cancel_checklist(session, intake, None)
            raise
        retrieval_id = await self._start_retrieval(session, intake, list(plan.claim_types))
        event_id += 1
        yield encode_sse(
            event_id,
            "retrieval.started",
            RetrievalStartedEvent(
                retrieval_run_id=retrieval_id,
                claim_type=None,
                claim_types=list(plan.claim_types),
                tax_year=plan.tax_year,
            ),
        )
        try:
            grounding = await self._await_cancellable(
                self._retriever.retrieve_checklist(plan),
                generation_id=session.generation.id,
            )
            checklist, citations, confirmation_message_id = await self._persist_checklist(
                session, intake, retrieval_id, grounding
            )
        except TaxGenerationCancelled:
            await self._cancel_checklist(session, intake, retrieval_id)
            return
        except asyncio.CancelledError:
            await self._cancel_checklist(session, intake, retrieval_id)
            raise
        except RetrievalUnavailableError:
            await self._fail_retrieval(session, intake, retrieval_id)
            raise ServiceUnavailableError(
                "insufficient_evidence", "Checklist evidence is unavailable"
            ) from None
        finally:
            await self._cancellation_store.clear(session.generation.id)
        event_id += 1
        yield encode_sse(
            event_id,
            "retrieval.completed",
            RetrievalCompletedEvent(
                retrieval_run_id=retrieval_id,
                status="completed",
                collection_name=self._retriever.collection_name,
                retrieval_config_version=self._retriever.config_version,
                candidate_count=grounding.candidate_count,
                selected_count=grounding.selected_count,
            ),
        )
        content = "Your ATO-backed document checklist is ready."
        event_id += 1
        yield encode_sse(
            event_id,
            "message.delta",
            MessageDeltaEvent(
                generation_id=session.generation.id,
                message_id=session.assistant_message.id,
                seq=1,
                delta=content,
            ),
        )
        event_id += 1
        yield encode_sse(
            event_id,
            "message.completed",
            MessageCompletedEvent(
                generation_id=session.generation.id,
                message_id=session.assistant_message.id,
                completion_kind="document_checklist",
                content_type="document_checklist",
                structured_content=checklist.model_dump(mode="json"),
                grounded=True,
                citations=citations,
            ),
        )
        confirmation = SummaryConfirmationContent(
            type="summary_confirmation",
            tax_intake_id=intake.id,
            prompt="Would you like a personalised tax preparation summary based on this checklist?",
        )
        event_id += 1
        yield encode_sse(
            event_id,
            "message.completed",
            MessageCompletedEvent(
                generation_id=session.generation.id,
                message_id=confirmation_message_id,
                completion_kind="summary_confirmation",
                content_type="summary_confirmation",
                structured_content=confirmation.model_dump(mode="json"),
                grounded=False,
                citations=[],
            ),
        )

    async def _start_retrieval(
        self, session: ChatSession, intake: TaxIntakeSession, claim_types: list[str]
    ) -> UUID:
        query_hash = hashlib.sha256(
            f"{intake.tax_year}:{','.join(claim_types)}".encode()
        ).hexdigest()
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"questionnaire_active", "questionnaire_completed"},
                status="retrieving_documents",
            )
            run = await uow.retrieval_runs.create(
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                conversation_id=session.conversation_id,
                user_message_id=session.user_message.id,
                assistant_message_id=session.assistant_message.id,
                intent="tax_assistance",
                claim_type=None,
                claim_types=claim_types,
                tax_year=intake.tax_year,
                query_hash=query_hash,
                embedding_provider=self._retriever.provider_name,
                embedding_model=self._retriever.embedding_model,
                retrieval_config_version=self._retriever.config_version,
                collection_name=self._retriever.collection_name,
                top_k=self._retriever.top_k,
                score_threshold=Decimal(str(self._retriever.score_threshold)),
            )
            if run is None:
                raise NotFoundError()
            await uow.generation_runs.attach_retrieval(
                session.generation.id,
                run.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
            )
            await uow.commit()
            return run.id

    async def _summary_inputs(
        self, session: ChatSession, intake: TaxIntakeSession
    ) -> tuple[list[str], list[str], list[CitationSnapshot]]:
        if intake.checklist_message_id is None:
            raise ConflictError("invalid_workflow_state", "The intake has no persisted checklist")
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            items = await uow.checklist_items.list_for_message(
                intake.checklist_message_id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
            )
            citations = await uow.citations.list_for_message(
                intake.checklist_message_id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
            )
        if not items or not citations:
            raise ConflictError("invalid_workflow_state", "The checklist snapshot is incomplete")
        facts = [
            f"{question_key}: {', '.join(option_codes)}"
            for question_key, option_codes in sorted(intake.answers.items())
        ]
        requirements = [
            f"{item.document_name}: {item.plain_language_explanation}" for item in items
        ]
        return facts, requirements, citations

    async def _persist_declined_summary(
        self, session: ChatSession, intake: TaxIntakeSession, content: str
    ) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
                content=content,
                model_provider="deterministic",
                model_name=CHECKLIST_VERSION,
                prompt_version=CHECKLIST_VERSION,
                completion_kind="clarification",
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
            )
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"awaiting_summary_confirmation"},
                status="summary_declined",
                summary_requested=False,
            )
            await uow.commit()

    async def _persist_generated_summary(
        self,
        session: ChatSession,
        intake: TaxIntakeSession,
        content: str,
        summary: TaxSummaryContent,
        source_citations: list[CitationSnapshot],
    ) -> list[CitationEvent]:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            citation_events: list[CitationEvent] = []
            for source in source_citations:
                snapshot = await uow.citations.add(
                    tenant_id=session.tenant_id,
                    owner_user_id=session.owner_user_id,
                    message_id=session.assistant_message.id,
                    retrieval_run_id=source.retrieval_run_id,
                    ordinal=source.ordinal,
                    claim_type=source.claim_type,
                    document_id=source.document_id,
                    content_hash=source.content_hash,
                    chunk_ids=list(source.chunk_ids),
                    title=source.title,
                    url=source.url,
                    section=source.section,
                    tax_years=list(source.tax_years),
                    source_accessed_at=source.source_accessed_at,
                )
                if snapshot is None:
                    raise RuntimeError("summary citation persistence failed")
                citation_events.append(_citation_event(snapshot))
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
                content=content,
                model_provider=self._llm.provider_name,
                model_name=self._llm.model_name,
                prompt_version="phase-5d-tax-summary-v1",
                retrieval_run_id=source_citations[0].retrieval_run_id,
                completion_kind="tax_summary",
                content_type="tax_summary",
                structured_content=summary.model_dump(mode="json"),
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
            )
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"generating_summary"},
                status="summary_completed",
                summary_requested=True,
            )
            await uow.commit()
        return citation_events

    async def _fail_summary(
        self, session: ChatSession, intake: TaxIntakeSession, content: str
    ) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="failed",
                content=content,
                model_provider=self._llm.provider_name,
                model_name=self._llm.model_name,
                prompt_version="phase-5d-tax-summary-v1",
                content_type="tax_summary",
                error_code="llm_unavailable",
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="failed",
                failure_reason="llm_unavailable",
            )
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"generating_summary"},
                status="awaiting_summary_confirmation",
                summary_requested=None,
            )
            await uow.commit()

    async def _persist_checklist(
        self,
        session: ChatSession,
        intake: TaxIntakeSession,
        retrieval_id: UUID,
        grounding: ChecklistGroundingContext,
    ) -> tuple[DocumentChecklistContent, list[CitationEvent], UUID]:
        items = [
            ChecklistItemContent(
                id=uuid4(),
                ordinal=index,
                claim_type=item.claim_type,
                document_name=f"Records for {item.claim_type.replace('_', ' ')}",
                plain_language_explanation=(
                    "Keep records that support this item as described by the linked ATO source."
                ),
                how_to_obtain="Download or retain the original statement, receipt, or log.",
                applies_because=f"You selected {', '.join(item.source_option_codes)}.",
                citation_ordinals=list(item.citation_ordinals),
            )
            for index, item in enumerate(grounding.items, start=1)
        ]
        confirmation = SummaryConfirmationContent(
            type="summary_confirmation",
            tax_intake_id=intake.id,
            prompt="Would you like a personalised tax preparation summary based on this checklist?",
        )
        checklist = DocumentChecklistContent(
            type="document_checklist",
            tax_intake_id=intake.id,
            tax_year=grounding.tax_year,
            items=items,
            summary_confirmation=confirmation,
        )
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            citation_events: list[CitationEvent] = []
            for ordinal, candidate in enumerate(grounding.citations, start=1):
                snapshot = await uow.citations.add(
                    tenant_id=session.tenant_id,
                    owner_user_id=session.owner_user_id,
                    message_id=session.assistant_message.id,
                    retrieval_run_id=retrieval_id,
                    ordinal=ordinal,
                    claim_type=candidate.claim_type,
                    document_id=candidate.document_id,
                    content_hash=candidate.content_hash,
                    chunk_ids=list(candidate.chunk_ids),
                    title=candidate.title,
                    url=candidate.source_url,
                    section=candidate.section,
                    tax_years=[candidate.tax_year],
                    source_accessed_at=candidate.accessed_at,
                )
                if snapshot is None:
                    raise RuntimeError("citation persistence failed")
                citation_events.append(_citation_event(snapshot))
            for item in items:
                persisted = await uow.checklist_items.add(
                    tenant_id=session.tenant_id,
                    owner_user_id=session.owner_user_id,
                    message_id=session.assistant_message.id,
                    item_id=item.id,
                    ordinal=item.ordinal,
                    claim_type=item.claim_type,
                    document_name=item.document_name,
                    plain_language_explanation=item.plain_language_explanation,
                    how_to_obtain=item.how_to_obtain,
                    applies_because=item.applies_because,
                    citation_ordinals=item.citation_ordinals,
                )
                if persisted is None:
                    raise RuntimeError("checklist persistence failed")
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
                content="Your ATO-backed document checklist is ready.",
                model_provider="deterministic",
                model_name=CHECKLIST_VERSION,
                prompt_version=CHECKLIST_VERSION,
                retrieval_run_id=retrieval_id,
                completion_kind="document_checklist",
                content_type="document_checklist",
                structured_content=checklist.model_dump(mode="json"),
            )
            confirmation_message = await uow.messages.create_assistant_message(
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                conversation_id=session.conversation_id,
                parent_message_id=session.user_message.id,
                content=confirmation.prompt,
                status="completed",
                completion_kind="summary_confirmation",
                content_type="summary_confirmation",
                structured_content=confirmation.model_dump(mode="json"),
            )
            if confirmation_message is None:
                raise RuntimeError("summary confirmation persistence failed")
            await uow.retrieval_runs.finish(
                retrieval_id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
                candidate_count=grounding.candidate_count,
                selected_count=grounding.selected_count,
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
            )
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"retrieving_documents", "checklist_ready"},
                status="awaiting_summary_confirmation",
                checklist_message_id=session.assistant_message.id,
            )
            await uow.commit()
        return checklist, citation_events, confirmation_message.id

    async def _complete_without_topics(
        self, session: ChatSession, intake: TaxIntakeSession, *, start_event_id: int
    ) -> AsyncIterator[str]:
        content = (
            "No supported income or deduction topic was selected, so no checklist was generated."
        )
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
                content=content,
                model_provider="deterministic",
                model_name=CHECKLIST_VERSION,
                prompt_version=CHECKLIST_VERSION,
                completion_kind="clarification",
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
            )
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"questionnaire_active", "questionnaire_completed"},
                status="summary_declined",
                summary_requested=False,
            )
            await uow.commit()
        yield encode_sse(
            start_event_id,
            "message.delta",
            MessageDeltaEvent(
                generation_id=session.generation.id,
                message_id=session.assistant_message.id,
                seq=1,
                delta=content,
            ),
        )
        yield encode_sse(
            start_event_id + 1,
            "message.completed",
            MessageCompletedEvent(
                generation_id=session.generation.id,
                message_id=session.assistant_message.id,
                completion_kind="clarification",
                grounded=False,
                citations=[],
            ),
        )

    async def _fail_retrieval(
        self, session: ChatSession, intake: TaxIntakeSession, retrieval_id: UUID
    ) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.retrieval_runs.finish(
                retrieval_id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="failed",
                candidate_count=0,
                selected_count=0,
                failure_reason="insufficient_evidence",
            )
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="failed",
                content="",
                model_provider="deterministic",
                model_name=CHECKLIST_VERSION,
                prompt_version=CHECKLIST_VERSION,
                retrieval_run_id=retrieval_id,
                content_type="document_checklist",
                error_code="insufficient_evidence",
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="failed",
                failure_reason="insufficient_evidence",
            )
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"retrieving_documents"},
                status="questionnaire_completed",
            )
            await uow.commit()

    async def _await_cancellable(
        self,
        awaitable: Awaitable[T],
        *,
        generation_id: UUID,
    ) -> T:
        task = asyncio.ensure_future(awaitable)
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=self._cancellation_poll_seconds)
                if await self._cancellation_store.is_requested(generation_id):
                    raise TaxGenerationCancelled()
            return await task
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def _cancel_checklist(
        self,
        session: ChatSession,
        intake: TaxIntakeSession,
        retrieval_id: UUID | None,
    ) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            if retrieval_id is not None:
                await uow.retrieval_runs.finish(
                    retrieval_id,
                    tenant_id=session.tenant_id,
                    owner_user_id=session.owner_user_id,
                    status="cancelled",
                    candidate_count=0,
                    selected_count=0,
                    failure_reason="cancelled",
                )
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="cancelled",
                content="",
                model_provider="deterministic",
                model_name=CHECKLIST_VERSION,
                prompt_version=CHECKLIST_VERSION,
                retrieval_run_id=retrieval_id,
                content_type="document_checklist",
                error_code="cancelled",
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="cancelled",
                failure_reason="cancelled",
            )
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"questionnaire_completed", "retrieving_documents"},
                status="questionnaire_completed",
            )
            await uow.commit()

    async def _cancel_summary(
        self, session: ChatSession, intake: TaxIntakeSession, content: str
    ) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="cancelled",
                content=content,
                model_provider=self._llm.provider_name,
                model_name=self._llm.model_name,
                prompt_version="phase-5d-tax-summary-v1",
                content_type="tax_summary",
                error_code="cancelled",
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="cancelled",
                failure_reason="cancelled",
            )
            await uow.tax_intakes.transition(
                intake.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                expected={"generating_summary"},
                status="awaiting_summary_confirmation",
                summary_requested=None,
            )
            await uow.commit()

    async def _replay(self, session: ChatSession, *, start_event_id: int) -> AsyncIterator[str]:
        if session.assistant_message.content:
            yield encode_sse(
                start_event_id,
                "message.delta",
                MessageDeltaEvent(
                    generation_id=session.generation.id,
                    message_id=session.assistant_message.id,
                    seq=1,
                    delta=session.assistant_message.content,
                ),
            )
            start_event_id += 1
        if session.assistant_message.status == "completed":
            completion_kind = session.assistant_message.completion_kind
            if completion_kind is None:
                raise RuntimeError("completed message has no completion kind")
            yield encode_sse(
                start_event_id,
                "message.completed",
                MessageCompletedEvent(
                    generation_id=session.generation.id,
                    message_id=session.assistant_message.id,
                    completion_kind=completion_kind,
                    content_type=session.assistant_message.content_type,
                    structured_content=session.assistant_message.structured_content,
                    grounded=bool(session.replay_citations),
                    citations=[_citation_event(item) for item in session.replay_citations],
                ),
            )


def _citation_event(snapshot: CitationSnapshot) -> CitationEvent:
    return CitationEvent(
        ordinal=snapshot.ordinal,
        claim_type=snapshot.claim_type,
        title=snapshot.title,
        url=snapshot.url,
        document_id=snapshot.document_id,
        content_hash=snapshot.content_hash,
        chunk_ids=list(snapshot.chunk_ids),
        tax_year=snapshot.tax_years[0],
        accessed_at=snapshot.source_accessed_at,
    )
