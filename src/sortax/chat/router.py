from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from sortax.api.errors import ConflictError, NotFoundError, ServiceUnavailableError
from sortax.chat.models import (
    CitationResponse,
    ConversationPageResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    GenerationResponse,
    MessagePageResponse,
    MessageResponse,
    RetryMessageRequest,
    UpdateConversationRequest,
    generation_response,
)
from sortax.chat.service import ChatCoordinator
from sortax.conversations import Conversation
from sortax.identity.dependencies import CurrentIdentity
from sortax.infrastructure.persistence import PersistenceUnitOfWork
from sortax.infrastructure.persistence.repositories import IdempotencyConflictError
from sortax.messages import CitationSnapshot, Message

router = APIRouter(tags=["chat"])


def get_chat_coordinator(request: Request) -> ChatCoordinator:
    coordinator = getattr(request.app.state, "chat_coordinator", None)
    if coordinator is None:
        raise ServiceUnavailableError("configuration_error", "Chat persistence is not configured")
    return cast(ChatCoordinator, coordinator)


ChatCoordinatorDependency = Annotated[ChatCoordinator, Depends(get_chat_coordinator)]


@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation(
    identity: CurrentIdentity,
    request: Request,
    payload: CreateConversationRequest | None = None,
) -> ConversationResponse:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise ServiceUnavailableError("configuration_error", "Database is not configured")
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.create(
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
            title=payload.title if payload and payload.title else "New conversation",
        )
        await uow.commit()
    return _conversation_response(conversation)


@router.get("/conversations", response_model=ConversationPageResponse)
async def list_conversations(
    identity: CurrentIdentity,
    request: Request,
    status_filter: Annotated[
        Literal["active", "archived"] | None,
        Query(alias="status"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> ConversationPageResponse:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise ServiceUnavailableError("configuration_error", "Database is not configured")
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversations = await uow.conversations.list_owned(
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
            status=status_filter,
            limit=limit,
        )
    return ConversationPageResponse(items=[_conversation_response(item) for item in conversations])


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: UUID,
    identity: CurrentIdentity,
    request: Request,
) -> ConversationResponse:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise ServiceUnavailableError("configuration_error", "Database is not configured")
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.get_owned(
            conversation_id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
        )
    if conversation is None:
        raise NotFoundError()
    return _conversation_response(conversation)


@router.patch("/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: UUID,
    payload: UpdateConversationRequest,
    identity: CurrentIdentity,
    request: Request,
) -> ConversationResponse:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise ServiceUnavailableError("configuration_error", "Database is not configured")
    async with PersistenceUnitOfWork(session_factory) as uow:
        try:
            conversation = await uow.conversations.update_owned(
                conversation_id,
                tenant_id=identity.tenant_id,
                owner_user_id=identity.user_id,
                expected_version=payload.version,
                title=payload.title,
                status=payload.status,
            )
        except IdempotencyConflictError as exc:
            raise ConflictError("idempotency_conflict", "Conversation version differs") from exc
        if conversation is None:
            raise NotFoundError()
        await uow.commit()
    return _conversation_response(conversation)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    identity: CurrentIdentity,
    request: Request,
    coordinator: ChatCoordinatorDependency,
) -> Response:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise ServiceUnavailableError("configuration_error", "Database is not configured")
    async with PersistenceUnitOfWork(session_factory) as uow:
        active = await uow.generation_runs.find_active_for_conversation(
            conversation_id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
        )
    if active is not None:
        await coordinator.cancel(
            active.id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
        )
    async with PersistenceUnitOfWork(session_factory) as uow:
        await uow.conversations.delete_owned(
            conversation_id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
        )
        await uow.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagePageResponse,
)
async def list_messages(
    conversation_id: UUID,
    identity: CurrentIdentity,
    request: Request,
) -> MessagePageResponse:
    session_factory = request.app.state.session_factory
    if session_factory is None:
        raise ServiceUnavailableError("configuration_error", "Database is not configured")
    async with PersistenceUnitOfWork(session_factory) as uow:
        conversation = await uow.conversations.get_owned(
            conversation_id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
        )
        if conversation is None:
            raise NotFoundError()
        messages = await uow.messages.list_owned(
            conversation_id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
        )
        responses: list[MessageResponse] = []
        for message in messages:
            citations = await uow.citations.list_for_message(
                message.id,
                tenant_id=identity.tenant_id,
                owner_user_id=identity.user_id,
            )
            responses.append(_message_response(message, citations))
    return MessagePageResponse(items=responses)


@router.post("/conversations/{conversation_id}/messages")
async def create_message_and_stream(
    conversation_id: UUID,
    payload: CreateMessageRequest,
    identity: CurrentIdentity,
    request: Request,
    coordinator: ChatCoordinatorDependency,
) -> StreamingResponse:
    session = await coordinator.prepare(
        tenant_id=identity.tenant_id,
        owner_user_id=identity.user_id,
        conversation_id=conversation_id,
        client_message_id=payload.client_message_id,
        content=payload.content,
    )
    request_id = str(request.state.request_id)
    return StreamingResponse(
        coordinator.stream(session, request_id=request_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/generations/{generation_id}/cancel",
    response_model=GenerationResponse,
)
async def cancel_generation(
    generation_id: UUID,
    identity: CurrentIdentity,
    coordinator: ChatCoordinatorDependency,
) -> GenerationResponse:
    run = await coordinator.cancel(
        generation_id,
        tenant_id=identity.tenant_id,
        owner_user_id=identity.user_id,
    )
    return generation_response(run)


@router.post(
    "/messages/{message_id}/retry",
    response_model=GenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_message(
    message_id: UUID,
    payload: RetryMessageRequest,
    identity: CurrentIdentity,
    request: Request,
    coordinator: ChatCoordinatorDependency,
) -> GenerationResponse:
    session = await coordinator.prepare_retry(
        tenant_id=identity.tenant_id,
        owner_user_id=identity.user_id,
        message_id=message_id,
        client_message_id=payload.client_message_id,
    )
    if not session.replay:
        async for _event in coordinator.stream(session, request_id=str(request.state.request_id)):
            pass
    run = await coordinator.get_generation(
        session.generation.id,
        tenant_id=identity.tenant_id,
        owner_user_id=identity.user_id,
    )
    return generation_response(run)


def _conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        expires_at=conversation.expires_at,
        version=conversation.version,
    )


def _message_response(message: Message, citations: list[CitationSnapshot]) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        status=message.status,
        parent_message_id=message.parent_message_id,
        retry_of_message_id=message.retry_of_message_id,
        model_provider=message.model_provider,
        model_name=message.model_name,
        retrieval_run_id=message.retrieval_run_id,
        completion_kind=message.completion_kind,
        grounded=message.grounded,
        citation_count=message.citation_count,
        citations=[
            CitationResponse(
                title=citation.title,
                url=citation.url,
                document_id=citation.document_id,
                content_hash=citation.content_hash,
                chunk_ids=list(citation.chunk_ids),
                tax_year=citation.tax_years[0],
                accessed_at=citation.source_accessed_at,
            )
            for citation in citations
        ],
        created_at=message.created_at,
        completed_at=message.completed_at,
    )
