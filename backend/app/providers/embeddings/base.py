"""Embedding provider contract."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar, Self

from app.core.config import EmbeddingProviderMode, Settings


class EmbeddingProvider(ABC):
    """Text embeddings behind one interface.

    Every chunk stores `model_name` next to its vector. Retrieval compares a query
    only with chunks embedded by the same model, so changing the model requires
    re-indexing.

    Failures raise `app.providers.errors.ProviderError`.
    """

    mode: ClassVar[EmbeddingProviderMode]
    live: ClassVar[bool]

    @classmethod
    @abstractmethod
    def from_settings(cls, settings: Settings) -> Self: ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier stored in `chunks.embedding_model`."""

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages for indexing. Returns one vector per input, in order."""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Release network resources. Called once on shutdown."""
