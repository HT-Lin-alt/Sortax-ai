import hashlib
import math
import re

from sortax.embedding_gateway.base import EmbeddingProviderError


class FakeEmbeddingProvider:
    """Deterministic feature-hash embeddings for local development and tests."""

    _token_pattern = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]", re.IGNORECASE)

    def __init__(self, dimensions: int = 64, model_name: str = "fake-embedding-v1") -> None:
        if dimensions <= 1:
            raise ValueError("dimensions must be greater than one")
        self._dimensions = dimensions
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        normalized = " ".join(text.lower().replace("_", " ").split())
        if not normalized:
            raise EmbeddingProviderError("embedding input must not be empty")

        features: list[str] = []
        tokens = self._token_pattern.findall(normalized)
        if not tokens:
            raise EmbeddingProviderError("embedding input must contain searchable text")
        features.extend(tokens)
        for token in tokens:
            if token.isascii() and len(token) >= 3:
                features.extend(token[index : index + 3] for index in range(len(token) - 2))
        features.extend(
            f"{left}:{right}"
            for left, right in zip(tokens, tokens[1:], strict=False)
            if not left.isascii() or not right.isascii()
        )

        vector = [0.0] * self._dimensions
        for feature in features:
            digest = hashlib.sha256(feature.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            vector[index] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector))
        return [value / magnitude for value in vector]
