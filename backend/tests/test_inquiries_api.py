"""Inquiry drafts, confirmation and the visitor-facing delivery endpoints."""

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.core.db import SessionFactory
from app.models.conversations import Conversation
from app.models.inquiries import InquiryDelivery
from app.models.jobs import Job
from app.worker import job_types
from tests.inquiry_support import create_confirmed, handoff_body, purchase_body

UNKNOWN_ID = "00000000-0000-4000-8000-000000000001"

pytestmark = pytest.mark.usefixtures("session_factory")


async def _count(session_factory: SessionFactory, model: type) -> int:
    async with session_factory() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_empty_purchase_draft_lists_every_required_field(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/inquiries", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "purchase"
    assert body["status"] == "draft"
    assert body["missing_fields"] == [
        "product",
        "quantity",
        "timeline",
        "contact_name",
        "contact_email",
    ]
    assert body["contact"] == {"name": None, "email": None, "company": None, "phone": None}
    assert body["delivery"] is None
    assert body["confirmed_at"] is None


async def test_handoff_draft_requires_contact_and_the_question(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/inquiries", json={"kind": "handoff"})

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "handoff"
    assert body["missing_fields"] == ["contact_name", "contact_email", "notes"]


async def test_draft_is_filled_step_by_step_and_then_confirmed(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/inquiries", json={"product": "Standing desk"})
    inquiry_id = created.json()["id"]

    updated = await client.patch(
        f"/api/inquiries/{inquiry_id}",
        json={"quantity": 20, "timeline": "next month", "contact": {"name": "Jane Doe"}},
    )
    assert updated.status_code == 200
    assert updated.json()["missing_fields"] == ["contact_email"]
    assert updated.json()["product"] == "Standing desk"

    completed = await client.patch(
        f"/api/inquiries/{inquiry_id}", json={"contact": {"email": " jane.doe@example.com "}}
    )
    assert completed.json()["missing_fields"] == []
    assert completed.json()["contact"] == {
        "name": "Jane Doe",
        "email": "jane.doe@example.com",
        "company": None,
        "phone": None,
    }

    confirmed = await client.post(f"/api/inquiries/{inquiry_id}/confirm")
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["confirmed_at"] is not None
    assert body["delivery"] == {
        "status": "pending",
        "crm_mode": "simulated",
        "live": False,
        "attempt_count": 0,
        "last_error": None,
        "failure_reason": None,
        "last_attempt_at": None,
        "next_attempt_at": None,
        "delivered_at": None,
        "crm_contact_id": None,
        "crm_record_id": None,
        "attempts": [],
    }

    read = await client.get(f"/api/inquiries/{inquiry_id}")
    assert read.status_code == 200
    assert read.json() == body


async def test_handoff_is_confirmed_without_purchase_fields(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/inquiries", json=handoff_body())
    inquiry_id = created.json()["id"]
    assert created.json()["missing_fields"] == []

    confirmed = await client.post(f"/api/inquiries/{inquiry_id}/confirm")

    assert confirmed.status_code == 200
    body = confirmed.json()
    assert (body["kind"], body["status"]) == ("handoff", "confirmed")
    assert (body["product"], body["quantity"], body["timeline"]) == (None, None, None)
    assert body["delivery"]["status"] == "pending"


async def test_null_clears_a_field_and_omitted_fields_keep_their_value(
    client: httpx.AsyncClient,
) -> None:
    created = await client.post("/api/inquiries", json=purchase_body())
    inquiry_id = created.json()["id"]

    response = await client.patch(
        f"/api/inquiries/{inquiry_id}", json={"timeline": None, "contact": {"phone": None}}
    )

    body = response.json()
    assert body["timeline"] is None
    assert body["missing_fields"] == ["timeline"]
    assert body["contact"]["phone"] is None
    assert body["contact"]["name"] == "Jane Doe"
    assert body["product"] == "Standing desk"

    cleared = await client.patch(f"/api/inquiries/{inquiry_id}", json={"contact": None})
    assert cleared.json()["contact"] == {
        "name": None,
        "email": None,
        "company": None,
        "phone": None,
    }


async def test_kind_cannot_be_changed_after_creation(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/inquiries", json=handoff_body())
    inquiry_id = created.json()["id"]

    response = await client.patch(
        f"/api/inquiries/{inquiry_id}", json={"kind": "purchase", "notes": "Another question"}
    )

    assert response.status_code == 200
    assert response.json()["kind"] == "handoff"
    assert response.json()["notes"] == "Another question"


async def test_draft_can_be_linked_to_a_conversation(
    client: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    async with session_factory() as session:
        conversation = Conversation()
        session.add(conversation)
        await session.commit()

    linked = await client.post(
        "/api/inquiries", json=handoff_body(conversation_id=str(conversation.id))
    )
    unknown = await client.post("/api/inquiries", json=handoff_body(conversation_id=UNKNOWN_ID))

    assert linked.status_code == 201
    assert linked.json()["conversation_id"] == str(conversation.id)
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("body", "missing"),
    [
        (purchase_body(quantity=None), ["quantity"]),
        (purchase_body(contact={"name": "Jane Doe"}), ["contact_email"]),
        ({"kind": "purchase", "notes": "Call me"}, None),
        (handoff_body(notes=None), ["notes"]),
        (handoff_body(contact={"email": "sam.lee@example.com"}), ["contact_name"]),
    ],
)
async def test_incomplete_draft_cannot_be_confirmed(
    client: httpx.AsyncClient,
    session_factory: SessionFactory,
    body: dict[str, object],
    missing: list[str] | None,
) -> None:
    created = await client.post("/api/inquiries", json=body)
    inquiry_id = created.json()["id"]
    expected = missing if missing is not None else created.json()["missing_fields"]

    response = await client.post(f"/api/inquiries/{inquiry_id}/confirm")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert [detail["field"] for detail in error["details"]] == expected
    assert (await client.get(f"/api/inquiries/{inquiry_id}")).json()["status"] == "draft"
    assert await _count(session_factory, InquiryDelivery) == 0
    assert await _count(session_factory, Job) == 0


async def test_confirmed_inquiry_cannot_be_changed(client: httpx.AsyncClient) -> None:
    inquiry_id = await create_confirmed(client, purchase_body())

    response = await client.patch(f"/api/inquiries/{inquiry_id}", json={"quantity": 99})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    assert (await client.get(f"/api/inquiries/{inquiry_id}")).json()["quantity"] == 20


async def test_confirming_twice_queues_one_delivery(
    client: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    inquiry_id = await create_confirmed(client, purchase_body())
    first = (await client.get(f"/api/inquiries/{inquiry_id}")).json()

    again = await client.post(f"/api/inquiries/{inquiry_id}/confirm")

    assert again.status_code == 200
    assert again.json() == first
    assert await _count(session_factory, InquiryDelivery) == 1
    async with session_factory() as session:
        jobs = (await session.execute(select(Job))).scalars().all()
    assert [(job.job_type, job.payload) for job in jobs] == [
        (job_types.DELIVER_INQUIRY, {"inquiry_id": inquiry_id})
    ]


async def test_concurrent_confirmations_queue_one_delivery(
    client: httpx.AsyncClient, session_factory: SessionFactory
) -> None:
    created = await client.post("/api/inquiries", json=purchase_body())
    inquiry_id = created.json()["id"]

    responses = await asyncio.gather(
        *(client.post(f"/api/inquiries/{inquiry_id}/confirm") for _ in range(5))
    )

    assert [response.status_code for response in responses] == [200] * 5
    assert {response.json()["confirmed_at"] for response in responses} == {
        responses[0].json()["confirmed_at"]
    }
    assert await _count(session_factory, InquiryDelivery) == 1
    assert await _count(session_factory, Job) == 1


async def test_delivery_endpoints_reject_a_draft(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/inquiries", json=purchase_body())
    inquiry_id = created.json()["id"]

    status = await client.get(f"/api/inquiries/{inquiry_id}/delivery")
    retry = await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")

    assert status.status_code == 409
    assert retry.status_code == 409


async def test_retry_is_rejected_unless_the_delivery_failed(client: httpx.AsyncClient) -> None:
    inquiry_id = await create_confirmed(client, purchase_body())

    response = await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")

    assert response.status_code == 409
    assert "pending" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/inquiries/{id}"),
        ("PATCH", "/api/inquiries/{id}"),
        ("POST", "/api/inquiries/{id}/confirm"),
        ("GET", "/api/inquiries/{id}/delivery"),
        ("POST", "/api/inquiries/{id}/delivery/retry"),
    ],
)
async def test_unknown_inquiry_is_not_found(
    client: httpx.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(
        method, path.format(id=uuid.uuid4()), json={} if method == "PATCH" else None
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "not_found",
        "message": "Inquiry not found.",
        "details": [],
    }


async def test_invalid_values_are_rejected_with_field_details(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/inquiries", json={})
    inquiry_id = created.json()["id"]

    response = await client.patch(
        f"/api/inquiries/{inquiry_id}",
        json={"quantity": 0, "product": "   ", "contact": {"email": "not-an-email"}},
    )

    assert response.status_code == 422
    assert {detail["field"] for detail in response.json()["error"]["details"]} == {
        "body.quantity",
        "body.product",
        "body.contact.email",
    }
