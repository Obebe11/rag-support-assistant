"""Indexing status after a worker dies in the middle of indexing a document version."""

import dataclasses
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.db import SessionFactory
from app.providers.embeddings.local import LocalEmbeddingProvider
from app.providers.factory import Providers, build_providers
from app.worker.queue import ABANDONED_ERROR
from tests.kb import ask, ingest, run_jobs, upload

V1 = b"# Returns\n\n## Window\n\nThirty days from delivery.\n"
V2 = b"# Returns\n\n## Window\n\nForty-five days from delivery.\n"


class WorkerKilledError(BaseException):
    """Stops the worker mid-attempt without any cleanup, like a killed process."""


class _KillingEmbeddings(LocalEmbeddingProvider):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise WorkerKilledError


def _killing_providers(settings: Settings) -> Providers:
    return dataclasses.replace(build_providers(settings), embeddings=_KillingEmbeddings())


async def _sql(session_factory: SessionFactory, statement: str) -> None:
    async with session_factory() as session:
        await session.execute(text(statement))
        await session.commit()


async def _only_one_attempt(session_factory: SessionFactory) -> None:
    await _sql(session_factory, "UPDATE jobs SET max_attempts = 1 WHERE status = 'queued'")


async def _expire_leases(session_factory: SessionFactory) -> None:
    """Make every running job look abandoned, as after a worker crash long ago."""
    await _sql(
        session_factory,
        "UPDATE jobs SET locked_at = now() - interval '1 day' WHERE status = 'running'",
    )


async def _document(
    client: httpx.AsyncClient, headers: dict[str, str], document_id: str
) -> dict[str, Any]:
    response = await client.get(f"/api/admin/documents/{document_id}", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _search(client: httpx.AsyncClient, headers: dict[str, str], query: str) -> list[str]:
    response = await client.post(
        "/api/admin/documents/search", headers=headers, json={"query": query}
    )
    assert response.status_code == 200, response.text
    return [item["content"] for item in response.json()["items"]]


async def test_worker_death_on_the_final_attempt_fails_the_version_instead_of_leaving_it_indexing(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document_id = (await upload(client, admin_headers, V1)).json()["id"]
    await _only_one_attempt(session_factory)

    with pytest.raises(WorkerKilledError):
        await run_jobs(session_factory, settings, _killing_providers(settings))
    stuck = (await _document(client, admin_headers, document_id))["latest_version"]
    assert stuck["indexing_status"] == "indexing", "the dead worker recorded nothing"

    # The lease still holds: nobody can tell a dead worker from a slow one yet.
    assert await run_jobs(session_factory, settings) == 0
    assert (await _document(client, admin_headers, document_id))["latest_version"][
        "indexing_status"
    ] == "indexing"

    await _expire_leases(session_factory)
    assert await run_jobs(session_factory, settings) == 0, "the job is given up, not run again"

    failed = (await _document(client, admin_headers, document_id))["latest_version"]
    assert (failed["indexing_status"], failed["indexing_error"], failed["is_active"]) == (
        "failed",
        ABANDONED_ERROR,
        False,
    )
    assert await _search(client, admin_headers, "return window") == []


async def test_worker_death_while_replacing_a_document_keeps_the_old_version_answering(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document = await ingest(client, admin_headers, session_factory, settings, V1)
    await upload(client, admin_headers, V2, document_id=document["id"])
    await _only_one_attempt(session_factory)

    with pytest.raises(WorkerKilledError):
        await run_jobs(session_factory, settings, _killing_providers(settings))
    await _expire_leases(session_factory)
    assert await run_jobs(session_factory, settings) == 0

    versions = {
        version["version_number"]: version
        for version in (await _document(client, admin_headers, document["id"]))["versions"]
    }
    assert (versions[1]["indexing_status"], versions[1]["is_active"]) == ("ready", True)
    assert (versions[2]["indexing_status"], versions[2]["is_active"]) == ("failed", False)
    assert versions[2]["indexing_error"] == ABANDONED_ERROR
    passages = await _search(client, admin_headers, "return window days from delivery")
    assert any("Thirty days" in passage for passage in passages)
    assert not any("Forty-five" in passage for passage in passages)
    reply = await ask(client, "How many days from delivery is the return window?")
    assert "Forty-five" not in reply["content"]


async def test_worker_death_before_the_final_attempt_is_repaired_by_the_next_attempt(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    document_id = (await upload(client, admin_headers, V1)).json()["id"]

    with pytest.raises(WorkerKilledError):
        await run_jobs(session_factory, settings, _killing_providers(settings))
    await _expire_leases(session_factory)
    assert await run_jobs(session_factory, settings) == 1, "a running worker takes the job over"

    version = (await _document(client, admin_headers, document_id))["latest_version"]
    assert (version["indexing_status"], version["indexing_error"], version["is_active"]) == (
        "ready",
        None,
        True,
    )
