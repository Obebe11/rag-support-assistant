"""Application settings, loaded from environment variables and the root `.env` file."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class LLMProviderMode(StrEnum):
    LOCAL = "local"
    OPENAI_COMPATIBLE = "openai_compatible"


class EmbeddingProviderMode(StrEnum):
    LOCAL = "local"
    OPENAI_COMPATIBLE = "openai_compatible"


class CRMProviderMode(StrEnum):
    SIMULATED = "simulated"
    HUBSPOT = "hubspot"


class Settings(BaseSettings):
    """Runtime configuration.

    Shared file: T3, T4 and T5 may only add fields here, never rename or remove them.
    """

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = Field(
        description="SQLAlchemy URL with the asyncpg driver, for example "
        "postgresql+asyncpg://user:password@host:port/dbname.",
    )

    admin_api_token: SecretStr | None = Field(
        default=None,
        description="Bearer token for /api/admin. Admin endpoints reject every request "
        "while it is unset.",
    )
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    llm_provider: LLMProviderMode = LLMProviderMode.LOCAL
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None

    embedding_provider: EmbeddingProviderMode = EmbeddingProviderMode.LOCAL
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_model: str | None = None

    crm_provider: CRMProviderMode = CRMProviderMode.SIMULATED
    hubspot_access_token: SecretStr | None = None
    hubspot_base_url: str = "https://api.hubapi.com"
    hubspot_api_version: str = Field(
        default="2026-09",
        pattern=r"^\d{4}-\d{2}$",
        description="Date-based HubSpot API version used in request paths.",
    )
    hubspot_timeout_seconds: float = Field(default=10.0, gt=0)
    crm_access_check_enabled: bool = Field(
        default=True,
        description="Check CRM credentials and required fields at startup and report "
        "the result in /api/health.",
    )
    crm_access_check_interval_seconds: float = Field(default=300.0, gt=0)
    delivery_max_attempts: int = Field(
        default=5,
        ge=1,
        description="Automatic delivery attempts per inquiry before the delivery fails. "
        "A manual retry starts a new set.",
    )

    max_upload_bytes: int = Field(default=10 * 1024 * 1024, gt=0)

    worker_poll_interval_seconds: float = Field(default=1.0, gt=0)
    job_backoff_base_seconds: float = Field(default=5.0, gt=0)
    job_backoff_max_seconds: float = Field(default=300.0, gt=0)
    job_timeout_seconds: float = Field(default=120.0, gt=0)
    job_lease_seconds: float = Field(default=300.0, gt=0)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must start with postgresql+asyncpg://")
        return value

    @model_validator(mode="after")
    def _check_provider_settings(self) -> Self:
        missing: list[str] = []
        if self.llm_provider is LLMProviderMode.OPENAI_COMPATIBLE:
            missing += [
                name
                for name, value in (
                    ("LLM_BASE_URL", self.llm_base_url),
                    ("LLM_MODEL", self.llm_model),
                )
                if not value
            ]
        if self.embedding_provider is EmbeddingProviderMode.OPENAI_COMPATIBLE:
            missing += [
                name
                for name, value in (
                    ("EMBEDDING_BASE_URL", self.embedding_base_url),
                    ("EMBEDDING_MODEL", self.embedding_model),
                )
                if not value
            ]
        if self.crm_provider is CRMProviderMode.HUBSPOT and self.hubspot_access_token is None:
            missing.append("HUBSPOT_ACCESS_TOKEN")
        if missing:
            raise ValueError("Missing settings for the selected providers: " + ", ".join(missing))
        if self.job_lease_seconds <= self.job_timeout_seconds:
            raise ValueError("JOB_LEASE_SECONDS must be greater than JOB_TIMEOUT_SECONDS")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
