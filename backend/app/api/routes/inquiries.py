"""Visitor inquiry endpoints. Owner: T4."""

import uuid
from http import HTTPStatus

from fastapi import APIRouter

from app.api.deps import CRMProviderDep, SessionDep, SettingsDep
from app.api.errors import error_responses
from app.schemas.inquiries import DeliveryRead, InquiryCreate, InquiryRead, InquiryUpdate
from app.services.inquiries import service

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


@router.post(
    "",
    status_code=HTTPStatus.CREATED,
    summary="Create an inquiry draft",
    responses=error_responses(404, 422),
)
async def create_inquiry(body: InquiryCreate, session: SessionDep) -> InquiryRead:
    """Create a draft of either kind. Returns 404 for an unknown `conversation_id`."""
    return service.inquiry_to_read(await service.create_draft(session, body))


@router.get(
    "/{inquiry_id}",
    summary="Get an inquiry",
    responses=error_responses(404, 422),
)
async def get_inquiry(inquiry_id: uuid.UUID, session: SessionDep) -> InquiryRead:
    return service.inquiry_to_read(await service.get_inquiry(session, inquiry_id))


@router.patch(
    "/{inquiry_id}",
    summary="Update an inquiry draft",
    responses=error_responses(404, 409, 422),
)
async def update_inquiry(
    inquiry_id: uuid.UUID, body: InquiryUpdate, session: SessionDep
) -> InquiryRead:
    """Change a draft. A confirmed inquiry cannot be changed (409)."""
    return service.inquiry_to_read(await service.update_draft(session, inquiry_id, body))


@router.post(
    "/{inquiry_id}/confirm",
    summary="Confirm an inquiry and queue its delivery to the CRM",
    responses=error_responses(404, 409, 422),
)
async def confirm_inquiry(
    inquiry_id: uuid.UUID, session: SessionDep, settings: SettingsDep, crm: CRMProviderDep
) -> InquiryRead:
    """Confirm a complete draft. Nothing is sent to the CRM before this call.

    Returns 422 with the missing fields if the draft is incomplete. Confirming an
    already confirmed inquiry returns it unchanged and never queues a second delivery.
    """
    inquiry = await service.confirm_inquiry(
        session, inquiry_id, crm_mode=crm.mode, max_attempts=settings.delivery_max_attempts
    )
    return service.inquiry_to_read(inquiry)


@router.get(
    "/{inquiry_id}/delivery",
    summary="Get the delivery status of a confirmed inquiry",
    responses=error_responses(404, 409, 422),
)
async def get_inquiry_delivery(inquiry_id: uuid.UUID, session: SessionDep) -> DeliveryRead:
    """Returns 409 while the inquiry is still a draft."""
    return service.delivery_to_read(await service.get_delivery(session, inquiry_id))


@router.post(
    "/{inquiry_id}/delivery/retry",
    status_code=HTTPStatus.ACCEPTED,
    summary="Retry a failed delivery",
    responses=error_responses(404, 409, 422),
)
async def retry_inquiry_delivery(
    inquiry_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> DeliveryRead:
    """Queue another delivery attempt. Returns 409 unless the delivery has failed.

    A retry reuses the delivery's idempotency key, so it never creates a duplicate lead.
    """
    delivery = await service.retry_delivery(
        session, inquiry_id, max_attempts=settings.delivery_max_attempts
    )
    return service.delivery_to_read(delivery)
