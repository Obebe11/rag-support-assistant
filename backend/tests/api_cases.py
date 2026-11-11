"""Requests for the declared API operations, derived from the OpenAPI schema.

The lists come from the application itself, so a new route is covered by the
access tests without anyone having to remember to add it.
"""

from fastapi import FastAPI

ANY_ID = "00000000-0000-4000-8000-000000000001"
ADMIN_PREFIX = "/api/admin/"


def declared_operations(app: FastAPI) -> list[tuple[str, str]]:
    """Every declared operation as (method, path), with path parameters filled in."""
    operations = []
    for path, item in app.openapi()["paths"].items():
        concrete = path
        for parameter in ("conversation_id", "inquiry_id", "document_id"):
            concrete = concrete.replace(f"{{{parameter}}}", ANY_ID)
        assert "{" not in concrete, f"Unknown path parameter in {path}"
        operations += [(method.upper(), concrete) for method in item]
    return sorted(operations)


def admin_operations(app: FastAPI) -> list[tuple[str, str]]:
    return [(method, path) for method, path in declared_operations(app) if is_admin(path)]


def visitor_operations(app: FastAPI) -> list[tuple[str, str]]:
    return [(method, path) for method, path in declared_operations(app) if not is_admin(path)]


def is_admin(path: str) -> bool:
    return path.startswith(ADMIN_PREFIX)
