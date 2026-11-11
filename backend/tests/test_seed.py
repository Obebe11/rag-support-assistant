"""Seeding the knowledge base from a manifest."""

import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.db import SessionFactory
from app.models import Chunk, Document
from app.providers.embeddings.local import MODEL_NAME, LocalEmbeddingProvider
from app.services.documents.seeding import ManifestError, load_manifest, seed_manifest
from tests.kb import NORTHLINE, REPLACEMENT_TEST, ask

MAX_BYTES = 10 * 1024 * 1024


class _OtherModel(LocalEmbeddingProvider):
    """The same vectors under another model name, as after a change of embedding model."""

    @property
    def model_name(self) -> str:
        return "another-embedding-model"


def _manifest(directory: Path, *entries: dict[str, Any]) -> Path:
    path = directory / "manifest.json"
    path.write_text(json.dumps({"schema_version": 1, "documents": list(entries)}))
    return path


def _small_corpus(directory: Path) -> Path:
    """A copy of the replacement-test folder that a test may change."""
    for source in REPLACEMENT_TEST.iterdir():
        shutil.copy(source, directory / source.name)
    return directory / "manifest.json"


async def test_seeding_the_corpus_twice_loads_each_document_once(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
) -> None:
    manifest = json.loads((NORTHLINE / "manifest.json").read_text())["documents"]
    embeddings = LocalEmbeddingProvider()

    first = await seed_manifest(
        session_factory, embeddings, NORTHLINE / "manifest.json", max_upload_bytes=MAX_BYTES
    )
    second = await seed_manifest(
        session_factory, embeddings, NORTHLINE / "manifest.json", max_upload_bytes=MAX_BYTES
    )

    assert len(first) == len(manifest) == 13
    assert {result.action for result in first} == {"created"}
    assert {result.action for result in second} == {"unchanged"}
    assert [r.document_id for r in second] == [r.document_id for r in first]
    assert all(result.chunk_count > 0 and result.version_number == 1 for result in second)

    # A manifest entry is found again by its title; version and file name are kept too.
    listed = (
        await client.get("/api/admin/documents", headers=admin_headers, params={"limit": 100})
    ).json()
    assert listed["total"] == 13
    stored = {item["id"]: item for item in listed["items"]}
    for entry, result in zip(manifest, first, strict=True):
        document = stored[str(result.document_id)]
        version = document["active_version"]
        assert result.doc_id == entry["doc_id"]
        assert document["title"] == entry["title"]
        assert version["version_label"] == entry["version"]
        assert version["source_filename"] == Path(entry["path"]).name
        assert version["indexing_status"] == "ready"
        assert result.as_json()["document_id"] == document["id"]
    # Only `documents/` is loaded: the PDF sources are not part of the corpus.
    assert all(Path(entry["path"]).parts[0] == "documents" for entry in manifest)

    # The questions of the readiness check, on the seeded corpus in local mode.
    expected = {
        "How much does standard shipping cost?": ("$14.95", {"Shipping Policy"}),
        "How long do I have to return an item?": ("30 days", {"Returns Policy"}),
        "What does the warranty cover?": ("materials and workmanship", {"Warranty Policy"}),
    }
    for question, (fact, documents) in expected.items():
        reply = await ask(client, question)
        assert reply["answer_type"] == "grounded", question
        assert fact in reply["content"], question
        cited = {citation["document_title"] for citation in reply["citations"]}
        assert cited & (documents | {"Frequently Asked Questions"}), question
    for question in ("Do you ship to Canada?", "Can I pay with cryptocurrency?"):
        reply = await ask(client, question)
        assert (reply["answer_type"], reply["citations"]) == ("knowledge_gap", []), question


async def test_a_changed_file_becomes_a_new_version_of_the_same_document(
    client: httpx.AsyncClient, session_factory: SessionFactory, tmp_path: Path
) -> None:
    manifest_path = _small_corpus(tmp_path)
    embeddings = LocalEmbeddingProvider()
    first = await seed_manifest(
        session_factory, embeddings, manifest_path, max_upload_bytes=MAX_BYTES
    )

    # The current Returns Policy takes the place of the superseded file.
    manifest = json.loads(manifest_path.read_text())
    manifest["documents"][0]["version"] = "2.0"
    manifest_path.write_text(json.dumps(manifest))
    shutil.copy(NORTHLINE / "documents" / "returns-policy.md", tmp_path / "returns-policy-v1.3.md")
    second = await seed_manifest(
        session_factory, embeddings, manifest_path, max_upload_bytes=MAX_BYTES
    )
    third = await seed_manifest(
        session_factory, embeddings, manifest_path, max_upload_bytes=MAX_BYTES
    )

    assert [(r.doc_id, r.action) for r in first] == [
        ("northline-returns-policy", "created"),
        ("northline-shipping-policy", "created"),
    ]
    assert [r.action for r in second] == ["replaced", "unchanged"]
    assert [r.action for r in third] == ["unchanged", "unchanged"]
    assert [r.document_id for r in second] == [r.document_id for r in first]
    assert (second[0].version_number, second[0].version_label) == (2, "2.0")
    reply = await ask(client, "What is the restocking fee for an opened item?")
    assert "15% restocking fee" in reply["content"]
    assert "20%" not in reply["content"]


