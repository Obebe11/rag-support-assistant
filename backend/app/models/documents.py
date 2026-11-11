"""Knowledge base: documents, their versions and retrievable chunks.

Retrieval rule: a chunk takes part in active retrieval only while its version has
`is_active = true`. Replacing a document activates the new version and deactivates
the old one in a single transaction once the new version is indexed. Deleting a
document sets `deleted_at` and deactivates every version. A partial unique index
allows at most one active version per document.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, created_at_column, enum_column, updated_at_column, uuid_pk
from app.models.enums import IndexingStatus


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    title: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentVersion.version_number",
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number"),
        Index(
            "uq_document_versions_active_document",
            "document_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer)
    version_label: Mapped[str | None] = mapped_column(String(100))
    """Version stated by the source itself, for example "2026-03" or "v2"."""

    source_filename: Mapped[str] = mapped_column(String(300))
    media_type: Mapped[str] = mapped_column(String(100))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    """Original uploaded file. Kept in the database so the worker needs no shared volume."""

    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    indexing_status: Mapped[IndexingStatus] = mapped_column(
        enum_column(IndexingStatus), server_default=IndexingStatus.PENDING.value
    )
    indexing_error: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int | None] = mapped_column(Integer)
    chunk_count: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = created_at_column()

    document: Mapped[Document] = relationship(back_populates="versions")
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document_version", cascade="all, delete-orphan"
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("document_version_id", "chunk_index"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    heading: Mapped[str | None] = mapped_column(Text)
    """Section heading path for Markdown sources, for example "Returns > Refunds"."""
    page_number: Mapped[int | None] = mapped_column(Integer)
    """1-based page number for PDF sources."""

    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    """No fixed dimension: the embedding model is configuration, not schema.

    Vectors of different models never mix in one query: always filter by
    `embedding_model` before comparing distances.
    """
    embedding_model: Mapped[str | None] = mapped_column(String(200), index=True)

    created_at: Mapped[datetime] = created_at_column()

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
