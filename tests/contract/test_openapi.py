from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

OPENAPI_PATH = Path(__file__).parents[2] / "docs" / "openapi.yaml"
ATO_MANIFEST_PATH = Path(__file__).parents[2] / "manifests" / "ato" / "sources.yaml"
DEMO_QUESTIONS_PATH = Path(__file__).parents[2] / "manifests" / "ato" / "demo-questions.yaml"


def load_contract() -> dict[str, Any]:
    with OPENAPI_PATH.open(encoding="utf-8") as contract_file:
        contract: dict[str, Any] = yaml.safe_load(contract_file)
    return contract


def walk_local_refs(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            yield reference
        for child in value.values():
            yield from walk_local_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_local_refs(child)


def resolve_local_ref(contract: dict[str, Any], reference: str) -> Any:
    current: Any = contract
    for segment in reference.removeprefix("#/").split("/"):
        current = current[segment]
    return current


def test_openapi_contract_is_version_3_1() -> None:
    contract = load_contract()

    assert contract["openapi"] == "3.1.0"
    assert contract["info"]["version"] == "0.2.0"


def test_all_local_references_resolve() -> None:
    contract = load_contract()
    references = list(walk_local_refs(contract))

    assert references
    for reference in references:
        assert resolve_local_ref(contract, reference) is not None


def test_operation_ids_are_present_and_unique() -> None:
    contract = load_contract()
    http_methods = {"get", "post", "put", "patch", "delete"}
    operations = [
        operation
        for path_item in contract["paths"].values()
        for method, operation in path_item.items()
        if method in http_methods
    ]
    operation_ids = [operation.get("operationId") for operation in operations]

    assert all(operation_ids)
    assert len(operation_ids) == len(set(operation_ids))


def test_phase_0r_rag_contract_is_explicit() -> None:
    contract = load_contract()
    schemas = contract["components"]["schemas"]
    error_codes = schemas["Error"]["properties"]["code"]["enum"]
    create_message = contract["paths"]["/api/v1/conversations/{conversation_id}/messages"]["post"]

    assert "Citation" in schemas
    assert "retrieval_unavailable" in error_codes
    assert "insufficient_evidence" in error_codes
    assert set(create_message["x-sse-event-schemas"]) >= {
        "retrieval.started",
        "retrieval.completed",
        "message.completed",
        "message.failed",
    }

    message_properties = schemas["Message"]["properties"]
    assert message_properties["citations"]["items"]["$ref"] == "#/components/schemas/Citation"
    assert message_properties["retrieval_run_id"]["format"] == "uuid"


def test_ato_demo_manifest_has_reviewable_official_sources() -> None:
    manifest = yaml.safe_load(ATO_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["version"] == 1
    assert manifest["collection"] == "ato_knowledge_demo"
    assert manifest["defaults"]["tax_year"] == "2025-26"
    assert manifest["defaults"]["accessed_at"]
    assert {source["media_type"] for source in manifest["sources"]} == {
        "application/pdf",
        "text/html",
    }
    assert {source["claim_type"] for source in manifest["sources"]} == {
        "self_education",
        "work_related_car",
        "working_from_home",
    }

    document_ids = [source["document_id"] for source in manifest["sources"]]
    assert len(document_ids) == len(set(document_ids))
    for source in manifest["sources"]:
        assert urlparse(source["source_url"]).hostname == "www.ato.gov.au"
        assert not Path(source["local_path"]).is_absolute()
        assert Path(source["local_path"]).parts[:2] == ("data", "ato")


def test_demo_questions_cover_success_clarification_and_failure() -> None:
    suite = yaml.safe_load(DEMO_QUESTIONS_PATH.read_text(encoding="utf-8"))
    questions = suite["questions"]

    assert 5 <= len(questions) <= 10
    assert len({question["id"] for question in questions}) == len(questions)
    outcomes = {question["expected"] for question in questions}
    assert outcomes == {"grounded", "clarification", "insufficient_evidence"}
    assert all(question["prompt"].strip() for question in questions)
