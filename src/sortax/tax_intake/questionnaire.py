from collections.abc import Sequence
from typing import Final

from sortax.tax_intake.models import QuestionnaireOption, QuestionnaireQuestion
from sortax.tax_intake.taxonomy import ClaimType, map_questionnaire_options

QUESTIONNAIRE_VERSION: Final = "limited-tax-2025-26-v1"
NONE_OPTION: Final = "none"

QUESTIONNAIRE: Final[tuple[QuestionnaireQuestion, ...]] = (
    QuestionnaireQuestion(
        key="first_tax_return",
        order=1,
        prompt="Is this your first Australian tax return?",
        question_type="single",
        options=(
            QuestionnaireOption(code="yes", label="Yes, this is my first return"),
            QuestionnaireOption(code="no", label="No, I have lodged before"),
        ),
    ),
    QuestionnaireQuestion(
        key="work_expenses",
        order=2,
        prompt="Which work-related expenses did you have?",
        question_type="multiple",
        options=(
            QuestionnaireOption(code="working_from_home", label="Working from home"),
            QuestionnaireOption(code="work_related_car", label="Work-related car expenses"),
            QuestionnaireOption(code="self_education", label="Self-education expenses"),
            QuestionnaireOption(code=NONE_OPTION, label="None of these"),
        ),
    ),
    QuestionnaireQuestion(
        key="income_sources",
        order=3,
        prompt="Which income did you receive?",
        question_type="multiple",
        options=(
            QuestionnaireOption(code="salary_wages", label="Salary or wages / PAYG"),
            QuestionnaireOption(
                code="residential_rental_property", label="Residential rental property"
            ),
            QuestionnaireOption(code="australian_bank_interest", label="Australian bank interest"),
            QuestionnaireOption(code=NONE_OPTION, label="None of these"),
        ),
    ),
)


class QuestionnaireValidationError(ValueError):
    pass


def validate_answer(question_key: str, option_codes: Sequence[str]) -> list[str]:
    question = next((item for item in QUESTIONNAIRE if item.key == question_key), None)
    if question is None:
        raise QuestionnaireValidationError("unknown question_key")
    normalized = list(dict.fromkeys(option_codes))
    if not normalized:
        raise QuestionnaireValidationError("at least one option is required")
    if question.question_type == "single" and len(normalized) != 1:
        raise QuestionnaireValidationError("single-select questions require one option")
    allowed = {option.code for option in question.options}
    if any(option not in allowed for option in normalized):
        raise QuestionnaireValidationError("answer contains an unknown option")
    if NONE_OPTION in normalized and len(normalized) != 1:
        raise QuestionnaireValidationError("none is mutually exclusive")
    return normalized


def current_step(answers: dict[str, list[str]]) -> int:
    for index, question in enumerate(QUESTIONNAIRE):
        if question.required and question.key not in answers:
            return index
    return len(QUESTIONNAIRE)


def require_complete(answers: dict[str, list[str]]) -> None:
    if current_step(answers) != len(QUESTIONNAIRE):
        raise QuestionnaireValidationError("all required questions must be answered")


def selected_claim_types(answers: dict[str, list[str]]) -> tuple[ClaimType, ...]:
    require_complete(answers)
    options = [
        option
        for question in QUESTIONNAIRE
        for option in answers.get(question.key, [])
        if option != NONE_OPTION
        and option
        in {
            "salary_wages",
            "working_from_home",
            "work_related_car",
            "self_education",
            "residential_rental_property",
            "australian_bank_interest",
        }
    ]
    return map_questionnaire_options(options)
