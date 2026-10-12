from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from sortax.api.errors import AppError, ConflictError, NotFoundError, ServiceUnavailableError
from sortax.identity.dependencies import CurrentIdentity
from sortax.infrastructure.persistence import PersistenceUnitOfWork
from sortax.infrastructure.persistence.repositories import (
    IdempotencyConflictError,
    OptimisticLockError,
)
from sortax.tax_intake.api_models import (
    IntakeActionRequest,
    SaveAnswerRequest,
    SummaryRequest,
    TaxIntakeResponse,
    tax_intake_response,
)
from sortax.tax_intake.models import TaxIntakeSession
from sortax.tax_intake.questionnaire import (
    QUESTIONNAIRE,
    QuestionnaireValidationError,
    current_step,
    validate_answer,
)
from sortax.tax_intake.service import TaxWorkflowCoordinator

router = APIRouter(tags=["tax-intake"])


def get_tax_workflow_coordinator(request: Request) -> TaxWorkflowCoordinator:
    coordinator = getattr(request.app.state, "tax_workflow_coordinator", None)
    if coordinator is None:
        raise ServiceUnavailableError(
            "configuration_error", "Tax workflow persistence is not configured"
        )
    return cast(TaxWorkflowCoordinator, coordinator)


TaxWorkflowDependency = Annotated[TaxWorkflowCoordinator, Depends(get_tax_workflow_coordinator)]


def _session_factory(request: Request):  # type: ignore[no-untyped-def]
    factory = request.app.state.session_factory
    if factory is None:
        raise ServiceUnavailableError("configuration_error", "Database is not configured")
    return factory


@router.get("/tax-intakes/{intake_id}", response_model=TaxIntakeResponse)
async def get_tax_intake(
    intake_id: UUID,
    identity: CurrentIdentity,
    request: Request,
) -> TaxIntakeResponse:
    async with PersistenceUnitOfWork(_session_factory(request)) as uow:
        intake = await uow.tax_intakes.get_owned(
            intake_id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
        )
    if intake is None:
        raise NotFoundError()
    return _response(intake)


@router.put("/tax-intakes/{intake_id}/answers/{question_key}", response_model=TaxIntakeResponse)
async def save_tax_intake_answer(
    intake_id: UUID,
    question_key: str,
    payload: SaveAnswerRequest,
    identity: CurrentIdentity,
    request: Request,
) -> TaxIntakeResponse:
    try:
        option_codes = validate_answer(question_key, payload.selected_options)
    except QuestionnaireValidationError as exc:
        raise AppError(
            status_code=422,
            code="invalid_questionnaire_answer",
            message=str(exc),
        ) from exc
    async with PersistenceUnitOfWork(_session_factory(request)) as uow:
        existing = await uow.tax_intakes.get_owned(
            intake_id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
        )
        if existing is None:
            raise NotFoundError()
        answers = {**existing.answers, question_key: option_codes}
        try:
            intake = await uow.tax_intakes.save_answer(
                intake_id,
                tenant_id=identity.tenant_id,
                owner_user_id=identity.user_id,
                question_key=question_key,
                option_codes=option_codes,
                current_step=current_step(answers),
                expected_version=payload.version,
            )
        except OptimisticLockError as exc:
            raise ConflictError(
                "version_conflict", "The tax intake version is stale; reload and retry"
            ) from exc
        except IdempotencyConflictError as exc:
            raise ConflictError(
                "invalid_workflow_state", "The questionnaire is no longer editable"
            ) from exc
        if intake is None:
            raise NotFoundError()
        await uow.commit()
    return _response(intake)


@router.post("/tax-intakes/{intake_id}/complete")
async def complete_tax_intake(
    intake_id: UUID,
    payload: IntakeActionRequest,
    identity: CurrentIdentity,
    request: Request,
    coordinator: TaxWorkflowDependency,
) -> StreamingResponse:
    try:
        session, intake = await coordinator.prepare_complete(
            intake_id=intake_id,
            tenant_id=identity.tenant_id,
            owner_user_id=identity.user_id,
            client_request_id=payload.client_request_id,
            expected_version=payload.version,
        )
    except QuestionnaireValidationError as exc:
        raise AppError(
            status_code=422,
            code="questionnaire_incomplete",
            message=str(exc),
        ) from exc
    return StreamingResponse(
        coordinator.stream_complete(
            session,
            intake,
            request_id=str(request.state.request_id),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/tax-intakes/{intake_id}/summary")
async def handle_tax_summary(
    intake_id: UUID,
    payload: SummaryRequest,
    identity: CurrentIdentity,
    request: Request,
    coordinator: TaxWorkflowDependency,
) -> StreamingResponse:
    session, intake = await coordinator.prepare_summary(
        intake_id=intake_id,
        tenant_id=identity.tenant_id,
        owner_user_id=identity.user_id,
        client_request_id=payload.client_request_id,
        requested=payload.requested,
        expected_version=payload.version,
    )
    return StreamingResponse(
        coordinator.stream_summary(
            session,
            intake,
            requested=payload.requested,
            request_id=str(request.state.request_id),
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _response(intake: TaxIntakeSession) -> TaxIntakeResponse:
    return tax_intake_response(intake, QUESTIONNAIRE)
