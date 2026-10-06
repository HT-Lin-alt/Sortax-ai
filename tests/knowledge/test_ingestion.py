from pathlib import Path

import pytest

from sortax.embedding_gateway import FakeEmbeddingProvider
from sortax.knowledge.ingestion import ingest_manifest
from sortax.knowledge.ports import KnowledgeChunk


class MemoryKnowledgeStore:
    def __init__(self) -> None:
        self.documents: dict[str, list[KnowledgeChunk]] = {}
        self.ensure_calls = 0
        self.rebuild_calls = 0
        self.replace_calls = 0

    async def ensure_collection(self, collection_name: str, dimensions: int) -> None:
        assert collection_name == "ato_knowledge_demo"
        assert dimensions == 8
        self.ensure_calls += 1

    async def rebuild_collection(self, collection_name: str, dimensions: int) -> None:
        self.documents.clear()
        self.rebuild_calls += 1

    async def get_document_hashes(self, collection_name: str, document_id: str) -> set[str]:
        return {chunk.content_hash for chunk in self.documents.get(document_id, [])}

    async def get_document_embedding_models(
        self, collection_name: str, document_id: str
    ) -> set[str]:
        return {chunk.embedding_model for chunk in self.documents.get(document_id, [])}

    async def replace_document(
        self,
        collection_name: str,
        document_id: str,
        chunks: list[KnowledgeChunk],
    ) -> None:
        self.documents[document_id] = chunks
        self.replace_calls += 1


def _write_manifest(root: Path, *, include_missing: bool = False) -> Path:
    manifest = root / "manifest.yaml"
    missing = (
        """
  - document_id: missing-source
    title: Missing source
    source_url: https://www.ato.gov.au/missing
    local_path: data/ato/missing.txt
    media_type: text/plain
    claim_type: self_education
"""
        if include_missing
        else ""
    )
    manifest.write_text(
        """version: 1
collection: ato_knowledge_demo
defaults:
  tax_year: "2025-26"
  accessed_at: "2026-10-04"
sources:
  - document_id: working-from-home
    title: Working from home
    source_url: https://www.ato.gov.au/working-from-home
    local_path: data/ato/source.html
    media_type: text/html
    claim_type: working_from_home
"""
        + missing,
        encoding="utf-8",
    )
    return manifest


@pytest.mark.asyncio
async def test_ingestion_imports_then_skips_unchanged_document(tmp_path: Path) -> None:
    data_dir = tmp_path / "data" / "ato"
    data_dir.mkdir(parents=True)
    source = data_dir / "source.html"
    source.write_text("<h1>ATO</h1><p>Eligible working from home expenses.</p>", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    store = MemoryKnowledgeStore()
    provider = FakeEmbeddingProvider(dimensions=8)

    first = await ingest_manifest(
        manifest,
        data_dir=Path("data/ato"),
        project_root=tmp_path,
        provider=provider,
        store=store,
        chunk_size=200,
        chunk_overlap=20,
    )
    second = await ingest_manifest(
        manifest,
        data_dir=Path("data/ato"),
        project_root=tmp_path,
        provider=provider,
        store=store,
        chunk_size=200,
        chunk_overlap=20,
    )

    assert first.documents_imported == 1
    assert first.chunks_written == 1
    assert second.documents_imported == 0
    assert second.documents_skipped == 1
    assert store.replace_calls == 1


@pytest.mark.asyncio
async def test_changed_document_replaces_old_chunks(tmp_path: Path) -> None:
    data_dir = tmp_path / "data" / "ato"
    data_dir.mkdir(parents=True)
    source = data_dir / "source.html"
    source.write_text("<p>Original ATO content.</p>", encoding="utf-8")
    manifest = _write_manifest(tmp_path)
    store = MemoryKnowledgeStore()
    provider = FakeEmbeddingProvider(dimensions=8)
    options = {
        "data_dir": Path("data/ato"),
        "project_root": tmp_path,
        "provider": provider,
        "store": store,
        "chunk_size": 200,
        "chunk_overlap": 20,
    }

    await ingest_manifest(manifest, **options)  # type: ignore[arg-type]
    old_ids = {chunk.chunk_id for chunk in store.documents["working-from-home"]}
    source.write_text("<p>Updated and reviewed ATO content.</p>", encoding="utf-8")
    result = await ingest_manifest(manifest, **options)  # type: ignore[arg-type]
    new_ids = {chunk.chunk_id for chunk in store.documents["working-from-home"]}

    assert result.documents_imported == 1
    assert old_ids.isdisjoint(new_ids)


@pytest.mark.asyncio
async def test_dry_run_needs_no_external_services_and_reports_missing_file(tmp_path: Path) -> None:
    data_dir = tmp_path / "data" / "ato"
    data_dir.mkdir(parents=True)
    (data_dir / "source.html").write_text("<p>Reviewed ATO content.</p>", encoding="utf-8")
    manifest = _write_manifest(tmp_path, include_missing=True)

    result = await ingest_manifest(
        manifest,
        data_dir=Path("data/ato"),
        project_root=tmp_path,
        provider=None,
        store=None,
        dry_run=True,
        chunk_size=200,
        chunk_overlap=20,
    )

    assert result.documents_seen == 2
    assert result.documents_ready == 1
    assert result.documents_imported == 0
    assert result.documents_failed == 1
    assert result.failures[0].document_id == "missing-source"
