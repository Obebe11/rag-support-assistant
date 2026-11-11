"""The seam between chat (T3) and inquiries (T4).

The chat service calls `InquiryIntentDetector.assess` for every visitor message
and never imports inquiry internals. The inquiry module provides the real
detector through `app.services.inquiries.intent.build_inquiry_intent_detector`.

Shared file: the contract below changes only additively.
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
