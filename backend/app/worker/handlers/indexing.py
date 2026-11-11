"""Document indexing jobs. Owner: T3.

Register the handler for `app.worker.job_types.INDEX_DOCUMENT_VERSION` here.
"""

from app.worker.registry import JobRegistry


def register(registry: JobRegistry) -> None:
    """No indexing handler yet."""
