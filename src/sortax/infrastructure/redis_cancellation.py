from uuid import UUID

from redis.asyncio import Redis


class RedisCancellationStore:
    """Short-lived generation cancellation flags shared by API instances."""

    def __init__(self, url: str, *, ttl_seconds: int = 600) -> None:
        self._client: Redis = Redis.from_url(url, decode_responses=True)
        self._ttl_seconds = ttl_seconds

    async def request(self, generation_id: UUID) -> None:
        await self._client.set(self._key(generation_id), "1", ex=self._ttl_seconds)

    async def is_requested(self, generation_id: UUID) -> bool:
        return bool(await self._client.exists(self._key(generation_id)))

    async def clear(self, generation_id: UUID) -> None:
        await self._client.delete(self._key(generation_id))

    async def close(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _key(generation_id: UUID) -> str:
        return f"sortax:generation:cancel:{generation_id}"
