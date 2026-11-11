"""Load a document manifest into the knowledge base, idempotently.

A manifest (`knowledge-base/northline/manifest.json` and the files with the
same format) lists documents by `doc_id`. The `documents` table has no such
column, so a manifest entry is matched to a stored document by its **title**:
titles are unique within a manifest, and a replacement keeps the title while
the file name may change. `seed_manifest` returns the `doc_id` of every entry
with the ID of its stored document.

Indexing runs in this process through the same function the worker uses, so
seeding needs no running worker and returns when every document is searchable.
"""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core.db import SessionFactory
from app.models import Chunk, Document
from app.models.enums import IndexingStatus
from app.providers.embeddings.base import EmbeddingProvider
from app.services.documents.indexing import index_document_version
from app.services.documents.service import add_version, create_document, prepare_upload

SeedAction = Literal["created", "replaced", "reindexed", "unchanged"]


class ManifestError(Exception):
    """The manifest cannot be used."""


@dataclass(frozen=True, slots=True)
class ManifestDocument:
    doc_id: str
    title: str
    version: str | None
    path: Path


@dataclass(frozen=True, slots=True)
class SeedResult:
    doc_id: str
    title: str
    document_id: uuid.UUID
    version_number: int
    version_label: str | None
    source_filename: str
    chunk_count: int
    action: SeedAction

    def as_json(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "document_id": str(self.document_id),
            "version_number": self.version_number,
            "version_label": self.version_label,
            "source_filename": self.source_filename,
            "chunk_count": self.chunk_count,
            "action": self.action,
        }


def load_manifest(manifest_path: Path) -> list[ManifestDocument]:
    """Read a manifest and check that its files exist and its titles are unique."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = manifest["documents"]
        documents = [
            ManifestDocument(
                doc_id=str(entry["doc_id"]),
                title=str(entry["title"]),
                version=str(entry["version"]) if entry.get("version") is not None else None,
                path=manifest_path.parent / str(entry["path"]),
            )
            for entry in entries
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ManifestError(f"Cannot read the manifest {manifest_path}: {exc}") from exc
    for key in ("doc_id", "title"):
        values = [getattr(document, key) for document in documents]
        if len(set(values)) != len(values):
            raise ManifestError(f"The manifest {manifest_path} repeats a {key}.")
    root = manifest_path.parent.resolve()
    for document in documents:
        if not document.path.resolve().is_relative_to(root) or not document.path.is_file():
            raise ManifestError(f"The file of {document.doc_id} is missing: {document.path}")
    return documents


async def seed_manifest(
    session_factory: SessionFactory,
    embeddings: EmbeddingProvider,
    manifest_path: Path,
    *,
    max_upload_bytes: int,
) -> list[SeedResult]:
    """Make the knowledge base hold the current file of every manifest entry.

    A document that is missing is created. A document whose latest version has
    another checksum gets a new version. A document that is not searchable with
    the current embedding model is indexed again. Everything else is left alone,
    so a second run changes nothing.

    Raises `ApiError` for a file the upload checks reject and
    `IndexingFailedError` when a document cannot be indexed.
    """
    results: list[SeedResult] = []
    for entry in load_manifest(manifest_path):
        upload = await prepare_upload(
            filename=entry.path.name,
            content_type=None,
            data=entry.path.read_bytes(),
            max_bytes=max_upload_bytes,
        )
        async with session_factory() as session:
            document = (
                (
                    await session.execute(
                        select(Document)
                        .where(Document.title == entry.title, Document.deleted_at.is_(None))
                        .options(selectinload(Document.versions))
                        .order_by(Document.created_at, Document.id)
                    )
                )
                .scalars()
                .first()
            )
            action: SeedAction
            if document is None:
                document = await create_document(
                    session,
                    upload,
                    title=entry.title,
                    version_label=entry.version,
                    enqueue_indexing=False,
                )
                action = "created"
            elif document.versions[-1].checksum_sha256 != upload.checksum:
                document = await add_version(
                    session,
                    document.id,
                    upload,
                    version_label=entry.version,
                    enqueue_indexing=False,
                )
                action = "replaced"
            else:
                latest = document.versions[-1]
                searchable = (
                    await session.execute(
                        select(func.count())
                        .select_from(Chunk)
                        .where(
                            Chunk.document_version_id == latest.id,
                            Chunk.embedding_model == embeddings.model_name,
                        )
                    )
                ).scalar_one()
                ready = latest.is_active and latest.indexing_status is IndexingStatus.READY
                action = "unchanged" if ready and searchable else "reindexed"

            version = document.versions[-1]
            if action != "unchanged":
                await index_document_version(session, version.id, embeddings)
                await session.commit()
                await session.refresh(version)
            results.append(
                SeedResult(
                    doc_id=entry.doc_id,
                    title=document.title,
                    document_id=document.id,
                    version_number=version.version_number,
                    version_label=version.version_label,
                    source_filename=version.source_filename,
                    chunk_count=version.chunk_count or 0,
                    action=action,
                )
            )
    return results
