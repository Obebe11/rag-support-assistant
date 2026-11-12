"""The seam between the chat and the inquiries.

The chat service calls `InquiryIntentDetector.assess` for every visitor message
and never imports inquiry internals. The inquiry module provides the real
detector through `app.services.inquiries.intent.build_inquiry_intent_detector`.

The contract below changes only additively.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import MessageRole
from app.schemas.inquiries import InquiryField


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class InquiryIntent:
    """What the inquiry module concluded about a conversation."""

    detected: bool
    """True when the visitor wants to buy or asks for a quote."""
    fields: Mapping[InquiryField, str | int] = field(default_factory=dict)
    """Inquiry fields extracted from the conversation so far."""
    missing_fields: tuple[InquiryField, ...] = ()
    """Required fields the assistant still has to ask for."""
    inquiry_id: uuid.UUID | None = None
    """The draft the inquiry module created or updated, if it keeps one."""
    question: str | None = None
    """The part of the new message that asks a question next to the request, if any.

    "We want to order 12 shredders. Would shipping be free?" gives "Would shipping
    be free?". The chat answers it from the knowledge base before it offers the inquiry.
    """


NO_INQUIRY_INTENT = InquiryIntent(detected=False)


class InquiryIntentDetector(Protocol):
    async def assess(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        turns: Sequence[ConversationTurn],
    ) -> InquiryIntent:
        """Assess purchase intent after a new visitor message.

        `turns` is the conversation in order; the last item is the new visitor
        message. `session` is the chat request's session: an implementation may
        write through it (for example, to save a draft) but must not commit, so
        the draft and the chat reply are stored in one transaction.
        """
        ...


class NoOpInquiryIntentDetector:
    """Default detector: never reports purchase intent."""

    async def assess(
        self,
        session: AsyncSession,
        *,
        conversation_id: uuid.UUID,
        turns: Sequence[ConversationTurn],
    ) -> InquiryIntent:
        return NO_INQUIRY_INTENT
