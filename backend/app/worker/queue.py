"""Job queue operations.

None of these functions commit. `enqueue` is meant to run in the same
transaction as the change that needs the job, so the job exists only if that
change is committed.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.base import JSONDict
from app.models.enums import JobStatus
from app.models.jobs import Job

DEFAULT_MAX_ATTEMPTS = 5
MAX_ERROR_LENGTH = 2000
ABANDONED_ERROR = "The worker stopped during the final attempt."


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    backoff_base_seconds: float
    backoff_max_seconds: float

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetryPolicy":
        return cls(
            backoff_base_seconds=settings.job_backoff_base_seconds,
            backoff_max_seconds=settings.job_backoff_max_seconds,
        )

    def delay_after(self, attempt: int) -> timedelta:
        """Wait before the next try: base, 2x base, 4x base, ... capped at the maximum."""
        seconds = min(self.backoff_max_seconds, self.backoff_base_seconds * 2 ** (attempt - 1))
        return timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    job: Job
    created: bool
    """False when a job with the same idempotency key already existed."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def enqueue(
    session: AsyncSession,
    job_type: str,
    payload: JSONDict | None = None,
    *,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> EnqueueResult:
    """Add a job. With an `idempotency_key`, the same key never creates a second job."""
    statement = (
        insert(Job)
        .values(
            id=uuid.uuid4(),
            job_type=job_type,
            payload=payload or {},
            status=JobStatus.QUEUED,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            run_at=run_at or _utcnow(),
        )
        .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
        .returning(Job)
    )
    job = (await session.execute(statement)).scalar_one_or_none()
    if job is not None:
        return EnqueueResult(job=job, created=True)
    existing = (
        await session.execute(select(Job).where(Job.idempotency_key == idempotency_key))
    ).scalar_one()
    return EnqueueResult(job=existing, created=False)


async def claim_next(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: float,
    now: datetime | None = None,
    abandoned: list[Job] | None = None,
) -> Job | None:
    """Lock the next due job for this worker, or return None.

    A job is due when it is queued and its `run_at` has passed, or when it is
    running but its lease expired (the worker that held it is gone). Rows locked
    by another transaction are skipped, so workers never wait on each other.
    The caller must commit to publish the claim.

    A job whose worker died during its final attempt is failed here, without
    running its handler again. Each such job is appended to `abandoned`, so the
    caller can bring the record the job was working on in line before it commits.
    """
    now = now or _utcnow()
    lease_expired_before = now - timedelta(seconds=lease_seconds)
    statement = (
        select(Job)
        .where(
            or_(
                and_(Job.status == JobStatus.QUEUED, Job.run_at <= now),
                and_(Job.status == JobStatus.RUNNING, Job.locked_at < lease_expired_before),
            )
        )
        .order_by(Job.run_at, Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    while True:
        job = (await session.execute(statement)).scalar_one_or_none()
        if job is None:
            return None
        if job.status is JobStatus.RUNNING and job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED
            job.last_error = ABANDONED_ERROR
            job.finished_at = now
            job.locked_by = None
            job.locked_at = None
            await session.flush()
            if abandoned is not None:
                abandoned.append(job)
            continue
        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.locked_by = worker_id
        job.locked_at = now
        await session.flush()
        return job


async def mark_succeeded(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    result: JSONDict | None = None,
    now: datetime | None = None,
) -> bool:
    """Finish a job. Returns False if this worker no longer holds it."""
    outcome = await session.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.RUNNING, Job.locked_by == worker_id)
        .values(
            status=JobStatus.SUCCEEDED,
            result=result,
            last_error=None,
            locked_by=None,
            locked_at=None,
            finished_at=now or _utcnow(),
        )
    )
    assert isinstance(outcome, CursorResult)
    return outcome.rowcount == 1


async def mark_failed(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    worker_id: str,
    error: str,
    policy: RetryPolicy,
    retryable: bool = True,
    now: datetime | None = None,
) -> JobStatus | None:
    """Record a failed attempt.

    The job goes back to the queue with a backoff delay while attempts remain and
    the error is retryable; otherwise it fails for good. Returns the new status,
    or None if this worker no longer holds the job.
    """
    now = now or _utcnow()
    job = (
        await session.execute(
            select(Job)
            .where(Job.id == job_id, Job.status == JobStatus.RUNNING, Job.locked_by == worker_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    job.last_error = error[:MAX_ERROR_LENGTH]
    job.locked_by = None
    job.locked_at = None
    if retryable and job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED
        job.run_at = now + policy.delay_after(job.attempts)
    else:
        job.status = JobStatus.FAILED
        job.finished_at = now
    await session.flush()
    return job.status


async def requeue(
    session: AsyncSession, job_id: uuid.UUID, *, now: datetime | None = None
) -> Job | None:
    """Put a failed job back in the queue with a fresh set of attempts.

    Returns None when the job does not exist or is not in the failed state.
    """
    job = (
        await session.execute(
            select(Job)
            .where(Job.id == job_id, Job.status == JobStatus.FAILED)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if job is None:
        return None
    job.status = JobStatus.QUEUED
    job.attempts = 0
    job.run_at = now or _utcnow()
    job.finished_at = None
    await session.flush()
    return job
