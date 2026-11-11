"""Service health and provider modes."""

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import (
    CRMAccessMonitorDep,
    EmbeddingProviderDep,
    LLMProviderDep,
    SessionFactoryDep,
    SettingsDep,
)
from app.core.config import Settings
from app.providers.crm.access import UNCHECKED, CRMAccessSnapshot
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.factory import CRM_PROVIDERS
from app.providers.llm.base import LLMProvider
from app.schemas.health import (
    CRMAccessState,
    CRMAccessStatus,
    CRMProviderStatus,
    EmbeddingProviderStatus,
    HealthResponse,
    LLMProviderStatus,
    ProviderModes,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def provider_modes(
    settings: Settings,
    llm: LLMProvider,
    embeddings: EmbeddingProvider,
    crm_access: CRMAccessSnapshot = UNCHECKED,
) -> ProviderModes:
    """Modes and models of the running providers.

    The LLM and embedding entries are read from the provider objects that
    answer requests, so `model` here is the value a reply reports in its
    `usage`: the configured model of a live API, the name of the local
    embedding scheme, and nothing for the local LLM mode, which runs no model.
    """
    return ProviderModes(
        llm=LLMProviderStatus(mode=llm.mode, live=llm.live, model=llm.model_name),
        embeddings=EmbeddingProviderStatus(
            mode=embeddings.mode, live=embeddings.live, model=embeddings.model_name
        ),
        crm=CRMProviderStatus(
            mode=settings.crm_provider,
            live=CRM_PROVIDERS[settings.crm_provider].live,
            access=CRMAccessStatus(
                state=crm_access.state,
                message=crm_access.message,
                checked_at=crm_access.checked_at,
            ),
        ),
    )


@router.get("/health", summary="Service health and provider modes")
async def get_health(
    settings: SettingsDep,
    session_factory: SessionFactoryDep,
    llm: LLMProviderDep,
    embeddings: EmbeddingProviderDep,
    crm_access: CRMAccessMonitorDep,
) -> HealthResponse:
    """Report whether the database answers and which provider modes are active.

    A provider with `live: false` runs in local or simulated mode. The UI must
    label it and must not present it as a working LLM or a live CRM integration.

    `providers.crm.access` is the result of the CRM access check. The status is
    `degraded` when the database is unavailable or the CRM access check failed.
    """
    database_ok = True
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database health check failed")
        database_ok = False
    access = crm_access.snapshot()
    healthy = database_ok and access.state is not CRMAccessState.FAILED
    return HealthResponse(
        status="ok" if healthy else "degraded",
        version=__version__,
        database="ok" if database_ok else "unavailable",
        providers=provider_modes(settings, llm, embeddings, access),
    )
