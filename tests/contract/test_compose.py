from pathlib import Path
from typing import Any

import yaml

COMPOSE_PATH = Path(__file__).parents[2] / "compose.yaml"


def load_compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_compose_defines_pinned_milvus_standalone_stack() -> None:
    compose = load_compose()
    services = compose["services"]

    assert services["milvus"]["image"] == "milvusdb/milvus:v3.0.2"
    assert services["etcd"]["image"] == "quay.io/coreos/etcd:v3.5.25"
    assert services["minio"]["image"] == "milvusdb/minio:RELEASE.2024-12-18T13-15-44Z"
    assert services["milvus"]["depends_on"] == {
        "etcd": {"condition": "service_healthy"},
        "minio": {"condition": "service_healthy"},
    }
    assert "19530:19530" in services["milvus"]["ports"]


def test_api_waits_for_milvus_and_uses_internal_uri() -> None:
    compose = load_compose()
    api = compose["services"]["api"]
    environment = compose["x-app-environment"]

    assert api["depends_on"]["milvus"] == {"condition": "service_healthy"}
    assert "alembic upgrade head" in " ".join(api["command"])
    assert environment["SORTAX_MILVUS_URI"] == "http://milvus:19530"
    assert environment["SORTAX_EMBEDDING_PROVIDER"] == "fake"
