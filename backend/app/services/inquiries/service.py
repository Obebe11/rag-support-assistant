"""Inquiry drafts, confirmation, delivery status and manual retries.

Functions that change data commit their own unit of work, except
`create_draft_in_session` and `apply_fields`, which the intent detector uses
inside the chat's transaction.
"""

import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from sqlalchemy import String, cast, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.errors import ConflictError, NotFoundError, ValidationApiError
from app.core.config import CRMProviderMode
from app.models.conversations import Conversation
from app.models.enums import DeliveryStatus, InquiryKind, InquiryStatus, JobStatus
from app.models.inquiries import Inquiry, InquiryDelivery
from app.models.jobs import Job
from app.providers.factory import CRM_PROVIDERS
from app.schemas.common import ErrorDetail
from app.schemas.inquiries import (
    ContactRead,
    DeliveryAttemptRead,
    DeliveryFailureReason,
    DeliveryRead,
    InquiryCreate,
    InquiryField,
    InquiryList,
    InquiryRead,
    InquiryUpdate,
    required_inquiry_fields,
)
from app.worker import job_types, queue

JOB_KEY_PREFIX = f"{job_types.DELIVER_INQUIRY}:"
FAILURE_REASON_KEY = "failure_reason"
"""Key in `inquiry_deliveries.crm_details` that keeps why a delivery failed."""

_CONTACT_FIELDS: Mapping[str, InquiryField] = {
    "name": InquiryField.CONTACT_NAME,
    "email": InquiryField.CONTACT_EMAIL,
    "company": InquiryField.CONTACT_COMPANY,
    "phone": InquiryField.CONTACT_PHONE,
}
_ABANDONED_ERROR = "The worker stopped before it recorded the result of the last attempt."


def utcnow() -> datetime:
    return datetime.now(UTC)


def delivery_job_key(inquiry_id: uuid.UUID) -> str:
    """Idempotency key of the delivery job: one job per inquiry."""
    return f"{JOB_KEY_PREFIX}{inquiry_id}"


def crm_idempotency_key(inquiry_id: uuid.UUID) -> str:
    """Sent to the CRM with every attempt, so a repeat finds the existing record."""
    return f"inquiry:{inquiry_id}"


# --- Reading -----------------------------------------------------------------


def missing_fields(inquiry: Inquiry) -> list[InquiryField]:
    """Fields required for the inquiry's kind that are still empty."""
    return [
        field
        for field in required_inquiry_fields(inquiry.kind)
        if getattr(inquiry, field.value) in (None, "")
    ]


def field_values(inquiry: Inquiry) -> dict[InquiryField, str | int]:
    """Every filled field of the inquiry."""
    values: dict[InquiryField, str | int] = {}
    for field in InquiryField:
        value = getattr(inquiry, field.value)
        if value not in (None, ""):
            values[field] = value
    return values


def delivery_to_read(delivery: InquiryDelivery) -> DeliveryRead:
    failure_reason: DeliveryFailureReason | None = None
    if delivery.status is DeliveryStatus.FAILED:
        stored = (delivery.crm_details or {}).get(FAILURE_REASON_KEY)
        failure_reason = (
            DeliveryFailureReason(stored)
            if stored in set(DeliveryFailureReason)
            else DeliveryFailureReason.ATTEMPTS_EXHAUSTED
        )
    mode = CRMProviderMode(delivery.crm_mode)
    return DeliveryRead(
        status=delivery.status,
        crm_mode=mode,
        live=CRM_PROVIDERS[mode].live,
        attempt_count=delivery.attempt_count,
        last_error=delivery.last_error,
        failure_reason=failure_reason,
        last_attempt_at=delivery.last_attempt_at,
        next_attempt_at=delivery.next_attempt_at,
        delivered_at=delivery.delivered_at,
        crm_contact_id=delivery.crm_contact_id,
        crm_record_id=delivery.crm_record_id,
        attempts=[DeliveryAttemptRead.model_validate(attempt) for attempt in delivery.attempts],
    )


