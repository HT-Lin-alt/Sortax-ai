from typing import Any

import pytest

from sortax.infrastructure.milvus import (
    MilvusVectorStore,
    VectorStoreConfigurationError,
    VectorStoreUnavailable,
)
from sortax.knowledge.ports import KnowledgeChunk


class FakeMilvusClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.closed = False
        self.timeouts: list[float | None] = []

    def list_collections(self, *, timeout: float | None = None) -> list[str]:
        self.timeouts.append(timeout)
        if self.fail:
            raise RuntimeError("sdk detail must remain internal")
        return ["ato_knowledge_demo"]

    def close(self) -> None:
        self.closed = True


class FakeIngestionMilvusClient(FakeMilvusClient):
    def __init__(self, *, exists: bool = False, dimension: int = 8) -> None:
        super().__init__()
        self.exists = exists
        self.dimension = dimension
        self.created: list[dict[str, Any]] = []
        self.dropped: list[str] = []
        self.rows: list[dict[str, Any]] = []
        self.deleted_ids: list[str] = []
        self.search_results: list[list[dict[str, Any]]] = []
        self.search_calls: list[dict[str, Any]] = []

    def has_collection(self, *, collection_name: str, timeout: float | None = None) -> bool:
        return self.exists

    def create_collection(self, **kwargs: Any) -> None:
        self.created.append(kwargs)
        self.exists = True
        self.dimension = kwargs["dimension"]

    def describe_collection(self, *, collection_name: str, **kwargs: Any) -> dict[str, Any]:
        return {"fields": [{"name": "embedding", "params": {"dim": str(self.dimension)}}]}

    def drop_collection(self, *, collection_name: str, **kwargs: Any) -> None:
        self.dropped.append(collection_name)
        self.exists = False
        self.rows.clear()

    def query(self, **kwargs: Any) -> list[dict[str, Any]]:
        document_id = kwargs["filter"].split('"')[1]
        fields = kwargs["output_fields"]
        return [
            {field: row[field] for field in fields}
            for row in self.rows
            if row["document_id"] == document_id
        ]

    def upsert(self, **kwargs: Any) -> None:
        incoming = kwargs["data"]
        incoming_ids = {row["chunk_id"] for row in incoming}
        self.rows = [row for row in self.rows if row["chunk_id"] not in incoming_ids]
        self.rows.extend(incoming)

    def delete(self, **kwargs: Any) -> None:
        self.deleted_ids.extend(kwargs["ids"])
        self.rows = [row for row in self.rows if row["chunk_id"] not in kwargs["ids"]]

    def search(self, **kwargs: Any) -> list[list[dict[str, Any]]]:
        self.search_calls.append(kwargs)
        return self.search_results


@pytest.mark.asyncio
async def test_milvus_adapter_connects_checks_and_closes() -> None:
    client = FakeMilvusClient()
    received_options: dict[str, Any] = {}

    def factory(**options: Any) -> FakeMilvusClient:
        received_options.update(options)
        return client

    store = MilvusVectorStore(
        uri="http://milvus:19530",
        database="default",
        timeout_seconds=2.5,
        client_factory=factory,
    )

    await store.connect()

    assert received_options == {
        "uri": "http://milvus:19530",
        "db_name": "default",
        "timeout": 2.5,
    }
    assert await store.healthcheck() is True
    await store.close()
    assert client.closed is True


@pytest.mark.asyncio
async def test_milvus_adapter_normalizes_connection_failure() -> None:
    client = FakeMilvusClient(fail=True)
    store = MilvusVectorStore(
        uri="http://milvus:19530",
        client_factory=lambda **_options: client,
    )

    with pytest.raises(VectorStoreUnavailable, match="Milvus is unavailable"):
        await store.connect()

    assert client.closed is True
    assert await store.healthcheck() is False


@pytest.mark.asyncio
async def test_milvus_adapter_creates_expected_ingestion_collection() -> None:
    client = FakeIngestionMilvusClient()
    store = MilvusVectorStore(uri="http://milvus:19530", client_factory=lambda **_options: client)
    await store.connect()

    await store.ensure_collection("ato_knowledge_demo", 8)

    assert client.created[0]["primary_field_name"] == "chunk_id"
    assert client.created[0]["vector_field_name"] == "embedding"
    assert client.created[0]["metric_type"] == "COSINE"
    assert client.created[0]["dimension"] == 8


@pytest.mark.asyncio
async def test_milvus_adapter_rejects_existing_dimension_mismatch() -> None:
    client = FakeIngestionMilvusClient(exists=True, dimension=7)
    store = MilvusVectorStore(uri="http://milvus:19530", client_factory=lambda **_options: client)
    await store.connect()

    with pytest.raises(VectorStoreConfigurationError, match="expected 8"):
        await store.ensure_collection("ato_knowledge_demo", 8)


@pytest.mark.asyncio
async def test_milvus_replace_writes_new_chunks_before_deleting_stale_ids() -> None:
    client = FakeIngestionMilvusClient(exists=True)
    client.rows = [
        {
            "chunk_id": "doc:old:00000",
            "document_id": "doc",
            "content_hash": "sha256:old",
        }
    ]
    store = MilvusVectorStore(uri="http://milvus:19530", client_factory=lambda **_options: client)
    await store.connect()
    chunk = KnowledgeChunk(
        chunk_id="doc:new:00000",
        document_id="doc",
        content_hash="sha256:new",
        text="reviewed content",
        embedding=[0.1] * 8,
        title="Title",
        source_url="https://www.ato.gov.au/doc",
        media_type="text/html",
        claim_type="working_from_home",
        tax_year="2025-26",
        accessed_at="2026-10-04",
        embedding_model="fake-v1",
        parser_version="parser-v1",
        chunk_index=0,
        page_number=None,
        section_path="Title",
    )

    await store.replace_document("ato_knowledge_demo", "doc", [chunk])

    assert client.deleted_ids == ["doc:old:00000"]
    assert [row["chunk_id"] for row in client.rows] == ["doc:new:00000"]


@pytest.mark.asyncio
async def test_milvus_search_filters_claim_and_year_and_maps_metadata() -> None:
    client = FakeIngestionMilvusClient(exists=True)
    client.search_results = [
        [
            {
                "distance": 0.91,
                "entity": {
                    "chunk_id": "car:hash:00000",
                    "document_id": "car",
                    "content_hash": "sha256:hash",
                    "text": "Keep a logbook and written evidence.",
                    "title": "Car expenses",
                    "source_url": "https://www.ato.gov.au/car",
                    "claim_type": "work_related_car",
                    "tax_year": "2025-26",
                    "accessed_at": "2026-10-04",
                    "section_path": "Records",
                },
            }
        ]
    ]
    store = MilvusVectorStore(uri="http://milvus:19530", client_factory=lambda **_options: client)
    await store.connect()

    hits = await store.search(
        "ato_knowledge_demo",
        [0.1] * 8,
        claim_type="work_related_car",
        tax_year="2025-26",
        limit=5,
    )

    assert len(hits) == 1
    assert hits[0].chunk_id == "car:hash:00000"
    assert hits[0].score == 0.91
    call = client.search_calls[0]
    assert call["filter"] == 'claim_type == "work_related_car" and tax_year == "2025-26"'
    assert call["limit"] == 5
