"""Queue mechanics: enqueue, claim, retry with backoff, idempotency, leases."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.db import SessionFactory
from app.models.enums import JobStatus
from app.models.jobs import Job
from app.worker import queue
from app.worker.queue import RetryPolicy

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
LEASE_SECONDS = 300.0
POLICY = RetryPolicy(backoff_base_seconds=5, backoff_max_seconds=60)


async def _enqueue(
    session_factory: SessionFactory, job_type: str = "test.job", **kwargs: object
) -> uuid.UUID:
    kwargs.setdefault("run_at", NOW)
    async with session_factory() as session:
        result = await queue.enqueue(session, job_type, **kwargs)  # type: ignore[arg-type]
        await session.commit()
        return result.job.id


async def _claim(
    session_factory: SessionFactory, worker_id: str = "worker-a", now: datetime = NOW
) -> Job | None:
    async with session_factory() as session:
        job = await queue.claim_next(
            session, worker_id=worker_id, lease_seconds=LEASE_SECONDS, now=now
        )
        await session.commit()
        return job


async def _get(session_factory: SessionFactory, job_id: uuid.UUID) -> Job:
    async with session_factory() as session:
        return (await session.execute(select(Job).where(Job.id == job_id))).scalar_one()


async def _fail(
    session_factory: SessionFactory,
    job_id: uuid.UUID,
    *,
    worker_id: str = "worker-a",
    now: datetime = NOW,
    retryable: bool = True,
) -> JobStatus | None:
    async with session_factory() as session:
        status = await queue.mark_failed(
            session,
            job_id,
            worker_id=worker_id,
            error="CRM timed out",
            policy=POLICY,
            retryable=retryable,
            now=now,
        )
        await session.commit()
        return status


async def test_enqueue_stores_a_queued_job(session_factory: SessionFactory) -> None:
    async with session_factory() as session:
        result = await queue.enqueue(
            session, "inquiries.deliver", {"inquiry_id": "abc"}, max_attempts=3
        )
        await session.commit()

    job = await _get(session_factory, result.job.id)
    assert result.created is True
    assert job.job_type == "inquiries.deliver"
    assert job.payload == {"inquiry_id": "abc"}
    assert job.status is JobStatus.QUEUED
    assert job.attempts == 0
    assert job.max_attempts == 3


async def test_enqueue_is_not_visible_until_the_caller_commits(
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        await queue.enqueue(session, "test.job", run_at=NOW)
        assert await _claim(session_factory) is None
        await session.rollback()

    assert await _claim(session_factory) is None


async def test_same_idempotency_key_returns_the_existing_job(
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        first = await queue.enqueue(session, "test.job", {"n": 1}, idempotency_key="deliver:42")
        second = await queue.enqueue(session, "test.job", {"n": 2}, idempotency_key="deliver:42")
        await session.commit()
    async with session_factory() as session:
        third = await queue.enqueue(session, "test.job", {"n": 3}, idempotency_key="deliver:42")
        await session.commit()
        total = (await session.execute(select(func.count()).select_from(Job))).scalar_one()

    assert (first.created, second.created, third.created) == (True, False, False)
    assert first.job.id == second.job.id == third.job.id
    assert third.job.payload == {"n": 1}
    assert total == 1


async def test_concurrent_enqueues_with_one_key_create_one_job(
    session_factory: SessionFactory,
) -> None:
    async def enqueue_once() -> bool:
        async with session_factory() as session:
            result = await queue.enqueue(session, "test.job", idempotency_key="deliver:7")
            await session.commit()
            return result.created

    created = await asyncio.gather(*(enqueue_once() for _ in range(8)))

    assert sorted(created) == [False] * 7 + [True]


async def test_jobs_without_a_key_are_never_merged(session_factory: SessionFactory) -> None:
    first = await _enqueue(session_factory)
    second = await _enqueue(session_factory)

    assert first != second


async def test_claim_marks_the_job_running_and_counts_the_attempt(
    session_factory: SessionFactory,
) -> None:
    job_id = await _enqueue(session_factory)

    claimed = await _claim(session_factory)

    assert claimed is not None
    assert claimed.id == job_id
    job = await _get(session_factory, job_id)
    assert job.status is JobStatus.RUNNING
    assert job.attempts == 1
    assert job.locked_by == "worker-a"
    assert job.locked_at == NOW


async def test_claim_returns_none_when_the_queue_is_empty(session_factory: SessionFactory) -> None:
    assert await _claim(session_factory) is None


async def test_claim_skips_jobs_scheduled_for_later(session_factory: SessionFactory) -> None:
    job_id = await _enqueue(session_factory, run_at=NOW + timedelta(minutes=5))

    assert await _claim(session_factory, now=NOW) is None
    later = await _claim(session_factory, now=NOW + timedelta(minutes=5))
    assert later is not None
    assert later.id == job_id


async def test_claim_takes_the_oldest_due_job_first(session_factory: SessionFactory) -> None:
    newer = await _enqueue(session_factory, run_at=NOW - timedelta(minutes=1))
    older = await _enqueue(session_factory, run_at=NOW - timedelta(minutes=10))

    first = await _claim(session_factory)
    second = await _claim(session_factory)

    assert first is not None
    assert second is not None
    assert [first.id, second.id] == [older, newer]


async def test_two_workers_never_claim_the_same_job(session_factory: SessionFactory) -> None:
    job_ids = {await _enqueue(session_factory), await _enqueue(session_factory)}

    async with session_factory() as session_a, session_factory() as session_b:
        # Worker A holds its row lock (no commit yet) while worker B claims.
        job_a = await queue.claim_next(
            session_a, worker_id="worker-a", lease_seconds=LEASE_SECONDS, now=NOW
        )
        job_b = await queue.claim_next(
            session_b, worker_id="worker-b", lease_seconds=LEASE_SECONDS, now=NOW
        )
        nothing_left = await queue.claim_next(
            session_b, worker_id="worker-b", lease_seconds=LEASE_SECONDS, now=NOW
        )
        await session_a.commit()
        await session_b.commit()

    assert job_a is not None
    assert job_b is not None
    assert {job_a.id, job_b.id} == job_ids
    assert nothing_left is None


async def test_success_finishes_the_job_and_stores_the_result(
    session_factory: SessionFactory,
) -> None:
    job_id = await _enqueue(session_factory)
    await _claim(session_factory)

    async with session_factory() as session:
        finished = await queue.mark_succeeded(
            session, job_id, worker_id="worker-a", result={"chunks": 12}, now=NOW
        )
        await session.commit()

    job = await _get(session_factory, job_id)
    assert finished is True
    assert job.status is JobStatus.SUCCEEDED
    assert job.result == {"chunks": 12}
    assert job.finished_at == NOW
    assert job.locked_by is None
    assert await _claim(session_factory, now=NOW + timedelta(days=1)) is None


async def test_failure_requeues_the_job_with_exponential_backoff(
    session_factory: SessionFactory,
) -> None:
    job_id = await _enqueue(session_factory, max_attempts=5)
    delays = []
    now = NOW
    for _ in range(4):
        claimed = await _claim(session_factory, now=now)
        assert claimed is not None
        assert await _fail(session_factory, job_id, now=now) is JobStatus.QUEUED
        job = await _get(session_factory, job_id)
        delays.append((job.run_at - now).total_seconds())
        assert await _claim(session_factory, now=job.run_at - timedelta(seconds=1)) is None
        now = job.run_at

    job = await _get(session_factory, job_id)
    assert delays == [5, 10, 20, 40]
    assert job.attempts == 4
    assert job.last_error == "CRM timed out"
    assert job.locked_by is None


def test_backoff_is_capped() -> None:
    assert [POLICY.delay_after(attempt).total_seconds() for attempt in (1, 2, 3, 4, 5, 6, 20)] == [
        5,
        10,
        20,
        40,
        60,
        60,
        60,
    ]


async def test_job_fails_for_good_after_the_last_attempt(session_factory: SessionFactory) -> None:
    job_id = await _enqueue(session_factory, max_attempts=2)
    await _claim(session_factory)
    assert await _fail(session_factory, job_id) is JobStatus.QUEUED
    retry_time = (await _get(session_factory, job_id)).run_at
    await _claim(session_factory, now=retry_time)

    status = await _fail(session_factory, job_id, now=retry_time)

    job = await _get(session_factory, job_id)
    assert status is JobStatus.FAILED
    assert job.status is JobStatus.FAILED
    assert job.attempts == 2
    assert job.finished_at == retry_time
    assert await _claim(session_factory, now=NOW + timedelta(days=1)) is None


async def test_non_retryable_failure_fails_the_job_at_once(
    session_factory: SessionFactory,
) -> None:
    job_id = await _enqueue(session_factory, max_attempts=5)
    await _claim(session_factory)

    status = await _fail(session_factory, job_id, retryable=False)

    assert status is JobStatus.FAILED
    assert (await _get(session_factory, job_id)).attempts == 1


async def test_long_errors_are_truncated(session_factory: SessionFactory) -> None:
    job_id = await _enqueue(session_factory)
    await _claim(session_factory)

    async with session_factory() as session:
        await queue.mark_failed(
            session, job_id, worker_id="worker-a", error="x" * 10_000, policy=POLICY, now=NOW
        )
        await session.commit()

    assert len((await _get(session_factory, job_id)).last_error or "") == queue.MAX_ERROR_LENGTH


async def test_a_job_with_a_live_lease_is_not_reclaimed(session_factory: SessionFactory) -> None:
    await _enqueue(session_factory)
    await _claim(session_factory, "worker-a", now=NOW)

    almost_expired = NOW + timedelta(seconds=LEASE_SECONDS)

    assert await _claim(session_factory, "worker-b", now=almost_expired) is None


async def test_a_job_with_an_expired_lease_is_reclaimed(session_factory: SessionFactory) -> None:
    job_id = await _enqueue(session_factory)
    await _claim(session_factory, "worker-a", now=NOW)
    expired = NOW + timedelta(seconds=LEASE_SECONDS + 1)

    reclaimed = await _claim(session_factory, "worker-b", now=expired)

    assert reclaimed is not None
    assert reclaimed.id == job_id
    job = await _get(session_factory, job_id)
    assert job.locked_by == "worker-b"
    assert job.attempts == 2


async def test_a_worker_that_lost_its_lease_cannot_finish_or_fail_the_job(
    session_factory: SessionFactory,
) -> None:
    job_id = await _enqueue(session_factory)
    await _claim(session_factory, "worker-a", now=NOW)
    await _claim(session_factory, "worker-b", now=NOW + timedelta(seconds=LEASE_SECONDS + 1))

    async with session_factory() as session:
        finished = await queue.mark_succeeded(session, job_id, worker_id="worker-a")
        await session.commit()
    failed = await _fail(session_factory, job_id, worker_id="worker-a")

    job = await _get(session_factory, job_id)
    assert finished is False
    assert failed is None
    assert job.status is JobStatus.RUNNING
    assert job.locked_by == "worker-b"


async def test_an_expired_lease_on_the_final_attempt_fails_the_job(
    session_factory: SessionFactory,
) -> None:
    dead = await _enqueue(session_factory, max_attempts=1, run_at=NOW - timedelta(minutes=1))
    healthy = await _enqueue(session_factory, run_at=NOW)
    await _claim(session_factory, "worker-a", now=NOW - timedelta(minutes=1))
    expired = NOW + timedelta(seconds=LEASE_SECONDS + 1)

    claimed = await _claim(session_factory, "worker-b", now=expired)

    assert claimed is not None
    assert claimed.id == healthy
    dead_job = await _get(session_factory, dead)
    assert dead_job.status is JobStatus.FAILED
    assert dead_job.last_error == "The worker stopped during the final attempt."
    assert dead_job.attempts == 1


async def test_requeue_gives_a_failed_job_fresh_attempts(session_factory: SessionFactory) -> None:
    job_id = await _enqueue(session_factory, max_attempts=1)
    await _claim(session_factory)
    await _fail(session_factory, job_id)
    later = NOW + timedelta(hours=1)

    async with session_factory() as session:
        requeued = await queue.requeue(session, job_id, now=later)
        await session.commit()

    assert requeued is not None
    job = await _get(session_factory, job_id)
    assert job.status is JobStatus.QUEUED
    assert job.attempts == 0
    assert job.run_at == later
    assert job.finished_at is None
    claimed = await _claim(session_factory, now=later)
    assert claimed is not None
    assert claimed.id == job_id


async def test_requeue_ignores_jobs_that_have_not_failed(session_factory: SessionFactory) -> None:
    queued = await _enqueue(session_factory)
    running = await _enqueue(session_factory)
    await _claim(session_factory)

    async with session_factory() as session:
        results = [
            await queue.requeue(session, queued),
            await queue.requeue(session, running),
            await queue.requeue(session, uuid.uuid4()),
        ]
        await session.commit()

    assert results == [None, None, None]
