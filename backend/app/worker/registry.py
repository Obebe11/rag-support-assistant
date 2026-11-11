"""Job handlers by job type."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.base import JSONDict
from app.providers.factory import Providers


class PermanentJobError(Exception):
    """Raise from a handler when retrying cannot help. The job fails at once."""


@dataclass(frozen=True, slots=True)
class JobContext:
    """Everything a handler receives.

    Writes made through `session` are committed together with the job's success
    and rolled back if the handler raises. To keep something even when the
    attempt fails (for example, a delivery attempt record), commit `session`
    before raising.
    """

    job_id: uuid.UUID
    job_type: str
    payload: JSONDict
    attempt: int
    max_attempts: int
    session: AsyncSession
    settings: Settings
    providers: Providers

    @property
    def is_final_attempt(self) -> bool:
        return self.attempt >= self.max_attempts


type JobHandler = Callable[[JobContext], Awaitable[JSONDict | None]]
"""A handler may return a small JSON object; it is stored in `jobs.result`.

Any exception retries the job with backoff until attempts run out, except
`PermanentJobError`. A job can run more than once (a retry, or a worker that
died mid-attempt), so handlers must be idempotent.
"""


class JobRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        if job_type in self._handlers:
            raise ValueError(f"A handler for job type {job_type!r} is already registered.")
        self._handlers[job_type] = handler

    def handler_for(self, job_type: str) -> JobHandler | None:
        return self._handlers.get(job_type)

    @property
    def job_types(self) -> frozenset[str]:
        return frozenset(self._handlers)
