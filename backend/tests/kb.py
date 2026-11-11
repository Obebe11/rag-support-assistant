"""Helpers for knowledge base and chat tests."""

import dataclasses
import io
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from pypdf import PdfWriter

from app.core.config import REPO_ROOT, Settings
from app.core.db import SessionFactory
from app.providers.factory import Providers, build_providers
from app.worker.handlers import load_handlers
from app.worker.registry import JobRegistry
from app.worker.runner import Worker

NORTHLINE = REPO_ROOT / "knowledge-base" / "northline"
NORTHLINE_DOCUMENTS = NORTHLINE / "documents"
REPLACEMENT_TEST = REPO_ROOT / "knowledge-base" / "northline-replacement-test"
EVAL_FIXTURES = REPO_ROOT / "evals" / "fixtures"

MARKDOWN = "text/markdown"
PDF = "application/pdf"


def blank_pdf() -> bytes:
    """A valid PDF with one empty page: no text layer."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _file(source: Path | bytes, filename: str | None) -> tuple[str, bytes, str]:
    data = source.read_bytes() if isinstance(source, Path) else source
    name = filename or (source.name if isinstance(source, Path) else "document.md")
    return name, data, PDF if name.endswith(".pdf") else MARKDOWN


async def run_jobs(
    session_factory: SessionFactory, settings: Settings, providers: Providers | None = None
) -> int:
    """Run the worker until no job is due. Returns the number of jobs processed."""
    registry = JobRegistry()
    load_handlers(registry)
    worker = Worker(
        session_factory=session_factory,
        registry=registry,
        settings=settings,
        providers=providers or build_providers(settings),
        worker_id="test-worker",
    )
    processed = 0
    while await worker.run_once():
        processed += 1
    return processed


async def upload(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    source: Path | bytes,
    *,
    filename: str | None = None,
    document_id: str | None = None,
    **form: str,
) -> httpx.Response:
    """Upload a new document, or a new version when `document_id` is given."""
    path = f"/api/admin/documents/{document_id}/versions" if document_id else "/api/admin/documents"
    return await client.post(
        path, headers=headers, files={"file": _file(source, filename)}, data=form or None
    )


async def ingest(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
    source: Path | bytes,
    **kwargs: Any,
) -> dict[str, Any]:
    """Upload, index, and return the document as the admin API shows it."""
    response = await upload(client, headers, source, **kwargs)
    assert response.status_code == 202, response.text
    await run_jobs(session_factory, settings)
    document_id = response.json()["id"]
    detail = await client.get(f"/api/admin/documents/{document_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body: dict[str, Any] = detail.json()
    return body


async def start_conversation(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/conversations")
    assert response.status_code == 201, response.text
    conversation_id: str = response.json()["id"]
    return conversation_id


async def ask(
    client: httpx.AsyncClient, question: str, conversation_id: str | None = None
) -> dict[str, Any]:
    """Send a visitor message and return the assistant's reply."""
    conversation_id = conversation_id or await start_conversation(client)
    response = await client.post(
        f"/api/conversations/{conversation_id}/messages", json={"content": question}
    )
    assert response.status_code == 201, response.text
    reply: dict[str, Any] = response.json()["assistant_message"]
    return reply


def replace_providers(app: FastAPI, **changes: Any) -> None:
    """Swap providers of a running app, for example to add a mock transport."""
    app.state.providers = dataclasses.replace(app.state.providers, **changes)
