import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from sortax.config import KnowledgeSettings, Settings
from sortax.knowledge.ports import KnowledgeChunk
from sortax.rag.models import VectorSearchHit


class MilvusClientLike(Protocol):
    def list_collections(self, *, timeout: float | None = None) -> list[str]: ...

    def has_collection(self, *, collection_name: str, timeout: float | None = None) -> bool: ...

    def create_collection(self, **kwargs: Any) -> None: ...

    def describe_collection(self, *, collection_name: str, **kwargs: Any) -> dict[str, Any]: ...

    def drop_collection(self, *, collection_name: str, **kwargs: Any) -> None: ...

    def query(self, **kwargs: Any) -> list[dict[str, Any]]: ...

    def search(self, **kwargs: Any) -> list[list[dict[str, Any]]]: ...

    def upsert(self, **kwargs: Any) -> Any: ...

    def delete(self, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...


MilvusClientFactory = Callable[..., MilvusClientLike]


class VectorStoreUnavailable(RuntimeError):
    """A normalized Milvus connectivity failure without SDK internals."""


class VectorStoreConfigurationError(RuntimeError):
    """An existing collection is incompatible with the configured embeddings."""


def _default_client_factory(**kwargs: Any) -> MilvusClientLike:
    from pymilvus import MilvusClient

    return cast(MilvusClientLike, MilvusClient(**kwargs))


class MilvusVectorStore:
    """Milvus lifecycle and ATO knowledge ingestion adapter."""

    def __init__(
        self,
        *,
        uri: str,
        database: str = "default",
        token: str | None = None,
        timeout_seconds: float = 5.0,
        client_factory: MilvusClientFactory = _default_client_factory,
    ) -> None:
        self._uri = uri
        self._database = database
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory
        self._client: MilvusClientLike | None = None

    @classmethod
    def from_settings(cls, settings: Settings | KnowledgeSettings) -> "MilvusVectorStore":
        token = settings.milvus_token.get_secret_value() if settings.milvus_token else None
        return cls(
            uri=settings.milvus_uri,
            database=settings.milvus_database,
            token=token,
            timeout_seconds=settings.milvus_connect_timeout_seconds,
        )

    async def connect(self) -> None:
        if self._client is not None:
            return

        options: dict[str, Any] = {
            "uri": self._uri,
            "db_name": self._database,
            "timeout": self._timeout_seconds,
        }
        if self._token:
            options["token"] = self._token

        client: MilvusClientLike | None = None
        try:
            client = await asyncio.to_thread(self._client_factory, **options)
            await asyncio.to_thread(
                client.list_collections,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            if client is not None:
                await asyncio.to_thread(client.close)
            raise VectorStoreUnavailable("Milvus is unavailable") from exc
        self._client = client

    async def healthcheck(self) -> bool:
        if self._client is None:
            return False
        try:
            await asyncio.to_thread(
                self._client.list_collections,
                timeout=self._timeout_seconds,
            )
        except Exception:
            return False
        return True

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await asyncio.to_thread(client.close)

    async def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        client = self._require_client()
        exists = await asyncio.to_thread(
            client.has_collection,
            collection_name=collection_name,
            timeout=self._timeout_seconds,
        )
        if not exists:
            await self._create_collection(client, collection_name, dimensions)
            return
        description = await asyncio.to_thread(
            client.describe_collection,
            collection_name=collection_name,
            timeout=self._timeout_seconds,
        )
        actual_dimension = _vector_dimension(description, "embedding")
        if actual_dimension != dimensions:
            raise VectorStoreConfigurationError(
                f"collection embedding dimension is {actual_dimension}, expected {dimensions}"
            )

    async def rebuild_collection(self, collection_name: str, dimensions: int) -> None:
        client = self._require_client()
        exists = await asyncio.to_thread(
            client.has_collection,
            collection_name=collection_name,
            timeout=self._timeout_seconds,
        )
        if exists:
            await asyncio.to_thread(
                client.drop_collection,
                collection_name=collection_name,
                timeout=self._timeout_seconds,
            )
        await self._create_collection(client, collection_name, dimensions)

    async def get_document_hashes(self, collection_name: str, document_id: str) -> set[str]:
        rows = await self._query_document(collection_name, document_id, ["content_hash"])
        return {str(row["content_hash"]) for row in rows if "content_hash" in row}

    async def get_document_embedding_models(
        self, collection_name: str, document_id: str
    ) -> set[str]:
        rows = await self._query_document(collection_name, document_id, ["embedding_model"])
        return {str(row["embedding_model"]) for row in rows if "embedding_model" in row}

    async def replace_document(
        self,
        collection_name: str,
        document_id: str,
        chunks: list[KnowledgeChunk],
    ) -> None:
        if not chunks:
            raise ValueError("at least one knowledge chunk is required")
        if any(chunk.document_id != document_id for chunk in chunks):
            raise ValueError("all chunks must belong to the requested document")
        client = self._require_client()
        old_rows = await self._query_document(collection_name, document_id, ["chunk_id"])
        old_ids = {str(row["chunk_id"]) for row in old_rows if "chunk_id" in row}
        imported_at = datetime.now(UTC).isoformat()
        entities = [
            {
                "chunk_id": chunk.chunk_id,
                "embedding": chunk.embedding,
                "document_id": chunk.document_id,
                "content_hash": chunk.content_hash,
                "text": chunk.text,
                "title": chunk.title,
                "source_url": chunk.source_url,
                "media_type": chunk.media_type,
                "claim_type": chunk.claim_type,
                "tax_year": chunk.tax_year,
                "accessed_at": chunk.accessed_at,
                "embedding_model": chunk.embedding_model,
                "parser_version": chunk.parser_version,
                "imported_at": imported_at,
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "section_path": chunk.section_path,
            }
            for chunk in chunks
        ]
        await asyncio.to_thread(
            client.upsert,
            collection_name=collection_name,
            data=entities,
            timeout=self._timeout_seconds,
        )
        stale_ids = sorted(old_ids - {chunk.chunk_id for chunk in chunks})
        if stale_ids:
            await asyncio.to_thread(
                client.delete,
                collection_name=collection_name,
                ids=stale_ids,
                timeout=self._timeout_seconds,
            )

    async def search(
        self,
        collection_name: str,
        vector: list[float],
        *,
        claim_type: str,
        tax_year: str,
        limit: int,
    ) -> list[VectorSearchHit]:
        if not vector:
            raise ValueError("query vector must not be empty")
        if limit <= 0:
            raise ValueError("search limit must be positive")
        client = self._require_client()
        safe_claim_type = _escape_filter_value(claim_type)
        safe_tax_year = _escape_filter_value(tax_year)
        output_fields = [
            "chunk_id",
            "document_id",
            "content_hash",
            "text",
            "title",
            "source_url",
            "claim_type",
            "tax_year",
            "accessed_at",
            "section_path",
        ]
        try:
            result = await asyncio.to_thread(
                client.search,
                collection_name=collection_name,
                data=[vector],
                anns_field="embedding",
                filter=(f'claim_type == "{safe_claim_type}" and tax_year == "{safe_tax_year}"'),
                limit=limit,
                output_fields=output_fields,
                search_params={"metric_type": "COSINE", "params": {}},
                consistency_level="Strong",
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            raise VectorStoreUnavailable("Milvus search is unavailable") from exc

        rows = result[0] if result else []
        hits: list[VectorSearchHit] = []
        try:
            for row in rows:
                entity = row.get("entity", row)
                score = row.get("distance", row.get("score"))
                if score is None:
                    raise ValueError("search result is missing a score")
                hits.append(
                    VectorSearchHit(
                        chunk_id=str(entity["chunk_id"]),
                        document_id=str(entity["document_id"]),
                        content_hash=str(entity["content_hash"]),
                        text=str(entity["text"]),
                        title=str(entity["title"]),
                        source_url=str(entity["source_url"]),
                        claim_type=str(entity["claim_type"]),
                        tax_year=str(entity["tax_year"]),
                        accessed_at=str(entity["accessed_at"]),
                        score=float(score),
                        section_path=(
                            str(entity["section_path"])
                            if entity.get("section_path") is not None
                            else None
                        ),
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise VectorStoreConfigurationError("Milvus returned invalid search metadata") from exc
        return hits

    async def _query_document(
        self, collection_name: str, document_id: str, output_fields: list[str]
    ) -> list[dict[str, Any]]:
        client = self._require_client()
        escaped_document_id = document_id.replace("\\", "\\\\").replace('"', '\\"')
        return await asyncio.to_thread(
            client.query,
            collection_name=collection_name,
            filter=f'document_id == "{escaped_document_id}"',
            output_fields=output_fields,
            consistency_level="Strong",
            timeout=self._timeout_seconds,
        )

    async def _create_collection(
        self, client: MilvusClientLike, collection_name: str, dimensions: int
    ) -> None:
        await asyncio.to_thread(
            client.create_collection,
            collection_name=collection_name,
            dimension=dimensions,
            primary_field_name="chunk_id",
            id_type="string",
            vector_field_name="embedding",
            metric_type="COSINE",
            auto_id=False,
            max_length=512,
            enable_dynamic_field=True,
            consistency_level="Strong",
            timeout=self._timeout_seconds,
        )

    def _require_client(self) -> MilvusClientLike:
        if self._client is None:
            raise VectorStoreUnavailable("Milvus is not connected")
        return self._client


def _vector_dimension(description: dict[str, Any], field_name: str) -> int | None:
    for field in description.get("fields", []):
        if field.get("name") == field_name:
            raw_dimension = field.get("params", {}).get("dim")
            try:
                return int(raw_dimension)
            except (TypeError, ValueError):
                return None
    return None


def _escape_filter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
