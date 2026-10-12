from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sortax.tax_intake.taxonomy import SUPPORTED_TAX_YEAR

WorkflowStatus = Literal[
    "questionnaire_active",
    "questionnaire_completed",
    "retrieving_documents",
    "checklist_ready",
    "awaiting_summary_confirmation",
    "summary_declined",
    "generating_summary",
    "summary_completed",
    "cancelled",
    "failed",
]
TaxQuestionType = Literal["single", "multiple"]


class QuestionnaireOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    label: str


class QuestionnaireQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    order: int = Field(ge=1, le=3)
    prompt: str
    question_type: TaxQuestionType
    required: bool = True
    options: tuple[QuestionnaireOption, ...]


class TaxIntakeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_key: str
    selected_options: list[str] = Field(min_length=1)
    updated_at: datetime


class TaxIntakeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    template_version: str
    tax_year: str
    status: WorkflowStatus
    current_step: int = Field(ge=1, le=3)
    questions: tuple[QuestionnaireQuestion, ...]
    answers: list[TaxIntakeAnswer]
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class QuestionnaireContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["questionnaire"]
    tax_intake: TaxIntakeResponse


class ChecklistItemContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    ordinal: int = Field(ge=1)
    claim_type: str
    document_name: str
    plain_language_explanation: str
    how_to_obtain: str
    applies_because: str
    citation_ordinals: list[int] = Field(min_length=1)


class DocumentChecklistContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["document_checklist"]
    tax_intake_id: UUID
    tax_year: str
    items: list[ChecklistItemContent] = Field(min_length=1)
    summary_confirmation: "SummaryConfirmationContent"

    @model_validator(mode="after")
    def unique_ordinals(self) -> "DocumentChecklistContent":
        ordinals = [item.ordinal for item in self.items]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("checklist item ordinals must be unique")
        return self


class SummaryConfirmationContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["summary_confirmation"]
    tax_intake_id: UUID
    prompt: str


class TaxSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str
    plain_language_text: str
    citation_ordinals: list[int] = Field(min_length=1)


class TaxSummaryContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tax_summary"]
    tax_intake_id: UUID
    tax_year: str
    sections: list[TaxSummarySection] = Field(min_length=1)
    disclaimer: str


@dataclass(frozen=True, slots=True)
class TaxIntakeSession:
    id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    conversation_id: UUID
    template_version: str
    tax_year: str
    workflow_status: WorkflowStatus
    current_step: int
    answers: dict[str, list[str]]
    answer_updated_at: dict[str, datetime]
    version: int
    summary_requested: bool | None
    checklist_message_id: UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    id: UUID
    tenant_id: UUID
    message_id: UUID
    ordinal: int
    claim_type: str
    document_name: str
    plain_language_explanation: str
    how_to_obtain: str
    applies_because: str
    citation_ordinals: tuple[int, ...]


TAX_INTAKE_TAX_YEAR = SUPPORTED_TAX_YEAR
