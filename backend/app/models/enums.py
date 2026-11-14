"""Domain enumerations stored in the database and exposed through the API.

Values are stored as plain strings without database CHECK constraints, so a new
member can be added without a migration. Never rename or remove a member.
"""

from enum import StrEnum


class IndexingStatus(StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class AnswerType(StrEnum):
    """How the assistant answered a visitor message."""

    GROUNDED = "grounded"
    """The answer is supported by the knowledge base and carries citations."""
    KNOWLEDGE_GAP = "knowledge_gap"
    """The documents do not answer the question; the assistant offers a human handoff.
    It carries citations when it names a related documented fact."""
    CLARIFICATION = "clarification"
    """The assistant needs more detail before it can answer. It carries citations
    when it names the documented options."""
    INQUIRY_OFFER = "inquiry_offer"
    """The visitor wants to buy; the assistant collects details or offers an inquiry draft."""
    REFUSAL = "refusal"
    """The visitor asked for something outside the assistant's role, such as revealing
    its instructions, changing documents or approving a discount. The assistant declines."""


class InquiryStatus(StrEnum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"


class InquiryKind(StrEnum):
    """What the visitor asks for. Set when the inquiry is created and never changed."""

    PURCHASE = "purchase"
    """A purchase request: product, quantity, timeline and contact details."""
    HANDOFF = "handoff"
    """A human handoff after a knowledge gap: contact details and the visitor's question."""


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    """Queued, or waiting for the next retry."""
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    FAILED = "failed"
    """Every automatic attempt failed; a manual retry is possible."""


class DeliveryAttemptOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
