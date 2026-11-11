"""Document indexing jobs. Owner: T3.

Registers the handler for `app.worker.job_types.INDEX_DOCUMENT_VERSION`.
"""

import uuid

from app.models.base import JSONDict
from app.services.documents.indexing import IndexingFailedError, index_document_version
from app.worker import job_types
from app.worker.registry import JobContext, JobRegistry, PermanentJobError


async def index_version(context: JobContext) -> JSONDict:
    """Index the version named in the payload and activate it.

    A file that cannot be parsed fails the job at once. A provider failure that
    may pass (timeout, rate limit) is retried with backoff.
    """
    try:
        version_id = uuid.UUID(str(context.payload.get("document_version_id")))
    except ValueError as exc:
        raise PermanentJobError("The job payload has no valid document_version_id.") from exc
    try:
        return await index_document_version(
            context.session,
            version_id,
            context.providers.embeddings,
            final_attempt=context.is_final_attempt,
        )
    except IndexingFailedError as exc:
        if exc.retryable:
            raise
        raise PermanentJobError(str(exc)) from exc


def register(registry: JobRegistry) -> None:
    registry.register(job_types.INDEX_DOCUMENT_VERSION, index_version)
