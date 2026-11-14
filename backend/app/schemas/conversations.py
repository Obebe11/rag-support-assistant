"""Conversation and message schemas."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.core.config import EmbeddingProviderMode, LLMProviderMode
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


class RetrievedSource(BaseModel):
    """One passage that retrieval returned for a visitor message."""

    rank: int = Field(description="1-based position in the retrieval result.")
    score: float = Field(
        description="Retrieval similarity. It ranks passages; it does not measure whether "
        "the answer is correct."
    )
    document_id: uuid.UUID
    document_title: str
    document_version_id: uuid.UUID
    version_number: int
    version_label: str | None = None
    source_filename: str
    chunk_id: uuid.UUID
    section: str | None = Field(default=None, description="Section heading path.")
    page_number: int | None = Field(default=None, description="1-based page, for PDF sources.")


class MessageUsage(BaseModel):
    """Measured facts about how an assistant reply was produced."""

    llm_mode: LLMProviderMode
    llm_live: bool = Field(
        description="False when the reply was assembled from retrieved passages in local "
        "mode, without an LLM."
    )
    llm_model: str | None = None
    embedding_mode: EmbeddingProviderMode | None = None
    embedding_model: str | None = None
    input_tokens: int | None = Field(
        default=None, description="LLM prompt tokens, when the API reports them."
    )
    output_tokens: int | None = Field(
        default=None, description="LLM completion tokens, when the API reports them."
    )
    response_time_ms: int = Field(description="Time to produce the reply, in milliseconds.")
    retrieval_time_ms: int | None = Field(
        default=None, description="Part of the response time spent on embedding and search."
    )
    llm_time_ms: int | None = Field(
        default=None, description="Part of the response time spent on the LLM call."
    )
    retrieved: list[RetrievedSource] = Field(
        default_factory=list,
        description="The passages retrieval returned for this message, best first. "
        "Empty when the reply needed no retrieval.",
    )
    note: str | None = Field(
        default=None, description="Why the reply differs from what the LLM proposed, if it does."
    )
    question_answer_type: AnswerType | None = Field(
        default=None,
        description="Set on an `inquiry_offer` reply to a message that also asked a question: "
        "how the question was answered, `grounded` or `knowledge_gap`. The citations of the "
        "message support that answer.",
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
    citations: list[Citation] = Field(
        default_factory=list,
        description="Sources of a `grounded` answer. A `clarification` or `knowledge_gap` "
        "has them when it names documented facts, such as the options to choose from. An "
        "`inquiry_offer` has them when the visitor's message also asked a question that the "
        "documents answer.",
    )
    inquiry: InquiryRead | None = Field(
        default=None,
        description="The inquiry offered with this assistant message, in its current "
        "state. It is a draft until the visitor confirms it.",
    )
    usage: MessageUsage | None = Field(
        default=None,
        description="Set on assistant messages: provider modes, model, token counts, "
        "timing and the retrieved passages.",
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
    inquiries: list[InquiryRead] = Field(
        default_factory=list,
        description="Every inquiry of the conversation in its current state, oldest first: "
        "purchase inquiries and human handoff requests, drafts and confirmed ones. A handoff "
        "request is not attached to a message, so a client restores it from this list.",
    )
