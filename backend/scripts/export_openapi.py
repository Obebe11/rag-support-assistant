"""Write the API contract to docs/openapi.json: `python -m scripts.export_openapi`.

The frontend generates its typed client from this file.
"""

import json
from pathlib import Path

from fastapi import FastAPI

from app.core.config import REPO_ROOT, Settings
from app.main import create_app

OPENAPI_PATH = REPO_ROOT / "docs" / "openapi.json"


def render_openapi(app: FastAPI) -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    # The schema does not depend on the environment, so no real database is needed.
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://unused@localhost/unused",
    )
    Path(OPENAPI_PATH).write_text(render_openapi(create_app(settings)), encoding="utf-8")
    print(f"Wrote {OPENAPI_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
