from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sortax.tax_intake.models import (
    QuestionnaireQuestion,
    TaxIntakeAnswer,
    TaxIntakeSession,
)
from sortax.tax_intake.models import TaxIntakeResponse as TaxIntakeResponse


def tax_intake_response(
    intake: TaxIntakeSession,
    questions: tuple[QuestionnaireQuestion, ...],
) -> TaxIntakeResponse:
    return TaxIntakeResponse(
        id=intake.id,
        conversation_id=intake.conversation_id,
        template_version=intake.template_version,
        tax_year=intake.tax_year,
        status=intake.workflow_status,
        current_step=min(intake.current_step + 1, len(questions)),
        questions=questions,
        answers=[
            TaxIntakeAnswer(
                question_key=question.key,
                selected_options=list(intake.answers[question.key]),
                updated_at=intake.answer_updated_at.get(question.key, intake.updated_at),
            )
            for question in questions
            if question.key in intake.answers
        ],
        version=intake.version,
        created_at=intake.created_at,
        updated_at=intake.updated_at,
        completed_at=intake.completed_at,
    )


class SaveAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_options: list[str] = Field(min_length=1)
    version: int = Field(ge=1)


class IntakeActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_request_id: UUID
    version: int = Field(ge=1)


class SummaryRequest(IntakeActionRequest):
    requested: bool
