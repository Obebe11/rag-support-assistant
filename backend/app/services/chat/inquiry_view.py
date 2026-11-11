"""Read model of the inquiry attached to an assistant message.

The chat service does not import the inquiry module. This view is built from
the shared model and schema only, so a message can carry the draft the inquiry
module saved through the intent seam.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import CRMProviderMode
from app.models import Inquiry, InquiryDelivery
from app.providers.factory import CRM_PROVIDERS
from app.schemas.inquiries import (
    REQUIRED_INQUIRY_FIELDS,
    ContactRead,
    DeliveryAttemptRead,
    DeliveryRead,
    InquiryRead,
)


def _delivery_read(delivery: InquiryDelivery) -> DeliveryRead:
    mode = CRMProviderMode(delivery.crm_mode)
    return DeliveryRead(
        status=delivery.status,
        crm_mode=mode,
        live=CRM_PROVIDERS[mode].live,
        attempt_count=delivery.attempt_count,
        last_error=delivery.last_error,
        last_attempt_at=delivery.last_attempt_at,
        next_attempt_at=delivery.next_attempt_at,
        delivered_at=delivery.delivered_at,
        crm_contact_id=delivery.crm_contact_id,
        crm_record_id=delivery.crm_record_id,
        attempts=[DeliveryAttemptRead.model_validate(attempt) for attempt in delivery.attempts],
    )


def inquiry_read(inquiry: Inquiry) -> InquiryRead:
    return InquiryRead(
        id=inquiry.id,
        conversation_id=inquiry.conversation_id,
        status=inquiry.status,
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
        missing_fields=[
            field for field in REQUIRED_INQUIRY_FIELDS if getattr(inquiry, field.value) is None
        ],
        created_at=inquiry.created_at,
        updated_at=inquiry.updated_at,
        confirmed_at=inquiry.confirmed_at,
        delivery=_delivery_read(inquiry.delivery) if inquiry.delivery is not None else None,
    )


async def load_inquiry_reads(
    session: AsyncSession, inquiry_ids: Iterable[uuid.UUID | None]
) -> dict[uuid.UUID, InquiryRead]:
    """Current state of the given inquiries, by ID."""
    wanted = {inquiry_id for inquiry_id in inquiry_ids if inquiry_id is not None}
    if not wanted:
        return {}
    inquiries = (
        await session.execute(
            select(Inquiry)
            .where(Inquiry.id.in_(wanted))
            .options(selectinload(Inquiry.delivery).selectinload(InquiryDelivery.attempts))
            .execution_options(populate_existing=True)
        )
    ).scalars()
    return {inquiry.id: inquiry_read(inquiry) for inquiry in inquiries}
