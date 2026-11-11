"""Visitor chat endpoints. Owner: T3."""

import logging
import uuid
from http import HTTPStatus

from fastapi import APIRouter

from app.api.deps import (
    EmbeddingProviderDep,
    InquiryIntentDetectorDep,
    LLMProviderDep,
    SessionDep,
)
from app.api.errors import ApiError, error_responses
from app.providers.errors import ProviderError
from app.schemas.common import ErrorCode
from app.schemas.conversations import ConversationRead, MessageCreate, MessageExchange
from app.services.chat import service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", status_code=HTTPStatus.CREATED, summary="Start a conversation")
async def create_conversation(session: SessionDep) -> ConversationRead:
    conversation = await service.create_conversation(session)
    return await service.to_conversation_read(session, conversation)


@router.get(
    "/{conversation_id}",
    summary="Get a conversation with its messages",
    responses=error_responses(404, 422),
)
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationRead:
    conversation = await service.load_conversation(session, conversation_id)
    return await service.to_conversation_read(session, conversation)


@router.post(
    "/{conversation_id}/messages",
    status_code=HTTPStatus.CREATED,
    summary="Send a visitor message and get the assistant's reply",
    responses=error_responses(404, 422, 503),
)
async def create_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    session: SessionDep,
    llm: LLMProviderDep,
    embeddings: EmbeddingProviderDep,
    detector: InquiryIntentDetectorDep,
) -> MessageExchange:
    """Store the visitor message and return the assistant's reply.

    The reply's `answer_type` tells the UI what to show:

    - `grounded`: an answer with `citations`.
    - `knowledge_gap`: the documents do not answer the question; offer a human handoff.
    - `clarification`: the assistant asks for more detail.
    - `inquiry_offer`: the visitor wants to buy; `inquiry` may carry a draft to
      review and confirm.
    - `refusal`: the visitor asked for something outside the assistant's role,
      such as revealing its instructions or changing documents.

    The reply uses the earlier messages of the conversation, so a follow-up
    question can depend on them. `usage` reports how the reply was produced:
    provider modes, model, token counts, timing and the retrieved passages.

    `503` means the LLM or embedding provider failed. Nothing is stored then:
    send the message again.
    """
    try:
        user_message, assistant_message = await service.post_message(
            session,
            conversation_id,
            body.content,
            llm=llm,
            embeddings=embeddings,
            detector=detector,
        )
    except ProviderError as exc:
        await session.rollback()
        logger.warning("Provider failure while answering in %s: %s", conversation_id, exc)
        raise ApiError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            ErrorCode.SERVICE_UNAVAILABLE,
            "The assistant is temporarily unavailable. Please send your message again.",
        ) from exc
    user_read, assistant_read = await service.to_message_reads(
        session, [user_message, assistant_message]
    )
    return MessageExchange(user_message=user_read, assistant_message=assistant_read)
