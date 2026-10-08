import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

from sortax.embedding_gateway import EmbeddingProvider, EmbeddingProviderError
from sortax.knowledge.manifest import load_manifest
from sortax.knowledge.parsing import (
    DocumentParseError,
    chunk_document,
    parse_document,
    read_source,
    resolve_source_path,
    validate_extension,
)
from sortax.knowledge.ports import KnowledgeChunk, KnowledgeVectorStore

PARSER_VERSION = "sortax-parser-v2"


@dataclass(frozen=True, slots=True)
class IngestionFailure:
    document_id: str
    reason: str


@dataclass(slots=True)
class IngestionSummary:
    collection: str
    dry_run: bool
    documents_seen: int = 0
    documents_ready: int = 0
    documents_imported: int = 0
    documents_skipped: int = 0
    chunks_ready: int = 0
    chunks_written: int = 0
    ready_document_ids: list[str] = field(default_factory=list)
    imported_document_ids: list[str] = field(default_factory=list)
    skipped_document_ids: list[str] = field(default_factory=list)
    failures: list[IngestionFailure] = field(default_factory=list)

    @property
    def documents_failed(self) -> int:
        return len(self.failures)

    def to_dict(self) -> dict[str, object]:
        return {
            "collection": self.collection,
            "dry_run": self.dry_run,
            "documents_seen": self.documents_seen,
            "documents_ready": self.documents_ready,
            "documents_imported": self.documents_imported,
            "documents_skipped": self.documents_skipped,
            "documents_failed": self.documents_failed,
            "chunks_ready": self.chunks_ready,
            "chunks_written": self.chunks_written,
            "ready_document_ids": self.ready_document_ids,
            "imported_document_ids": self.imported_document_ids,
            "skipped_document_ids": self.skipped_document_ids,
            "failures": [
                {"document_id": item.document_id, "reason": item.reason} for item in self.failures
            ],
        }


async def ingest_manifest(
    manifest_path: Path,
    *,
    data_dir: Path,
    project_root: Path,
    provider: EmbeddingProvider | None,
    store: KnowledgeVectorStore | None,
    dry_run: bool = False,
    rebuild: bool = False,
    max_file_bytes: int = 10_485_760,
    chunk_size: int = 1200,
    chunk_overlap: int = 200,
    expected_collection: str | None = None,
) -> IngestionSummary:
    """Validate and import every source, isolating failures to individual documents."""

    manifest = load_manifest(manifest_path)
    if expected_collection is not None and manifest.collection != expected_collection:
        raise ValueError("manifest collection does not match configured Milvus collection")
    if not dry_run and (provider is None or store is None):
        raise ValueError("an embedding provider and vector store are required for ingestion")

    summary = IngestionSummary(collection=manifest.collection, dry_run=dry_run)
    if not dry_run:
        if provider is None or store is None:
            raise ValueError("an embedding provider and vector store are required for ingestion")
        if rebuild:
            await store.rebuild_collection(manifest.collection, provider.dimensions)
        else:
            await store.ensure_collection(manifest.collection, provider.dimensions)

    for source in manifest.sources:
        summary.documents_seen += 1
        try:
            path = resolve_source_path(
                source.local_path,
                data_dir=data_dir,
                project_root=project_root,
            )
            validate_extension(path, source.media_type)
            content = read_source(path, max_file_bytes=max_file_bytes)
            content_hash = f"sha256:{hashlib.sha256(content).hexdigest()}"
            document = parse_document(content, source.media_type)
            text_chunks = chunk_document(
                document,
                max_chars=chunk_size,
                overlap_chars=chunk_overlap,
            )
            summary.documents_ready += 1
            summary.chunks_ready += len(text_chunks)
            summary.ready_document_ids.append(source.document_id)

            if dry_run:
                continue
            if provider is None or store is None:
                raise ValueError(
                    "an embedding provider and vector store are required for ingestion"
                )
            existing_hashes = await store.get_document_hashes(
                manifest.collection, source.document_id
            )
            existing_models = await store.get_document_embedding_models(
                manifest.collection, source.document_id
            )
            if existing_hashes == {content_hash} and existing_models == {provider.model_name}:
                summary.documents_skipped += 1
                summary.skipped_document_ids.append(source.document_id)
                continue

            embeddings = await provider.embed_documents([chunk.text for chunk in text_chunks])
            _validate_embeddings(embeddings, len(text_chunks), provider.dimensions)
            hash_fragment = content_hash.removeprefix("sha256:")[:20]
            records = [
                KnowledgeChunk(
                    chunk_id=f"{source.document_id}:{hash_fragment}:{index:05d}",
                    document_id=source.document_id,
                    content_hash=content_hash,
                    text=chunk.text,
                    embedding=embedding,
                    title=source.title,
                    source_url=str(source.source_url),
                    media_type=source.media_type,
                    claim_type=source.claim_type,
                    tax_year=manifest.defaults.tax_year,
                    accessed_at=manifest.defaults.accessed_at,
                    embedding_model=provider.model_name,
                    parser_version=PARSER_VERSION,
                    chunk_index=index,
                    page_number=chunk.page_number,
                    section_path=chunk.section_path or source.title,
                )
                for index, (chunk, embedding) in enumerate(
                    zip(text_chunks, embeddings, strict=True)
                )
            ]
            await store.replace_document(manifest.collection, source.document_id, records)
            summary.documents_imported += 1
            summary.chunks_written += len(records)
            summary.imported_document_ids.append(source.document_id)
        except Exception as exc:
            reason = _safe_failure_reason(exc)
            summary.failures.append(IngestionFailure(document_id=source.document_id, reason=reason))
    return summary


def _validate_embeddings(
    embeddings: list[list[float]], expected_count: int, expected_dimensions: int
) -> None:
    if len(embeddings) != expected_count:
        raise ValueError("embedding provider returned an unexpected item count")
    if any(len(vector) != expected_dimensions for vector in embeddings):
        raise ValueError("embedding provider returned an unexpected dimension")
    if any(not math.isfinite(value) for vector in embeddings for value in vector):
        raise ValueError("embedding provider returned a non-finite value")


def _safe_failure_reason(exc: Exception) -> str:
    if isinstance(exc, (DocumentParseError, EmbeddingProviderError, ValueError)):
        return str(exc).strip() or "document ingestion failed"
    return "document ingestion failed"
