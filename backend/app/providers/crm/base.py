"""CRM provider contract."""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Self

from app.core.config import CRMProviderMode, Settings
from app.models.enums import InquiryKind


@dataclass(frozen=True, slots=True)
class LeadContact:
    name: str
    email: str
    company: str | None = None
    phone: str | None = None


@dataclass(frozen=True, slots=True)
class LeadPayload:
    """A confirmed inquiry, ready to become a lead in the CRM.

    A purchase inquiry always carries `product`, `quantity` and `timeline`. A human
    handoff carries the visitor's question in `notes` and may leave them empty.
    """

    inquiry_id: uuid.UUID
    idempotency_key: str
    product: str | None
    quantity: int | None
    timeline: str | None
    contact: LeadContact
    notes: str | None = None
    kind: InquiryKind = InquiryKind.PURCHASE
    attempt: int = 1
    """Number of this delivery attempt for the inquiry, starting at 1."""
    confirmed_at: datetime | None = None
    """When the visitor confirmed the inquiry."""


@dataclass(frozen=True, slots=True)
class LeadResult:
    contact_id: str
    record_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CRMAccessCheck:
    ok: bool
    message: str | None = None


class CRMProvider(ABC):
    """Lead delivery behind one interface.

    `live` is False for the simulated mode, which stores nothing outside this
    system and must never be presented as a real CRM integration.

    `deliver_lead` must be safe to repeat: a call with an `idempotency_key` that
    already succeeded returns the existing records instead of creating new ones.

    Failures raise `app.providers.errors.ProviderError`; its `retryable` flag
    decides whether the delivery job tries again.
    """

    mode: ClassVar[CRMProviderMode]
    live: ClassVar[bool]

    @classmethod
    @abstractmethod
    def from_settings(cls, settings: Settings) -> Self: ...

    @abstractmethod
    async def check_access(self) -> CRMAccessCheck:
        """Verify credentials and the fields the integration needs."""

    @abstractmethod
    async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
        """Create or update the contact and save the inquiry details."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Release network resources. Called once on shutdown."""
