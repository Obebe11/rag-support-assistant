"""Inquiry delivery jobs. Owner: T4.

Register the handler for `app.worker.job_types.DELIVER_INQUIRY` here.
"""

from app.worker.registry import JobRegistry


def register(registry: JobRegistry) -> None:
    """No delivery handler yet."""
