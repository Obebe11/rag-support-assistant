"""Health and provider mode schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import CRMProviderMode, EmbeddingProviderMode, LLMProviderMode


class LLMProviderStatus(BaseModel):
    mode: LLMProviderMode
    live: bool = Field(
        description="True when a real LLM API is configured. False in local mode, which "
        "is not a working LLM."
    )
    model: str | None = None


class EmbeddingProviderStatus(BaseModel):
    mode: EmbeddingProviderMode
    live: bool = Field(description="True when a real embedding API is configured.")
    model: str | None = None


class CRMAccessState(StrEnum):
    OK = "ok"
    """The last access check passed."""
    FAILED = "failed"
    """The last access check failed; deliveries are likely to fail too."""
    UNCHECKED = "unchecked"
    """No access check has finished yet, or the check is disabled."""


class CRMAccessStatus(BaseModel):
    """The CRM access check: credentials, permissions and the fields the integration
    writes. It runs at startup and is refreshed periodically."""

    state: CRMAccessState
    message: str | None = Field(
        default=None, description="What the check found. Never contains credentials."
    )
    checked_at: datetime | None = None


class CRMProviderStatus(BaseModel):
    mode: CRMProviderMode
    live: bool = Field(
        description="True when inquiries are sent to a real CRM. False when delivery is simulated."
    )
    access: CRMAccessStatus | None = Field(
        default=None,
        description="Result of the CRM access check. The server always sends it; it is "
        "optional in the contract so that older clients stay valid.",
    )


class ProviderModes(BaseModel):
    llm: LLMProviderStatus
    embeddings: EmbeddingProviderStatus
    crm: CRMProviderStatus


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: Literal["ok", "unavailable"]
    providers: ProviderModes
