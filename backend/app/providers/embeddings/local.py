"""Local embedding mode: offline and deterministic, no external API.

The vector is a hashed bag of words: stemmed terms and adjacent term pairs are
hashed into a fixed number of buckets, weighted by a damped term frequency and
normalized to unit length. It matches passages that share words with the query.
It knows no synonyms and no meaning, so it is a demo mode, not a replacement
for an embedding model. No model is downloaded and nothing leaves the process.
"""

import hashlib
import itertools
import math
from collections import Counter
from collections.abc import Sequence
from typing import ClassVar, Self

from app.core.config import EmbeddingProviderMode, Settings
from app.core.text import content_terms
from app.providers.embeddings.base import EmbeddingProvider

DIMENSIONS = 1024
MODEL_NAME = f"local-hashing-v1-{DIMENSIONS}"
_PAIR_WEIGHT = 0.5
_EMPTY_FEATURE = "\x00empty"


def _bucket(feature: str) -> tuple[int, float]:
    value = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
    return value % DIMENSIONS, 1.0 if value >> 63 else -1.0


def embed_text(text: str) -> list[float]:
    terms = content_terms(text)
    features: Counter[str] = Counter(terms)
    pairs: Counter[str] = Counter(f"{left}\x00{right}" for left, right in itertools.pairwise(terms))
    vector = [0.0] * DIMENSIONS
    for counts, weight in ((features, 1.0), (pairs, _PAIR_WEIGHT)):
        for feature, count in counts.items():
            index, sign = _bucket(feature)
            vector[index] += sign * weight * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        # Text without a single content term. A zero vector has no cosine
        # distance, so use one fixed direction that matches nothing useful.
        index, _ = _bucket(_EMPTY_FEATURE)
        vector[index] = 1.0
        return vector
    return [value / norm for value in vector]


class LocalEmbeddingProvider(EmbeddingProvider):
    mode: ClassVar[EmbeddingProviderMode] = EmbeddingProviderMode.LOCAL
    live: ClassVar[bool] = False

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls()

    @property
    def model_name(self) -> str:
        return MODEL_NAME

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [embed_text(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return embed_text(text)
