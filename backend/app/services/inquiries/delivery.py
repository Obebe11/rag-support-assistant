"""Delivers one confirmed inquiry to the CRM. Runs inside the delivery job.

Owner: T4.

Each run is one attempt:

1. Mark the delivery `in_progress` and commit, so the status is visible while
   the CRM call runs.
2. Call the CRM provider with the delivery's idempotency key.
3. On success, write the result. The worker commits it together with the job's
   success; if the worker lost its lease meanwhile, both are rolled back and the
   job runs again, which is safe because the CRM call is idempotent.
4. On failure, record the attempt and the new status, commit, then raise so the
   job queue schedules a retry (temporary error) or fails the job (permanent
   error, or no attempts left).
"""

import asyncio
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import JSONDict
from app.models.enums import DeliveryAttemptOutcome, DeliveryStatus, InquiryStatus, JobStatus
from app.models.inquiries import Inquiry, InquiryDelivery, InquiryDeliveryAttempt
from app.models.jobs import Job
from app.providers.crm.base import LeadContact, LeadPayload
from app.providers.errors import ProviderError
from app.schemas.inquiries import DeliveryFailureReason
from app.services.inquiries.service import FAILURE_REASON_KEY, missing_fields, utcnow
from app.worker.queue import MAX_ERROR_LENGTH, RetryPolicy
from app.worker.registry import JobContext, PermanentJobError

logger = logging.getLogger(__name__)

CRM_CALL_TIMEOUT_SHARE = 0.5
"""Share of the job timeout the CRM call may use. The rest is left for recording
the outcome, so a slow CRM becomes a recorded temporary failure instead of a job
that timed out without a trace."""


class DeliveryAttemptFailedError(Exception):
    """A delivery attempt failed with a temporary error; the job queue retries it."""


def _inquiry_id(payload: JSONDict) -> uuid.UUID:
    try:
        return uuid.UUID(str(payload["inquiry_id"]))
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("The job payload has no valid inquiry_id.") from exc