async def test_documents_are_indexed_again_for_a_new_embedding_model(
    session_factory: SessionFactory, tmp_path: Path
) -> None:
    manifest_path = _small_corpus(tmp_path)
    await seed_manifest(
        session_factory, LocalEmbeddingProvider(), manifest_path, max_upload_bytes=MAX_BYTES
    )

    changed = await seed_manifest(
        session_factory, _OtherModel(), manifest_path, max_upload_bytes=MAX_BYTES
    )
    again = await seed_manifest(
        session_factory, _OtherModel(), manifest_path, max_upload_bytes=MAX_BYTES
    )

    assert [r.action for r in changed] == ["reindexed", "reindexed"]
    assert [r.action for r in again] == ["unchanged", "unchanged"]
    assert {r.version_number for r in changed} == {1}
    async with session_factory() as session:
        models = (await session.execute(select(Chunk.embedding_model).distinct())).scalars().all()
    assert MODEL_NAME != "another-embedding-model"
    assert models == ["another-embedding-model"]


async def test_a_deleted_document_is_created_again(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    tmp_path: Path,
) -> None:
    manifest_path = _small_corpus(tmp_path)
    embeddings = LocalEmbeddingProvider()
    first = await seed_manifest(
        session_factory, embeddings, manifest_path, max_upload_bytes=MAX_BYTES
    )
    await client.delete(f"/api/admin/documents/{first[0].document_id}", headers=admin_headers)

    second = await seed_manifest(
        session_factory, embeddings, manifest_path, max_upload_bytes=MAX_BYTES
    )

    assert [r.action for r in second] == ["created", "unchanged"]
    assert second[0].document_id != first[0].document_id
    assert second[0].version_number == 1


@pytest.mark.parametrize(
    ("entries", "message"),
    [
        (
            [
                {"doc_id": "a", "title": "One", "path": "a.md"},
                {"doc_id": "a", "title": "Two", "path": "a.md"},
            ],
            "repeats a doc_id",
        ),
        (
            [
                {"doc_id": "a", "title": "One", "path": "a.md"},
                {"doc_id": "b", "title": "One", "path": "a.md"},
            ],
            "repeats a title",
        ),
        ([{"doc_id": "a", "title": "One", "path": "missing.md"}], "is missing"),
        ([{"doc_id": "a", "title": "One", "path": "../outside.md"}], "is missing"),
        ([{"doc_id": "a", "path": "a.md"}], "Cannot read the manifest"),
    ],
)
async def test_a_broken_manifest_is_rejected_before_anything_is_stored(
    session_factory: SessionFactory,
    tmp_path: Path,
    entries: list[dict[str, Any]],
    message: str,
) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "a.md").write_text("# One\n\nText.\n")
    (tmp_path / "outside.md").write_text("# Outside\n\nText.\n")
    manifest_path = _manifest(corpus, *entries)

    with pytest.raises(ManifestError, match=message):
        await seed_manifest(
            session_factory, LocalEmbeddingProvider(), manifest_path, max_upload_bytes=MAX_BYTES
        )

    async with session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Document))).scalar_one() == 0


def test_a_manifest_that_is_not_json_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text("not json")

    with pytest.raises(ManifestError, match="Cannot read the manifest"):
        load_manifest(tmp_path / "manifest.json")
    with pytest.raises(ManifestError, match="Cannot read the manifest"):
        load_manifest(tmp_path / "absent.json")


def test_the_evaluation_fixtures_use_the_same_manifest_format() -> None:
    fixtures = load_manifest(NORTHLINE.parents[1] / "evals" / "fixtures" / "manifest.json")

    assert len(fixtures) == 2
    assert all(document.path.is_file() for document in fixtures)


async def test_the_settings_limit_applies_to_seeded_files(
    session_factory: SessionFactory, settings: Settings, tmp_path: Path
) -> None:
    manifest_path = _small_corpus(tmp_path)

    with pytest.raises(ApiError) as raised:
        await seed_manifest(
            session_factory, LocalEmbeddingProvider(), manifest_path, max_upload_bytes=100
        )

    assert raised.value.status_code == 413
    assert settings.max_upload_bytes > 100
