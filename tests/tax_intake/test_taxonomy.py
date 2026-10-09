import pytest

from sortax.tax_intake import (
    SUPPORTED_CLAIM_TYPES,
    UnsupportedQuestionnaireOptionError,
    map_questionnaire_options,
)


def test_questionnaire_options_map_to_all_supported_claim_types_in_stable_order() -> None:
    selections = (
        "working_from_home",
        "salary_wages",
        "working_from_home",
        "residential_rental_property",
        "work_related_car",
        "self_education",
        "australian_bank_interest",
    )

    assert map_questionnaire_options(selections) == (
        "working_from_home",
        "salary_wages",
        "residential_rental_property",
        "work_related_car",
        "self_education",
        "australian_bank_interest",
    )
    assert set(map_questionnaire_options(SUPPORTED_CLAIM_TYPES)) == set(SUPPORTED_CLAIM_TYPES)


def test_questionnaire_mapping_rejects_unknown_option() -> None:
    with pytest.raises(UnsupportedQuestionnaireOptionError, match="overseas_income"):
        map_questionnaire_options(("salary_wages", "overseas_income"))
