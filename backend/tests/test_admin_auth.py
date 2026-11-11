import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app
from tests.api_cases import admin_operations, visitor_operations
from tests.conftest import make_settings

ADMIN_OPERATION_COUNT = 7
"""Admin operations in the contract. A new admin route raises this number."""


def test_the_access_tests_cover_every_admin_operation(app: FastAPI) -> None:
    operations = admin_operations(app)

    assert len(operations) == ADMIN_OPERATION_COUNT
    assert ("POST", "/api/admin/documents") in operations
    assert ("POST", "/api/admin/documents/search") in operations
    assert ("GET", "/api/admin/inquiries") in operations


async def test_every_admin_endpoint_without_a_token_returns_401(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    for method, path in admin_operations(app):
        response = await client.request(method, path)

        assert response.status_code == 401, f"{method} {path}"
        assert response.headers["www-authenticate"] == "Bearer", f"{method} {path}"
        assert response.json() == {
            "error": {
                "code": "unauthorized",
                "message": "Administrator token required.",
                "details": [],
            }
        }, f"{method} {path}"


async def test_every_admin_endpoint_with_a_wrong_token_returns_403(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    for method, path in admin_operations(app):
        response = await client.request(
            method, path, headers={"Authorization": "Bearer wrong-token"}
        )

        assert response.status_code == 403, f"{method} {path}"
        assert response.json() == {
            "error": {
                "code": "forbidden",
                "message": "Administrator token rejected.",
                "details": [],
            }
        }, f"{method} {path}"


@pytest.mark.parametrize(
    "authorization",
    ["Basic dGVzdC1hZG1pbi10b2tlbjo=", "test-admin-token", "Bearer"],
    ids=["basic-scheme", "no-scheme", "empty-bearer"],
)
async def test_admin_endpoint_with_a_non_bearer_header_returns_401(
    client: httpx.AsyncClient, authorization: str
) -> None:
    response = await client.get("/api/admin/documents", headers={"Authorization": authorization})

    assert response.status_code == 401


async def test_admin_endpoint_accepts_the_configured_token(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await client.get("/api/admin/documents", headers=admin_headers)

    assert response.status_code == 200


async def test_every_admin_endpoint_is_closed_when_no_token_is_configured(
    settings: Settings,
) -> None:
    app = create_app(make_settings(settings.database_url, admin_api_token=None))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for method, path in admin_operations(app):
                missing = await client.request(method, path)
                assert missing.status_code == 401, f"{method} {path}"
                for token in ("None", "test-admin-token"):
                    response = await client.request(
                        method, path, headers={"Authorization": f"Bearer {token}"}
                    )
                    assert response.status_code == 403, f"{method} {path} with {token!r}"


async def test_authorization_is_checked_before_the_request_is_validated(
    client: httpx.AsyncClient,
) -> None:
    """A visitor learns nothing about admin endpoints, not even validation rules."""
    invalid_query = await client.get("/api/admin/inquiries", params={"limit": "many"})
    missing_file = await client.post("/api/admin/documents", data={"title": "No file"})
    invalid_id = await client.delete("/api/admin/documents/not-a-uuid")

    assert [invalid_query.status_code, missing_file.status_code, invalid_id.status_code] == [
        401,
        401,
        401,
    ]


async def test_no_visitor_endpoint_asks_for_a_token(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    operations = visitor_operations(app)

    assert ("POST", "/api/conversations") in operations
    for method, path in operations:
        response = await client.request(method, path)

        assert response.status_code not in (401, 403), f"{method} {path}"
