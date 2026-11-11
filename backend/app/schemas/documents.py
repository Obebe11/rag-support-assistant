"""Knowledge base administration schemas."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import IndexingStatus
from app.schemas.common import ApiModel


class DocumentVersionRead(ApiModel):
    id: uuid.UUID
    version_number: int
    version_label: str | None = None
    source_filename: str
    media_type: str
    byte_size: int
    checksum_sha256: str
    is_active: bool = Field(description="True when this version takes part in retrieval.")
    indexing_status: IndexingStatus
    indexing_error: str | None = None
    page_count: int | None = None
    chunk_count: int | None = None
    created_at: datetime
    indexed_at: datetime | None = None
    activated_at: datetime | None = None


class DocumentRead(ApiModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime
    active_version: DocumentVersionRead | None = Field(
        default=None,
        description="The version used for retrieval. Empty until the first version is indexed.",
    )
    latest_version: DocumentVersionRead = Field(
        description="The most recent upload. It differs from the active version while a "
        "replacement is being indexed or after its indexing failed."
    )


class DocumentDetail(DocumentRead):
    versions: list[DocumentVersionRead]


class DocumentList(BaseModel):
    items: list[DocumentRead]
    total: int


class RetrievalSearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    top_k: int = Field(default=5, ge=1, le=50)


class RetrievedPassage(BaseModel):
    """A chunk of an active document version, as retrieval returns it."""

    rank: int = Field(description="1-based position in the result.")
    score: float = Field(
        description="Cosine similarity. It ranks passages; it does not measure whether "
        "a passage answers the query."
    )
    document_id: uuid.UUID
    document_title: str
    document_version_id: uuid.UUID
    version_number: int
    version_label: str | None = None
    source_filename: str
    chunk_id: uuid.UUID
    chunk_index: int
    section: str | None = Field(
        default=None, description='Section heading path, for example "Returns > Refunds".'
    )
    section_title: str | None = Field(
        default=None, description="Exact text of the heading directly above the passage."
    )
    page_number: int | None = Field(default=None, description="1-based page, for PDF sources.")
    content: str


class RetrievalSearchResponse(BaseModel):
    embedding_model: str = Field(description="Only chunks embedded by this model are searched.")
    items: list[RetrievedPassage]
