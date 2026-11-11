"""Health and provider mode schemas."""

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


class CRMProviderStatus(BaseModel):
    mode: CRMProviderMode
    live: bool = Field(
        description="True when inquiries are sent to a real CRM. False when delivery is simulated."
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