def inquiry_to_read(inquiry: Inquiry) -> InquiryRead:
    """Build the API representation. `inquiry.delivery` and its attempts must be loaded."""
    return InquiryRead(
        id=inquiry.id,
        conversation_id=inquiry.conversation_id,
        status=inquiry.status,
        kind=inquiry.kind,
        product=inquiry.product,
        quantity=inquiry.quantity,
        timeline=inquiry.timeline,
        contact=ContactRead(
            name=inquiry.contact_name,
            email=inquiry.contact_email,
            company=inquiry.contact_company,
            phone=inquiry.contact_phone,
        ),
        notes=inquiry.notes,
        missing_fields=missing_fields(inquiry),
        created_at=inquiry.created_at,
        updated_at=inquiry.updated_at,
        confirmed_at=inquiry.confirmed_at,
        delivery=delivery_to_read(inquiry.delivery) if inquiry.delivery is not None else None,
    )


_WITH_DELIVERY = selectinload(Inquiry.delivery).selectinload(InquiryDelivery.attempts)


async def _load(session: AsyncSession, inquiry_id: uuid.UUID, *, lock: bool = False) -> Inquiry:
    statement = (
        select(Inquiry)
        .where(Inquiry.id == inquiry_id)
        .options(_WITH_DELIVERY)
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update()
    inquiry = (await session.execute(statement)).scalar_one_or_none()
    if inquiry is None:
        raise NotFoundError("Inquiry not found.")
    return inquiry


async def sync_deliveries_with_jobs(
    session: AsyncSession, *, inquiry_id: uuid.UUID | None = None
) -> int:
    """Correct delivery rows whose attempt ended without a recorded result.

    The delivery handler records every outcome itself. It cannot when the worker
    process dies or the job times out mid-attempt; the job queue then retries or
    fails the job, and the delivery row would keep saying "in progress". This
    brings such rows in line with their job. Returns the number of rows changed;
    the caller commits.
    """
    job_key = func.concat(JOB_KEY_PREFIX, cast(InquiryDelivery.inquiry_id, String))
    scope = [Job.idempotency_key == job_key]
    if inquiry_id is not None:
        scope.append(InquiryDelivery.inquiry_id == inquiry_id)

    failed = await session.execute(
        update(InquiryDelivery)
        .where(
            *scope,
            Job.status == JobStatus.FAILED,
            InquiryDelivery.status.in_([DeliveryStatus.PENDING, DeliveryStatus.IN_PROGRESS]),
        )
        .values(
            status=DeliveryStatus.FAILED,
            next_attempt_at=None,
            last_error=func.coalesce(Job.last_error, _ABANDONED_ERROR),
            crm_details={FAILURE_REASON_KEY: DeliveryFailureReason.ATTEMPTS_EXHAUSTED.value},
        )
        .execution_options(synchronize_session=False)
    )
    waiting = await session.execute(
        update(InquiryDelivery)
        .where(
            *scope,
            Job.status == JobStatus.QUEUED,
            InquiryDelivery.status == DeliveryStatus.IN_PROGRESS,
        )
        .values(
            status=DeliveryStatus.PENDING,
            next_attempt_at=Job.run_at,
            last_error=func.coalesce(Job.last_error, _ABANDONED_ERROR),
        )
        .execution_options(synchronize_session=False)
    )
    assert isinstance(failed, CursorResult)
    assert isinstance(waiting, CursorResult)
    return failed.rowcount + waiting.rowcount


def _may_be_stale(inquiry: Inquiry) -> bool:
    return inquiry.delivery is not None and inquiry.delivery.status in (
        DeliveryStatus.PENDING,
        DeliveryStatus.IN_PROGRESS,
    )


async def get_inquiry(session: AsyncSession, inquiry_id: uuid.UUID) -> Inquiry:
    """Load an inquiry with its delivery and attempts. Raises 404 when it does not exist."""
    inquiry = await _load(session, inquiry_id)
    if _may_be_stale(inquiry) and await sync_deliveries_with_jobs(session, inquiry_id=inquiry_id):
        await session.commit()
        inquiry = await _load(session, inquiry_id)
    return inquiry


async def read_inquiries(
    session: AsyncSession, inquiry_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, InquiryRead]:
    """API representations of several inquiries in one query, by ID.

    For callers outside this module (the chat shows the inquiry offered with a
    message). Unknown IDs are left out. Does not commit.
    """
    ids = list(set(inquiry_ids))
    if not ids:
        return {}
    inquiries = (
        (
            await session.execute(
                select(Inquiry)
                .where(Inquiry.id.in_(ids))
                .options(_WITH_DELIVERY)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return {inquiry.id: inquiry_to_read(inquiry) for inquiry in inquiries}


async def read_conversation_inquiries(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[InquiryRead]:
    """Every inquiry of a conversation in its current state, oldest first.

    For the chat: a human handoff request is created by the client and is not
    attached to a message, so the conversation lists it. Does not commit.
    """
    inquiries = (
        (
            await session.execute(
                select(Inquiry)
                .where(Inquiry.conversation_id == conversation_id)
                .order_by(Inquiry.created_at, Inquiry.id)
                .options(_WITH_DELIVERY)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return [inquiry_to_read(inquiry) for inquiry in inquiries]


async def get_delivery(session: AsyncSession, inquiry_id: uuid.UUID) -> InquiryDelivery:
    inquiry = await get_inquiry(session, inquiry_id)
    if inquiry.delivery is None:
        raise ConflictError("The inquiry is a draft. Delivery starts after it is confirmed.")
    return inquiry.delivery


async def list_inquiries(
    session: AsyncSession,
    *,
    status: InquiryStatus | None = None,
    delivery_status: DeliveryStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> InquiryList:
    """Inquiries with their delivery, newest first."""
    if await sync_deliveries_with_jobs(session):
        await session.commit()

    filters = []
    if status is not None:
        filters.append(Inquiry.status == status)
    if delivery_status is not None:
        filters.append(
            Inquiry.id.in_(
                select(InquiryDelivery.inquiry_id).where(InquiryDelivery.status == delivery_status)
            )
        )
    total = (
        await session.execute(select(func.count()).select_from(Inquiry).where(*filters))
    ).scalar_one()
    inquiries = (
        (
            await session.execute(
                select(Inquiry)
                .where(*filters)
                .options(_WITH_DELIVERY)
                .order_by(Inquiry.created_at.desc(), Inquiry.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return InquiryList(items=[inquiry_to_read(inquiry) for inquiry in inquiries], total=total)


# --- Drafts ------------------------------------------------------------------


def apply_fields(inquiry: Inquiry, values: Mapping[InquiryField, str | int | None]) -> None:
    """Set inquiry fields by name. `None` clears a field."""
    for field, value in values.items():
        setattr(inquiry, field.value, value)


def _changes(body: InquiryCreate | InquiryUpdate) -> dict[InquiryField, str | int | None]:
    """Fields the request sets. An omitted field is absent; an explicit null clears it."""
    changes: dict[InquiryField, str | int | None] = {}
    for name in ("product", "quantity", "timeline", "notes"):
        if name in body.model_fields_set:
            changes[InquiryField(name)] = getattr(body, name)
    if "contact" in body.model_fields_set:
        if body.contact is None:
            changes.update(dict.fromkeys(_CONTACT_FIELDS.values()))
        else:
            for name in body.contact.model_fields_set:
                changes[_CONTACT_FIELDS[name]] = getattr(body.contact, name)
    return changes


def create_draft_in_session(
    session: AsyncSession,
    *,
    kind: InquiryKind = InquiryKind.PURCHASE,
    conversation_id: uuid.UUID | None = None,
    values: Mapping[InquiryField, str | int | None] | None = None,
) -> Inquiry:
    """Add a draft to the session without flushing or committing."""
    now = utcnow()
    inquiry = Inquiry(
        id=uuid.uuid4(),
        kind=kind,
        status=InquiryStatus.DRAFT,
        conversation_id=conversation_id,
        created_at=now,
        updated_at=now,
    )
    inquiry.delivery = None
    apply_fields(inquiry, values or {})
    session.add(inquiry)
    return inquiry


async def create_draft(session: AsyncSession, body: InquiryCreate) -> Inquiry:
    if body.conversation_id is not None:
        conversation = await session.get(Conversation, body.conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found.")
    inquiry = create_draft_in_session(
        session, kind=body.kind, conversation_id=body.conversation_id, values=_changes(body)
    )
    await session.commit()
    return inquiry


async def update_draft(
    session: AsyncSession, inquiry_id: uuid.UUID, body: InquiryUpdate
) -> Inquiry:
    inquiry = await _load(session, inquiry_id, lock=True)
    if inquiry.status is not InquiryStatus.DRAFT:
        raise ConflictError("A confirmed inquiry cannot be changed.")
    apply_fields(inquiry, _changes(body))
    await session.commit()
    return await _load(session, inquiry_id)


# --- Confirmation and delivery -----------------------------------------------


async def confirm_inquiry(
    session: AsyncSession,
    inquiry_id: uuid.UUID,
    *,
    crm_mode: CRMProviderMode,
    max_attempts: int,
) -> Inquiry:
    """Confirm a complete draft and queue its delivery in the same transaction.

    Confirming again returns the inquiry unchanged: the row lock makes concurrent
    calls take turns, and the second one finds the inquiry already confirmed.
    """
    inquiry = await _load(session, inquiry_id, lock=True)
    if inquiry.status is InquiryStatus.CONFIRMED:
        await session.rollback()
        return await get_inquiry(session, inquiry_id)

    missing = missing_fields(inquiry)
    if missing:
        raise ValidationApiError(
            "The inquiry is incomplete. Fill in the missing fields before confirming.",
            details=[
                ErrorDetail(field=field.value, message="This field is required.")
                for field in missing
            ],
        )

    now = utcnow()
    inquiry.status = InquiryStatus.CONFIRMED
    inquiry.confirmed_at = now
    session.add(
        InquiryDelivery(
            inquiry_id=inquiry.id,
            status=DeliveryStatus.PENDING,
            crm_mode=crm_mode.value,
            idempotency_key=crm_idempotency_key(inquiry.id),
            attempt_count=0,
        )
    )
    await queue.enqueue(
        session,
        job_types.DELIVER_INQUIRY,
        {"inquiry_id": str(inquiry.id)},
        idempotency_key=delivery_job_key(inquiry.id),
        max_attempts=max_attempts,
    )
    await session.commit()
    return await _load(session, inquiry_id)


async def retry_delivery(
    session: AsyncSession, inquiry_id: uuid.UUID, *, max_attempts: int
) -> InquiryDelivery:
    """Queue a failed delivery again with a fresh set of automatic attempts.

    The delivery keeps its idempotency key and the job keeps its own, so a retry
    reuses both and cannot create a second job or a second CRM record.
    """
    inquiry = await _load(session, inquiry_id, lock=True)
    if inquiry.delivery is None:
        raise ConflictError("The inquiry is a draft. Delivery starts after it is confirmed.")
    if await sync_deliveries_with_jobs(session, inquiry_id=inquiry_id):
        inquiry = await _load(session, inquiry_id, lock=True)
    delivery = inquiry.delivery
    assert delivery is not None
    if delivery.status is not DeliveryStatus.FAILED:
        raise ConflictError(
            f"Only a failed delivery can be retried; this one is {delivery.status.value}."
        )

    now = utcnow()
    job = (
        await session.execute(
            select(Job)
            .where(Job.idempotency_key == delivery_job_key(inquiry_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if job is None:
        await queue.enqueue(
            session,
            job_types.DELIVER_INQUIRY,
            {"inquiry_id": str(inquiry_id)},
            idempotency_key=delivery_job_key(inquiry_id),
            max_attempts=max_attempts,
        )
    elif await queue.requeue(session, job.id, now=now) is None:
        # The handler recorded the failure a moment ago and the queue has not yet.
        raise ConflictError("The last attempt is still being recorded. Try again in a moment.")

    delivery.status = DeliveryStatus.PENDING
    delivery.next_attempt_at = now
    delivery.crm_details = None
    await session.commit()
    return (await _load(session, inquiry_id)).delivery or delivery
