"""Delivery of confirmed inquiries: retries, statuses, restarts and no duplicates.

Every test runs the real worker and handler on PostgreSQL. The CRM is the
simulated provider, or a subclass that fails at a chosen point.
"""

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.db import SessionFactory
from app.models.enums import JobStatus
from app.models.inquiries import InquiryDelivery
from app.models.jobs import Job
from app.providers.crm.base import LeadPayload, LeadResult
from app.providers.crm.simulated import SimulatedCRMProvider
from app.providers.errors import ProviderError
from app.worker import job_types, queue
from tests.inquiry_support import (
    api_client,
    create_confirmed,
    delivery_job,
    delivery_row,
    delivery_worker,
    expire_leases,
    get_delivery,
    handoff_body,
    make_jobs_due,
    purchase_body,
)
from tests.kb import ask, start_conversation

pytestmark = pytest.mark.usefixtures("session_factory")


class WorkerKilledError(BaseException):
    """Stops the worker mid-attempt without any cleanup, like a killed process."""


class ScriptedCRM(SimulatedCRMProvider):
    """A simulated CRM that misbehaves on chosen calls.

    `before` raises before anything is stored. `after` stores the contact and the
    record first and then raises: the CRM did the work but the answer was lost.
    """

    def __init__(
        self,
        *,
        before: dict[int, BaseException] | None = None,
        after: dict[int, BaseException] | None = None,
    ) -> None:
        super().__init__()
        self.before = before or {}
        self.after = after or {}
        self.calls: list[LeadPayload] = []

    async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
        self.calls.append(lead)
        call = len(self.calls)
        if call in self.before:
            raise self.before[call]
        result = await super().deliver_lead(lead)
        if call in self.after:
            raise self.after[call]
        return result


def _temporary(message: str = "CRM is temporarily unavailable.") -> ProviderError:
    return ProviderError(message, retryable=True)


def _permanent(message: str = "The CRM rejected the credentials.") -> ProviderError:
    return ProviderError(message, retryable=False)


def _outcomes(delivery: dict[str, Any]) -> list[tuple[int, str]]:
    return [(attempt["attempt_number"], attempt["outcome"]) for attempt in delivery["attempts"]]


@pytest.mark.parametrize("body", [purchase_body(), handoff_body()], ids=["purchase", "handoff"])
async def test_confirmed_inquiry_is_delivered(
    client: httpx.AsyncClient,
    session_factory: SessionFactory,
    settings: Settings,
    body: dict[str, Any],
) -> None:
    crm = SimulatedCRMProvider()
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, body)

    assert await worker.run_once() is True

    delivery = await get_delivery(client, inquiry_id)
    assert delivery["status"] == "delivered"
    assert (delivery["crm_mode"], delivery["live"]) == ("simulated", False)
    assert delivery["attempt_count"] == 1
    assert delivery["delivered_at"] is not None
    assert delivery["last_error"] is None
    assert delivery["failure_reason"] is None
    assert delivery["next_attempt_at"] is None
    assert _outcomes(delivery) == [(1, "succeeded")]
    contact = crm.state.contacts[body["contact"]["email"]]
    record = crm.state.records[f"inquiry:{inquiry_id}"]
    assert delivery["crm_contact_id"] == contact.id == record.contact_id
    assert delivery["crm_record_id"] == record.id
    assert record.lead.kind.value == body.get("kind", "purchase")
    assert record.lead.notes == body["notes"]
    assert (await delivery_job(session_factory, inquiry_id)).status is JobStatus.SUCCEEDED
    assert await worker.run_once() is False


