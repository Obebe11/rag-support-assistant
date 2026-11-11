"""Inquiry and delivery schemas."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.core.config import CRMProviderMode
from app.models.enums import DeliveryAttemptOutcome, DeliveryStatus, InquiryKind, InquiryStatus
from app.schemas.common import ApiModel


class InquiryField(StrEnum):
    PRODUCT = "product"
    QUANTITY = "quantity"
    TIMELINE = "timeline"
    CONTACT_NAME = "contact_name"
    CONTACT_EMAIL = "contact_email"
    CONTACT_COMPANY = "contact_company"
    CONTACT_PHONE = "contact_phone"
    NOTES = "notes"


REQUIRED_INQUIRY_FIELDS: tuple[InquiryField, ...] = (
    InquiryField.PRODUCT,
    InquiryField.QUANTITY,
    InquiryField.TIMELINE,
    InquiryField.CONTACT_NAME,
    InquiryField.CONTACT_EMAIL,
)
"""Fields a purchase draft needs before the visitor can confirm it."""

REQUIRED_HANDOFF_FIELDS: tuple[InquiryField, ...] = (
    InquiryField.CONTACT_NAME,
    InquiryField.CONTACT_EMAIL,
    InquiryField.NOTES,
)
"""Fields a human handoff draft needs: who to reach and the visitor's question (`notes`)."""


def required_inquiry_fields(kind: InquiryKind) -> tuple[InquiryField, ...]:
    """Fields a draft of this kind needs before the visitor can confirm it."""
    if kind is InquiryKind.HANDOFF:
        return REQUIRED_HANDOFF_FIELDS
    return REQUIRED_INQUIRY_FIELDS


type Product = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
type Quantity = Annotated[int, Field(ge=1, le=1_000_000)]
type Timeline = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
type ContactName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
type ContactEmail = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]
type ContactCompany = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
type ContactPhone = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=50)
]
type Notes = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class ContactInput(BaseModel):
    name: ContactName | None = None
    email: ContactEmail | None = None
    company: ContactCompany | None = None
    phone: ContactPhone | None = None


class InquiryCreate(BaseModel):
    """Create a draft. Every field is optional; missing ones can be added later."""

    kind: InquiryKind = Field(
        default=InquiryKind.PURCHASE,
        description="`purchase` is a purchase request. `handoff` asks a person to answer "
        "a question the documents could not; put the question in `notes`. The kind "
        "cannot be changed later.",
    )
    conversation_id: uuid.UUID | None = None
    product: Product | None = None
    quantity: Quantity | None = None
    timeline: Timeline | None = None
    contact: ContactInput | None = None
    notes: Notes | None = None


class InquiryUpdate(BaseModel):
    """Change a draft. Omitted fields keep their value; `null` clears a field."""

    product: Product | None = None
    quantity: Quantity | None = None
    timeline: Timeline | None = None
    contact: ContactInput | None = None
    notes: Notes | None = None


class ContactRead(ApiModel):
    name: str | None = None
    email: str | None = None
    company: str | None = None
    phone: str | None = None


class DeliveryAttemptRead(ApiModel):
    attempt_number: int
    outcome: DeliveryAttemptOutcome
    error: str | None = None
    started_at: datetime
    finished_at: datetime


class DeliveryFailureReason(StrEnum):
    """Why a delivery stopped in the `failed` status."""

    PERMANENT_ERROR = "permanent_error"
    """The CRM rejected the request. A retry fails the same way until the cause is fixed."""
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    """Every automatic attempt hit a temporary error. A manual retry may succeed."""


class DeliveryRead(ApiModel):
    """Delivery state of a confirmed inquiry.

    How to read `status`:

    - `pending` with `attempt_count` 0: queued, no attempt yet.
    - `in_progress`: an attempt is running.
    - `pending` with `attempt_count` above 0: the last attempt failed with a temporary
      error; the next automatic attempt starts at `next_attempt_at`.
    - `delivered`: the CRM confirmed the record.
    - `failed`: no automatic attempt is left; see `failure_reason`. A manual retry is
      possible.
    """

    status: DeliveryStatus
    crm_mode: CRMProviderMode
    live: bool = Field(
        description="False when the delivery is simulated and no real CRM record exists."
    )
    attempt_count: int
    last_error: str | None = None
    failure_reason: DeliveryFailureReason | None = Field(
        default=None, description="Set only while `status` is `failed`."
    )
    last_attempt_at: datetime | None = None
    next_attempt_at: datetime | None = None
    delivered_at: datetime | None = None
    crm_contact_id: str | None = None
    crm_record_id: str | None = None
    attempts: list[DeliveryAttemptRead] = Field(default_factory=list)


class InquiryRead(ApiModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    status: InquiryStatus
    kind: InquiryKind = Field(
        description="Decides which fields are required: `purchase` needs product, "
        "quantity, timeline, contact name and contact email; `handoff` needs contact "
        "name, contact email and notes (the visitor's question)."
    )
    product: str | None = None
    quantity: int | None = None
    timeline: str | None = None
    contact: ContactRead
    notes: str | None = None
    missing_fields: list[InquiryField] = Field(
        default_factory=list,
        description="Fields required for this inquiry's `kind` that are still empty. "
        "A draft can be confirmed only when this list is empty.",
    )
    created_at: datetime
    updated_at: datetime
    confirmed_at: datetime | None = None
    delivery: DeliveryRead | None = Field(
        default=None, description="Present once the inquiry is confirmed."
    )


class InquiryList(BaseModel):
    items: list[InquiryRead]
    total: int
