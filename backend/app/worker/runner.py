"""The worker loop: claim a job, run its handler, record the outcome."""

import asyncio
import contextlib
import logging
import os
import socket
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.db import SessionFactory
from app.models.base import JSONDict
from app.models.jobs import Job
from app.providers.factory import Providers
from app.worker import queue
from app.worker.registry import JobContext, JobRegistry, PermanentJobError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ClaimedJob:
    id: uuid.UUID
    job_type: str
    payload: JSONDict
    attempt: int
    max_attempts: int


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class Worker:
    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        registry: JobRegistry,
        settings: Settings,
        providers: Providers,
        worker_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._settings = settings
        self._providers = providers
        self._policy = queue.RetryPolicy.from_settings(settings)
        self.worker_id = worker_id or default_worker_id()

    async def run_forever(self, stop: asyncio.Event) -> None:
        """Process jobs until `stop` is set. The job in progress always finishes."""
        logger.info(
            "Worker %s started; job types: %s",
            self.worker_id,
            ", ".join(sorted(self._registry.job_types)) or "none",
        )
        while not stop.is_set():
            try:
                processed = await self.run_once()
            except Exception:
                logger.exception("Worker %s could not poll the queue", self.worker_id)
                processed = False
            if not processed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        stop.wait(), timeout=self._settings.worker_poll_interval_seconds
                    )
        logger.info("Worker %s stopped", self.worker_id)

    async def run_once(self) -> bool:
        """Process at most one job. Returns False when no job was due."""
        async with self._session_factory() as session:
            abandoned: list[Job] = []
            job = await queue.claim_next(
                session,
                worker_id=self.worker_id,
                lease_seconds=self._settings.job_lease_seconds,
                abandoned=abandoned,
            )
            for dead in abandoned:
                await self._settle_abandoned(session, dead)
            claimed = (
                None
                if job is None
                else _ClaimedJob(job.id, job.job_type, job.payload, job.attempts, job.max_attempts)
            )
            await session.commit()
        if claimed is None:
            return False
        await self._execute(claimed)
        return True

    async def _settle_abandoned(self, session: AsyncSession, job: Job) -> None:
        """Let the job type record that its job failed without a final handler run.

        The hook shares the transaction that fails the job. If the hook itself
        fails, its writes are undone and the job still fails: a broken hook must
        not stop the worker from polling.
        """
        logger.warning(
            "Job %s (%s) failed: its worker stopped during the final attempt",
            job.id,
            job.job_type,
        )
        hook = self._registry.abandoned_handler_for(job.job_type)
        if hook is None:
            return
        try:
            async with session.begin_nested():
                await hook(session, job)
        except Exception:
            logger.exception(
                "Could not record the failure of abandoned job %s (%s)", job.id, job.job_type
            )

    async def _execute(self, job: _ClaimedJob) -> None:
        handler = self._registry.handler_for(job.job_type)
        if handler is None:
            await self._record_failure(
                job, f"No handler is registered for job type {job.job_type!r}.", retryable=False
            )
            return
        try:
            async with self._session_factory() as session:
                context = JobContext(
                    job_id=job.id,
                    job_type=job.job_type,
                    payload=job.payload,
                    attempt=job.attempt,
                    max_attempts=job.max_attempts,
                    session=session,
                    settings=self._settings,
                    providers=self._providers,
                )
                async with asyncio.timeout(self._settings.job_timeout_seconds):
                    result = await handler(context)
                if await queue.mark_succeeded(
                    session, job.id, worker_id=self.worker_id, result=result
                ):
                    await session.commit()
                    logger.info("Job %s (%s) succeeded", job.id, job.job_type)
                else:
                    await session.rollback()
                    logger.warning(
                        "Job %s (%s) finished after its lease was lost; changes rolled back",
                        job.id,
                        job.job_type,
                    )
        except PermanentJobError as exc:
            await self._record_failure(job, str(exc), retryable=False)
        except Exception as exc:
            logger.exception("Job %s (%s) attempt %s failed", job.id, job.job_type, job.attempt)
            await self._record_failure(job, f"{type(exc).__name__}: {exc}", retryable=True)

    async def _record_failure(self, job: _ClaimedJob, error: str, *, retryable: bool) -> None:
        async with self._session_factory() as session:
            status = await queue.mark_failed(
                session,
                job.id,
                worker_id=self.worker_id,
                error=error,
                policy=self._policy,
                retryable=retryable,
            )
            await session.commit()
        logger.warning("Job %s (%s) -> %s: %s", job.id, job.job_type, status or "lease lost", error)
