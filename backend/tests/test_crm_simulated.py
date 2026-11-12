"""The simulated CRM: offline, deterministic, labeled, with failure triggers."""

import uuid

import httpx
import pytest

from app.core.config import Settings
from app.core.db import SessionFactory
from app.models.enums import InquiryKind
from app.providers.crm.base import LeadContact, LeadPayload
from app.providers.crm.simulated import SimulatedCRMProvider, simulated_failure_for
from app.providers.errors import ProviderError
from tests.inquiry_support import (
    create_confirmed,
    delivery_worker,
    get_delivery,
    handoff_body,
    make_jobs_due,
    purchase_body,
)


def _lead(
    email: str = "jane.doe@example.com", *, attempt: int = 1, key: str = "inquiry:1"
) -> LeadPayload:
    return LeadPayload(
        inquiry_id=uuid.UUID(int=1),
        idempotency_key=key,
        kind=InquiryKind.PURCHASE,
        product="Standing desk",
        quantity=20,
        timeline="next month",
        contact=LeadContact(name="Jane Doe", email=email),
        attempt=attempt,
    )


async def test_simulated_crm_is_labeled_as_not_live() -> None:
    crm = SimulatedCRMProvider()

    check = await crm.check_access()
    result = await crm.deliver_lead(_lead())

    assert crm.live is False
    assert check.ok is True
    assert check.message is not None
    assert "Simulated" in check.message
    assert result.details["simulated"] is True


async def test_same_inquiry_always_gets_the_same_ids_even_after_a_restart() -> None:
    first = await SimulatedCRMProvider().deliver_lead(_lead())
    after_restart = await SimulatedCRMProvider().deliver_lead(_lead())
    other = await SimulatedCRMProvider().deliver_lead(_lead("sam.lee@example.com", key="inquiry:2"))

    assert (first.contact_id, first.record_id) == (
        after_restart.contact_id,
        after_restart.record_id,
    )
    assert first.contact_id.startswith("sim-contact-")
    assert first.record_id is not None
    assert first.record_id.startswith("sim-record-")
    assert other.contact_id != first.contact_id
    assert other.record_id != first.record_id


async def test_repeating_a_delivery_returns_the_existing_record() -> None:
    crm = SimulatedCRMProvider()

    first = await crm.deliver_lead(_lead())
    repeat = await crm.deliver_lead(_lead(attempt=2))

    assert (repeat.contact_id, repeat.record_id) == (first.contact_id, first.record_id)
    assert first.details["record_created"] is True
    assert repeat.details["record_created"] is False
    assert len(crm.state.contacts) == len(crm.state.records) == 1


@pytest.mark.parametrize(
    ("email", "retryable", "attempts"),
    [
        ("buyer+fail@example.com", True, None),
        ("buyer+fail2@example.com", True, 2),
        ("buyer+FAIL1@example.com", True, 1),
        ("buyer+reject@example.com", False, None),
        ("buyer+reject1@example.com", False, 1),
    ],
)
def test_failure_tags_are_read_from_the_contact_email(
    email: str, retryable: bool, attempts: int | None
) -> None:
    failure = simulated_failure_for(email)

    assert failure is not None
    assert (failure.retryable, failure.attempts) == (retryable, attempts)


@pytest.mark.parametrize(
    "email",
    [
        "buyer@example.com",
        "buyer+sales@example.com",
        "fail@example.com",
        "reject1@fail.example.com",
    ],
)
def test_ordinary_emails_do_not_trigger_a_failure(email: str) -> None:
    assert simulated_failure_for(email) is None


async def test_fail_tag_fails_the_first_attempts_only() -> None:
    crm = SimulatedCRMProvider()

    for attempt in (1, 2):
        with pytest.raises(ProviderError) as error:
            await crm.deliver_lead(_lead("buyer+fail2@example.com", attempt=attempt))
        assert error.value.retryable is True
    result = await crm.deliver_lead(_lead("buyer+fail2@example.com", attempt=3))

    assert result.record_id is not None
    assert len(crm.state.records) == 1


async def test_reject_tag_is_a_permanent_error() -> None:
    crm = SimulatedCRMProvider()

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead("buyer+reject@example.com", attempt=7))

    assert error.value.retryable is False
    assert crm.state.records == {}


@pytest.mark.usefixtures("session_factory")
async def test_fail_tag_shows_a_retry_and_then_a_delivery(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    """The demo path: error status, automatic retry, delivered."""
    crm = SimulatedCRMProvider()
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, purchase_body(email="buyer+fail1@example.com"))

    await worker.run_once()
    failed_once = await get_delivery(client, inquiry_id)
    await make_jobs_due(session_factory)
    await worker.run_once()
    delivered = await get_delivery(client, inquiry_id)

    assert failed_once["status"] == "pending"
    assert "temporary failure" in failed_once["last_error"]
    assert delivered["status"] == "delivered"
    assert len(crm.state.records) == 1


@pytest.mark.usefixtures("session_factory")
async def test_reject_tag_shows_a_permanent_error_and_a_manual_retry_delivers(
    client: httpx.AsyncClient, session_factory: SessionFactory, settings: Settings
) -> None:
    crm = SimulatedCRMProvider()
    worker = delivery_worker(session_factory, settings, crm)
    inquiry_id = await create_confirmed(client, handoff_body(email="visitor+reject1@example.com"))

    await worker.run_once()
    rejected = await get_delivery(client, inquiry_id)
    await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")
    await worker.run_once()
    delivered = await get_delivery(client, inquiry_id)

    assert (rejected["status"], rejected["failure_reason"]) == ("failed", "permanent_error")
    assert delivered["status"] == "delivered"
    assert len(crm.state.records) == 1
