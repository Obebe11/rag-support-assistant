"""Visitor inquiry endpoints. Owner: T4."""

import uuid
from http import HTTPStatus

from fastapi import APIRouter

from app.api.errors import NotImplementedApiError, error_responses
from app.schemas.inquiries import DeliveryRead, InquiryCreate, InquiryRead, InquiryUpdate

router = APIRouter(prefix="/inquiries", tags=["inquiries"])


@router.post(
    "",
    status_code=HTTPStatus.CREATED,
    summary="Create an inquiry draft",
    responses=error_responses(404, 422),
)
async def create_inquiry(body: InquiryCreate) -> InquiryRead:
    raise NotImplementedApiError("Creating an inquiry draft")


@router.get(
    "/{inquiry_id}",
    summary="Get an inquiry",
    responses=error_responses(404, 422),
)
async def get_inquiry(inquiry_id: uuid.UUID) -> InquiryRead:
    raise NotImplementedApiError("Reading an inquiry")


@router.patch(
    "/{inquiry_id}",
    summary="Update an inquiry draft",
    responses=error_responses(404, 409, 422),
)
async def update_inquiry(inquiry_id: uuid.UUID, body: InquiryUpdate) -> InquiryRead:
    """Change a draft. A confirmed inquiry cannot be changed (409)."""
    raise NotImplementedApiError("Updating an inquiry draft")


@router.post(
    "/{inquiry_id}/confirm",
    summary="Confirm an inquiry and queue its delivery to the CRM",
    responses=error_responses(404, 409, 422),
)
async def confirm_inquiry(inquiry_id: uuid.UUID) -> InquiryRead:
    """Confirm a complete draft. Nothing is sent to the CRM before this call.

    Returns 422 with the missing fields if the draft is incomplete. Confirming an
    already confirmed inquiry returns it unchanged and never queues a second delivery.
    """
    raise NotImplementedApiError("Confirming an inquiry")


@router.get(
    "/{inquiry_id}/delivery",
    summary="Get the delivery status of a confirmed inquiry",
    responses=error_responses(404, 409, 422),
)
async def get_inquiry_delivery(inquiry_id: uuid.UUID) -> DeliveryRead:
    """Returns 409 while the inquiry is still a draft."""
    raise NotImplementedApiError("Reading the delivery status")


@router.post(
    "/{inquiry_id}/delivery/retry",
    status_code=HTTPStatus.ACCEPTED,
    summary="Retry a failed delivery",
    responses=error_responses(404, 409, 422),
)
async def retry_inquiry_delivery(inquiry_id: uuid.UUID) -> DeliveryRead:
    """Queue another delivery attempt. Returns 409 unless the delivery has failed.

    A retry reuses the delivery's idempotency key, so it never creates a duplicate lead.
    """
    raise NotImplementedApiError("Retrying a delivery")
