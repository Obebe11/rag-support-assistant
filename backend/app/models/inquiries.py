"""Purchase inquiries and their delivery to the CRM."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    JSONDict,
    created_at_column,
    enum_column,
    updated_at_column,
    uuid_pk,
)
from app.models.enums import DeliveryAttemptOutcome, DeliveryStatus, InquiryStatus


class Inquiry(Base):
    """A visitor's purchase request. Every field is optional while it is a draft."""

    __tablename__ = "inquiries"

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[InquiryStatus] = mapped_column(
        enum_column(InquiryStatus), server_default=InquiryStatus.DRAFT.value, index=True
    )

    product: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int | None] = mapped_column(Integer)
    timeline: Mapped[str | None] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_email: Mapped[str | None] = mapped_column(String(320))
    contact_company: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    delivery: Mapped["InquiryDelivery | None"] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan"
    )


class InquiryDelivery(Base):
    """Delivery of one confirmed inquiry to the CRM. At most one row per inquiry."""

    __tablename__ = "inquiry_deliveries"

    id: Mapped[uuid.UUID] = uuid_pk()
    inquiry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inquiries.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        enum_column(DeliveryStatus), server_default=DeliveryStatus.PENDING.value, index=True
    )
    crm_mode: Mapped[str] = mapped_column(String(32))
    """CRM provider mode that handles this delivery: "simulated" or "hubspot"."""
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    """Sent to the CRM with every attempt so a retry never creates a duplicate lead."""

    attempt_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    crm_contact_id: Mapped[str | None] = mapped_column(String(200))
    crm_record_id: Mapped[str | None] = mapped_column(String(200))
    """ID of the CRM record that stores the inquiry details."""
    crm_details: Mapped[JSONDict | None] = mapped_column(JSONB(none_as_null=True))
    """Other provider-specific facts, for example the record type or URL."""

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    inquiry: Mapped[Inquiry] = relationship(back_populates="delivery")
    attempts: Mapped[list["InquiryDeliveryAttempt"]] = relationship(
        back_populates="delivery",
        cascade="all, delete-orphan",
        order_by="InquiryDeliveryAttempt.attempt_number",
    )


class InquiryDeliveryAttempt(Base):
    __tablename__ = "inquiry_delivery_attempts"
    __table_args__ = (UniqueConstraint("delivery_id", "attempt_number"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inquiry_deliveries.id", ondelete="CASCADE")
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[DeliveryAttemptOutcome] = mapped_column(enum_column(DeliveryAttemptOutcome))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    delivery: Mapped[InquiryDelivery] = relationship(back_populates="attempts")
