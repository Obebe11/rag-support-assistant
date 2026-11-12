"""Knowledge base administration endpoints."""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile

from app.api.deps import EmbeddingProviderDep, SessionDep, SettingsDep
from app.api.errors import error_responses
from app.schemas.documents import (
    DocumentDetail,
    DocumentList,
    DocumentRead,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    RetrievedPassage,
)
from app.services.documents import retrieval, service

router = APIRouter(prefix="/documents", tags=["admin: documents"])

DocumentFile = Annotated[
    UploadFile, File(description="A Markdown file or a PDF with a text layer.")
]
VersionLabel = Annotated[
    str | None,
    Form(max_length=100, description='Version stated by the source, for example "2026-03".'),
]


async def _read_upload(file: UploadFile, max_bytes: int) -> service.DocumentUpload:
    # One byte over the limit is enough to know the file is too large.
    data = await file.read(max_bytes + 1)
    return await service.prepare_upload(
        filename=file.filename, content_type=file.content_type, data=data, max_bytes=max_bytes
    )


@router.get("", summary="List documents", responses=error_responses(422))
async def list_documents(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    documents, total = await service.list_documents(session, limit=limit, offset=offset)
    return DocumentList(
        items=[service.to_document_read(document) for document in documents], total=total
    )


@router.post(
    "",
    status_code=HTTPStatus.ACCEPTED,
    summary="Upload a new document",
    responses=error_responses(413, 415, 422),
)
async def upload_document(
    session: SessionDep,
    settings: SettingsDep,
    file: DocumentFile,
    title: Annotated[
        str | None,
        Form(max_length=300, description="Defaults to the title found in the file."),
    ] = None,
    version_label: VersionLabel = None,
) -> DocumentRead:
    """Store the file and queue it for indexing. Poll the document for its indexing status."""
    upload = await _read_upload(file, settings.max_upload_bytes)
    document = await service.create_document(
        session, upload, title=title, version_label=version_label
    )
    return service.to_document_read(document)


@router.post(
    "/search",
    summary="Search the active knowledge base",
    responses=error_responses(422, 503),
)
async def search_documents(
    body: RetrievalSearchRequest, session: SessionDep, embeddings: EmbeddingProviderDep
) -> RetrievalSearchResponse:
    """Return the passages retrieval finds for a query, best first, without an answer.

    Only active versions of documents that are not deleted are searched. Use it
    to inspect retrieval, for example to check that an expected source is among
    the top results.
    """
    chunks = await retrieval.search_or_unavailable(
        session, embeddings, body.query, limit=body.top_k
    )
    return RetrievalSearchResponse(
        embedding_model=embeddings.model_name,
        items=[
            RetrievedPassage(
                rank=rank,
                score=chunk.score,
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                document_version_id=chunk.document_version_id,
                version_number=chunk.version_number,
                version_label=chunk.version_label,
                source_filename=chunk.source_filename,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                section=chunk.heading,
                section_title=chunk.section_title,
                page_number=chunk.page_number,
                content=chunk.content,
            )
            for rank, chunk in enumerate(chunks, start=1)
        ],
    )


@router.get(
    "/{document_id}",
    summary="Get a document with its versions and indexing status",
    responses=error_responses(404, 422),
)
async def get_document(document_id: uuid.UUID, session: SessionDep) -> DocumentDetail:
    return service.to_document_detail(await service.load_document(session, document_id))


@router.post(
    "/{document_id}/versions",
    status_code=HTTPStatus.ACCEPTED,
    summary="Replace a document with a new version",
    responses=error_responses(404, 413, 415, 422),
)
async def replace_document(
    document_id: uuid.UUID,
    session: SessionDep,
    settings: SettingsDep,
    file: DocumentFile,
    version_label: VersionLabel = None,
) -> DocumentRead:
    """Store a new version and queue it for indexing.

    The previous version keeps answering questions until the new one is indexed.
    Then the new version becomes active and the old chunks leave retrieval.
    """
    await service.load_document(session, document_id)
    upload = await _read_upload(file, settings.max_upload_bytes)
    document = await service.add_version(session, document_id, upload, version_label=version_label)
    return service.to_document_read(document)


@router.delete(
    "/{document_id}",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete a document",
    responses=error_responses(404, 422),
)
async def delete_document(document_id: uuid.UUID, session: SessionDep) -> None:
    """Remove the document and all its chunks from retrieval."""
    await service.delete_document(session, document_id)
