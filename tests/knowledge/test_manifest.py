from pathlib import Path

import pytest
from pydantic import ValidationError

from sortax.knowledge import KnowledgeManifest, load_manifest

MANIFEST_PATH = Path(__file__).parents[2] / "manifests" / "ato" / "sources.yaml"


def test_phase_3b_manifest_loads_all_supported_claim_types() -> None:
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest.collection == "ato_knowledge_demo"
    assert manifest.defaults.tax_year == "2025-26"
    assert {source.claim_type for source in manifest.sources} == {
        "australian_bank_interest",
        "residential_rental_property",
        "salary_wages",
        "self_education",
        "work_related_car",
        "working_from_home",
    }
    assert {source.media_type for source in manifest.sources} == {
        "application/pdf",
        "text/html",
    }
    assert {
        source.local_path.name
        for source in manifest.sources
        if source.claim_type
        in {"salary_wages", "residential_rental_property", "australian_bank_interest"}
    } == {
        "salary-wages-income-statement.pdf",
        "rental-property-records.html",
        "bank-accounts-and-income-bonds.pdf",
    }


def test_manifest_rejects_non_ato_source() -> None:
    with pytest.raises(ValidationError):
        KnowledgeManifest.model_validate(
            {
                "version": 1,
                "collection": "ato_knowledge_demo",
                "defaults": {"tax_year": "2025-26", "accessed_at": "2026-10-04"},
                "sources": [
                    {
                        "document_id": "bad-source",
                        "title": "Bad source",
                        "source_url": "https://example.com/source",
                        "local_path": "data/ato/source.html",
                        "media_type": "text/html",
                        "claim_type": "working_from_home",
                    }
                ],
            }
        )
