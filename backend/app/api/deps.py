"""FastAPI dependencies shared by every route.

Change it only additively.
"""

import secrets
from collections.abc import AsyncIterator
from http import HTTPStatus
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError
from app.core.config import Settings
from app.core.db import SessionFactory
from app.providers.crm.access import CRMAccessMonitor
from app.providers.crm.base import CRMProvider
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.factory import Providers
from app.providers.llm.base import LLMProvider
from app.schemas.common import ErrorCode
from app.services.inquiry_intent import InquiryIntentDetector


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_session_factory(request: Request) -> SessionFactory:
    session_factory: SessionFactory = request.app.state.session_factory
    return session_factory


SessionFactoryDep = Annotated[SessionFactory, Depends(get_session_factory)]


async def get_session(session_factory: SessionFactoryDep) -> AsyncIterator[AsyncSession]:
    """Yield a session for one request. The route or service commits explicitly."""
    async with session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _get_providers(request: Request) -> Providers:
    providers: Providers = request.app.state.providers
    return providers


def get_llm_provider(providers: Annotated[Providers, Depends(_get_providers)]) -> LLMProvider:
    return providers.llm


def get_embedding_provider(
    providers: Annotated[Providers, Depends(_get_providers)],
) -> EmbeddingProvider:
    return providers.embeddings


def get_crm_provider(providers: Annotated[Providers, Depends(_get_providers)]) -> CRMProvider:
    return providers.crm


LLMProviderDep = Annotated[LLMProvider, Depends(get_llm_provider)]
EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
CRMProviderDep = Annotated[CRMProvider, Depends(get_crm_provider)]


def get_inquiry_intent_detector(request: Request) -> InquiryIntentDetector:
    detector: InquiryIntentDetector = request.app.state.inquiry_intent_detector
    return detector


InquiryIntentDetectorDep = Annotated[InquiryIntentDetector, Depends(get_inquiry_intent_detector)]


def get_crm_access_monitor(request: Request) -> CRMAccessMonitor:
    monitor: CRMAccessMonitor = request.app.state.crm_access
    return monitor


CRMAccessMonitorDep = Annotated[CRMAccessMonitor, Depends(get_crm_access_monitor)]

_admin_bearer = HTTPBearer(
    scheme_name="AdminToken",
    description="Administrator token from the ADMIN_API_TOKEN setting.",
    auto_error=False,
)


def require_admin(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_admin_bearer)],
    settings: SettingsDep,
) -> None:
    """Allow the request only with the configured administrator token.

    401: no bearer token was sent. 403: the token is wrong, or admin access is not
    configured on this server.
    """
    if credentials is None:
        raise ApiError(
            HTTPStatus.UNAUTHORIZED,
            ErrorCode.UNAUTHORIZED,
            "Administrator token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expected = settings.admin_api_token
    if expected is None or not secrets.compare_digest(
        credentials.credentials.encode(), expected.get_secret_value().encode()
    ):
        raise ApiError(HTTPStatus.FORBIDDEN, ErrorCode.FORBIDDEN, "Administrator token rejected.")
