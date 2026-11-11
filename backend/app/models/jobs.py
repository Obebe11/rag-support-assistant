"""Background jobs stored in PostgreSQL. See `app.worker` for the queue mechanics."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    JSONDict,
    created_at_column,
    enum_column,
    updated_at_column,
    uuid_pk,
)
from app.models.enums import JobStatus


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_queued_run_at", "run_at", postgresql_where=text("status = 'queued'")),
        Index(
            "ix_jobs_running_locked_at", "locked_at", postgresql_where=text("status = 'running'")
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_type: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[JSONDict] = mapped_column(JSONB, server_default="{}")
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus), server_default=JobStatus.QUEUED.value
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    """Enqueueing the same key twice returns the existing job instead of a new one."""

    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    """Earliest time the job may be claimed."""

    locked_by: Mapped[str | None] = mapped_column(String(200))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[JSONDict | None] = mapped_column(JSONB)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
