from typing import Protocol

from sortax.rag.models import VectorSearchHit


class VectorStore(Protocol):
    """Application port implemented by vector-store infrastructure adapters."""

    async def connect(self) -> None: ...

    async def healthcheck(self) -> bool: ...

    async def close(self) -> None: ...

    async def search(
        self,
        collection_name: str,
        vector: list[float],
        *,
        claim_type: str,
        tax_year: str,
        limit: int,
    ) -> list[VectorSearchHit]: ...
