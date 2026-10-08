import asyncio
from typing import Protocol
from uuid import UUID


class CancellationStore(Protocol):
    async def request(self, generation_id: UUID) -> None: ...

    async def is_requested(self, generation_id: UUID) -> bool: ...

    async def clear(self, generation_id: UUID) -> None: ...

    async def close(self) -> None: ...


class InMemoryCancellationStore:
    """Process-local fallback used by tests and Redis-disabled development."""

    def __init__(self) -> None:
        self._requested: set[UUID] = set()
        self._lock = asyncio.Lock()

    async def request(self, generation_id: UUID) -> None:
        async with self._lock:
            self._requested.add(generation_id)

    async def is_requested(self, generation_id: UUID) -> bool:
        async with self._lock:
            return generation_id in self._requested

    async def clear(self, generation_id: UUID) -> None:
        async with self._lock:
            self._requested.discard(generation_id)

    async def close(self) -> None:
        return None
