"""Inquiry delivery jobs. Owner: T4.

The handler for `app.worker.job_types.DELIVER_INQUIRY` lives in
`app.services.inquiries.delivery`.
"""

from app.services.inquiries.delivery import deliver_inquiry
from app.worker import job_types
from app.worker.registry import JobRegistry


def register(registry: JobRegistry) -> None:
    registry.register(job_types.DELIVER_INQUIRY, deliver_inquiry)
