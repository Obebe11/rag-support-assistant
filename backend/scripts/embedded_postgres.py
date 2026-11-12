"""Embedded PostgreSQL + pgvector for development and tests on machines without Docker.

Uses the `pixeltable-pgserver` wheel, which bundles PostgreSQL and the pgvector
extension. The server listens on a Unix socket inside (or next to) its data
directory, so it never takes a TCP port.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from pixeltable_pgserver.postgres_server import PostgresServer


def _asyncpg_url(server: "PostgresServer", database: str) -> str:
    info = server.get_postmaster_info()
    if info.socket_dir is not None:
        return (
            f"postgresql+asyncpg://{server.postgres_user}@/{database}"
            f"?host={quote(str(info.socket_dir))}&port={info.port}"
        )
    return f"postgresql+asyncpg://{server.postgres_user}@{info.hostname}:{info.port}/{database}"


@contextmanager
def embedded_postgres(data_dir: Path, database: str = "handoff") -> Iterator[str]:
    """Start a server on `data_dir`, create `database` if needed, yield its asyncpg URL.

    The server stops when the context exits and no other process uses the same
    data directory.
    """
    if not database.isidentifier():
        raise ValueError(f"Not a valid database name: {database!r}")
    # Imported here: the package is a development dependency, and the scripts that
    # are given a DATABASE_URL (as in the container image) must load without it.
    from pixeltable_pgserver.postgres_server import get_server

    data_dir.mkdir(parents=True, exist_ok=True)
    server = get_server(data_dir, cleanup_mode="stop")
    try:
        # The name is checked above; psql takes no bind parameters.
        exists = server.psql(f"SELECT 1 FROM pg_database WHERE datname = '{database}';")  # noqa: S608
        if "(1 row)" not in exists:
            server.psql(f'CREATE DATABASE "{database}";')
        yield _asyncpg_url(server, database)
    finally:
        server.cleanup()
