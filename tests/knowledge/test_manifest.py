from pathlib import Path

import pytest
from pydantic import ValidationError

from sortax.knowledge import KnowledgeManifest, load_manifest

MANIFEST_PATH = Path(__file__).parents[2] / "manifests" / "ato" / "sources.yaml"


def test_phase_0r_manifest_loads_into_domain_model() -> None:
    manifest = load_manifest(MANIFEST_PATH)

    assert manifest.collection == "ato_knowledge_demo"
    assert manifest.defaults.tax_year == "2025-26"
    assert {source.claim_type for source in manifest.sources} == {
        "self_education",
        "work_related_car",
        "working_from_home",
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
