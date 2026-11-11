"""Load a document manifest into the knowledge base: `python -m scripts.seed_knowledge_base`.

Without arguments it loads the Northline corpus from
`knowledge-base/northline/manifest.json`. The command is idempotent: a second
run changes nothing, and a changed file becomes a new version of its document.
It indexes the documents itself and returns when they are searchable, so no
worker has to run.

The database comes from DATABASE_URL, or from the embedded PostgreSQL in
`.local/postgres` that `make dev` uses. Providers come from the environment
and `.env`, as for the API.

`--map-file` writes the `doc_id` of every manifest entry with the ID of its
stored document as JSON. Evaluation cases refer to documents by `doc_id`.
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.api.errors import ApiError
from app.core.config import REPO_ROOT, Settings
from app.core.db import create_engine, create_session_factory
from app.providers.factory import build_embedding_provider
from app.services.documents.indexing import IndexingFailedError
from app.services.documents.seeding import ManifestError, SeedResult, seed_manifest
from scripts.dev import DevSettings, database, migrate

DEFAULT_MANIFEST = REPO_ROOT / "knowledge-base" / "northline" / "manifest.json"


async def seed(settings: Settings, manifest_path: Path) -> list[SeedResult]:
    engine = create_engine(settings.database_url)
    embeddings = build_embedding_provider(settings)
    try:
        return await seed_manifest(
            create_session_factory(engine),
            embeddings,
            manifest_path,
            max_upload_bytes=settings.max_upload_bytes,
        )
    finally:
        await embeddings.aclose()
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--map-file", type=Path, help="Write doc_id to document ID as JSON.")
    arguments = parser.parse_args()
    manifest_path: Path = arguments.manifest.resolve()

    with database(DevSettings()) as database_url:
        migrate(database_url)
        settings = Settings(database_url=database_url)
        try:
            results = asyncio.run(seed(settings, manifest_path))
        except (ManifestError, IndexingFailedError, ApiError) as exc:
            print(f"Seeding failed: {exc}")
            return 1

    for result in results:
        label = f" ({result.version_label})" if result.version_label else ""
        print(
            f"{result.action:<10} {result.doc_id:<40} version {result.version_number}{label}, "
            f"{result.chunk_count} chunks, document {result.document_id}"
        )
    print(
        f"{len(results)} documents from {manifest_path} are searchable "
        f"(embedding mode: {settings.embedding_provider.value})."
    )
    if arguments.map_file:
        arguments.map_file.write_text(
            json.dumps([result.as_json() for result in results], indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {arguments.map_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
