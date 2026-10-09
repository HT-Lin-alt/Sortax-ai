import asyncio
import hashlib
from collections.abc import AsyncIterator, Awaitable
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, TypeVar, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sortax.api.errors import ConflictError, NotFoundError, ServiceUnavailableError
from sortax.chat.cancellation import CancellationStore, InMemoryCancellationStore
from sortax.chat.events import (
    CitationEvent,
    GenerationStartedEvent,
    HeartbeatEvent,
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
from sortax.intent import IntentClassificationError, IntentClassifier, IntentHistoryMessage
from sortax.llm_gateway import (
    LLMProvider,
    LLMProviderError,
    LLMProviderRateLimited,
    LLMProviderTimeout,
    LLMProviderUnavailable,
    LLMStreamChunk,
)
from sortax.messages import CitationSnapshot, CompletionKind, GenerationRun, Message
from sortax.prompting import (
    HistoryMessage,
    build_answer_request,
    build_clarification_request,
    build_general_chat_request,
)
from sortax.rag import (
    ClarificationRequired,
    GroundingContext,
    RetrievalHistoryMessage,
    RetrievalPlan,
    RetrievalUnavailableError,
    Retriever,
)

PROMPT_VERSION = "phase-5c-v1"
T = TypeVar("T")


class GenerationCancelled(RuntimeError):
    """Internal control flow for a requested generation cancellation."""


class ChatCoordinator:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        intent_classifier: IntentClassifier,
        retriever: Retriever,
        llm: LLMProvider,
        cancellation_store: CancellationStore | None = None,
        first_token_timeout_seconds: float = 30.0,
        heartbeat_seconds: float = 15.0,
        max_duration_seconds: float = 300.0,
        cancellation_poll_seconds: float = 0.5,
    ) -> None:
        if (
            min(
                first_token_timeout_seconds,
                heartbeat_seconds,
                max_duration_seconds,
                cancellation_poll_seconds,
            )
            <= 0
        ):
            raise ValueError("stream timing values must be positive")
        if first_token_timeout_seconds > max_duration_seconds:
            raise ValueError("first-token timeout cannot exceed total duration")
        self._session_factory = session_factory
        self._intent_classifier = intent_classifier
        self._retriever = retriever
        self._llm = llm
        self._cancellation_store = cancellation_store or InMemoryCancellationStore()
        self._first_token_timeout_seconds = first_token_timeout_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._max_duration_seconds = max_duration_seconds
        self._cancellation_poll_seconds = cancellation_poll_seconds
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

        self._cancellations.setdefault(session.generation.id, asyncio.Event())
        loop = asyncio.get_running_loop()
        stream_deadline = loop.time() + self._max_duration_seconds
        content = ""
        retrieval_run_id: UUID | None = None
        retrieval_completed = False
        citations: list[CitationEvent] = []
        completion_kind: CompletionKind = "clarification"
        provider_request_id: str | None = None
        input_tokens: int | None = None
        output_tokens: int | None = None
        pending_chunk_task: asyncio.Future[LLMStreamChunk] | None = None
        try:
            intent_history = tuple(
                IntentHistoryMessage(role=item.role, content=item.content)
                for item in session.history
            )
            intent = await self._await_cancellable(
                self._intent_classifier.classify(
                    session.user_content,
                    intent_history,
                ),
                generation_id=session.generation.id,
                deadline=stream_deadline,
            )
            if intent.intent == "general_chat":
                completion_kind = "general_chat"
                llm_request = build_general_chat_request(
                    user_content=session.user_content,
                    history=session.history,
                )
            elif intent.intent == "unsupported_tax_topic":
                llm_request = build_clarification_request(
                    user_content=session.user_content,
                    history=session.history,
                    clarification=ClarificationRequired(missing_fields=("supported_tax_topic",)),
                )
            elif intent.intent == "tax_assistance":
                llm_request = build_clarification_request(
                    user_content=session.user_content,
                    history=session.history,
                    clarification=ClarificationRequired(missing_fields=("tax_intake",)),
                )
            else:
                retrieval_history = tuple(
                    RetrievalHistoryMessage(role=item.role, content=item.content)
                    for item in session.history
                )
                plan_result = await self._await_cancellable(
                    self._retriever.plan(
                        session.user_content,
                        retrieval_history,
                    ),
                    generation_id=session.generation.id,
                    deadline=stream_deadline,
                )
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
                    grounding = await self._await_cancellable(
                        self._retriever.retrieve(plan_result),
                        generation_id=session.generation.id,
                        deadline=stream_deadline,
                    )
                    if not grounding.evidence or not grounding.citations:
                        raise ServiceUnavailableError(
                            "insufficient_evidence", "Retrieved evidence is insufficient"
                        )
                    citations = await self._complete_retrieval(
                        session,
                        retrieval_run_id,
                        grounding,
                    )
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
            first_token_received = False
            first_token_deadline = loop.time() + self._first_token_timeout_seconds
            next_heartbeat_at = loop.time() + self._heartbeat_seconds
            llm_iterator = self._llm.stream(llm_request).__aiter__()
            pending_chunk_task = asyncio.ensure_future(llm_iterator.__anext__())
            while pending_chunk_task is not None:
                now = loop.time()
                deadlines = [
                    self._cancellation_poll_seconds,
                    max(0.0, stream_deadline - now),
                    max(0.0, next_heartbeat_at - now),
                ]
                if not first_token_received:
                    deadlines.append(max(0.0, first_token_deadline - now))
                done, _pending = await asyncio.wait(
                    {pending_chunk_task},
                    timeout=min(deadlines),
                )
                if await self._is_cancelled(session.generation.id):
                    raise GenerationCancelled()
                now = loop.time()
                if now >= stream_deadline:
                    raise LLMProviderTimeout("generation exceeded the total stream deadline")
                if not first_token_received and now >= first_token_deadline:
                    raise LLMProviderTimeout("generation exceeded the first-token deadline")
                if pending_chunk_task in done:
                    try:
                        chunk = pending_chunk_task.result()
                    except StopAsyncIteration:
                        pending_chunk_task = None
                        break
                    pending_chunk_task = asyncio.ensure_future(llm_iterator.__anext__())
                    provider_request_id = chunk.provider_request_id or provider_request_id
                    input_tokens = (
                        chunk.input_tokens if chunk.input_tokens is not None else input_tokens
                    )
                    output_tokens = (
                        chunk.output_tokens if chunk.output_tokens is not None else output_tokens
                    )
                    if not chunk.delta:
                        continue
                    if not first_token_received:
                        first_token_received = True
                        await self._mark_first_token(session)
                    content += chunk.delta
                    sequence += 1
                    event_id += 1
                    yield encode_sse(
                        event_id,
                        "message.delta",
                        MessageDeltaEvent(
                            generation_id=session.generation.id,
                            message_id=session.assistant_message.id,
                            seq=sequence,
                            delta=chunk.delta,
                        ),
                    )
                    next_heartbeat_at = loop.time() + self._heartbeat_seconds
                elif now >= next_heartbeat_at:
                    event_id += 1
                    yield encode_sse(
                        event_id,
                        "heartbeat",
                        HeartbeatEvent(
                            generation_id=session.generation.id,
                            emitted_at=datetime.now(UTC),
                        ),
                    )
                    next_heartbeat_at = loop.time() + self._heartbeat_seconds
            if await self._is_cancelled(session.generation.id):
                raise GenerationCancelled()
            if not content:
                raise LLMProviderError("language model returned no text")
            await self._mark_completed(
                session,
                content,
                retrieval_run_id,
                completion_kind,
                provider_request_id=provider_request_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
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
        except GenerationCancelled:
            if retrieval_run_id is not None and not retrieval_completed:
                await self._finish_retrieval(
                    session,
                    retrieval_run_id,
                    status="cancelled",
                    failure_reason="cancelled",
                )
            await self._mark_cancelled(session, content, retrieval_run_id)
            return
        except asyncio.CancelledError:
            await self._mark_cancelled(session, content, retrieval_run_id)
            raise
        except Exception as exc:
            code, message, retryable = _safe_stream_error(exc)
            if retrieval_run_id is not None and not retrieval_completed:
                await self._finish_retrieval(
                    session,
                    retrieval_run_id,
                    status="failed",
                    failure_reason=code,
                )
            await self._mark_failed(
                session,
                content,
                retrieval_run_id,
                code,
                provider_request_id=provider_request_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
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
            if pending_chunk_task is not None and not pending_chunk_task.done():
                pending_chunk_task.cancel()
                with suppress(asyncio.CancelledError):
                    await pending_chunk_task
            self._cancellations.pop(session.generation.id, None)
            with suppress(Exception):
                await self._cancellation_store.clear(session.generation.id)

    async def cancel(
        self, generation_id: UUID, *, tenant_id: UUID, owner_user_id: UUID
    ) -> GenerationRun:
        cancellation_requested = False
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            generation = await uow.generation_runs.get_owned(
                generation_id,
                tenant_id=tenant_id,
                owner_user_id=owner_user_id,
            )
            if generation is None:
                raise NotFoundError()
            if generation.status not in {"completed", "failed", "cancelled"}:
                cancellation_requested = True
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
        if cancellation_requested:
            cancellation = self._cancellations.get(generation_id)
            if cancellation is not None:
                cancellation.set()
            await self._cancellation_store.request(generation_id)
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
            completion_kind = session.assistant_message.completion_kind
            if completion_kind is None:
                raise RuntimeError("completed assistant message is missing completion kind")
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

    async def _await_cancellable(
        self,
        awaitable: Awaitable[T],
        *,
        generation_id: UUID,
        deadline: float,
    ) -> T:
        task = asyncio.ensure_future(awaitable)
        try:
            while not task.done():
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise LLMProviderTimeout("generation exceeded the total stream deadline")
                await asyncio.wait(
                    {task},
                    timeout=min(self._cancellation_poll_seconds, remaining),
                )
                if await self._is_cancelled(generation_id):
                    raise GenerationCancelled()
            return await task
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def _is_cancelled(self, generation_id: UUID) -> bool:
        local = self._cancellations.get(generation_id)
        return bool(local and local.is_set()) or await self._cancellation_store.is_requested(
            generation_id
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

    async def _finish_retrieval(
        self,
        session: ChatSession,
        retrieval_run_id: UUID,
        *,
        status: Literal["failed", "cancelled"],
        failure_reason: str,
    ) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.retrieval_runs.finish(
                retrieval_run_id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status=status,
                candidate_count=0,
                selected_count=0,
                failure_reason=failure_reason,
            )
            await uow.commit()

    async def _mark_first_token(self, session: ChatSession) -> None:
        async with PersistenceUnitOfWork(self._session_factory) as uow:
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status="streaming",
                first_token_received=True,
            )
            await uow.commit()

    async def _mark_completed(
        self,
        session: ChatSession,
        content: str,
        retrieval_run_id: UUID | None,
        completion_kind: CompletionKind,
        *,
        provider_request_id: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        await self._set_terminal_state(
            session,
            status="completed",
            content=content,
            retrieval_run_id=retrieval_run_id,
            completion_kind=completion_kind,
            provider_request_id=provider_request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
        *,
        provider_request_id: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> None:
        await self._set_terminal_state(
            session,
            status="failed",
            content=content,
            retrieval_run_id=retrieval_run_id,
            error_code=error_code,
            provider_request_id=provider_request_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def _set_terminal_state(
        self,
        session: ChatSession,
        *,
        status: Literal["streaming", "completed", "failed", "cancelled"],
        content: str,
        retrieval_run_id: UUID | None,
        completion_kind: CompletionKind | None = None,
        error_code: str | None = None,
        provider_request_id: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
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
                completion_kind=completion_kind,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                error_code=error_code,
            )
            await uow.generation_runs.set_status(
                session.generation.id,
                tenant_id=session.tenant_id,
                owner_user_id=session.owner_user_id,
                status=status,
                failure_reason=error_code,
                cancel_requested=status == "cancelled",
                provider_request_id=provider_request_id,
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
    if isinstance(exc, IntentClassificationError):
        return exc.code, "The request could not be classified safely; please retry or clarify", True
    if isinstance(exc, LLMProviderRateLimited):
        return "quota_exceeded", "The response provider rate limit was exceeded", True
    if isinstance(exc, LLMProviderTimeout):
        return "provider_timeout", "The response provider timed out", True
    if isinstance(exc, LLMProviderUnavailable):
        return "provider_unavailable", "The response provider is unavailable", True
    if isinstance(exc, LLMProviderError):
        return "provider_error", "The response provider failed", True
    return "provider_error", "The response provider failed", True
