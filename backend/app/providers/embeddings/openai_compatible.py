"""Embedding provider for any API that implements OpenAI-style embeddings.

Base URL, API key and model come from configuration only. Owner: T3.
"""

from collections.abc import Sequence
from typing import ClassVar, Self

from pydantic import SecretStr

from app.core.config import EmbeddingProviderMode, Settings
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.errors import ProviderNotImplementedError


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    mode: ClassVar[EmbeddingProviderMode] = EmbeddingProviderMode.OPENAI_COMPATIBLE
    live: ClassVar[bool] = True

    def __init__(self, *, base_url: str, api_key: SecretStr | None, model: str) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        if settings.embedding_base_url is None or settings.embedding_model is None:
            raise ValueError(
                "EMBEDDING_BASE_URL and EMBEDDING_MODEL are required for openai_compatible."
            )
        return cls(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
        )

    @property
    def model_name(self) -> str:
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise ProviderNotImplementedError("The OpenAI-compatible embedding provider")

    async def embed_query(self, text: str) -> list[float]:
        raise ProviderNotImplementedError("The OpenAI-compatible embedding provider")
