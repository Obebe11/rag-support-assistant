import httpx
import pytest

from app.core.config import Settings
from app.main import create_app
from tests.api_cases import ADMIN_STUBS, VISITOR_STUBS, ApiCase
from tests.conftest import make_settings


async def _send(
    client: httpx.AsyncClient, case: ApiCase, headers: dict[str, str] | None = None
) -> httpx.Response:
    return await client.request(
        case.method,
        case.path,
        json=case.json,
        files=case.files,
        data=case.data or None,
        headers=headers,
    )


@pytest.mark.parametrize("case", ADMIN_STUBS, ids=lambda case: case.id)
async def test_admin_endpoint_without_a_token_returns_401(
    client: httpx.AsyncClient, case: ApiCase
) -> None:
    response = await _send(client, case)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "error": {
            "code": "unauthorized",
            "message": "Administrator token required.",
            "details": [],
        }
    }


@pytest.mark.parametrize("case", ADMIN_STUBS, ids=lambda case: case.id)
async def test_admin_endpoint_with_a_wrong_token_returns_403(
    client: httpx.AsyncClient, case: ApiCase
) -> None:
    response = await _send(client, case, {"Authorization": "Bearer wrong-token"})

    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "code": "forbidden",
            "message": "Administrator token rejected.",
            "details": [],
        }
    }


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


async def test_admin_is_closed_when_no_token_is_configured(settings: Settings) -> None:
    app = create_app(make_settings(settings.database_url, admin_api_token=None))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for token in ("", "None", "test-admin-token"):
                response = await client.get(
                    "/api/admin/documents", headers={"Authorization": f"Bearer {token}"}
                )
                assert response.status_code in (401, 403), token
                assert response.status_code != 501


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


@pytest.mark.parametrize("case", VISITOR_STUBS, ids=lambda case: case.id)
async def test_visitor_endpoint_needs_no_token(client: httpx.AsyncClient, case: ApiCase) -> None:
    response = await _send(client, case)

    assert response.status_code not in (401, 403)
