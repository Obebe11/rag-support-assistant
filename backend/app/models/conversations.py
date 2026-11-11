"""Chat conversations and messages."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Identity, Index, Text
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
from app.models.enums import AnswerType, MessageRole


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = uuid_pk()
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.seq",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_id_seq", "conversation_id", "seq"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True))
    """Insertion order. `created_at` is the transaction time, so it cannot order
    a visitor message and its reply written in the same transaction."""

    role: Mapped[MessageRole] = mapped_column(enum_column(MessageRole))
    content: Mapped[str] = mapped_column(Text)

    answer_type: Mapped[AnswerType | None] = mapped_column(enum_column(AnswerType))
    """Set on assistant messages only."""
    citations: Mapped[list[JSONDict]] = mapped_column(JSONB, server_default="[]")
    """Snapshot of `app.schemas.conversations.Citation` items, so a message keeps its
    sources after the cited document is replaced or deleted."""
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inquiries.id", ondelete="SET NULL"), index=True
    )
    """The inquiry draft offered with this assistant message, if any."""
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """Measured facts about how the reply was produced: provider mode, model,
    token counts, latency."""

    created_at: Mapped[datetime] = created_at_column()

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
