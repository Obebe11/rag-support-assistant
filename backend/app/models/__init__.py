"""SQLAlchemy models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.conversations import Conversation, Message
from app.models.documents import Chunk, Document, DocumentVersion
from app.models.inquiries import Inquiry, InquiryDelivery, InquiryDeliveryAttempt
from app.models.jobs import Job

__all__ = [
    "Base",
    "Chunk",
    "Conversation",
    "Document",
    "DocumentVersion",
    "Inquiry",
    "InquiryDelivery",
    "InquiryDeliveryAttempt",
    "Job",
    "Message",
]
