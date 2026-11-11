"""FastAPI application factory. Run with `uvicorn app.main:create_app --factory`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app import __version__
from app.api.errors import register_error_handlers
from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.db import create_engine, create_session_factory
from app.core.logging import configure_logging
from app.providers.factory import build_providers
from app.services.inquiries.intent import build_inquiry_intent_detector


def _operation_id(route: APIRoute) -> str:
    return route.name


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        providers = build_providers(settings)
        app.state.session_factory = create_session_factory(engine)
        app.state.providers = providers
        app.state.inquiry_intent_detector = build_inquiry_intent_detector(settings, providers)
        try:
            yield
        finally:
            await providers.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Handoff AI API",
        version=__version__,
        summary="Grounded answers with citations and confirmed inquiry delivery to a CRM.",
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    register_error_handlers(app)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(api_router)
    return app