async def test_nothing_is_sent_to_the_crm_before_confirmation(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM()
    worker = delivery_worker(session_factory, settings, crm)
    await client.post("/api/inquiries", json=purchase_body())

    assert await worker.run_once() is False
    assert crm.calls == []


async def test_a_draft_made_in_the_chat_is_not_sent_even_when_the_visitor_agrees(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    """The chat only fills a draft. Confirmation is a separate, explicit request."""
    crm = ScriptedCRM()
    worker = delivery_worker(session_factory, settings, crm)
    conversation_id = await start_conversation(client)

    for message in (
        "I'd like to order 20 standing desks by the end of March.",
        "Jane Doe",
        "jane.doe@example.com",
        "Yes, that's correct",
    ):
        reply = await ask(client, message, conversation_id)
        assert reply["answer_type"] == "inquiry_offer", message

    inquiry = reply["inquiry"]
    assert (inquiry["status"], inquiry["missing_fields"]) == ("draft", [])
    assert inquiry["delivery"] is None
    assert await worker.run_once() is False
    assert crm.calls == []
    async with session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Job))).scalar_one() == 0
        assert (
            await session.execute(select(func.count()).select_from(InquiryDelivery))
        ).scalar_one() == 0

    # The same draft is sent once the visitor confirms it.
    confirmed = await client.post(f"/api/inquiries/{inquiry['id']}/confirm")
    assert confirmed.status_code == 200
    assert await worker.run_once() is True
    assert [lead.contact.email for lead in crm.calls] == ["jane.doe@example.com"]


async def test_temporary_failure_is_retried_without_a_duplicate(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM(before={1: _temporary()})
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, purchase_body())

    await worker.run_once()

    waiting = await get_delivery(client, inquiry_id)
    assert waiting["status"] == "pending"
    assert waiting["attempt_count"] == 1
    assert waiting["last_error"] == "CRM is temporarily unavailable."
    assert waiting["failure_reason"] is None
    assert waiting["next_attempt_at"] is not None
    assert _outcomes(waiting) == [(1, "failed")]
    assert await worker.run_once() is False, "the retry must wait for its backoff"

    await make_jobs_due(session_factory)
    await worker.run_once()

    delivered = await get_delivery(client, inquiry_id)
    assert delivered["status"] == "delivered"
    assert delivered["attempt_count"] == 2
    assert delivered["last_error"] is None
    assert delivered["next_attempt_at"] is None
    assert _outcomes(delivered) == [(1, "failed"), (2, "succeeded")]
    assert [lead.attempt for lead in crm.calls] == [1, 2]
    assert {lead.idempotency_key for lead in crm.calls} == {f"inquiry:{inquiry_id}"}
    assert len(crm.state.contacts) == 1
    assert len(crm.state.records) == 1


async def test_answer_lost_after_the_crm_stored_the_record_does_not_duplicate_it(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM(after={1: _temporary("Connection closed before the CRM answered.")})
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, purchase_body())

    await worker.run_once()
    assert len(crm.state.records) == 1, "the CRM stored the record although the call failed"
    assert (await get_delivery(client, inquiry_id))["status"] == "pending"

    await make_jobs_due(session_factory)
    await worker.run_once()

    delivered = await get_delivery(client, inquiry_id)
    assert delivered["status"] == "delivered"
    assert len(crm.state.contacts) == 1
    assert len(crm.state.records) == 1
    assert delivered["crm_record_id"] == crm.state.records[f"inquiry:{inquiry_id}"].id


async def test_permanent_error_fails_at_once(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM(before={1: _permanent()})
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, purchase_body())

    await worker.run_once()
    await make_jobs_due(session_factory)

    assert await worker.run_once() is False, "a permanent error must not be retried"
    delivery = await get_delivery(client, inquiry_id)
    assert delivery["status"] == "failed"
    assert delivery["failure_reason"] == "permanent_error"
    assert delivery["last_error"] == "The CRM rejected the credentials."
    assert delivery["attempt_count"] == 1
    assert delivery["next_attempt_at"] is None
    assert _outcomes(delivery) == [(1, "failed")]
    assert (await delivery_job(session_factory, inquiry_id)).status is JobStatus.FAILED
    assert crm.state.records == {}


