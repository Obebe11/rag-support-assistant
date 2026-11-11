"""Index one document version: parse, chunk, embed, store, activate.

The worker handler and the seed command both call `index_document_version`.

Activation is the last step and shares a transaction with the new chunks, so
retrieval switches from the old version to the new one at once. Until then, and
whenever indexing fails, the previous version keeps answering.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models import Chunk, Document, DocumentVersion
from app.models.base import JSONDict
from app.models.enums import IndexingStatus
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.errors import ProviderError
from app.services.documents.chunking import ChunkDraft, build_chunks, embedding_text
from app.services.documents.parsing import (
    DocumentParseError,
    ParsedDocument,
    media_type_format,
    parse_document,
)

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 1000


class IndexingFailedError(Exception):
    """Indexing did not finish. `retryable` says whether another attempt can help."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


def _parse_and_chunk(media_type: str, data: bytes) -> tuple[ParsedDocument, list[ChunkDraft]]:
    parsed = parse_document(media_type_format(media_type), data)
    chunks = build_chunks(parsed)
    if not chunks:
        raise DocumentParseError("The document has no text to index.")
    return parsed, chunks


async def index_document_version(
    session: AsyncSession,
    version_id: uuid.UUID,
    embeddings: EmbeddingProvider,
    *,
    final_attempt: bool = True,
) -> JSONDict:
    """Index a version and make it the active one.

    Commits the `indexing` status first, so it is visible while the work runs.
    On success the chunks, the `ready` status and the activation are left in
    the session for the caller to commit. On failure the error is committed to
    the version and `IndexingFailedError` is raised; the status goes back to
    `pending` when another attempt will follow, and to `failed` otherwise.

    Safe to run more than once: chunks of the version are replaced.
    """
    # `populate_existing` loads the file even when the session already holds the
    # version without it.
    version = await session.get(
        DocumentVersion,
        version_id,
        options=[undefer(DocumentVersion.content)],
        populate_existing=True,
    )
    if version is None:
        raise IndexingFailedError("The document version no longer exists.", retryable=False)
    document = await session.get(Document, version.document_id)
    if document is None or document.deleted_at is not None:
        return {"document_version_id": str(version_id), "skipped": "document_deleted"}

    version.indexing_status = IndexingStatus.INDEXING
    version.indexing_error = None
    media_type, content, title = version.media_type, version.content, document.title
    await session.commit()

    try:
        parsed, chunks = await asyncio.to_thread(_parse_and_chunk, media_type, content)
        vectors = await embeddings.embed_documents(
            [embedding_text(title, chunk) for chunk in chunks]
        )
        if len(vectors) != len(chunks):
            raise ProviderError(
                "The embedding provider returned a wrong number of vectors.", retryable=False
            )
        return await _store(session, version_id, parsed, chunks, vectors, embeddings.model_name)
    except (DocumentParseError, ProviderError) as exc:
        retryable = isinstance(exc, ProviderError) and exc.retryable
        await _record_failure(
            session, version_id, str(exc), will_retry=retryable and not final_attempt
        )
        raise IndexingFailedError(str(exc), retryable=retryable) from exc
    except asyncio.CancelledError:
        # The job timed out or the worker is stopping. Record it, then let the
        # cancellation continue.
        await _record_failure(
            session, version_id, "Indexing was interrupted.", will_retry=not final_attempt
        )
        raise
    except Exception as exc:
        await _record_failure(
            session, version_id, f"{type(exc).__name__}: {exc}", will_retry=not final_attempt
        )
        raise


async def _store(
    session: AsyncSession,
    version_id: uuid.UUID,
    parsed: ParsedDocument,
    chunks: list[ChunkDraft],
    vectors: list[list[float]],
    embedding_model: str,
) -> JSONDict:
    version = await session.get(DocumentVersion, version_id, populate_existing=True)
    if version is None:
        raise IndexingFailedError("The document version no longer exists.", retryable=False)
    # The document row is the lock for activation: replacements and deletion take it too.
    # The session already holds the document as it was before the work started, so the
    # row is read again: it may have been deleted in the meantime.
    document = (
        await session.execute(
            select(Document)
            .where(Document.id == version.document_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()

    await session.execute(delete(Chunk).where(Chunk.document_version_id == version_id))
    session.add_all(
        Chunk(
            document_version_id=version_id,
            chunk_index=index,
            content=chunk.content,
            heading=chunk.heading,
            page_number=chunk.page_number,
            embedding=vector,
            embedding_model=embedding_model,
        )
        for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
    )
    now = datetime.now(UTC)
    version.indexing_status = IndexingStatus.READY
    version.indexing_error = None
    version.indexed_at = now
    version.page_count = parsed.page_count
    version.chunk_count = len(chunks)

    activated = False
    if document.deleted_at is None:
        active = (
            await session.execute(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id, DocumentVersion.is_active.is_(True)
                )
            )
        ).scalar_one_or_none()
        # A newer upload that finished first stays active.
        if active is None or active.version_number < version.version_number:
            if active is not None:
                active.is_active = False
                active.deactivated_at = now
                # One active version per document: release the old one first.
                await session.flush()
            version.is_active = True
            version.activated_at = now
            version.deactivated_at = None
            document.updated_at = now
            activated = True
    await session.flush()
    return {
        "document_version_id": str(version_id),
        "chunk_count": len(chunks),
        "page_count": parsed.page_count,
        "activated": activated,
    }


async def _record_failure(
    session: AsyncSession, version_id: uuid.UUID, error: str, *, will_retry: bool
) -> None:
    await session.rollback()
    version = await session.get(DocumentVersion, version_id, populate_existing=True)
    if version is None:
        return
    version.indexing_status = IndexingStatus.PENDING if will_retry else IndexingStatus.FAILED
    version.indexing_error = error[:MAX_ERROR_LENGTH]
    await session.commit()
    logger.warning("Indexing of document version %s failed: %s", version_id, error)
