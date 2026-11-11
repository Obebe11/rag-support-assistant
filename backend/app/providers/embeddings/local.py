"""Local embedding mode: offline and deterministic, no external API.

Owner: T3.
"""

from collections.abc import Sequence
from typing import ClassVar, Self

from app.core.config import EmbeddingProviderMode, Settings
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.errors import ProviderNotImplementedError


class LocalEmbeddingProvider(EmbeddingProvider):
    mode: ClassVar[EmbeddingProviderMode] = EmbeddingProviderMode.LOCAL
    live: ClassVar[bool] = False

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls()

    @property
    def model_name(self) -> str:
        return "local"

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise ProviderNotImplementedError("The local embedding provider")

    async def embed_query(self, text: str) -> list[float]:
        raise ProviderNotImplementedError("The local embedding provider")
