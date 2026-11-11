"""Conversation and message schemas."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import AnswerType, MessageRole
from app.schemas.common import ApiModel
from app.schemas.inquiries import InquiryRead


class Citation(BaseModel):
    """A source that supports a grounded answer.

    Stored with the message as a snapshot, so it stays readable after the document
    is replaced or deleted.
    """

    document_id: uuid.UUID
    document_title: str
    document_version_id: uuid.UUID
    version_number: int
    version_label: str | None = None
    chunk_id: uuid.UUID
    page_number: int | None = Field(default=None, description="1-based page, for PDF sources.")
    section: str | None = Field(
        default=None, description="Section heading path, for Markdown sources."
    )
    excerpt: str
    score: float | None = Field(
        default=None,
        description="Retrieval similarity. It ranks passages; it does not measure whether "
        "the answer is correct.",
    )


class MessageCreate(BaseModel):
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class MessageRead(ApiModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    role: MessageRole
    content: str
    answer_type: AnswerType | None = Field(
        default=None, description="Set on assistant messages only."
    )
    citations: list[Citation] = Field(default_factory=list)
    inquiry: InquiryRead | None = Field(
        default=None,
        description="The inquiry offered with this assistant message, in its current "
        "state. It is a draft until the visitor confirms it.",
    )
    created_at: datetime


class MessageExchange(BaseModel):
    """The stored visitor message and the assistant's reply to it."""

    user_message: MessageRead
    assistant_message: MessageRead


class ConversationRead(ApiModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    messages: list[MessageRead] = Field(default_factory=list)
