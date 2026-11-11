"""Embedding provider for any API that implements OpenAI-style embeddings.

Base URL, API key and model come from configuration only. Owner: T3.
"""

from collections.abc import Sequence
from typing import Any, ClassVar, Self

import httpx
from pydantic import SecretStr

from app.core.config import EmbeddingProviderMode, Settings
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.openai_http import OpenAICompatibleClient

BATCH_SIZE = 64


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    mode: ClassVar[EmbeddingProviderMode] = EmbeddingProviderMode.OPENAI_COMPATIBLE
    live: ClassVar[bool] = True

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr | None,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._http = OpenAICompatibleClient(
            label="embedding", base_url=base_url, api_key=api_key, transport=transport
        )

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
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(await self._embed(list(texts[start : start + BATCH_SIZE])))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text]))[0]

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        body = await self._http.post_json("embeddings", {"model": self._model, "input": texts})
        items = body.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise self._http.malformed(f"expected {len(texts)} embeddings.")
        vectors: list[list[float] | None] = [None] * len(texts)
        for position, item in enumerate(items):
            index, vector = self._read_item(item, position)
            if not 0 <= index < len(texts) or vectors[index] is not None:
                raise self._http.malformed("embedding indexes do not match the inputs.")
            vectors[index] = vector
        return [vector for vector in vectors if vector is not None]

    def _read_item(self, item: Any, position: int) -> tuple[int, list[float]]:
        if not isinstance(item, dict):
            raise self._http.malformed("an embedding item is not an object.")
        index = item.get("index", position)
        values = item.get("embedding")
        if (
            not isinstance(index, int)
            or not isinstance(values, list)
            or not values
            or not all(isinstance(value, int | float) for value in values)
        ):
            raise self._http.malformed("an embedding item has no numeric vector.")
        return index, [float(value) for value in values]

    async def aclose(self) -> None:
        await self._http.aclose()
