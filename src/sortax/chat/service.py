import asyncio
import hashlib
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sortax.api.errors import ConflictError, NotFoundError, ServiceUnavailableError
from sortax.chat.events import (
    CitationEvent,
    GenerationStartedEvent,
    MessageCompletedEvent,
    MessageDeltaEvent,
    MessageFailedEvent,
    RetrievalCompletedEvent,
    RetrievalStartedEvent,
    StreamError,
    encode_sse,
)
from sortax.chat.models import ChatSession
from sortax.infrastructure.persistence import PersistenceUnitOfWork
from sortax.infrastructure.persistence.repositories import IdempotencyConflictError
from sortax.llm_gateway import LLMProvider
from sortax.messages import CitationSnapshot, GenerationRun, Message
from sortax.prompting import (
    HistoryMessage,
    build_answer_request,
    build_clarification_request,
)
from sortax.rag import (
    ClarificationRequired,
    GroundingContext,
    RetrievalHistoryMessage,
    RetrievalPlan,
    RetrievalUnavailableError,
    Retriever,
)

PROMPT_VERSION = "phase-5a-v1"


class ChatCoordinator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retriever: Retriever,
        llm: LLMProvider,
    ) -> None:
        self._session_factory = session_factory
        self._retriever = retriever
        self._llm = llm
        self._cancellations: dict[UUID, asyncio.Event] = {}

    async def prepare(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        conversation_id: UUID,
        client_message_id: UUID,
        content: str,
    ) -> ChatSession:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            try:
                created_result = await uow.messages.create_user_message(
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    conversation_id=conversation_id,
                    client_message_id=client_message_id,
                    content=content,
                )
            except IdempotencyConflictError as exc:
                raise ConflictError(
                    "idempotency_conflict", "The idempotency key payload differs"
                ) from exc
            if created_result is None:
                raise NotFoundError()
            user_message, created = created_result
            if not created:
                return await self._replay_session(
                    uow=uow,
                    user_message=user_message,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    content=content,
                )

            active = await uow.generation_runs.find_active_for_conversation(
                conversation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if active is not None:
                raise ConflictError(
                    "conversation_busy", "The conversation has an active generation"
                )
            messages = await uow.messages.list_owned(
                conversation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            history = _history_before(messages, user_message.id)
            assistant = await uow.messages.create_assistant_message(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                parent_message_id=user_message.id,
            )
            if assistant is None:
                raise NotFoundError()
            generation = await uow.generation_runs.create(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=conversation_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant.id,
            )
            if generation is None:
                raise NotFoundError()
            await uow.commit()

        self._cancellations[generation.id] = asyncio.Event()
        return ChatSession(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=conversation_id,
            user_message=user_message,
            assistant_message=assistant,
            generation=generation,
            user_content=content,
            history=history,
        )

    async def prepare_retry(
        self,
        *,
        tenant_id: UUID,
        owner_user_id: UUID,
        message_id: UUID,
        client_message_id: UUID,
    ) -> ChatSession:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            existing = await uow.messages.get_by_client_message_id(
                client_message_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if existing is not None:
                if existing.retry_of_message_id != message_id:
                    raise ConflictError(
                        "idempotency_conflict", "The idempotency key payload differs"
                    )
                generation = (
                    await uow.generation_runs.find_for_assistant_message(
                        existing.id,
                        tenant_id=tenant_id,
                        owner_user_id=owner_user_id,
                    )
                    if existing.parent_message_id
                    else None
                )
                if generation is None:
                    raise ConflictError("conversation_busy", "Retry state is incomplete")
                parent = await uow.messages.get_owned(
                    generation.user_message_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                )
                if parent is None:
                    raise NotFoundError()
                citations = await uow.citations.list_for_message(
                    existing.id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                )
                return ChatSession(
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    conversation_id=existing.conversation_id,
                    user_message=parent,
                    assistant_message=existing,
                    generation=generation,
                    user_content=parent.content,
                    history=(),
                    replay=True,
                    replay_citations=tuple(citations),
                )

            original = await uow.messages.get_owned(
                message_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if (
                original is None
                or original.role != "assistant"
                or original.parent_message_id is None
            ):
                raise NotFoundError()
            parent = await uow.messages.get_owned(
                original.parent_message_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if parent is None or parent.role != "user":
                raise NotFoundError()
            active = await uow.generation_runs.find_active_for_conversation(
                original.conversation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if active is not None:
                raise ConflictError(
                    "conversation_busy", "The conversation has an active generation"
                )
            messages = await uow.messages.list_owned(
                original.conversation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            history = _history_before(messages, parent.id)
            assistant = await uow.messages.create_assistant_message(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=original.conversation_id,
                parent_message_id=parent.id,
                retry_of_message_id=original.id,
                client_message_id=client_message_id,
            )
            if assistant is None:
                raise NotFoundError()
            generation = await uow.generation_runs.create(
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
                conversation_id=original.conversation_id,
                user_message_id=parent.id,
                assistant_message_id=assistant.id,
            )
            if generation is None:
                raise NotFoundError()
            await uow.commit()

        self._cancellations[generation.id] = asyncio.Event()
        return ChatSession(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=original.conversation_id,
            user_message=parent,
            assistant_message=assistant,
            generation=generation,
            user_content=parent.content,
            history=history,
        )

    async def stream(self, session: ChatSession, *, request_id: str) -> AsyncIterator[str]:
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
            async for replay_event in self._replay_events(session, start_event_id=event_id + 1):
                yield replay_event
            return

        cancellation = self._cancellations.setdefault(session.generation.id, asyncio.Event())
        content = ""
        retrieval_run_id: UUID | None = None
        retrieval_completed = False
        citations: list[CitationEvent] = []
        completion_kind: Literal["answer", "clarification"] = "clarification"
        try:
            retrieval_history = tuple(
                RetrievalHistoryMessage(role=item.role, content=item.content)
                for item in session.history
            )
            plan_result = await self._retriever.plan(session.user_content, retrieval_history)
            if isinstance(plan_result, ClarificationRequired):
                llm_request = build_clarification_request(
                    user_content=session.user_content,
                    history=session.history,
                    clarification=plan_result,
                )
            else:
                completion_kind = "answer"
                retrieval_run_id = await self._start_retrieval(session, plan_result)
                event_id += 1
                yield encode_sse(
                    event_id,
                    "retrieval.started",
                    RetrievalStartedEvent(
                        retrieval_run_id=retrieval_run_id,
                        claim_type=plan_result.claim_type,
                        tax_year=plan_result.tax_year,
                    ),
                )
                grounding = await self._retriever.retrieve(plan_result)
                if not grounding.evidence or not grounding.citations:
                    raise ServiceUnavailableError(
                        "insufficient_evidence", "Retrieved evidence is insufficient"
                    )
                citations = await self._complete_retrieval(session, retrieval_run_id, grounding)
                retrieval_completed = True
                event_id += 1
                yield encode_sse(
                    event_id,
                    "retrieval.completed",
                    RetrievalCompletedEvent(
                        retrieval_run_id=retrieval_run_id,
                        status="completed",
                        collection_name=self._retriever.collection_name,
                        retrieval_config_version=self._retriever.config_version,
                        candidate_count=grounding.candidate_count,
                        selected_count=grounding.selected_count,
                    ),
                )
                llm_request = build_answer_request(
                    user_content=session.user_content,
                    history=session.history,
                    grounding=grounding,
                )

            await self._mark_streaming(session, retrieval_run_id)
            sequence = 0
            async for delta in self._llm.stream(llm_request):
                if cancellation.is_set():
                    await self._mark_cancelled(session, content, retrieval_run_id)
                    return
                if not delta:
                    continue
                content += delta
                sequence += 1
                event_id += 1
                yield encode_sse(
                    event_id,
                    "message.delta",
                    MessageDeltaEvent(
                        generation_id=session.generation.id,
                        message_id=session.assistant_message.id,
                        seq=sequence,
                        delta=delta,
                    ),
                )
            if cancellation.is_set():
                await self._mark_cancelled(session, content, retrieval_run_id)
                return
            await self._mark_completed(session, content, retrieval_run_id)
            event_id += 1
            yield encode_sse(
                event_id,
                "message.completed",
                MessageCompletedEvent(
                    generation_id=session.generation.id,
                    message_id=session.assistant_message.id,
                    completion_kind=completion_kind,
                    grounded=bool(citations),
                    citations=citations,
                ),
            )
        except asyncio.CancelledError:
            await self._mark_cancelled(session, content, retrieval_run_id)
            raise
        except Exception as exc:
            code, message, retryable = _safe_stream_error(exc)
            if retrieval_run_id is not None and not retrieval_completed:
                await self._fail_retrieval(session, retrieval_run_id, code)
            await self._mark_failed(session, content, retrieval_run_id, code)
            event_id += 1
            yield encode_sse(
                event_id,
                "message.failed",
                MessageFailedEvent(
                    generation_id=session.generation.id,
                    message_id=session.assistant_message.id,
                    error=StreamError(
                        code=code,
                        message=message,
                        request_id=request_id,
                        retryable=retryable,
                    ),
                ),
            )
        finally:
            self._cancellations.pop(session.generation.id, None)

    async def cancel(
        self, generation_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> GenerationRun:
        cancellation = self._cancellations.get(generation_id)
        if cancellation is not None:
            cancellation.set()
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            generation = await uow.generation_runs.get_owned(
                generation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if generation is None:
                raise NotFoundError()
            if generation.status not in {"completed", "failed", "cancelled"}:
                updated = await uow.generation_runs.set_status(
                    generation_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    status="cancelled",
                    cancel_requested=True,
                )
                await uow.messages.set_assistant_state(
                    generation.assistant_message_id,
                    tenant_id=tenant_id,
                    owner_user_id=owner_user_id,
                    status="cancelled",
                    content="",
                    model_provider=self._llm.provider_name,
                    model_name=self._llm.model_name,
                    prompt_version=PROMPT_VERSION,
                    retrieval_run_id=generation.retrieval_run_id,
                )
                if updated is not None:
                    generation = updated
                await uow.commit()
            return generation

    async def get_generation(
        self, generation_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> GenerationRun:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            generation = await uow.generation_runs.get_owned(
                generation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if generation is None:
                raise NotFoundError()
            return generation

    async def _replay_session(
        self,
        *,
        uow: PersistenceUnitOfWork,
        user_message: Message,
        tenant_id: UUID,
        owner_user_id: UUID,
        content: str,
    ) -> ChatSession:
        generation = await uow.generation_runs.find_for_user_message(
            user_message.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        if generation is None:
            raise ConflictError("conversation_busy", "The previous request is incomplete")
        assistant = await uow.messages.get_owned(
            generation.assistant_message_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        if assistant is None:
            raise ConflictError("conversation_busy", "The previous request is incomplete")
        citations = await uow.citations.list_for_message(
            assistant.id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
        )
        return ChatSession(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            conversation_id=user_message.conversation_id,
            user_message=user_message,
            assistant_message=assistant,
            generation=generation,
            user_content=content,
            history=(),
            replay=True,
            replay_citations=tuple(citations),
        )

    async def _replay_events(
        self, session: ChatSession, *, start_event_id: int
    ) -> AsyncIterator[str]:
        event_id = start_event_id
        if session.assistant_message.content:
            yield encode_sse(
                event_id,
                "message.delta",
                MessageDeltaEvent(
                    generation_id=session.generation.id,
                    message_id=session.assistant_message.id,
                    seq=1,
                    delta=session.assistant_message.content,
                ),
            )
            event_id += 1
        if session.assistant_message.status == "completed":
            citations = [_snapshot_event(item) for item in session.replay_citations]
            yield encode_sse(
                event_id,
                "message.completed",
                MessageCompletedEvent(
                    generation_id=session.generation.id,
                    message_id=session.assistant_message.id,
                    completion_kind="answer" if citations else "clarification",
                    grounded=bool(citations),
                    citations=citations,
                ),
            )

    async def _start_retrieval(self, session: ChatSession, plan: RetrievalPlan) -> UUID:
        query_hash = (
            "sha256:"
            + hashlib.sha256(plan.minimized_query.encode(), usedforsecurity=False).hexdigest()
        )
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            run = await uow.retrieval_runs.create(
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                conversation_id=session.conversation_id,
                user_message_id=session.user_message.id,
                assistant_message_id=session.assistant_message.id,
                intent=plan.intent,
                claim_type=plan.claim_type,
                tax_year=plan.tax_year,
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

    async def _complete_retrieval(
        self,
        session: ChatSession,
        retrieval_run_id: UUID,
        grounding: GroundingContext,
    ) -> list[CitationEvent]:
        events: list[CitationEvent] = []
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            for ordinal, citation in enumerate(grounding.citations, start=1):
                snapshot = await uow.citations.add(
                    tenant_id=session.tenant_id,
                    owner_user_id=session.owner_user_id,
                    message_id=session.assistant_message.id,
                    retrieval_run_id=retrieval_run_id,
                    ordinal=ordinal,
                    document_id=citation.document_id,
                    content_hash=citation.content_hash,
                    chunk_ids=list(citation.chunk_ids),
                    title=citation.title,
                    url=citation.source_url,
                    section=citation.section,
                    tax_years=[citation.tax_year],
                    source_accessed_at=citation.accessed_at,
                )
                if snapshot is None:
                    raise NotFoundError()
                events.append(_snapshot_event(snapshot))
            await uow.retrieval_runs.finish(
                retrieval_run_id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="completed",
                candidate_count=grounding.candidate_count,
                selected_count=grounding.selected_count,
            )
            await uow.commit()
        return events

    async def _mark_streaming(self, session: ChatSession, retrieval_run_id: UUID | None) -> None:
        await self._set_terminal_state(
            session,
            status="streaming",
            content="",
            retrieval_run_id=retrieval_run_id,
        )

    async def _fail_retrieval(
        self, session: ChatSession, retrieval_run_id: UUID, failure_reason: str
    ) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.retrieval_runs.finish(
                retrieval_run_id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="failed",
                candidate_count=0,
                selected_count=0,
                failure_reason=failure_reason,
            )
            await uow.commit()

    async def _mark_completed(
        self, session: ChatSession, content: str, retrieval_run_id: UUID | None
    ) -> None:
        await self._set_terminal_state(
            session,
            status="completed",
            content=content,
            retrieval_run_id=retrieval_run_id,
        )

    async def _mark_cancelled(
        self, session: ChatSession, content: str, retrieval_run_id: UUID | None
    ) -> None:
        await self._set_terminal_state(
            session,
            status="cancelled",
            content=content,
            retrieval_run_id=retrieval_run_id,
        )

    async def _mark_failed(
        self,
        session: ChatSession,
        content: str,
        retrieval_run_id: UUID | None,
        error_code: str,
    ) -> None:
        await self._set_terminal_state(
            session,
            status="failed",
            content=content,
            retrieval_run_id=retrieval_run_id,
            error_code=error_code,
        )

    async def _set_terminal_state(
        self,
        session: ChatSession,
        *,
        status: Literal["streaming", "completed", "failed", "cancelled"],
        content: str,
        retrieval_run_id: UUID | None,
        error_code: str | None = None,
    ) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.messages.set_assistant_state(
                session.assistant_message.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status=status,
                content=content,
                model_provider=self._llm.provider_name,
                model_name=self._llm.model_name,
                prompt_version=PROMPT_VERSION,
                retrieval_run_id=retrieval_run_id,
                error_code=error_code,
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status=status,
                failure_reason=error_code,
                cancel_requested=status == "cancelled",
            )
            await uow.commit()


def _history_before(
    messages: list[Message], current_message_id: UUID
) -> tuple[HistoryMessage, ...]:
    history = [
        HistoryMessage(
            role=cast(Literal["user", "assistant"], message.role),
            content=message.content,
        )
        for message in messages
        if message.id != current_message_id
        and message.role in {"user", "assistant"}
        and message.status == "completed"
    ]
    return tuple(history[-20:])


def _snapshot_event(snapshot: CitationSnapshot) -> CitationEvent:
    return CitationEvent(
        title=snapshot.title,
        url=snapshot.url,
        document_id=snapshot.document_id,
        content_hash=snapshot.content_hash,
        chunk_ids=list(snapshot.chunk_ids),
        tax_year=snapshot.tax_years[0],
        accessed_at=snapshot.source_accessed_at,
    )


def _safe_stream_error(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, ServiceUnavailableError):
        return exc.code, exc.message, exc.retryable
    if isinstance(exc, RetrievalUnavailableError):
        if str(exc) == "insufficient evidence":
            return "insufficient_evidence", "Retrieved evidence is insufficient", False
        return "retrieval_unavailable", "The retrieval service is unavailable", True
    return "provider_error", "The response provider failed", True
