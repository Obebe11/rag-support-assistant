"""Knowledge base administration endpoints. Owner: T3."""

import uuid
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile

from app.api.errors import NotImplementedApiError, error_responses
from app.schemas.documents import DocumentDetail, DocumentList, DocumentRead

router = APIRouter(prefix="/documents", tags=["admin: documents"])

DocumentFile = Annotated[
    UploadFile, File(description="A Markdown file or a PDF with a text layer.")
]
VersionLabel = Annotated[
    str | None,
    Form(max_length=100, description='Version stated by the source, for example "2026-03".'),
]


@router.get("", summary="List documents", responses=error_responses(422))
async def list_documents(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentList:
    raise NotImplementedApiError("Listing documents")


@router.post(
    "",
    status_code=HTTPStatus.ACCEPTED,
    summary="Upload a new document",
    responses=error_responses(413, 415, 422),
)
async def upload_document(
    file: DocumentFile,
    title: Annotated[
        str | None,
        Form(max_length=300, description="Defaults to the title found in the file."),
    ] = None,
    version_label: VersionLabel = None,
) -> DocumentRead:
    """Store the file and queue it for indexing. Poll the document for its indexing status."""
    raise NotImplementedApiError("Uploading a document")


@router.get(
    "/{document_id}",
    summary="Get a document with its versions and indexing status",
    responses=error_responses(404, 422),
)
async def get_document(document_id: uuid.UUID) -> DocumentDetail:
    raise NotImplementedApiError("Reading a document")


@router.post(
    "/{document_id}/versions",
    status_code=HTTPStatus.ACCEPTED,
    summary="Replace a document with a new version",
    responses=error_responses(404, 413, 415, 422),
)
async def replace_document(
    document_id: uuid.UUID,
    file: DocumentFile,
    version_label: VersionLabel = None,
) -> DocumentRead:
    """Store a new version and queue it for indexing.

    The previous version keeps answering questions until the new one is indexed.
    Then the new version becomes active and the old chunks leave retrieval.
    """
    raise NotImplementedApiError("Replacing a document")


@router.delete(
    "/{document_id}",
    status_code=HTTPStatus.NO_CONTENT,
    summary="Delete a document",
    responses=error_responses(404, 422),
)
async def delete_document(document_id: uuid.UUID) -> None:
    """Remove the document and all its chunks from retrieval."""
    raise NotImplementedApiError("Deleting a document")