async def test_attempts_run_out_and_a_manual_retry_delivers(
    session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM(before={1: _temporary(), 2: _temporary(), 3: _temporary()})
    worker = delivery_worker(session_factory, settings, crm)
    async with api_client(settings, delivery_max_attempts=2) as client:
        inquiry_id = await create_confirmed(client, purchase_body())

        await worker.run_once()
        await make_jobs_due(session_factory)
        await worker.run_once()

        exhausted = await get_delivery(client, inquiry_id)
        assert exhausted["status"] == "failed"
        assert exhausted["failure_reason"] == "attempts_exhausted"
        assert exhausted["attempt_count"] == 2
        assert exhausted["next_attempt_at"] is None
        await make_jobs_due(session_factory)
        assert await worker.run_once() is False, "no automatic attempt is left"

        retry = await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")
        assert retry.status_code == 202
        assert retry.json()["status"] == "pending"
        assert retry.json()["failure_reason"] is None
        assert retry.json()["attempt_count"] == 2
        second_retry = await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")
        assert second_retry.status_code == 409

        await worker.run_once()
        still_failing = await get_delivery(client, inquiry_id)
        assert still_failing["status"] == "pending", "a manual retry gets a fresh set of attempts"

        await make_jobs_due(session_factory)
        await worker.run_once()
        delivered = await get_delivery(client, inquiry_id)

    assert delivered["status"] == "delivered"
    assert delivered["attempt_count"] == 4
    assert _outcomes(delivered) == [(1, "failed"), (2, "failed"), (3, "failed"), (4, "succeeded")]
    assert len(crm.state.records) == 1
    async with session_factory() as session:
        assert (await session.execute(select(func.count()).select_from(Job))).scalar_one() == 1


async def test_manual_retry_after_a_permanent_error(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM(before={1: _permanent()})
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, handoff_body())
    await worker.run_once()

    retry = await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")
    await worker.run_once()

    assert retry.status_code == 202
    delivered = await get_delivery(client, inquiry_id)
    assert delivered["status"] == "delivered"
    assert _outcomes(delivered) == [(1, "failed"), (2, "succeeded")]
    assert len(crm.state.records) == 1


async def test_undelivered_inquiry_survives_a_restart(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    """The queue and the delivery state live in PostgreSQL, not in a process."""
    first_process = delivery_worker(
        session_factory, settings, ScriptedCRM(before={1: _temporary()}), worker_id="before"
    )
    inquiry_id = await create_confirmed(client, purchase_body())
    await first_process.run_once()
    del first_process

    crm = SimulatedCRMProvider()
    second_process = delivery_worker(session_factory, settings, crm, worker_id="after")
    await make_jobs_due(session_factory)
    await second_process.run_once()

    delivered = await get_delivery(client, inquiry_id)
    assert delivered["status"] == "delivered"
    assert _outcomes(delivered) == [(1, "failed"), (2, "succeeded")]
    assert len(crm.state.records) == 1


async def test_a_delivery_queued_while_nothing_was_running_is_sent_after_a_restart(
    session_factory: SessionFactory, settings: Settings
) -> None:
    """Confirmed before any worker existed, and the API process ended in between."""
    async with api_client(settings) as client:
        inquiry_id = await create_confirmed(client, purchase_body())
        queued = await get_delivery(client, inquiry_id)

    crm = SimulatedCRMProvider()
    worker = delivery_worker(session_factory, settings, crm, worker_id="started-later")
    assert await worker.run_once() is True
    async with api_client(settings) as client:
        delivered = await get_delivery(client, inquiry_id)

    assert (queued["status"], queued["attempt_count"]) == ("pending", 0)
    assert delivered["status"] == "delivered"
    assert _outcomes(delivered) == [(1, "succeeded")]
    assert list(crm.state.records) == [f"inquiry:{inquiry_id}"]


async def test_delivery_recovers_after_the_worker_dies_mid_attempt(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM(after={1: WorkerKilledError()})
    dying = delivery_worker(session_factory, settings, crm, worker_id="dying")
    survivor = delivery_worker(session_factory, settings, crm, worker_id="survivor")
    inquiry_id = await create_confirmed(client, purchase_body())

    with pytest.raises(WorkerKilledError):
        await dying.run_once()

    stuck = await get_delivery(client, inquiry_id)
    assert stuck["status"] == "in_progress"
    assert stuck["attempt_count"] == 1
    assert await survivor.run_once() is False, "the lease of the dead worker still holds"

    await expire_leases(session_factory)
    assert await survivor.run_once() is True

    delivered = await get_delivery(client, inquiry_id)
    assert delivered["status"] == "delivered"
    assert delivered["attempt_count"] == 2
    assert _outcomes(delivered) == [(2, "succeeded")]
    assert len(crm.state.contacts) == 1
    assert len(crm.state.records) == 1


async def test_worker_death_on_the_last_attempt_is_reported_and_can_be_retried(
    session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM(before={1: WorkerKilledError()})
    worker = delivery_worker(session_factory, settings, crm)
    async with api_client(settings, delivery_max_attempts=1) as client:
        inquiry_id = await create_confirmed(client, purchase_body())
        with pytest.raises(WorkerKilledError):
            await worker.run_once()
        await expire_leases(session_factory)
        assert await worker.run_once() is False, "the queue gives up on the abandoned job"

        failed = await get_delivery(client, inquiry_id)
        assert failed["status"] == "failed"
        assert failed["failure_reason"] == "attempts_exhausted"
        assert failed["last_error"] == "The worker stopped during the final attempt."
        listed = await client.get(
            "/api/admin/inquiries",
            params={"delivery_status": "failed"},
            headers={"Authorization": "Bearer test-admin-token"},
        )
        assert [item["id"] for item in listed.json()["items"]] == [inquiry_id]

        retry = await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")
        assert retry.status_code == 202
        await worker.run_once()
        delivered = await get_delivery(client, inquiry_id)

    assert delivered["status"] == "delivered"
    assert len(crm.state.records) == 1


async def test_slow_crm_is_recorded_as_a_temporary_failure(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    class HangingCRM(SimulatedCRMProvider):
        async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
            await asyncio.sleep(30)
            return await super().deliver_lead(lead)

    worker = delivery_worker(
        session_factory, settings, HangingCRM(), job_timeout_seconds=0.2, job_lease_seconds=5
    )
    inquiry_id = await create_confirmed(client, purchase_body())

    await worker.run_once()

    delivery = await get_delivery(client, inquiry_id)
    assert delivery["status"] == "pending"
    assert delivery["last_error"] == "The CRM did not answer in time."
    assert _outcomes(delivery) == [(1, "failed")]
    assert (await delivery_job(session_factory, inquiry_id)).status is JobStatus.QUEUED


async def test_worker_that_lost_its_lease_cannot_undo_a_delivery(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    """A slow worker fails after another worker took the job over and delivered."""
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowThenFailingCRM(SimulatedCRMProvider):
        async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
            entered.set()
            await release.wait()
            raise ProviderError("The slow call finally failed.", retryable=True)

    crm = SimulatedCRMProvider()
    slow = delivery_worker(session_factory, settings, SlowThenFailingCRM(), worker_id="slow")
    fast = delivery_worker(session_factory, settings, crm, worker_id="fast")
    inquiry_id = await create_confirmed(client, purchase_body())

    slow_run = asyncio.create_task(slow.run_once())
    await entered.wait()
    await expire_leases(session_factory)
    assert await fast.run_once() is True
    release.set()
    await slow_run

    delivery = await get_delivery(client, inquiry_id)
    assert delivery["status"] == "delivered"
    assert delivery["last_error"] is None
    assert _outcomes(delivery) == [(1, "failed"), (2, "succeeded")]
    assert (await delivery_job(session_factory, inquiry_id)).status is JobStatus.SUCCEEDED
    assert len(crm.state.records) == 1


async def test_two_workers_delivering_the_same_inquiry_create_one_record(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    """Both workers reach the CRM; the idempotency key keeps one record."""
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowCRM(ScriptedCRM):
        async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
            if not self.calls:
                self.calls.append(lead)
                entered.set()
                await release.wait()
                return await SimulatedCRMProvider.deliver_lead(self, lead)
            return await super().deliver_lead(lead)

    crm = SlowCRM()
    slow = delivery_worker(session_factory, settings, crm, worker_id="slow")
    fast = delivery_worker(session_factory, settings, crm, worker_id="fast")
    inquiry_id = await create_confirmed(client, purchase_body())

    slow_run = asyncio.create_task(slow.run_once())
    await entered.wait()
    await expire_leases(session_factory)
    assert await fast.run_once() is True
    release.set()
    await slow_run

    delivery = await get_delivery(client, inquiry_id)
    assert delivery["status"] == "delivered"
    assert len(crm.calls) == 2
    assert len(crm.state.contacts) == 1
    assert len(crm.state.records) == 1
    assert _outcomes(delivery) == [(2, "succeeded")], "the late result was rolled back"


async def test_a_delivered_inquiry_cannot_be_retried(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM()
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, purchase_body())
    await worker.run_once()

    retry = await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")

    assert retry.status_code == 409
    assert "delivered" in retry.json()["error"]["message"]
    assert await worker.run_once() is False
    assert len(crm.calls) == 1
    assert (await get_delivery(client, inquiry_id))["status"] == "delivered"


async def test_second_job_for_a_delivered_inquiry_does_not_call_the_crm(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = ScriptedCRM()
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, purchase_body())
    await worker.run_once()

    async with session_factory() as session:
        same_key = await queue.enqueue(
            session,
            job_types.DELIVER_INQUIRY,
            {"inquiry_id": inquiry_id},
            idempotency_key=f"{job_types.DELIVER_INQUIRY}:{inquiry_id}",
        )
        stray = await queue.enqueue(session, job_types.DELIVER_INQUIRY, {"inquiry_id": inquiry_id})
        await session.commit()
    assert same_key.created is False
    assert stray.created is True

    assert await worker.run_once() is True

    assert len(crm.calls) == 1
    assert len(crm.state.records) == 1
    delivery = await get_delivery(client, inquiry_id)
    assert delivery["status"] == "delivered"
    assert delivery["attempt_count"] == 1
    async with session_factory() as session:
        stray_job = await session.get(Job, stray.job.id)
    assert stray_job is not None
    assert stray_job.status is JobStatus.SUCCEEDED
    assert stray_job.result == {"delivery_status": "delivered", "repeated": True}


async def test_repeat_inquiries_from_one_email_share_a_contact(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = SimulatedCRMProvider()
    worker = delivery_worker(session_factory, settings, crm)
    first = await create_confirmed(client, purchase_body(email="Jane.Doe@example.com"))
    second = await create_confirmed(
        client, handoff_body(contact={"name": "Jane D.", "email": "jane.doe@example.com"})
    )

    await worker.run_once()
    await worker.run_once()

    one = await get_delivery(client, first)
    two = await get_delivery(client, second)
    assert one["crm_contact_id"] == two["crm_contact_id"]
    assert one["crm_record_id"] != two["crm_record_id"]
    assert len(crm.state.contacts) == 1
    assert len(crm.state.records) == 2


async def test_delivery_records_the_mode_it_ran_in_and_no_contact_data_in_job_rows(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    worker = delivery_worker(session_factory, settings, SimulatedCRMProvider())
    inquiry_id = await create_confirmed(client, purchase_body())
    await worker.run_once()

    row = await delivery_row(session_factory, inquiry_id)
    job = await delivery_job(session_factory, inquiry_id)

    assert row.crm_mode == "simulated"
    assert row.idempotency_key == f"inquiry:{inquiry_id}"
    assert job.payload == {"inquiry_id": inquiry_id}
    assert "jane.doe@example.com" not in str(job.result)
