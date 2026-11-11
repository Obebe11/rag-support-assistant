"""Knowledge base administration schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

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
