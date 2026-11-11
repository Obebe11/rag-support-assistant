import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from scripts.export_openapi import OPENAPI_PATH, render_openapi
from tests.api_cases import ADMIN_STUBS, ANY_ID, VISITOR_STUBS, ApiCase

EXPECTED_OPERATIONS = {
    ("GET", "/api/health"),
    ("POST", "/api/conversations"),
    ("GET", "/api/conversations/{conversation_id}"),
    ("POST", "/api/conversations/{conversation_id}/messages"),
    ("POST", "/api/inquiries"),
    ("GET", "/api/inquiries/{inquiry_id}"),
    ("PATCH", "/api/inquiries/{inquiry_id}"),
    ("POST", "/api/inquiries/{inquiry_id}/confirm"),
    ("GET", "/api/inquiries/{inquiry_id}/delivery"),
    ("POST", "/api/inquiries/{inquiry_id}/delivery/retry"),
    ("GET", "/api/admin/documents"),
    ("POST", "/api/admin/documents"),
    ("GET", "/api/admin/documents/{document_id}"),
    ("POST", "/api/admin/documents/{document_id}/versions"),
    ("DELETE", "/api/admin/documents/{document_id}"),
    ("GET", "/api/admin/inquiries"),
}


def _operations(schema: dict[str, object]) -> set[tuple[str, str]]:
    paths = schema["paths"]
    assert isinstance(paths, dict)
    return {(method.upper(), path) for path, item in paths.items() for method in item}


def test_openapi_declares_the_whole_contract(app: FastAPI) -> None:
    assert _operations(app.openapi()) >= EXPECTED_OPERATIONS


def test_every_operation_declares_a_typed_success_response(app: FastAPI) -> None:
    schema = app.openapi()
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            success = [code for code in operation["responses"] if code.startswith("2")]
            assert len(success) == 1, f"{method} {path}"
            if success[0] == "204":
                continue
            content = operation["responses"][success[0]]["content"]["application/json"]
            assert "$ref" in content["schema"], f"{method} {path} has no response schema"


def test_every_declared_error_uses_the_common_format(app: FastAPI) -> None:
    schema = app.openapi()
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            for code, response in operation["responses"].items():
                if code.startswith("2"):
                    continue
                ref = response["content"]["application/json"]["schema"]["$ref"]
                assert ref == "#/components/schemas/ErrorResponse", f"{method} {path} {code}"


def test_admin_operations_declare_the_bearer_token(app: FastAPI) -> None:
    schema = app.openapi()
    assert schema["components"]["securitySchemes"]["AdminToken"] == {
        "type": "http",
        "scheme": "bearer",
        "description": "Administrator token from the ADMIN_API_TOKEN setting.",
    }
    for path, item in schema["paths"].items():
        for method, operation in item.items():
            is_admin = path.startswith("/api/admin/")
            assert (operation.get("security") == [{"AdminToken": []}]) is is_admin, (
                f"{method} {path}"
            )


def test_committed_openapi_file_is_up_to_date(app: FastAPI) -> None:
    committed = Path(OPENAPI_PATH).read_text(encoding="utf-8")
    assert committed == render_openapi(app), (
        "docs/openapi.json is stale. Run `make openapi` and commit the result."
    )


def test_every_stub_case_targets_a_declared_operation(app: FastAPI) -> None:
    """A stub case for a path that left the contract is a stale test."""
    declared = {
        (
            method,
            path.replace("{conversation_id}", ANY_ID)
            .replace("{inquiry_id}", ANY_ID)
            .replace("{document_id}", ANY_ID),
        )
        for method, path in _operations(app.openapi())
    }
    cases = {(case.method, case.path) for case in VISITOR_STUBS + ADMIN_STUBS}

    assert cases <= declared


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


@pytest.mark.parametrize("case", VISITOR_STUBS, ids=lambda case: case.id)
async def test_visitor_stub_returns_501_in_the_common_format(
    client: httpx.AsyncClient, case: ApiCase
) -> None:
    response = await _send(client, case)

    assert response.status_code == 501
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == "not_implemented"
    assert body["error"]["message"].endswith("is not implemented yet.")
    assert body["error"]["details"] == []


@pytest.mark.parametrize("case", ADMIN_STUBS, ids=lambda case: case.id)
async def test_admin_stub_returns_501_in_the_common_format(
    client: httpx.AsyncClient, admin_headers: dict[str, str], case: ApiCase
) -> None:
    response = await _send(client, case, admin_headers)

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_implemented"


async def test_validation_errors_use_the_common_format(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/inquiries",
        json={"quantity": 0, "contact": {"email": "not-an-email"}},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert {detail["field"] for detail in error["details"]} == {
        "body.quantity",
        "body.contact.email",
    }


async def test_malformed_json_uses_the_common_format(client: httpx.AsyncClient) -> None:
    response = await client.post(
        f"/api/conversations/{ANY_ID}/messages",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_unknown_route_uses_the_common_format(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "details": []}
    }


async def test_wrong_method_uses_the_common_format(client: httpx.AsyncClient) -> None:
    response = await client.delete("/api/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_openapi_file_is_valid_json() -> None:
    assert json.loads(Path(OPENAPI_PATH).read_text(encoding="utf-8"))["openapi"].startswith("3.")
