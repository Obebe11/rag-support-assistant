"""Visitor chat endpoints. Owner: T3."""

import uuid
from http import HTTPStatus

from fastapi import APIRouter

from app.api.errors import NotImplementedApiError, error_responses
from app.schemas.conversations import ConversationRead, MessageCreate, MessageExchange

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", status_code=HTTPStatus.CREATED, summary="Start a conversation")
async def create_conversation() -> ConversationRead:
    raise NotImplementedApiError("Starting a conversation")


@router.get(
    "/{conversation_id}",
    summary="Get a conversation with its messages",
    responses=error_responses(404, 422),
)
async def get_conversation(conversation_id: uuid.UUID) -> ConversationRead:
    raise NotImplementedApiError("Reading a conversation")


@router.post(
    "/{conversation_id}/messages",
    status_code=HTTPStatus.CREATED,
    summary="Send a visitor message and get the assistant's reply",
    responses=error_responses(404, 422),
)
async def create_message(conversation_id: uuid.UUID, body: MessageCreate) -> MessageExchange:
    """Store the visitor message and return the assistant's reply.

    The reply's `answer_type` tells the UI what to show:

    - `grounded`: an answer with `citations`.
    - `knowledge_gap`: the documents do not answer the question; offer a human handoff.
    - `clarification`: the assistant asks for more detail.
    - `inquiry_offer`: the visitor wants to buy; `inquiry` may carry a draft to
      review and confirm.
    """
    raise NotImplementedApiError("Sending a message")
