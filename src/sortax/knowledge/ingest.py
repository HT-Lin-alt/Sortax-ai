import argparse
import asyncio
import json
from pathlib import Path

from sortax.config import KnowledgeSettings
from sortax.embedding_gateway import (
    EmbeddingProvider,
    FakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from sortax.infrastructure.milvus import MilvusVectorStore
from sortax.knowledge.ingestion import ingest_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import reviewed local ATO documents")
    parser.add_argument("--manifest", type=Path, help="path to the source manifest")
    parser.add_argument("--data-dir", type=Path, help="allowed local source directory")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse and chunk files without embeddings or Milvus writes",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="drop and recreate the configured collection before import",
    )
    return parser


def _embedding_provider(settings: KnowledgeSettings) -> EmbeddingProvider:
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider(
            dimensions=settings.embedding_dimensions,
            model_name=settings.embedding_model,
        )
    api_key = settings.embedding_api_key
    if api_key is None:
        raise ValueError("SORTAX_EMBEDDING_API_KEY is required for the OpenAI provider")
    return OpenAIEmbeddingProvider(
        api_key=api_key.get_secret_value(),
        model_name=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
    )


async def _run(args: argparse.Namespace, settings: KnowledgeSettings) -> int:
    manifest_path = args.manifest or settings.ato_manifest_path
    data_dir = args.data_dir or settings.ato_data_dir
    provider: EmbeddingProvider | None = None
    store: MilvusVectorStore | None = None
    try:
        if not args.dry_run:
            provider = _embedding_provider(settings)
            store = MilvusVectorStore.from_settings(settings)
            await store.connect()
        summary = await ingest_manifest(
            manifest_path,
            data_dir=data_dir,
            project_root=Path.cwd(),
            provider=provider,
            store=store,
            dry_run=args.dry_run,
            rebuild=args.rebuild,
            max_file_bytes=settings.knowledge_max_file_bytes,
            chunk_size=settings.knowledge_chunk_size,
            chunk_overlap=settings.knowledge_chunk_overlap,
            expected_collection=settings.milvus_collection,
        )
        print(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False))
        return 1 if summary.documents_failed else 0
    finally:
        if store is not None:
            await store.close()


def main() -> int:
    args = _parser().parse_args()
    try:
        settings = KnowledgeSettings()
        return asyncio.run(_run(args, settings))
    except Exception as exc:
        print(json.dumps({"error": str(exc) or "ingestion failed"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
