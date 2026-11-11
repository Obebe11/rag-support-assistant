"""Helpers shared by the inquiry, delivery and CRM tests."""

import dataclasses
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from sqlalchemy import select, text

from app.core.config import Settings
from app.core.db import SessionFactory
from app.main import create_app
from app.models.inquiries import InquiryDelivery
from app.models.jobs import Job
from app.providers.crm.base import CRMProvider
from app.providers.factory import build_providers
from app.services.inquiries.service import delivery_job_key
from app.worker.handlers import load_handlers
from app.worker.registry import JobRegistry
from app.worker.runner import Worker


def purchase_body(email: str = "jane.doe@example.com", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "product": "Standing desk",
        "quantity": 20,
        "timeline": "by the end of March",
        "contact": {
            "name": "Jane Doe",
            "email": email,
            "company": "Acme Corp",
            "phone": "+1 555 010 2030",
        },
        "notes": "Black frame preferred.",
    }
    body.update(overrides)
    return body


def handoff_body(email: str = "sam.lee@example.com", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "handoff",
        "contact": {"name": "Sam Lee", "email": email},
        "notes": "Do you offer on-site assembly in Alaska?",
    }
    body.update(overrides)
    return body


@asynccontextmanager
async def api_client(settings: Settings, **overrides: object) -> AsyncIterator[httpx.AsyncClient]:
    """An API client on an application with changed settings."""
    app = create_app(settings.model_copy(update=overrides))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


def delivery_worker(
    session_factory: SessionFactory,
    settings: Settings,
    crm: CRMProvider,
    *,
    worker_id: str = "worker-a",
    **overrides: object,
) -> Worker:
    """A worker with the real handlers and the given CRM provider."""
    worker_settings = settings.model_copy(update=overrides)
    registry = JobRegistry()
    load_handlers(registry)
    return Worker(
        session_factory=session_factory,
        registry=registry,
        settings=worker_settings,
        providers=dataclasses.replace(build_providers(worker_settings), crm=crm),
        worker_id=worker_id,
    )


async def create_confirmed(client: httpx.AsyncClient, body: dict[str, Any]) -> str:
    """Create a draft, confirm it and return the inquiry ID."""
    created = await client.post("/api/inquiries", json=body)
    assert created.status_code == 201, created.text
    inquiry_id: str = created.json()["id"]
    confirmed = await client.post(f"/api/inquiries/{inquiry_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    return inquiry_id


async def get_delivery(client: httpx.AsyncClient, inquiry_id: str) -> dict[str, Any]:
    response = await client.get(f"/api/inquiries/{inquiry_id}/delivery")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def make_jobs_due(session_factory: SessionFactory) -> None:
    """Skip the retry backoff: every queued job may run now."""
    async with session_factory() as session:
        await session.execute(
            text("UPDATE jobs SET run_at = now() - interval '1 second' WHERE status = 'queued'")
        )
        await session.commit()


async def expire_leases(session_factory: SessionFactory) -> None:
    """Make every running job look abandoned, as after a worker crash long ago."""
    async with session_factory() as session:
        await session.execute(
            text("UPDATE jobs SET locked_at = now() - interval '1 day' WHERE status = 'running'")
        )
        await session.commit()


async def delivery_job(session_factory: SessionFactory, inquiry_id: str) -> Job:
    async with session_factory() as session:
        return (
            await session.execute(
                select(Job).where(Job.idempotency_key == delivery_job_key(uuid.UUID(inquiry_id)))
            )
        ).scalar_one()


async def delivery_row(session_factory: SessionFactory, inquiry_id: str) -> InquiryDelivery:
    async with session_factory() as session:
        return (
            await session.execute(
                select(InquiryDelivery).where(InquiryDelivery.inquiry_id == uuid.UUID(inquiry_id))
            )
        ).scalar_one()
