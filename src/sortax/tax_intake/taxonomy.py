from collections.abc import Sequence
from typing import Final, Literal

type ClaimType = Literal[
    "salary_wages",
    "working_from_home",
    "work_related_car",
    "self_education",
    "residential_rental_property",
    "australian_bank_interest",
]

SUPPORTED_TAX_YEAR: Final = "2025-26"
SUPPORTED_CLAIM_TYPES: Final[tuple[ClaimType, ...]] = (
    "salary_wages",
    "working_from_home",
    "work_related_car",
    "self_education",
    "residential_rental_property",
    "australian_bank_interest",
)

# The limited-service questionnaire uses the domain claim codes as its stable
# option codes. Keeping this mapping explicit prevents the frontend or an LLM
# from silently expanding the supported tax scope.
QUESTIONNAIRE_OPTION_TO_CLAIM_TYPE: Final[dict[str, ClaimType]] = {
    claim_type: claim_type for claim_type in SUPPORTED_CLAIM_TYPES
}


class UnsupportedQuestionnaireOptionError(ValueError):
    """A questionnaire selection is not part of the versioned limited scope."""


def map_questionnaire_options(option_codes: Sequence[str]) -> tuple[ClaimType, ...]:
    """Map supported option codes to unique claim types in selection order."""

    claim_types: list[ClaimType] = []
    seen: set[ClaimType] = set()
    for option_code in option_codes:
        try:
            claim_type = QUESTIONNAIRE_OPTION_TO_CLAIM_TYPE[option_code]
        except KeyError as exc:
            raise UnsupportedQuestionnaireOptionError(
                f"unsupported questionnaire option: {option_code}"
            ) from exc
        if claim_type not in seen:
            seen.add(claim_type)
            claim_types.append(claim_type)
    return tuple(claim_types)
