from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    chunk_id: str
    document_id: str
    content_hash: str
    text: str
    embedding: list[float]
    title: str
    source_url: str
    media_type: str
    claim_type: str
    tax_year: str
    accessed_at: str
    embedding_model: str
    parser_version: str
    chunk_index: int
    page_number: int | None
    section_path: str | None


class KnowledgeVectorStore(Protocol):
    async def ensure_collection(self, collection_name: str, dimensions: int) -> None: ...

    async def rebuild_collection(self, collection_name: str, dimensions: int) -> None: ...

    async def get_document_hashes(self, collection_name: str, document_id: str) -> set[str]: ...

    async def get_document_embedding_models(
        self, collection_name: str, document_id: str
    ) -> set[str]: ...

    async def replace_document(
        self,
        collection_name: str,
        document_id: str,
        chunks: list[KnowledgeChunk],
    ) -> None: ...
