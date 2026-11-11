"""Inquiry administration endpoints. Owner: T4."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.api.errors import error_responses
from app.models.enums import DeliveryStatus, InquiryStatus
from app.schemas.inquiries import InquiryList
from app.services.inquiries import service

router = APIRouter(prefix="/inquiries", tags=["admin: inquiries"])


@router.get(
    "",
    summary="List inquiries with their delivery status",
    responses=error_responses(422),
)
async def list_inquiries(
    session: SessionDep,
    status: Annotated[InquiryStatus | None, Query()] = None,
    delivery_status: Annotated[DeliveryStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InquiryList:
    """Newest first."""
    return await service.list_inquiries(
        session, status=status, delivery_status=delivery_status, limit=limit, offset=offset
    )
