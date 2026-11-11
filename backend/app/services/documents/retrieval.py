"""Vector search over the active knowledge base.

A chunk is searched only when its version is active, its document is not
deleted and it was embedded by the current embedding model. Search is exact
(no approximate index): the corpus of a demo is small.

The score is cosine similarity. It ranks passages; it does not say whether a
passage answers the question.
"""

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from http import HTTPStatus

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.models import Chunk, Document, DocumentVersion
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.errors import ProviderError
from app.schemas.common import ErrorCode
from app.services.documents.chunking import HEADING_SEPARATOR

DEFAULT_TOP_K = 5


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    chunk_index: int
    content: str
    heading: str | None
    page_number: int | None
    score: float
    document_id: uuid.UUID
    document_title: str
    document_version_id: uuid.UUID
    version_number: int
    version_label: str | None
    source_filename: str

    @property
    def section_title(self) -> str | None:
        """The heading directly above the passage: the last item of the heading path."""
        return self.heading.split(HEADING_SEPARATOR)[-1] if self.heading else None


def normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else list(vector)


def combine(vectors: Sequence[Sequence[float]], weights: Sequence[float]) -> list[float]:
    """Weighted sum of unit vectors, as a unit vector."""
    units = [normalize(vector) for vector in vectors]
    summed = [
        sum(weight * unit[index] for unit, weight in zip(units, weights, strict=True))
        for index in range(len(units[0]))
    ]
    return normalize(summed)


async def search_by_vector(
    session: AsyncSession,
    *,
    query_vector: Sequence[float],
    embedding_model: str,
    limit: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """The `limit` active chunks closest to `query_vector`, best first."""
    distance = Chunk.embedding.cosine_distance(list(query_vector)).label("distance")
    statement = (
        select(
            Chunk.id,
            Chunk.chunk_index,
            Chunk.content,
            Chunk.heading,
            Chunk.page_number,
            Document.id,
            Document.title,
            DocumentVersion.id,
            DocumentVersion.version_number,
            DocumentVersion.version_label,
            DocumentVersion.source_filename,
            distance,
        )
        .join(DocumentVersion, Chunk.document_version_id == DocumentVersion.id)
        .join(Document, DocumentVersion.document_id == Document.id)
        .where(
            DocumentVersion.is_active.is_(True),
            Document.deleted_at.is_(None),
            # Vectors of different models never meet in one comparison.
            Chunk.embedding_model == embedding_model,
            Chunk.embedding.is_not(None),
        )
        .order_by(distance, Chunk.id)
        .limit(limit)
    )
    results: list[RetrievedChunk] = []
    for row in (await session.execute(statement)).all():
        cosine_distance = float(row.distance)
        if math.isnan(cosine_distance):
            continue
        results.append(
            RetrievedChunk(
                chunk_id=row[0],
                chunk_index=row[1],
                content=row[2],
                heading=row[3],
                page_number=row[4],
                document_id=row[5],
                document_title=row[6],
                document_version_id=row[7],
                version_number=row[8],
                version_label=row[9],
                source_filename=row[10],
                score=round(1.0 - cosine_distance, 6),
            )
        )
    return results


async def search(
    session: AsyncSession,
    embeddings: EmbeddingProvider,
    query: str,
    *,
    limit: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """Embed `query` and return the closest active chunks, best first.

    This is the retrieval step on its own, without an answer. The evaluation
    runner uses it to check whether an expected source is among the top results.
    """
    query_vector = await embeddings.embed_query(query)
    return await search_by_vector(
        session, query_vector=query_vector, embedding_model=embeddings.model_name, limit=limit
    )


async def search_or_unavailable(
    session: AsyncSession,
    embeddings: EmbeddingProvider,
    query: str,
    *,
    limit: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """`search` for an API route: a provider failure becomes a 503 in the common format."""
    try:
        return await search(session, embeddings, query, limit=limit)
    except ProviderError as exc:
        raise ApiError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            ErrorCode.SERVICE_UNAVAILABLE,
            "The embedding provider is temporarily unavailable.",
        ) from exc
