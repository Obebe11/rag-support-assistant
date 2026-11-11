"""Conversations and the assistant's reply to a visitor message.

One visitor message is handled in one transaction: the message, the reply and
whatever the inquiry module saved through the intent seam are committed
together, or not at all.

Order of decisions for a new message:

1. An attempt to override the assistant's instructions is declined (`refusal`).
2. The inquiry module is asked about purchase intent (`inquiry_offer`).
3. Otherwise the knowledge base is searched and the reply is `grounded`,
   `knowledge_gap` or `clarification`.
"""

import asyncio
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.errors import NotFoundError
from app.models import Conversation, Message
from app.models.enums import AnswerType, MessageRole
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.llm.base import ChatMessage, LLMProvider
from app.schemas.conversations import (
    ConversationRead,
    MessageRead,
    MessageUsage,
    RetrievedSource,
)
from app.schemas.inquiries import InquiryField
from app.services.chat.answering import (
    REFUSAL_TEXT,
    AnswerDraft,
    Passage,
    is_elliptical,
    knowledge_gap,
)
from app.services.chat.extractive import compose_extractive_answer
from app.services.chat.guard import (
    is_embedded_instruction,
    is_instruction_override,
    strip_embedded_instructions,
)
from app.services.chat.inquiry_view import load_inquiry_reads
from app.services.chat.llm_answer import compose_llm_answer
from app.services.documents.retrieval import RetrievedChunk, combine, search_by_vector
from app.services.inquiry_intent import ConversationTurn, InquiryIntent, InquiryIntentDetector

CANDIDATE_LIMIT = 20
"""Chunks fetched per message. The local reply weighs question terms over all of them."""
ANSWER_PASSAGES = 8
"""Best chunks an answer may use. They are recorded in the message usage."""
CONTEXT_TURNS = 2
"""Earlier visitor messages that shape the search for a follow-up question."""
CONTEXT_QUERY_WEIGHT = 0.5
"""Weight of the earlier messages in the search vector, relative to the new message."""
ELLIPTICAL_CONTEXT_QUERY_WEIGHT = 1.0
"""The same weight for a short follow-up that names its subject in earlier messages."""
LLM_HISTORY_MESSAGES = 6

_FIELD_LABELS: dict[InquiryField, str] = {
    InquiryField.PRODUCT: "the product",
    InquiryField.QUANTITY: "the quantity",
    InquiryField.TIMELINE: "when you need it",
    InquiryField.CONTACT_NAME: "your name",
    InquiryField.CONTACT_EMAIL: "your email address",
    InquiryField.CONTACT_COMPANY: "your company",
    InquiryField.CONTACT_PHONE: "your phone number",
    InquiryField.NOTES: "any notes",
}


@dataclass(frozen=True, slots=True)
class _Reply:
    draft: AnswerDraft
    inquiry_id: uuid.UUID | None = None
    retrieved: Sequence[RetrievedChunk] = ()
    retrieval_time_ms: int | None = None


async def create_conversation(session: AsyncSession) -> Conversation:
    conversation = Conversation(id=uuid.uuid4())
    session.add(conversation)
    await session.commit()
    return await load_conversation(session, conversation.id)


async def load_conversation(
    session: AsyncSession, conversation_id: uuid.UUID, *, for_update: bool = False
) -> Conversation:
    statement = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
        .execution_options(populate_existing=True)
    )
    if for_update:
        # Two messages sent at once to one conversation are handled one after the other.
        statement = statement.with_for_update()
    conversation = (await session.execute(statement)).scalar_one_or_none()
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    return conversation


def _answered_exchanges(messages: Sequence[Message]) -> list[tuple[Message, Message]]:
    """Earlier visitor messages with their replies, without declined override attempts.

    A message the assistant refused must not steer later searches or prompts.
    """
    exchanges: list[tuple[Message, Message]] = []
    pending: Message | None = None
    for message in messages:
        if message.role is MessageRole.USER:
            pending = message
        elif pending is not None:
            if message.answer_type is not AnswerType.REFUSAL:
                exchanges.append((pending, message))
            pending = None
    return exchanges


def inquiry_offer_text(intent: InquiryIntent) -> str:
    if not intent.missing_fields:
        return (
            "I have prepared your purchase inquiry. Please review the details and confirm "
            "them, and I will send the inquiry to the sales team."
        )
    labels = [_FIELD_LABELS[field] for field in intent.missing_fields]
    listed = labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} and {labels[-1]}"
    return (
        "I can prepare a purchase inquiry for the sales team. "
        f"To complete it, please tell me {listed}."
    )


async def _query_vector(embeddings: EmbeddingProvider, question: str, context: str) -> list[float]:
    if not context:
        return await embeddings.embed_query(question)
    question_vector, context_vector = await asyncio.gather(
        embeddings.embed_query(question), embeddings.embed_query(context)
    )
    weight = ELLIPTICAL_CONTEXT_QUERY_WEIGHT if is_elliptical(question) else CONTEXT_QUERY_WEIGHT
    return combine([question_vector, context_vector], [1.0, weight])


