"""Local development runner: `python -m scripts.dev [up|db|migrate]`.

- `up` (default): database, migrations, API, worker and frontend dev server.
- `db`: only the embedded database; prints its URL and waits.
- `migrate`: apply migrations and exit.

Without DATABASE_URL the runner starts an embedded PostgreSQL with pgvector in
`.local/postgres` at the repository root, so no Docker or system PostgreSQL is
needed. Ports come from BACKEND_PORT and FRONTEND_PORT (environment or `.env`).
"""

import argparse
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
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import REPO_ROOT
from scripts.embedded_postgres import embedded_postgres

BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
EMBEDDED_DATA_DIR = REPO_ROOT / ".local" / "postgres"


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
        f"API: http://127.0.0.1:{settings.backend_port}/api/docs  "
        f"Frontend: http://127.0.0.1:{settings.frontend_port}/  (Ctrl+C to stop)",
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
    settings = DevSettings()
    with database(settings) as database_url:
        if action == "db":
            stop_requested().wait()
            return 0
        migrate(database_url)
        if action == "migrate":
            return 0
        return run_stack(settings, database_url)


if __name__ == "__main__":
    raise SystemExit(main())
