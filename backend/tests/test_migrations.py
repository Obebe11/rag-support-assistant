"""The initial migration: applies, rolls back, and matches the models."""

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.db import SessionFactory
from app.models import Base, Chunk, Document, DocumentVersion
from tests.conftest import alembic_config

EXPECTED_TABLES = {
    "chunks",
    "conversations",
    "document_versions",
    "documents",
    "inquiries",
    "inquiry_deliveries",
    "inquiry_delivery_attempts",
    "jobs",
    "messages",
}


def _table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


@pytest_asyncio.fixture
async def scratch_database_url(engine: AsyncEngine, database_url: str) -> AsyncIterator[str]:
    """An empty database, separate from the one the other tests share."""
    name = f"migration_test_{uuid.uuid4().hex[:12]}"
    async with engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(database_url).set(database=name).render_as_string(hide_password=False)
    finally:
        async with engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))


async def test_migration_applies_and_rolls_back(scratch_database_url: str) -> None:
    config = alembic_config(scratch_database_url)
    scratch_engine = create_async_engine(scratch_database_url)
    try:
        await asyncio.to_thread(command.upgrade, config, "head")
        async with scratch_engine.connect() as connection:
            upgraded = await connection.run_sync(_table_names)
            vector_installed = (
                await connection.execute(
                    text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
                )
            ).scalar_one()

        await asyncio.to_thread(command.downgrade, config, "base")
        async with scratch_engine.connect() as connection:
            downgraded = await connection.run_sync(_table_names)

        await asyncio.to_thread(command.upgrade, config, "head")
        async with scratch_engine.connect() as connection:
            upgraded_again = await connection.run_sync(_table_names)
    finally:
        await scratch_engine.dispose()

    assert upgraded == EXPECTED_TABLES | {"alembic_version"}
    assert vector_installed == 1
    assert downgraded == {"alembic_version"}
    assert upgraded_again == upgraded


def test_migrations_have_a_single_head() -> None:
    """Two heads mean two tasks added migrations in parallel; merge them first."""
    script = ScriptDirectory.from_config(alembic_config("postgresql+asyncpg://unused/unused"))

    assert len(script.get_heads()) == 1


async def test_models_match_the_migrated_schema(engine: AsyncEngine) -> None:
    """A model change without a migration fails here."""

    def diff(connection: Connection) -> list[object]:
        return list(compare_metadata(MigrationContext.configure(connection), Base.metadata))

    async with engine.connect() as connection:
        differences = await connection.run_sync(diff)

    assert differences == []


async def _add_version(
    session_factory: SessionFactory, document_id: uuid.UUID, number: int, *, active: bool
) -> uuid.UUID:
    async with session_factory() as session:
        version = DocumentVersion(
            document_id=document_id,
            version_number=number,
            source_filename="returns.md",
            media_type="text/markdown",
            byte_size=10,
            checksum_sha256="0" * 64,
            content=b"# Returns\n",
            is_active=active,
        )
        session.add(version)
        await session.commit()
        return version.id


async def test_vector_search_reads_only_chunks_of_the_active_version(
    session_factory: SessionFactory,
) -> None:
    """The retrieval rule the schema is built for, on real pgvector."""
    async with session_factory() as session:
        document = Document(title="Returns policy")
        session.add(document)
        await session.commit()
    old_version = await _add_version(session_factory, document.id, 1, active=False)
    new_version = await _add_version(session_factory, document.id, 2, active=True)
    async with session_factory() as session:
        session.add_all(
            [
                Chunk(
                    document_version_id=old_version,
                    chunk_index=0,
                    content="Returns are accepted within 14 days.",
                    embedding=[1.0, 0.0, 0.0],
                    embedding_model="test-model",
                ),
                Chunk(
                    document_version_id=new_version,
                    chunk_index=0,
                    content="Returns are accepted within 30 days.",
                    heading="Returns",
                    embedding=[0.9, 0.1, 0.0],
                    embedding_model="test-model",
                ),
                Chunk(
                    document_version_id=new_version,
                    chunk_index=1,
                    content="Warranty lasts two years.",
                    page_number=2,
                    embedding=[0.0, 1.0, 0.0],
                    embedding_model="test-model",
                ),
                Chunk(
                    document_version_id=new_version,
                    chunk_index=2,
                    content="Embedded by another model with another dimension.",
                    embedding=[1.0, 0.0],
                    embedding_model="other-model",
                ),
            ]
        )
        await session.commit()

    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(Chunk.content)
                    .join(DocumentVersion)
                    .where(DocumentVersion.is_active, Chunk.embedding_model == "test-model")
                    .order_by(Chunk.embedding.cosine_distance([1.0, 0.0, 0.0]))
                )
            )
            .scalars()
            .all()
        )

    assert rows == ["Returns are accepted within 30 days.", "Warranty lasts two years."]


async def test_a_document_has_at_most_one_active_version(
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        document = Document(title="Shipping policy")
        session.add(document)
        await session.commit()
    await _add_version(session_factory, document.id, 1, active=True)

    with pytest.raises(IntegrityError, match="uq_document_versions_active_document"):
        await _add_version(session_factory, document.id, 2, active=True)


async def test_deleting_a_document_removes_its_versions_and_chunks(
    session_factory: SessionFactory,
) -> None:
    async with session_factory() as session:
        document = Document(title="Warranty")
        session.add(document)
        await session.commit()
    version_id = await _add_version(session_factory, document.id, 1, active=True)
    async with session_factory() as session:
        session.add(Chunk(document_version_id=version_id, chunk_index=0, content="Two years."))
        await session.commit()

    async with session_factory() as session:
        await session.execute(text("DELETE FROM documents"))
        await session.commit()
        remaining = (
            await session.execute(
                text(
                    "SELECT (SELECT count(*) FROM document_versions)"
                    " + (SELECT count(*) FROM chunks)"
                )
            )
        ).scalar_one()

    assert remaining == 0
