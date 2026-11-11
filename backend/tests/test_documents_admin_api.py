"""Knowledge base administration: upload, indexing, replacement, deletion, access."""

import dataclasses
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, update
from starlette.types import Message, Receive, Scope, Send

from app.api.upload_guard import UploadGuardMiddleware
from app.core.config import Settings
from app.core.db import SessionFactory
from app.main import create_app
from app.models import Chunk, Document, DocumentVersion, Job
from app.models.enums import IndexingStatus, JobStatus
from app.providers.embeddings.local import MODEL_NAME, LocalEmbeddingProvider
from app.providers.errors import ProviderError
from app.providers.factory import build_providers
from tests.conftest import make_settings
from tests.kb import NORTHLINE_DOCUMENTS, blank_pdf, ingest, run_jobs, upload

RETURNS = NORTHLINE_DOCUMENTS / "returns-policy.md"
WARRANTY_PDF = NORTHLINE_DOCUMENTS / "warranty-policy.pdf"
SMALL = b"# Returns\n\n## Window\n\nThirty days from delivery.\n"
SMALL_V2 = b"# Returns\n\n## Window\n\nForty-five days from delivery.\n"
MISSING_ID = "00000000-0000-4000-8000-000000000001"


@asynccontextmanager
async def _client_with(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


async def _chunks(session_factory: SessionFactory, version_id: str) -> Sequence[Chunk]:
    async with session_factory() as session:
        return (
            (
                await session.execute(
                    select(Chunk)
                    .where(Chunk.document_version_id == uuid.UUID(version_id))
                    .order_by(Chunk.chunk_index)
                )
            )
            .scalars()
            .all()
        )


async def _search(
    client: httpx.AsyncClient, headers: dict[str, str], query: str, top_k: int = 5
) -> list[dict[str, Any]]:
    response = await client.post(
        "/api/admin/documents/search", headers=headers, json={"query": query, "top_k": top_k}
    )
    assert response.status_code == 200, response.text
    assert response.json()["embedding_model"] == MODEL_NAME
    items: list[dict[str, Any]] = response.json()["items"]
    return items


# --- Upload and indexing ---------------------------------------------------------


async def test_upload_stores_the_file_and_indexing_runs_in_the_background(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    response = await upload(client, admin_headers, RETURNS, version_label="2.0")

    assert response.status_code == 202
    queued = response.json()
    assert queued["title"] == "Returns Policy"
    assert queued["active_version"] is None
    assert queued["latest_version"]["indexing_status"] == "pending"
    assert queued["latest_version"]["is_active"] is False
    assert queued["latest_version"]["version_number"] == 1
    assert queued["latest_version"]["version_label"] == "2.0"
    assert queued["latest_version"]["source_filename"] == "returns-policy.md"
    assert queued["latest_version"]["media_type"] == "text/markdown"
    assert queued["latest_version"]["byte_size"] == RETURNS.stat().st_size
    assert await _search(client, admin_headers, "return window") == []

    assert await run_jobs(session_factory, settings) == 1

    detail = (
        await client.get(f"/api/admin/documents/{queued['id']}", headers=admin_headers)
    ).json()
    version = detail["versions"][0]
    assert detail["active_version"] == version == detail["latest_version"]
    assert version["indexing_status"] == "ready"
    assert version["indexing_error"] is None
    assert version["is_active"] is True
    assert version["chunk_count"] == 9
    assert version["page_count"] is None
    assert version["indexed_at"] is not None
    assert version["activated_at"] is not None


async def test_markdown_chunks_keep_their_section_heading(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, RETURNS)

    chunks = await _chunks(session_factory, document["active_version"]["id"])

    assert [chunk.chunk_index for chunk in chunks] == list(range(9))
    assert [chunk.heading for chunk in chunks][:4] == [
        None,
        "Return window",
        "Return authorization",
        "Item condition and refund amount",
    ]
    assert all(chunk.page_number is None for chunk in chunks)
    assert all(chunk.embedding_model == MODEL_NAME for chunk in chunks)
    assert "within 30 days of the delivery date" in chunks[1].content


async def test_pdf_chunks_keep_their_page_number_and_heading(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, WARRANTY_PDF)

    version = document["active_version"]
    chunks = await _chunks(session_factory, version["id"])
    by_heading = {chunk.heading: chunk for chunk in chunks}

    assert document["title"] == "Warranty Policy"
    assert version["media_type"] == "application/pdf"
    assert version["page_count"] == 3
    assert version["chunk_count"] == len(chunks)
    assert {chunk.page_number for chunk in chunks} == {1, 2, 3}
    assert by_heading["Warranty periods"].page_number == 1
    assert by_heading["Third-party supplies"].page_number == 2
    assert by_heading["Northline Care extended coverage"].page_number == 3
    assert "L-125 Thermal Laminator | 1 year" in by_heading["Warranty periods"].content


async def test_title_and_version_label_can_be_given_or_default_to_the_file(
    client: httpx.AsyncClient, admin_headers: dict[str, str], session_factory: SessionFactory
) -> None:
    named = await upload(client, admin_headers, SMALL, title="  Custom   title ")
    from_heading = await upload(client, admin_headers, SMALL, filename="any-name.md")
    from_filename = await upload(
        client, admin_headers, b"No heading, just text.\n", filename="plain-notes.md"
    )

    assert named.json()["title"] == "Custom title"
    assert named.json()["latest_version"]["version_label"] is None
    assert from_heading.json()["title"] == "Returns"
    assert from_filename.json()["title"] == "plain-notes"


async def test_list_shows_documents_with_their_versions_page_by_page(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    for title in ("Charlie", "alpha", "Bravo"):
        assert (await upload(client, admin_headers, SMALL, title=title)).status_code == 202
    await run_jobs(session_factory, settings)

    everything = (await client.get("/api/admin/documents", headers=admin_headers)).json()
    page = (
        await client.get(
            "/api/admin/documents", headers=admin_headers, params={"limit": 1, "offset": 1}
        )
    ).json()

    assert everything["total"] == 3
    assert [item["title"] for item in everything["items"]] == ["alpha", "Bravo", "Charlie"]
    assert all(item["active_version"]["indexing_status"] == "ready" for item in everything["items"])
    assert (page["total"], [item["title"] for item in page["items"]]) == (3, ["Bravo"])


@pytest.mark.parametrize(
    ("filename", "data", "status_code", "code"),
    [
        ("notes.txt", b"Plain text.", 415, "unsupported_media_type"),
        ("report.docx", b"PK\x03\x04 word", 415, "unsupported_media_type"),
        ("empty.md", b"   \n", 422, "validation_error"),
        ("binary.md", b"\xff\xfe\x00\x01", 422, "validation_error"),
        ("broken.pdf", b"%PDF-1.7\nnot really a pdf", 422, "validation_error"),
    ],
)
async def test_files_that_cannot_be_documents_are_rejected(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    filename: str,
    data: bytes,
    status_code: int,
    code: str,
) -> None:
    response = await upload(client, admin_headers, data, filename=filename)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    listing = await client.get("/api/admin/documents", headers=admin_headers)
    assert listing.json()["total"] == 0


async def test_indexing_failure_is_visible_and_leaves_nothing_searchable(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(
        client, admin_headers, session_factory, settings, blank_pdf(), filename="scan.pdf"
    )

    version = document["latest_version"]
    assert document["active_version"] is None
    assert version["indexing_status"] == "failed"
    assert "no text layer" in version["indexing_error"]
    assert version["is_active"] is False
    assert await _chunks(session_factory, version["id"]) == []
    async with session_factory() as session:
        job = (await session.execute(select(Job))).scalar_one()
    # A file that cannot be parsed is not retried.
    assert (job.status, job.attempts) == (JobStatus.FAILED, 1)


class _FlakyEmbeddings(LocalEmbeddingProvider):
    """Fails with a retryable error a set number of times, then works."""

    def __init__(self, failures: int) -> None:
        self.failures = failures

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.failures > 0:
            self.failures -= 1
            raise ProviderError("The embedding API returned HTTP 429: slow down", retryable=True)
        return await super().embed_documents(texts)


async def _make_jobs_due(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        await session.execute(
            update(Job)
            .where(Job.status == JobStatus.QUEUED)
            .values(run_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()


async def test_a_provider_failure_is_retried_and_the_error_is_shown_meanwhile(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    providers = dataclasses.replace(build_providers(settings), embeddings=_FlakyEmbeddings(1))
    document_id = (await upload(client, admin_headers, SMALL)).json()["id"]

    await run_jobs(session_factory, settings, providers)
    waiting = (
        await client.get(f"/api/admin/documents/{document_id}", headers=admin_headers)
    ).json()["latest_version"]
    await _make_jobs_due(session_factory)
    await run_jobs(session_factory, settings, providers)
    done = (await client.get(f"/api/admin/documents/{document_id}", headers=admin_headers)).json()[
        "latest_version"
    ]

    assert (waiting["indexing_status"], waiting["is_active"]) == ("pending", False)
    assert "HTTP 429" in waiting["indexing_error"]
    assert (done["indexing_status"], done["indexing_error"], done["is_active"]) == (
        "ready",
        None,
        True,
    )


async def test_indexing_fails_for_good_when_retries_run_out(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    providers = dataclasses.replace(build_providers(settings), embeddings=_FlakyEmbeddings(99))
    document_id = (await upload(client, admin_headers, SMALL)).json()["id"]
    async with session_factory() as session:
        await session.execute(update(Job).values(max_attempts=2))
        await session.commit()

    await run_jobs(session_factory, settings, providers)
    await _make_jobs_due(session_factory)
    await run_jobs(session_factory, settings, providers)

    version = (
        await client.get(f"/api/admin/documents/{document_id}", headers=admin_headers)
    ).json()["latest_version"]
    assert version["indexing_status"] == "failed"
    assert "HTTP 429" in version["indexing_error"]


async def test_indexing_twice_does_not_duplicate_chunks(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, RETURNS)
    async with session_factory() as session:
        job = (await session.execute(select(Job))).scalar_one()
        job.status = JobStatus.QUEUED
        job.attempts = 0
        await session.commit()

    assert await run_jobs(session_factory, settings) == 1

    again = (
        await client.get(f"/api/admin/documents/{document['id']}", headers=admin_headers)
    ).json()
    assert again["active_version"]["chunk_count"] == 9
    assert len(await _chunks(session_factory, again["active_version"]["id"])) == 9


# --- Replacement and deletion ------------------------------------------------------


async def test_replacement_becomes_active_only_after_it_is_indexed(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, SMALL)
    first_id = document["active_version"]["id"]

    response = await upload(
        client, admin_headers, SMALL_V2, document_id=document["id"], version_label="v2"
    )
    assert response.status_code == 202
    pending = response.json()
    assert pending["active_version"]["id"] == first_id
    assert pending["latest_version"]["version_number"] == 2
    assert pending["latest_version"]["indexing_status"] == "pending"
    # The old version keeps answering while the new one waits for indexing.
    assert (
        "Thirty days" in (await _search(client, admin_headers, "days from delivery"))[0]["content"]
    )

    await run_jobs(session_factory, settings)

    detail = (
        await client.get(f"/api/admin/documents/{document['id']}", headers=admin_headers)
    ).json()
    first, second = detail["versions"]
    assert detail["active_version"]["id"] == second["id"] == detail["latest_version"]["id"]
    assert (first["is_active"], second["is_active"]) == (False, True)
    assert (first["indexing_status"], second["indexing_status"]) == ("ready", "ready")
    results = await _search(client, admin_headers, "days from delivery")
    assert {item["document_version_id"] for item in results} == {second["id"]}
    assert "Forty-five days" in results[0]["content"]
    # The old chunks are kept for the record but are out of retrieval.
    assert len(await _chunks(session_factory, first_id)) == 1


async def test_a_failed_replacement_leaves_the_old_version_active(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, SMALL)

    await upload(
        client, admin_headers, blank_pdf(), filename="scan.pdf", document_id=document["id"]
    )
    await run_jobs(session_factory, settings)

    detail = (
        await client.get(f"/api/admin/documents/{document['id']}", headers=admin_headers)
    ).json()
    assert detail["active_version"]["version_number"] == 1
    assert detail["latest_version"]["version_number"] == 2
    assert detail["latest_version"]["indexing_status"] == "failed"
    assert (
        "Thirty days" in (await _search(client, admin_headers, "days from delivery"))[0]["content"]
    )


async def test_a_replacement_that_runs_out_of_retries_leaves_the_old_version_active(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, SMALL)
    providers = dataclasses.replace(build_providers(settings), embeddings=_FlakyEmbeddings(99))

    await upload(client, admin_headers, SMALL_V2, document_id=document["id"])
    async with session_factory() as session:
        await session.execute(
            update(Job).where(Job.status == JobStatus.QUEUED).values(max_attempts=2)
        )
        await session.commit()
    await run_jobs(session_factory, settings, providers)
    await _make_jobs_due(session_factory)
    await run_jobs(session_factory, settings, providers)

    detail = (
        await client.get(f"/api/admin/documents/{document['id']}", headers=admin_headers)
    ).json()
    assert detail["active_version"]["version_number"] == 1
    assert detail["latest_version"]["version_number"] == 2
    assert detail["latest_version"]["indexing_status"] == "failed"
    assert "HTTP 429" in detail["latest_version"]["indexing_error"]
    passages = await _search(client, admin_headers, "days from delivery")
    assert "Thirty days" in passages[0]["content"]
    assert all("Forty-five" not in passage["content"] for passage in passages)


async def test_an_older_upload_indexed_late_does_not_replace_a_newer_one(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, SMALL)
    await upload(client, admin_headers, SMALL_V2, document_id=document["id"])
    await upload(
        client,
        admin_headers,
        b"# Returns\n\nSixty days from delivery.\n",
        document_id=document["id"],
    )
    # Run the job of version 3 before the job of version 2.
    async with session_factory() as session:
        jobs = (await session.execute(select(Job).order_by(Job.created_at))).scalars().all()
        jobs[1].run_at = datetime.now(UTC) - timedelta(seconds=1)
        jobs[2].run_at = datetime.now(UTC) - timedelta(seconds=60)
        await session.commit()

    assert await run_jobs(session_factory, settings) == 2

    detail = (
        await client.get(f"/api/admin/documents/{document['id']}", headers=admin_headers)
    ).json()
    assert [version["is_active"] for version in detail["versions"]] == [False, False, True]
    assert [version["indexing_status"] for version in detail["versions"]] == ["ready"] * 3
    assert (
        "Sixty days" in (await _search(client, admin_headers, "days from delivery"))[0]["content"]
    )


async def test_delete_removes_the_document_from_the_api_and_from_retrieval(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    kept = await ingest(client, admin_headers, session_factory, settings, SMALL, title="Kept")
    gone = await ingest(client, admin_headers, session_factory, settings, SMALL_V2, title="Gone")

    response = await client.delete(f"/api/admin/documents/{gone['id']}", headers=admin_headers)

    assert response.status_code == 204
    assert response.content == b""
    listing = (await client.get("/api/admin/documents", headers=admin_headers)).json()
    assert [item["id"] for item in listing["items"]] == [kept["id"]]
    for method, path in (
        ("GET", f"/api/admin/documents/{gone['id']}"),
        ("DELETE", f"/api/admin/documents/{gone['id']}"),
    ):
        again = await client.request(method, path, headers=admin_headers)
        assert again.status_code == 404
        assert again.json()["error"]["code"] == "not_found"
    replace = await upload(client, admin_headers, SMALL, document_id=gone["id"])
    assert replace.status_code == 404
    results = await _search(client, admin_headers, "days from delivery", top_k=50)
    assert {item["document_id"] for item in results} == {kept["id"]}
    async with session_factory() as session:
        row = await session.get(Document, uuid.UUID(gone["id"]))
        active = (
            await session.execute(
                select(func.count())
                .select_from(DocumentVersion)
                .where(
                    DocumentVersion.document_id == uuid.UUID(gone["id"]),
                    DocumentVersion.is_active.is_(True),
                )
            )
        ).scalar_one()
    assert row is not None
    assert row.deleted_at is not None
    assert active == 0


async def test_a_document_deleted_before_indexing_never_becomes_searchable(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document_id = (await upload(client, admin_headers, SMALL)).json()["id"]
    await client.delete(f"/api/admin/documents/{document_id}", headers=admin_headers)

    assert await run_jobs(session_factory, settings) == 1

    assert await _search(client, admin_headers, "days from delivery") == []
    async with session_factory() as session:
        version = (await session.execute(select(DocumentVersion))).scalar_one()
        job = (await session.execute(select(Job))).scalar_one()
    assert (version.is_active, version.indexing_status) == (False, IndexingStatus.PENDING)
    assert (job.status, job.result) == (
        JobStatus.SUCCEEDED,
        {"document_version_id": str(version.id), "skipped": "document_deleted"},
    )


class _DeletingEmbeddings(LocalEmbeddingProvider):
    """Deletes the document through the API while its text is being embedded."""

    def __init__(self, client: httpx.AsyncClient, headers: dict[str, str], document_id: str):
        self.client, self.headers, self.document_id = client, headers, document_id

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self.client.delete(
            f"/api/admin/documents/{self.document_id}", headers=self.headers
        )
        assert response.status_code == 204
        return await super().embed_documents(texts)


async def test_a_document_deleted_while_it_is_indexed_is_not_activated(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document_id = (await upload(client, admin_headers, SMALL)).json()["id"]
    providers = dataclasses.replace(
        build_providers(settings),
        embeddings=_DeletingEmbeddings(client, admin_headers, document_id),
    )

    assert await run_jobs(session_factory, settings, providers) == 1

    async with session_factory() as session:
        version = (await session.execute(select(DocumentVersion))).scalar_one()
        job = (await session.execute(select(Job))).scalar_one()
    # The chunks are stored, but a deleted document has no active version.
    assert (version.is_active, version.activated_at) == (False, None)
    assert version.indexing_status is IndexingStatus.READY
    assert job.status is JobStatus.SUCCEEDED
    assert job.result is not None
    assert job.result["activated"] is False
    assert await _search(client, admin_headers, "days from delivery") == []


async def test_unknown_documents_return_404(
    client: httpx.AsyncClient, admin_headers: dict[str, str], session_factory: SessionFactory
) -> None:
    get = await client.get(f"/api/admin/documents/{MISSING_ID}", headers=admin_headers)
    delete = await client.delete(f"/api/admin/documents/{MISSING_ID}", headers=admin_headers)
    replace = await upload(client, admin_headers, SMALL, document_id=MISSING_ID)

    assert [get.status_code, delete.status_code, replace.status_code] == [404, 404, 404]


# --- Retrieval on its own ------------------------------------------------------------


async def test_search_returns_ranked_passages_with_their_source(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    returns = await ingest(
        client, admin_headers, session_factory, settings, RETURNS, version_label="2.0"
    )
    warranty = await ingest(client, admin_headers, session_factory, settings, WARRANTY_PDF)

    refunds = await _search(client, admin_headers, "When is the refund issued after a return?")
    coverage = await _search(
        client, admin_headers, "What does Northline Care extended coverage cost?", top_k=3
    )

    assert [item["rank"] for item in refunds] == [1, 2, 3, 4, 5]
    assert [item["score"] for item in refunds] == sorted(
        (item["score"] for item in refunds), reverse=True
    )
    top = refunds[0]
    assert top["document_id"] == returns["id"]
    assert top["document_title"] == "Returns Policy"
    assert top["version_number"] == 1
    assert top["version_label"] == "2.0"
    assert top["source_filename"] == "returns-policy.md"
    assert (top["section"], top["section_title"], top["page_number"]) == (
        "Refunds",
        "Refunds",
        None,
    )
    assert "within 7 business days" in top["content"]

    assert len(coverage) == 3
    assert coverage[0]["document_id"] == warranty["id"]
    assert (coverage[0]["section_title"], coverage[0]["page_number"]) == (
        "Northline Care extended coverage",
        3,
    )


async def test_search_only_compares_chunks_of_the_current_embedding_model(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    await ingest(client, admin_headers, session_factory, settings, SMALL)
    async with session_factory() as session:
        # Chunks left by another model have another dimension; comparing them would fail.
        await session.execute(update(Chunk).values(embedding=[1.0, 0.0], embedding_model="other"))
        await session.commit()

    assert await _search(client, admin_headers, "days from delivery") == []


async def test_search_validates_its_input(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    for body in (
        {"query": "  "},
        {"query": "returns", "top_k": 0},
        {"query": "returns", "top_k": 51},
    ):
        response = await client.post(
            "/api/admin/documents/search", headers=admin_headers, json=body
        )
        assert response.status_code == 422, body


# --- Upload size limit ------------------------------------------------------------------


def _multipart(data: bytes) -> tuple[bytes, str]:
    boundary = "test-boundary-7d1f"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="big.md"\r\n'
            f"Content-Type: text/markdown\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={boundary}"


async def test_a_file_over_the_limit_is_rejected(
    settings: Settings, admin_headers: dict[str, str], session_factory: SessionFactory
) -> None:
    limit = 2000
    async with _client_with(make_settings(settings.database_url, max_upload_bytes=limit)) as client:
        at_limit = await upload(client, admin_headers, b"# Fits\n\n" + b"a" * (limit - 8))
        # Just over the limit: passes the body cap, fails the exact check of the file.
        over = await upload(client, admin_headers, b"# Big\n\n" + b"a" * limit)
        # Far over the limit: rejected from Content-Length, before the body is read.
        huge = await upload(client, admin_headers, b"# Huge\n\n" + b"a" * 200_000)
        document_id = at_limit.json()["id"]
        replacement = await upload(
            client, admin_headers, b"# Big\n\n" + b"a" * limit, document_id=document_id
        )
        listing = await client.get("/api/admin/documents", headers=admin_headers)

    assert at_limit.status_code == 202
    for response in (over, huge, replacement):
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "payload_too_large"
        assert response.json()["error"]["details"] == []
        assert "2000 bytes" in response.json()["error"]["message"]
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["latest_version"]["version_number"] == 1


async def test_a_streamed_upload_without_content_length_is_cut_off_at_the_limit(
    settings: Settings, admin_headers: dict[str, str], session_factory: SessionFactory
) -> None:
    body, content_type = _multipart(b"# Huge\n\n" + b"a" * 400_000)
    sent = 0

    async def stream() -> AsyncIterator[bytes]:
        nonlocal sent
        for start in range(0, len(body), 16_384):
            sent += 1
            yield body[start : start + 16_384]

    async with _client_with(make_settings(settings.database_url, max_upload_bytes=2000)) as client:
        response = await client.post(
            "/api/admin/documents",
            headers={**admin_headers, "Content-Type": content_type},
            content=stream(),
        )
        listing = await client.get("/api/admin/documents", headers=admin_headers)

    assert "content-length" not in response.request.headers
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert listing.json()["total"] == 0


# --- Access ----------------------------------------------------------------------------


async def _visitor_requests(
    client: httpx.AsyncClient, document_id: str, headers: dict[str, str] | None
) -> list[httpx.Response]:
    return [
        await client.get("/api/admin/documents", headers=headers),
        await client.get(f"/api/admin/documents/{document_id}", headers=headers),
        await upload(client, headers or {}, SMALL_V2, title="Visitor upload"),
        await upload(client, headers or {}, SMALL_V2, document_id=document_id),
        await client.delete(f"/api/admin/documents/{document_id}", headers=headers),
        await client.post(
            "/api/admin/documents/search", headers=headers, json={"query": "days from delivery"}
        ),
    ]


async def test_a_content_length_that_is_not_a_number_does_not_break_the_guard(
    settings: Settings,
) -> None:
    calls: list[str] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        calls.append(scope["path"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    guard = UploadGuardMiddleware(inner, settings=settings)
    for declared in ("\u00b2", "-5", "12abc", ""):
        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/documents",
            "headers": [
                (b"authorization", b"Bearer test-admin-token"),
                (b"content-length", declared.encode("latin-1")),
            ],
        }
        await guard(scope, receive, send)

    # The request goes on; the streaming limit still applies to its body.
    assert calls == ["/api/admin/documents"] * 4
    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [204] * 4


@pytest.mark.parametrize(
    ("headers", "status_code", "code"),
    [
        (None, 401, "unauthorized"),
        ({"Authorization": "Bearer wrong-token"}, 403, "forbidden"),
        ({"Authorization": "Basic dGVzdC1hZG1pbi10b2tlbjo="}, 401, "unauthorized"),
    ],
    ids=["no-token", "wrong-token", "not-bearer"],
)
async def test_a_visitor_cannot_read_upload_replace_delete_or_search_documents(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
    headers: dict[str, str] | None,
    status_code: int,
    code: str,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, SMALL)

    responses = await _visitor_requests(client, document["id"], headers)

    assert [response.status_code for response in responses] == [status_code] * 6
    assert {response.json()["error"]["code"] for response in responses} == {code}
    # Nothing changed: one document, one version, still active and searchable.
    listing = (await client.get("/api/admin/documents", headers=admin_headers)).json()
    assert listing["total"] == 1
    assert listing["items"][0]["latest_version"]["version_number"] == 1
    assert listing["items"][0]["active_version"]["id"] == document["active_version"]["id"]
    assert await run_jobs(session_factory, settings) == 0
    assert (
        "Thirty days" in (await _search(client, admin_headers, "days from delivery"))[0]["content"]
    )


@pytest.mark.parametrize(
    ("authorization", "status_code", "message"),
    [
        (None, 401, "Administrator token required."),
        ("Bearer wrong-token", 403, "Administrator token rejected."),
    ],
    ids=["no-token", "wrong-token"],
)
@pytest.mark.parametrize("target", ["new-document", "new-version"])
async def test_a_visitor_upload_is_refused_before_its_body_is_read(
    client: httpx.AsyncClient,
    session_factory: SessionFactory,
    authorization: str | None,
    status_code: int,
    message: str,
    target: str,
) -> None:
    body, content_type = _multipart(b"# Huge\n\n" + b"a" * 400_000)
    chunks_sent = 0

    async def stream() -> AsyncIterator[bytes]:
        nonlocal chunks_sent
        for start in range(0, len(body), 16_384):
            chunks_sent += 1
            yield body[start : start + 16_384]

    headers = {"Content-Type": content_type}
    if authorization is not None:
        headers["Authorization"] = authorization
    path = "/api/admin/documents"
    if target == "new-version":
        path += "/00000000-0000-4000-8000-000000000001/versions"
    response = await client.post(path, headers=headers, content=stream())

    assert response.status_code == status_code
    if status_code == 401:
        assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["message"] == message
    assert chunks_sent == 0


async def test_uploads_are_closed_when_no_admin_token_is_configured(
    settings: Settings, session_factory: SessionFactory
) -> None:
    async with _client_with(make_settings(settings.database_url, admin_api_token=None)) as client:
        for headers in (
            {},
            {"Authorization": "Bearer test-admin-token"},
            {"Authorization": "Bearer "},
        ):
            response = await upload(client, headers, SMALL)
            assert response.status_code in (401, 403), headers
    async with session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Document))).scalar_one() == 0
