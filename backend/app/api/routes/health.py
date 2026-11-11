"""Service health and provider modes."""

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import SessionFactoryDep, SettingsDep
from app.core.config import Settings
from app.providers.factory import CRM_PROVIDERS, EMBEDDING_PROVIDERS, LLM_PROVIDERS
from app.schemas.health import (
    CRMProviderStatus,
    EmbeddingProviderStatus,
    HealthResponse,
    LLMProviderStatus,
    ProviderModes,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def provider_modes(settings: Settings) -> ProviderModes:
    return ProviderModes(
        llm=LLMProviderStatus(
            mode=settings.llm_provider,
            live=LLM_PROVIDERS[settings.llm_provider].live,
            model=settings.llm_model if LLM_PROVIDERS[settings.llm_provider].live else None,
        ),
        embeddings=EmbeddingProviderStatus(
            mode=settings.embedding_provider,
            live=EMBEDDING_PROVIDERS[settings.embedding_provider].live,
            model=(
                settings.embedding_model
                if EMBEDDING_PROVIDERS[settings.embedding_provider].live
                else None
            ),
        ),
        crm=CRMProviderStatus(
            mode=settings.crm_provider,
            live=CRM_PROVIDERS[settings.crm_provider].live,
        ),
    )


@router.get("/health", summary="Service health and provider modes")
async def get_health(settings: SettingsDep, session_factory: SessionFactoryDep) -> HealthResponse:
    """Report whether the database answers and which provider modes are active.

    A provider with `live: false` runs in local or simulated mode. The UI must
    label it and must not present it as a working LLM or a live CRM integration.
    """
    database_ok = True
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database health check failed")
        database_ok = False
    return HealthResponse(
        status="ok" if database_ok else "degraded",
        version=__version__,
        database="ok" if database_ok else "unavailable",
        providers=provider_modes(settings),
    )
