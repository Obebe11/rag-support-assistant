"""Knowledge base administration: upload, replace, delete, read.

Every change of the active version goes through the document row lock, so an
upload, a replacement, a deletion and the end of an indexing job never
interleave.
"""

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import PurePath

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.errors import ApiError, NotFoundError, ValidationApiError
from app.models import Document, DocumentVersion
from app.models.enums import IndexingStatus
from app.schemas.common import ErrorCode, ErrorDetail
from app.schemas.documents import DocumentDetail, DocumentRead, DocumentVersionRead
from app.services.documents.parsing import (
    DocumentFormat,
    DocumentParseError,
    detect_format,
    find_title,
)
from app.worker import job_types, queue

MAX_TITLE_LENGTH = 300
MAX_FILENAME_LENGTH = 300
MAX_VERSION_LABEL_LENGTH = 100


@dataclass(frozen=True, slots=True)
class DocumentUpload:
    """A file that passed the upload checks."""

    filename: str
    document_format: DocumentFormat
    data: bytes
    title: str | None
    """Title stated by the file itself, if any."""

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _file_error(message: str) -> ValidationApiError:
    return ValidationApiError(message, details=[ErrorDetail(field="body.file", message=message)])


def too_large_error(max_bytes: int) -> ApiError:
    return ApiError(
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        ErrorCode.PAYLOAD_TOO_LARGE,
        f"The file is larger than the upload limit of {max_bytes} bytes.",
    )


async def prepare_upload(
    *, filename: str | None, content_type: str | None, data: bytes, max_bytes: int
) -> DocumentUpload:
    """Check size, format and readability of an uploaded file.

    Raises 413 for a file over the limit, 415 for an unsupported format and 422
    for an empty or unreadable file. A readable file without text to index, such
    as a scanned PDF, is accepted: its indexing fails and the version shows why.
    """
    if len(data) > max_bytes:
        raise too_large_error(max_bytes)
    name = PurePath((filename or "").replace("\\", "/")).name.strip()[:MAX_FILENAME_LENGTH]
    name = name or "document"
    if not data.strip():
        raise _file_error("The file is empty.")
    document_format = detect_format(name, content_type, data)
    if document_format is None:
        raise ApiError(
            HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "Upload a Markdown file (.md) or a PDF with a text layer.",
        )
    try:
        title = await asyncio.to_thread(find_title, document_format, data)
    except DocumentParseError as exc:
        raise _file_error(str(exc)) from exc
    return DocumentUpload(filename=name, document_format=document_format, data=data, title=title)


def _clean(value: str | None, max_length: int) -> str | None:
    cleaned = " ".join(value.split())[:max_length] if value else ""
    return cleaned or None


def _new_version(upload: DocumentUpload, number: int, version_label: str | None) -> DocumentVersion:
    return DocumentVersion(
        id=uuid.uuid4(),
        version_number=number,
        version_label=_clean(version_label, MAX_VERSION_LABEL_LENGTH),
        source_filename=upload.filename,
        media_type=upload.document_format.media_type,
        byte_size=len(upload.data),
        checksum_sha256=upload.checksum,
        content=upload.data,
        is_active=False,
        indexing_status=IndexingStatus.PENDING,
    )


async def _enqueue_indexing(session: AsyncSession, version: DocumentVersion) -> None:
    await queue.enqueue(
        session,
        job_types.INDEX_DOCUMENT_VERSION,
        {"document_version_id": str(version.id)},
        idempotency_key=f"{job_types.INDEX_DOCUMENT_VERSION}:{version.id}",
    )


async def load_document(
    session: AsyncSession, document_id: uuid.UUID, *, for_update: bool = False
) -> Document:
    """Load a document that is not deleted, with its versions. Raises 404 otherwise."""
    statement = (
        select(Document)
        .where(Document.id == document_id, Document.deleted_at.is_(None))
        .options(selectinload(Document.versions))
        .execution_options(populate_existing=True)
    )
    if for_update:
        statement = statement.with_for_update()
    document = (await session.execute(statement)).scalar_one_or_none()
    if document is None:
        raise NotFoundError("Document not found.")
    return document


async def create_document(
    session: AsyncSession,
    upload: DocumentUpload,
    *,
    title: str | None = None,
    version_label: str | None = None,
    enqueue_indexing: bool = True,
) -> Document:
    """Store a new document with its first version and queue the version for indexing.

    Commits. The version takes part in retrieval once it is indexed.
    """
    resolved_title = (
        _clean(title, MAX_TITLE_LENGTH)
        or _clean(upload.title, MAX_TITLE_LENGTH)
        or PurePath(upload.filename).stem[:MAX_TITLE_LENGTH]
        or "Untitled document"
    )
    document = Document(id=uuid.uuid4(), title=resolved_title)
    version = _new_version(upload, 1, version_label)
    document.versions.append(version)
    session.add(document)
    await session.flush()
    if enqueue_indexing:
        await _enqueue_indexing(session, version)
    await session.commit()
    return await load_document(session, document.id)


async def add_version(
    session: AsyncSession,
    document_id: uuid.UUID,
    upload: DocumentUpload,
    *,
    version_label: str | None = None,
    enqueue_indexing: bool = True,
) -> Document:
    """Store a replacement as a new version and queue it for indexing.

    Commits. The current version keeps answering until the new one is indexed.
    """
    document = await load_document(session, document_id, for_update=True)
    version = _new_version(upload, document.versions[-1].version_number + 1, version_label)
    document.versions.append(version)
    document.updated_at = datetime.now(UTC)
    await session.flush()
    if enqueue_indexing:
        await _enqueue_indexing(session, version)
    await session.commit()
    return await load_document(session, document_id)


async def delete_document(session: AsyncSession, document_id: uuid.UUID) -> None:
    """Take the document and every version out of retrieval. Commits.

    The rows stay, so citations of earlier answers keep their source. An
    indexing job that is still running finds the document deleted and does not
    activate its version.
    """
    document = await load_document(session, document_id, for_update=True)
    now = datetime.now(UTC)
    document.deleted_at = now
    await session.execute(
        update(DocumentVersion)
        .where(DocumentVersion.document_id == document.id, DocumentVersion.is_active.is_(True))
        .values(is_active=False, deactivated_at=now)
    )
    await session.commit()


async def list_documents(
    session: AsyncSession, *, limit: int, offset: int
) -> tuple[list[Document], int]:
    not_deleted = Document.deleted_at.is_(None)
    total = (
        await session.execute(select(func.count()).select_from(Document).where(not_deleted))
    ).scalar_one()
    documents = (
        (
            await session.execute(
                select(Document)
                .where(not_deleted)
                .options(selectinload(Document.versions))
                .order_by(func.lower(Document.title), Document.created_at, Document.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(documents), total


def _versions(document: Document) -> list[DocumentVersionRead]:
    return [DocumentVersionRead.model_validate(version) for version in document.versions]


def to_document_read(document: Document) -> DocumentRead:
    versions = _versions(document)
    return DocumentRead(
        id=document.id,
        title=document.title,
        created_at=document.created_at,
        updated_at=document.updated_at,
        active_version=next((version for version in versions if version.is_active), None),
        latest_version=versions[-1],
    )


def to_document_detail(document: Document) -> DocumentDetail:
    return DocumentDetail(**to_document_read(document).model_dump(), versions=_versions(document))