async def _lock_delivery(session: AsyncSession, inquiry_id: uuid.UUID) -> InquiryDelivery | None:
    return (
        await session.execute(
            select(InquiryDelivery)
            .where(InquiryDelivery.inquiry_id == inquiry_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def _lead(inquiry: Inquiry, delivery: InquiryDelivery) -> LeadPayload:
    assert inquiry.contact_name is not None
    assert inquiry.contact_email is not None
    return LeadPayload(
        inquiry_id=inquiry.id,
        idempotency_key=delivery.idempotency_key,
        kind=inquiry.kind,
        product=inquiry.product,
        quantity=inquiry.quantity,
        timeline=inquiry.timeline,
        contact=LeadContact(
            name=inquiry.contact_name,
            email=inquiry.contact_email,
            company=inquiry.contact_company,
            phone=inquiry.contact_phone,
        ),
        notes=inquiry.notes,
        attempt=delivery.attempt_count,
    )


async def _still_holds_job(context: JobContext) -> bool:
    """False when another worker took the job over after this one lost its lease."""
    job = (
        await context.session.execute(
            select(Job).where(Job.id == context.job_id).execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    return job is not None and job.status is JobStatus.RUNNING and job.attempts == context.attempt


async def _record_failure(
    context: JobContext,
    *,
    inquiry_id: uuid.UUID,
    attempt_number: int,
    started_at: datetime,
    error: str,
    retryable: bool,
) -> None:
    session = context.session
    error = error[:MAX_ERROR_LENGTH]
    now = utcnow()
    delivery = await _lock_delivery(session, inquiry_id)
    if delivery is None:
        return
    session.add(
        InquiryDeliveryAttempt(
            delivery_id=delivery.id,
            attempt_number=attempt_number,
            outcome=DeliveryAttemptOutcome.FAILED,
            error=error,
            started_at=started_at,
            finished_at=now,
        )
    )
    # A worker that lost its lease must not overwrite the state written by the
    # worker that took the job over; it only adds its attempt to the log.
    if delivery.status is not DeliveryStatus.DELIVERED and await _still_holds_job(context):
        delivery.last_error = error
        if retryable and not context.is_final_attempt:
            delay = RetryPolicy.from_settings(context.settings).delay_after(context.attempt)
            delivery.status = DeliveryStatus.PENDING
            delivery.next_attempt_at = now + delay
        else:
            reason = (
                DeliveryFailureReason.ATTEMPTS_EXHAUSTED
                if retryable
                else DeliveryFailureReason.PERMANENT_ERROR
            )
            delivery.status = DeliveryStatus.FAILED
            delivery.next_attempt_at = None
            delivery.crm_details = {FAILURE_REASON_KEY: reason.value}
    await session.commit()


async def deliver_inquiry(context: JobContext) -> JSONDict | None:
    """Job handler for `inquiries.deliver`."""
    session = context.session
    inquiry_id = _inquiry_id(context.payload)
    crm = context.providers.crm

    delivery = await _lock_delivery(session, inquiry_id)
    inquiry = await session.get(Inquiry, inquiry_id, populate_existing=True)
    if delivery is None or inquiry is None or inquiry.status is not InquiryStatus.CONFIRMED:
        raise PermanentJobError("The inquiry is not confirmed or no longer exists.")
    if delivery.status is DeliveryStatus.DELIVERED:
        # The job ran again after a delivery that was already recorded.
        return {"delivery_status": DeliveryStatus.DELIVERED.value, "repeated": True}

    started_at = utcnow()
    delivery.status = DeliveryStatus.IN_PROGRESS
    delivery.crm_mode = crm.mode.value
    delivery.attempt_count += 1
    delivery.last_attempt_at = started_at
    delivery.next_attempt_at = None
    attempt_number = delivery.attempt_count
    incomplete = missing_fields(inquiry)
    lead = None if incomplete else _lead(inquiry, delivery)
    await session.commit()

    error: str
    retryable: bool
    try:
        if lead is None:
            names = ", ".join(field.value for field in incomplete)
            raise ProviderError(
                f"The confirmed inquiry has empty required fields: {names}.", retryable=False
            )
        async with asyncio.timeout(context.settings.job_timeout_seconds * CRM_CALL_TIMEOUT_SHARE):
            result = await crm.deliver_lead(lead)
    except ProviderError as exc:
        error, retryable = str(exc), exc.retryable
    except TimeoutError:
        error, retryable = "The CRM did not answer in time.", True
    except Exception as exc:
        logger.exception("Delivery of inquiry %s crashed in the CRM provider", inquiry_id)
        error, retryable = f"Unexpected error in the CRM provider ({type(exc).__name__}).", True
    else:
        delivery = await _lock_delivery(session, inquiry_id)
        if delivery is None:
            raise PermanentJobError("The inquiry was deleted during delivery.")
        now = utcnow()
        delivery.status = DeliveryStatus.DELIVERED
        delivery.delivered_at = delivery.delivered_at or now
        delivery.crm_contact_id = result.contact_id
        delivery.crm_record_id = result.record_id
        delivery.crm_details = dict(result.details) or None
        delivery.last_error = None
        delivery.next_attempt_at = None
        session.add(
            InquiryDeliveryAttempt(
                delivery_id=delivery.id,
                attempt_number=attempt_number,
                outcome=DeliveryAttemptOutcome.SUCCEEDED,
                started_at=started_at,
                finished_at=now,
            )
        )
        logger.info("Inquiry %s delivered to the %s CRM", inquiry_id, crm.mode.value)
        return {
            "delivery_status": DeliveryStatus.DELIVERED.value,
            "crm_contact_id": result.contact_id,
            "crm_record_id": result.record_id,
        }

    await _record_failure(
        context,
        inquiry_id=inquiry_id,
        attempt_number=attempt_number,
        started_at=started_at,
        error=error,
        retryable=retryable,
    )
    if retryable:
        raise DeliveryAttemptFailedError(error)
    raise PermanentJobError(error)
