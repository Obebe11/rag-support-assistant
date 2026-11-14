"""Local development runner: `python -m scripts.dev [up|db|migrate]`.

- `up` (default): database, migrations, API, worker and frontend dev server.
  Before the servers start, it creates `.env` when it is missing, checks the
  settings, loads the demo documents into an empty knowledge base, and indexes
  the documents again after a change of embedding model.
- `db`: only the embedded database; prints its URL and waits.
- `migrate`: apply migrations and exit.

Without DATABASE_URL the runner starts an embedded PostgreSQL with pgvector in
`.local/postgres` at the repository root, so no Docker or system PostgreSQL is
needed. Ports come from BACKEND_PORT and FRONTEND_PORT (environment or `.env`).
"""

import argparse
import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.api.errors import ApiError
from app.core.config import REPO_ROOT, Settings
from app.core.db import create_engine, create_session_factory
from app.providers.errors import ProviderError
from app.providers.factory import build_embedding_provider
from app.services.documents.indexing import IndexingFailedError
from app.services.documents.seeding import (
    ManifestError,
    count_documents,
    reindex_versions,
    seed_manifest,
    versions_without_model,
)
from scripts.configure import ensure_env_file
from scripts.embedded_postgres import embedded_postgres

BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
EMBEDDED_DATA_DIR = REPO_ROOT / ".local" / "postgres"
DEMO_MANIFEST = REPO_ROOT / "knowledge-base" / "northline" / "manifest.json"


class DevSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_ignore_empty=True, extra="ignore"
    )

    database_url: str | None = None
    backend_port: int = 8000
    frontend_port: int = 5173


@contextmanager
def database(settings: DevSettings) -> Iterator[str]:
    if settings.database_url:
        yield settings.database_url
        return
    with embedded_postgres(EMBEDDED_DATA_DIR) as url:
        print(f"Embedded PostgreSQL is running. DATABASE_URL={url}", flush=True)
        yield url


def migrate(database_url: str) -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = database_url
    command.upgrade(config, "head")


def load_settings(database_url: str) -> Settings | None:
    """The application settings, or None after printing what is wrong with them."""
    try:
        return Settings(database_url=database_url)
    except ValidationError as exc:
        print("The settings in .env cannot be used:", flush=True)
        for error in exc.errors():
            print(f"  - {error['msg'].removeprefix('Value error, ')}", flush=True)
        print("Run `make configure` to fix them.", flush=True)
        return None


async def _prepare_knowledge_base(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    embeddings = build_embedding_provider(settings)
    session_factory = create_session_factory(engine)
    try:
        if await count_documents(session_factory) == 0:
            print("The knowledge base is empty. Loading the demo documents...", flush=True)
            results = await seed_manifest(
                session_factory,
                embeddings,
                DEMO_MANIFEST,
                max_upload_bytes=settings.max_upload_bytes,
            )
            print(f"Loaded {len(results)} demo documents.", flush=True)
            return
        stale = await versions_without_model(session_factory, embeddings.model_name)
        if stale:
            print(
                f"Indexing {len(stale)} documents with the embedding model "
                f"{embeddings.model_name}...",
                flush=True,
            )
            # One request first: a wrong key or URL fails here and marks no document as failed.
            await embeddings.embed_query("test")
            await reindex_versions(session_factory, embeddings, stale)
            print("The documents are indexed.", flush=True)
    finally:
        await embeddings.aclose()
        await engine.dispose()


def prepare_knowledge_base(settings: Settings) -> None:
    """Make the documents searchable. A failure is reported and does not stop the stack."""
    try:
        asyncio.run(_prepare_knowledge_base(settings))
    except (ManifestError, IndexingFailedError, ApiError, ProviderError) as exc:
        print(f"The knowledge base is not ready: {exc}", flush=True)
        print("Check the embedding settings with `make configure`.", flush=True)


def stop_requested() -> threading.Event:
    """An event that is set on Ctrl+C or SIGTERM."""
    stop = threading.Event()
    for signal_number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, lambda *_: stop.set())
    return stop


def stop_process_group(process: subprocess.Popen[bytes], signal_number: int) -> None:
    """Signal a child and everything it started (reloaders, package-manager children)."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal_number)


def run_stack(settings: DevSettings, database_url: str) -> int:
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "BACKEND_PORT": str(settings.backend_port),
        "FRONTEND_PORT": str(settings.frontend_port),
    }
    commands: dict[str, tuple[list[str], Path]] = {
        "api": (
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--reload",
                "--reload-dir",
                "app",
                "--port",
                str(settings.backend_port),
            ],
            BACKEND_DIR,
        ),
        "worker": ([sys.executable, "-m", "app.worker"], BACKEND_DIR),
        "frontend": (["pnpm", "run", "dev"], FRONTEND_DIR),
    }
    # Each child leads its own process group, so stopping it also stops its children.
    processes = {
        name: subprocess.Popen(argv, cwd=cwd, env=env, start_new_session=True)  # noqa: S603
        for name, (argv, cwd) in commands.items()
    }
    print(
        f"\nOpen http://localhost:{settings.frontend_port}/\n"
        f"Admin: http://localhost:{settings.frontend_port}/admin "
        "(the token is ADMIN_API_TOKEN in .env)\n"
        f"API docs: http://localhost:{settings.backend_port}/api/docs\n"
        "Press Ctrl+C to stop.\n",
        flush=True,
    )
    stop = stop_requested()
    exit_code = 0
    try:
        while not stop.wait(0.5):
            for name, process in processes.items():
                if process.poll() is not None:
                    print(f"{name} exited with code {process.returncode}; stopping.", flush=True)
                    exit_code = process.returncode or 1
                    stop.set()
    finally:
        for process in processes.values():
            stop_process_group(process, signal.SIGTERM)
        for process in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                stop_process_group(process, signal.SIGKILL)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", nargs="?", default="up", choices=["up", "db", "migrate"])
    action: str = parser.parse_args().action
    if action == "up" and ensure_env_file():
        print("Created .env with demo settings and an admin token.", flush=True)
    settings = DevSettings()
    with database(settings) as database_url:
        if action == "db":
            stop_requested().wait()
            return 0
        migrate(database_url)
        if action == "migrate":
            return 0
        app_settings = load_settings(database_url)
        if app_settings is None:
            return 1
        prepare_knowledge_base(app_settings)
        return run_stack(settings, database_url)


if __name__ == "__main__":
    raise SystemExit(main())