async def _answer_from_documents(
    session: AsyncSession,
    *,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    question: str,
    exchanges: Sequence[tuple[Message, Message]],
) -> _Reply:
    context = "\n".join(user.content for user, _ in exchanges[-CONTEXT_TURNS:])
    started = time.perf_counter()
    query_vector = await _query_vector(embeddings, question, context)
    candidates = await search_by_vector(
        session,
        query_vector=query_vector,
        embedding_model=embeddings.model_name,
        limit=CANDIDATE_LIMIT,
    )
    retrieval_time_ms = round((time.perf_counter() - started) * 1000)

    # Document text is data. Blocks that give instructions to the assistant are
    # dropped before anything is quoted or sent to the LLM.
    # A section whose heading does so is dropped whole.
    usable = [
        Passage(chunk, text)
        for chunk in candidates
        if not is_embedded_instruction(chunk.heading or "")
        and (text := strip_embedded_instructions(chunk.content))
    ]
    top_ids = {chunk.chunk_id for chunk in candidates[:ANSWER_PASSAGES]}
    passages = [passage for passage in usable if passage.chunk.chunk_id in top_ids]

    if not passages:
        draft = knowledge_gap()
    elif llm.live:
        history = [
            ChatMessage(
                "user" if message.role is MessageRole.USER else "assistant", message.content
            )
            for exchange in exchanges
            for message in exchange
        ][-LLM_HISTORY_MESSAGES:]
        draft = await compose_llm_answer(llm, question, history, passages)
    else:
        draft = compose_extractive_answer(question, context, passages, usable)
    return _Reply(
        draft, retrieved=candidates[:ANSWER_PASSAGES], retrieval_time_ms=retrieval_time_ms
    )


def _usage(
    reply: _Reply, *, llm: LLMProvider, embeddings: EmbeddingProvider, response_time_ms: int
) -> MessageUsage:
    searched = reply.retrieval_time_ms is not None
    return MessageUsage(
        llm_mode=llm.mode,
        llm_live=llm.live,
        llm_model=reply.draft.model or llm.model_name,
        embedding_mode=embeddings.mode if searched else None,
        embedding_model=embeddings.model_name if searched else None,
        input_tokens=reply.draft.input_tokens,
        output_tokens=reply.draft.output_tokens,
        response_time_ms=response_time_ms,
        retrieval_time_ms=reply.retrieval_time_ms,
        llm_time_ms=reply.draft.llm_time_ms,
        retrieved=[
            RetrievedSource(
                rank=rank,
                score=round(chunk.score, 4),
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                document_version_id=chunk.document_version_id,
                version_number=chunk.version_number,
                version_label=chunk.version_label,
                source_filename=chunk.source_filename,
                chunk_id=chunk.chunk_id,
                section=chunk.heading,
                page_number=chunk.page_number,
            )
            for rank, chunk in enumerate(reply.retrieved, start=1)
        ],
        note=reply.draft.note,
    )


async def post_message(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    content: str,
    *,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    detector: InquiryIntentDetector,
) -> tuple[Message, Message]:
    """Store a visitor message and the assistant's reply. Commits both together.

    Raises `ProviderError` when a provider fails; nothing is stored then, so the
    visitor can send the message again.
    """
    started = time.perf_counter()
    conversation = await load_conversation(session, conversation_id, for_update=True)
    earlier = list(conversation.messages)

    user_message = Message(
        id=uuid.uuid4(), conversation_id=conversation.id, role=MessageRole.USER, content=content
    )
    session.add(user_message)
    await session.flush()

    if is_instruction_override(content):
        reply = _Reply(AnswerDraft(AnswerType.REFUSAL, REFUSAL_TEXT))
    else:
        turns = [ConversationTurn(message.role, message.content) for message in earlier]
        turns.append(ConversationTurn(MessageRole.USER, content))
        intent = await detector.assess(session, conversation_id=conversation.id, turns=turns)
        if intent.detected:
            reply = _Reply(
                AnswerDraft(AnswerType.INQUIRY_OFFER, inquiry_offer_text(intent)),
                inquiry_id=intent.inquiry_id,
            )
        else:
            reply = await _answer_from_documents(
                session,
                llm=llm,
                embeddings=embeddings,
                question=content,
                exchanges=_answered_exchanges(earlier),
            )

    usage = _usage(
        reply,
        llm=llm,
        embeddings=embeddings,
        response_time_ms=round((time.perf_counter() - started) * 1000),
    )
    assistant_message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=reply.draft.text,
        answer_type=reply.draft.answer_type,
        citations=[citation.model_dump(mode="json") for citation in reply.draft.citations],
        inquiry_id=reply.inquiry_id,
        usage=usage.model_dump(mode="json"),
    )
    session.add(assistant_message)
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    for message in (user_message, assistant_message):
        await session.refresh(message)
    return user_message, assistant_message


async def to_message_reads(session: AsyncSession, messages: Sequence[Message]) -> list[MessageRead]:
    """API view of messages. An offered inquiry is shown in its current state."""
    inquiries = await load_inquiry_reads(session, (message.inquiry_id for message in messages))
    return [
        MessageRead(
            id=message.id,
            conversation_id=message.conversation_id,
            role=message.role,
            content=message.content,
            answer_type=message.answer_type,
            citations=message.citations,
            inquiry=inquiries.get(message.inquiry_id) if message.inquiry_id else None,
            usage=message.usage,
            created_at=message.created_at,
        )
        for message in messages
    ]


async def to_conversation_read(
    session: AsyncSession, conversation: Conversation
) -> ConversationRead:
    return ConversationRead(
        id=conversation.id,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=await to_message_reads(session, conversation.messages),
    )
