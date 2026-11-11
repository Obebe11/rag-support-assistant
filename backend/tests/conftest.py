"""Test fixtures. Every test runs on a real PostgreSQL with pgvector.

By default the suite starts an embedded server in a temporary directory. Set
TEST_DATABASE_URL (postgresql+asyncpg://...) to use an existing disposable
database instead; the role must be allowed to create extensions and databases.
"""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import (
    CRMProviderMode,
    EmbeddingProviderMode,
    LLMProviderMode,
    Settings,
)
from app.core.db import SessionFactory, create_engine, create_session_factory
from app.main import create_app
from app.models import Base
from scripts.embedded_postgres import embedded_postgres

BACKEND_DIR = Path(__file__).resolve().parents[1]
ADMIN_TOKEN = "test-admin-token"


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    config.attributes["configure_logging"] = False
    return config


def make_settings(database_url: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": "test",
        "database_url": database_url,
        "admin_api_token": SecretStr(ADMIN_TOKEN),
        "cors_allowed_origins": [],
        "llm_provider": LLMProviderMode.LOCAL,
        "embedding_provider": EmbeddingProviderMode.LOCAL,
        "crm_provider": CRMProviderMode.SIMULATED,
        # Tests that cover the CRM access check turn it on with a mock transport.
        "crm_access_check_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        yield external
        return
    with embedded_postgres(tmp_path_factory.mktemp("pg"), database="handoff_test") as url:
        yield url


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> str:
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest.fixture(scope="session")
def settings(migrated_database_url: str) -> Settings:
    return make_settings(migrated_database_url)


@pytest_asyncio.fixture(scope="session")
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> SessionFactory:
    """A session factory on a database with empty tables."""
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return create_session_factory(engine)


@pytest_asyncio.fixture
async def app(settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}
