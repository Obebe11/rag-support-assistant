"""The worker loop: handlers, transactions, failures and shutdown."""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionFactory
from app.models.base import JSONDict
from app.models.conversations import Conversation
from app.models.enums import JobStatus
from app.models.jobs import Job
from app.providers.factory import build_providers
from app.worker import queue
from app.worker.handlers import load_handlers
from app.worker.registry import JobContext, JobHandler, JobRegistry, PermanentJobError
from app.worker.runner import Worker


def _worker(
    session_factory: SessionFactory,
    settings: Settings,
    handlers: dict[str, JobHandler],
    **setting_overrides: object,
) -> Worker:
    registry = JobRegistry()
    for job_type, handler in handlers.items():
        registry.register(job_type, handler)
    worker_settings = settings.model_copy(update=setting_overrides)
    return Worker(
        session_factory=session_factory,
        registry=registry,
        settings=worker_settings,
        providers=build_providers(worker_settings),
        worker_id="test-worker",
    )


async def _enqueue(session_factory: SessionFactory, job_type: str, **kwargs: object) -> uuid.UUID:
    async with session_factory() as session:
        result = await queue.enqueue(session, job_type, **kwargs)  # type: ignore[arg-type]
        await session.commit()
        return result.job.id


async def _get(session_factory: SessionFactory, job_id: uuid.UUID) -> Job:
    async with session_factory() as session:
        return (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()


async def _count_conversations(session_factory: SessionFactory) -> int:
    async with session_factory() as session:
        return (await session.execute(select(func.count()).select_from(Conversation))).scalar_one()


async def test_worker_runs_the_handler_and_marks_the_job_succeeded(
    session_factory: SessionFactory, settings: Settings
) -> None:
    seen: list[JobContext] = []

    async def handler(context: JobContext) -> JSONDict | None:
        seen.append(context)
        return {"ok": True}

    job_id = await _enqueue(session_factory, "test.job", payload={"n": 1}, max_attempts=3)
    worker = _worker(session_factory, settings, {"test.job": handler})

    assert await worker.run_once() is True

    job = await _get(session_factory, job_id)
    assert job.status is JobStatus.SUCCEEDED
    assert job.result == {"ok": True}
    assert len(seen) == 1
    assert (seen[0].job_id, seen[0].job_type, seen[0].payload) == (job_id, "test.job", {"n": 1})
    assert (seen[0].attempt, seen[0].max_attempts, seen[0].is_final_attempt) == (1, 3, False)
    assert seen[0].providers.crm.live is False


async def test_worker_reports_an_idle_queue(
    session_factory: SessionFactory, settings: Settings
) -> None:
    worker = _worker(session_factory, settings, {})

    assert await worker.run_once() is False


async def test_handler_writes_are_committed_with_the_job(
    session_factory: SessionFactory, settings: Settings
) -> None:
    async def handler(context: JobContext) -> JSONDict | None:
        context.session.add(Conversation())
        return None

    await _enqueue(session_factory, "test.job")
    worker = _worker(session_factory, settings, {"test.job": handler})

    await worker.run_once()

    assert await _count_conversations(session_factory) == 1


async def test_failed_handler_rolls_back_its_writes_and_schedules_a_retry(
    session_factory: SessionFactory, settings: Settings
) -> None:
    async def handler(context: JobContext) -> JSONDict | None:
        context.session.add(Conversation())
        await context.session.flush()
        raise RuntimeError("CRM is down")

    job_id = await _enqueue(session_factory, "test.job", max_attempts=3)
    worker = _worker(session_factory, settings, {"test.job": handler})
    before = datetime.now(UTC)

    assert await worker.run_once() is True

    job = await _get(session_factory, job_id)
    assert job.status is JobStatus.QUEUED
    assert job.attempts == 1
    assert job.last_error == "RuntimeError: CRM is down"
    assert job.run_at > before
    assert await _count_conversations(session_factory) == 0
    # The retry is delayed, so nothing is due right now.
    assert await worker.run_once() is False


async def test_writes_committed_by_the_handler_survive_a_failed_attempt(
    session_factory: SessionFactory, settings: Settings
) -> None:
    async def handler(context: JobContext) -> JSONDict | None:
        context.session.add(Conversation())
        await context.session.commit()
        raise RuntimeError("failed after recording the attempt")

    await _enqueue(session_factory, "test.job")
    worker = _worker(session_factory, settings, {"test.job": handler})

    await worker.run_once()

    assert await _count_conversations(session_factory) == 1


async def test_job_fails_after_its_last_attempt(
    session_factory: SessionFactory, settings: Settings
) -> None:
    attempts: list[bool] = []

    async def handler(context: JobContext) -> JSONDict | None:
        attempts.append(context.is_final_attempt)
        raise RuntimeError("still down")

    job_id = await _enqueue(session_factory, "test.job", max_attempts=2)
    worker = _worker(
        session_factory, settings, {"test.job": handler}, job_backoff_base_seconds=0.01
    )

    await worker.run_once()
    await asyncio.sleep(0.05)
    await worker.run_once()

    job = await _get(session_factory, job_id)
    assert attempts == [False, True]
    assert job.status is JobStatus.FAILED
    assert job.attempts == 2


async def test_permanent_error_fails_the_job_without_a_retry(
    session_factory: SessionFactory, settings: Settings
) -> None:
    async def handler(context: JobContext) -> JSONDict | None:
        raise PermanentJobError("The inquiry no longer exists.")

    job_id = await _enqueue(session_factory, "test.job", max_attempts=5)
    worker = _worker(session_factory, settings, {"test.job": handler})

    await worker.run_once()

    job = await _get(session_factory, job_id)
    assert job.status is JobStatus.FAILED
    assert job.attempts == 1
    assert job.last_error == "The inquiry no longer exists."


async def test_job_without_a_handler_fails(
    session_factory: SessionFactory, settings: Settings
) -> None:
    job_id = await _enqueue(session_factory, "unknown.job")
    worker = _worker(session_factory, settings, {})

    await worker.run_once()

    job = await _get(session_factory, job_id)
    assert job.status is JobStatus.FAILED
    assert job.last_error == "No handler is registered for job type 'unknown.job'."


async def test_handler_that_exceeds_the_timeout_is_retried(
    session_factory: SessionFactory, settings: Settings
) -> None:
    async def handler(context: JobContext) -> JSONDict | None:
        await asyncio.sleep(5)
        return None

    job_id = await _enqueue(session_factory, "test.job")
    worker = _worker(session_factory, settings, {"test.job": handler}, job_timeout_seconds=0.05)

    await worker.run_once()

    job = await _get(session_factory, job_id)
    assert job.status is JobStatus.QUEUED
    assert job.last_error is not None
    assert job.last_error.startswith("TimeoutError")


async def test_result_of_a_worker_that_lost_its_lease_is_discarded(
    session_factory: SessionFactory, settings: Settings
) -> None:
    job_id = await _enqueue(session_factory, "test.job")

    async def handler(context: JobContext) -> JSONDict | None:
        context.session.add(Conversation())
        # Another worker takes the job over while this handler is still running.
        async with session_factory() as other:
            job = (await other.execute(select(Job).where(Job.id == job_id))).scalar_one()
            job.locked_by = "another-worker"
            await other.commit()
        return {"ok": True}

    worker = _worker(session_factory, settings, {"test.job": handler})

    await worker.run_once()

    job = await _get(session_factory, job_id)
    assert job.status is JobStatus.RUNNING
    assert job.locked_by == "another-worker"
    assert job.result is None
    assert await _count_conversations(session_factory) == 0


async def test_run_forever_drains_the_queue_and_stops_on_request(
    session_factory: SessionFactory, settings: Settings
) -> None:
    processed: list[int] = []
    stop = asyncio.Event()

    async def handler(context: JobContext) -> JSONDict | None:
        processed.append(context.payload["n"])
        if len(processed) == 3:
            stop.set()
        return None

    for n in range(3):
        await _enqueue(session_factory, "test.job", payload={"n": n})
    worker = _worker(
        session_factory, settings, {"test.job": handler}, worker_poll_interval_seconds=0.01
    )

    await asyncio.wait_for(worker.run_forever(stop), timeout=10)

    assert sorted(processed) == [0, 1, 2]


def test_registry_rejects_a_second_handler_for_the_same_job_type() -> None:
    async def handler(context: JobContext) -> JSONDict | None:
        return None

    registry = JobRegistry()
    registry.register("test.job", handler)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("test.job", handler)
    assert registry.job_types == frozenset({"test.job"})
    assert registry.handler_for("other.job") is None


def test_handler_modules_load_without_conflicts() -> None:
    registry = JobRegistry()

    load_handlers(registry)

    # Indexing (T3) and delivery (T4) handlers are registered by their owners.
    assert registry.job_types <= {"documents.index_version", "inquiries.deliver"}
