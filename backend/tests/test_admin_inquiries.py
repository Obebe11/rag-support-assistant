"""The administrator's inquiry list: access control, filters and paging."""

import httpx
import pytest

from app.core.config import Settings
from app.core.db import SessionFactory
from app.providers.crm.simulated import SimulatedCRMProvider
from tests.inquiry_support import (
    api_client,
    create_confirmed,
    delivery_worker,
    handoff_body,
    purchase_body,
)

pytestmark = pytest.mark.usefixtures("session_factory")

LIST = "/api/admin/inquiries"


async def test_visitor_without_a_token_cannot_list_inquiries(client: httpx.AsyncClient) -> None:
    await create_confirmed(client, purchase_body())

    response = await client.get(LIST)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "unauthorized"
    assert "jane.doe@example.com" not in response.text


async def test_wrong_token_cannot_list_inquiries(client: httpx.AsyncClient) -> None:
    await create_confirmed(client, purchase_body())

    response = await client.get(LIST, headers={"Authorization": "Bearer not-the-admin-token"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert "jane.doe@example.com" not in response.text


async def test_list_is_closed_when_no_admin_token_is_configured(settings: Settings) -> None:
    async with api_client(settings, admin_api_token=None) as client:
        response = await client.get(LIST, headers={"Authorization": "Bearer test-admin-token"})

    assert response.status_code == 403


async def test_admin_lists_inquiries_with_delivery_status_newest_first(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    delivered_id = await create_confirmed(client, purchase_body())
    await delivery_worker(session_factory, settings, SimulatedCRMProvider()).run_once()
    queued_id = await create_confirmed(client, handoff_body())
    draft_id = (await client.post("/api/inquiries", json={"product": "Desk lamp"})).json()["id"]

    response = await client.get(LIST, headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [item["id"] for item in body["items"]] == [draft_id, queued_id, delivered_id]
    draft, queued, delivered = body["items"]
    assert (draft["status"], draft["delivery"]) == ("draft", None)
    assert draft["missing_fields"] == ["quantity", "timeline", "contact_name", "contact_email"]
    assert (queued["kind"], queued["delivery"]["status"]) == ("handoff", "pending")
    assert delivered["delivery"]["status"] == "delivered"
    assert delivered["delivery"]["crm_record_id"] is not None
    assert [attempt["outcome"] for attempt in delivered["delivery"]["attempts"]] == ["succeeded"]
    assert delivered["contact"]["email"] == "jane.doe@example.com"


async def test_admin_filters_by_inquiry_and_delivery_status(
    client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    session_factory: SessionFactory,
    settings: Settings,
) -> None:
    worker = delivery_worker(session_factory, settings, SimulatedCRMProvider())
    delivered_id = await create_confirmed(client, purchase_body())
    rejected_id = await create_confirmed(client, purchase_body(email="buyer+reject@example.com"))
    await worker.run_once()
    await worker.run_once()
    queued_id = await create_confirmed(client, handoff_body())
    draft_id = (await client.post("/api/inquiries", json={})).json()["id"]

    async def ids(**params: str) -> list[str]:
        response = await client.get(LIST, params=params, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["total"] == len(response.json()["items"])
        return [item["id"] for item in response.json()["items"]]

    assert await ids(status="draft") == [draft_id]
    assert await ids(status="confirmed") == [queued_id, rejected_id, delivered_id]
    assert await ids(delivery_status="delivered") == [delivered_id]
    assert await ids(delivery_status="failed") == [rejected_id]
    assert await ids(delivery_status="pending") == [queued_id]
    assert await ids(delivery_status="in_progress") == []
    assert await ids(status="draft", delivery_status="failed") == []


async def test_admin_list_is_paged(
    client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = [
        (await client.post("/api/inquiries", json={"product": f"Item {number}"})).json()["id"]
        for number in range(5)
    ]

    first = await client.get(LIST, params={"limit": 2}, headers=admin_headers)
    second = await client.get(LIST, params={"limit": 2, "offset": 2}, headers=admin_headers)
    invalid = await client.get(LIST, params={"limit": 0}, headers=admin_headers)

    assert first.json()["total"] == second.json()["total"] == 5
    assert [item["id"] for item in first.json()["items"]] == created[:-3:-1]
    assert [item["id"] for item in second.json()["items"]] == created[-3:-5:-1]
    assert invalid.status_code == 422
