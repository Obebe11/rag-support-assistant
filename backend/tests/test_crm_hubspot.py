"""The HubSpot provider against an in-memory fake of the HubSpot API.

No test here talks to HubSpot. The fake follows the documented request and
response shapes of API version 2026-09; a live account may still behave
differently, which is why the provider is labeled as not verified live.
"""

import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import CRMProviderMode, Settings
from app.core.db import SessionFactory
from app.models.enums import InquiryKind
from app.providers import factory
from app.providers.crm.access import CRMAccessMonitor
from app.providers.crm.base import LeadContact, LeadPayload
from app.providers.crm.hubspot import (
    HubSpotCRMProvider,
    contact_properties,
    note_body,
    split_name,
)
from app.providers.errors import ProviderError
from app.providers.factory import build_providers
from app.schemas.health import CRMAccessState
from tests.conftest import make_settings
from tests.inquiry_support import (
    api_client,
    create_confirmed,
    delivery_worker,
    get_delivery,
    handoff_body,
    make_jobs_due,
    purchase_body,
)

TOKEN = "test-hubspot-service-key"
V = "2026-09"
UPSERT = f"/crm/objects/{V}/contacts/batch/upsert"
NOTES = f"/crm/objects/{V}/notes"
NOTES_READ = f"/crm/objects/{V}/notes/batch/read"

type Outcome = httpx.Response | Exception


def _error(status: int, category: str, message: str, **extra: object) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "status": "error",
            "category": category,
            "message": message,
            "correlationId": "7b0c3f2a-1d4e-4f6a-9b8c-0d1e2f3a4b5c",
            **extra,
        },
    )


class FakeHubSpot:
    """Contacts, notes and their associations, with scripted failures."""

    def __init__(self) -> None:
        self.contacts: dict[str, dict[str, Any]] = {}
        self.notes: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.missing_properties: set[str] = set()
        self.properties_forbidden = False
        self.association_page_size = 500
        self._next_id = 1000
        self._scripted: list[tuple[str, str, Outcome, bool]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def provider(self, **kwargs: Any) -> HubSpotCRMProvider:
        return HubSpotCRMProvider(
            access_token=SecretStr(TOKEN), transport=self.transport(), **kwargs
        )

    def fail_once(self, method: str, path: str, outcome: Outcome, *, after: bool = False) -> None:
        """Make the next matching call fail.

        With `after`, HubSpot does the work first and the answer is lost.
        """
        self._scripted.append((method, path, outcome, after))

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [
            request
            for request in self.requests
            if request.method == method and request.url.path == path
        ]

    def _new_id(self) -> str:
        self._next_id += 1
        return str(self._next_id)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return _error(401, "INVALID_AUTHENTICATION", "Authentication credentials not found.")
        for index, (method, path, outcome, after) in enumerate(self._scripted):
            if method == request.method and path == request.url.path:
                del self._scripted[index]
                if after:
                    self._route(request)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        return self._route(request)

    def _route(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if (method, path) == ("GET", f"/account-info/{V}/details"):
            return httpx.Response(
                200,
                json={"portalId": 24680, "accountType": "DEVELOPER_TEST", "uiDomain": "app.x"},
            )
        if method == "GET" and path in (f"/crm/objects/{V}/contacts", NOTES):
            return httpx.Response(200, json={"results": []})
        if method == "GET" and path.startswith(f"/crm/properties/{V}/"):
            object_type, name = path.removeprefix(f"/crm/properties/{V}/").split("/")
            if self.properties_forbidden:
                return _error(403, "MISSING_SCOPES", "This app hasn't been granted all scopes.")
            if f"{object_type}.{name}" in self.missing_properties:
                return _error(404, "OBJECT_NOT_FOUND", f"Property {name} does not exist.")
            return httpx.Response(200, json={"name": name})
        if (method, path) == ("POST", UPSERT):
            return self._upsert(json.loads(request.content))
        if method == "GET" and path.endswith("/associations/notes"):
            return self._associations(path.split("/")[-3], request.url.params.get("after"))
        if (method, path) == ("POST", NOTES_READ):
            body = json.loads(request.content)
            assert body["propertiesWithHistory"] == []
            assert len(body["inputs"]) <= 100
            found = [self.notes[item["id"]] for item in body["inputs"] if item["id"] in self.notes]
            return httpx.Response(
                200,
                json={
                    "status": "COMPLETE",
                    "results": [
                        {"id": note["id"], "properties": note["properties"]} for note in found
                    ],
                },
            )
        if (method, path) == ("POST", NOTES):
            return self._create_note(json.loads(request.content))
        return _error(404, "NOT_FOUND", f"No route for {method} {path}")

    def _upsert(self, body: dict[str, Any]) -> httpx.Response:
        (item,) = body["inputs"]
        assert item["idProperty"] == "email"
        email = item["id"].lower()
        existing = next((c for c in self.contacts.values() if c["email"] == email), None)
        if existing is None:
            existing = {"id": self._new_id(), "email": email, "properties": {}}
            self.contacts[existing["id"]] = existing
            new = True
        else:
            new = False
        existing["properties"].update(item["properties"])
        return httpx.Response(
            200,
            json={
                "status": "COMPLETE",
                "results": [
                    {"id": existing["id"], "new": new, "properties": existing["properties"]}
                ],
            },
        )

    def _associations(self, contact_id: str, after: str | None) -> httpx.Response:
        note_ids = [note["id"] for note in self.notes.values() if note["contact_id"] == contact_id]
        start = int(after or 0)
        page = note_ids[start : start + self.association_page_size]
        body: dict[str, Any] = {
            "results": [
                {
                    "toObjectId": int(note_id),
                    "associationTypes": [
                        {"category": "HUBSPOT_DEFINED", "typeId": 201, "label": None}
                    ],
                }
                for note_id in page
            ]
        }
        if start + self.association_page_size < len(note_ids):
            body["paging"] = {"next": {"after": str(start + self.association_page_size)}}
        return httpx.Response(200, json=body)

    def _create_note(self, body: dict[str, Any]) -> httpx.Response:
        (association,) = body["associations"]
        assert association["types"] == [
            {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}
        ]
        contact_id = association["to"]["id"]
        assert contact_id in self.contacts
        assert set(body["properties"]) == {"hs_timestamp", "hs_note_body"}
        note = {"id": self._new_id(), "contact_id": contact_id, "properties": body["properties"]}
        self.notes[note["id"]] = note
        return httpx.Response(201, json={"id": note["id"], "properties": note["properties"]})

    def add_note(self, contact_id: str, text: str) -> None:
        note_id = self._new_id()
        self.notes[note_id] = {
            "id": note_id,
            "contact_id": contact_id,
            "properties": {"hs_note_body": text},
        }


def _lead(
    email: str = "jane.doe@example.com",
    *,
    inquiry: int = 1,
    kind: InquiryKind = InquiryKind.PURCHASE,
    **overrides: Any,
) -> LeadPayload:
    values: dict[str, Any] = {
        "inquiry_id": uuid.UUID(int=inquiry),
        "idempotency_key": f"inquiry:{uuid.UUID(int=inquiry)}",
        "kind": kind,
        "product": "Standing desk",
        "quantity": 20,
        "timeline": "by the end of March",
        "contact": LeadContact(
            name="Jane Doe", email=email, company="Acme Corp", phone="+1 555 010 2030"
        ),
        "notes": "Black frame preferred.",
        "confirmed_at": datetime(2026, 11, 11, 18, 40, 12, 345678, tzinfo=UTC),
    }
    values.update(overrides)
    return LeadPayload(**values)


@pytest.fixture
def hubspot() -> FakeHubSpot:
    return FakeHubSpot()


# --- Delivery -------------------------------------------------------------------


async def test_new_contact_and_note_are_created(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()

    result = await crm.deliver_lead(_lead())

    (contact,) = hubspot.contacts.values()
    (note,) = hubspot.notes.values()
    assert (result.contact_id, result.record_id) == (contact["id"], note["id"])
    assert result.details == {
        "record_type": "note",
        "contact_created": True,
        "record_created": True,
        "api_version": "2026-09",
    }
    assert contact["properties"] == {
        "email": "jane.doe@example.com",
        "firstname": "Jane",
        "lastname": "Doe",
        "company": "Acme Corp",
        "phone": "+1 555 010 2030",
    }
    assert note["contact_id"] == contact["id"]
    assert note["properties"]["hs_timestamp"] == "2026-11-11T18:40:12.345Z"
    body = note["properties"]["hs_note_body"]
    for expected in (
        "Purchase inquiry",
        "Product: Standing desk",
        "Quantity: 20",
        "Timeline: by the end of March",
        "Notes: Black frame preferred.",
        "Reference: inquiry:00000000-0000-0000-0000-000000000001",
    ):
        assert expected in body
    assert [request.url.path for request in hubspot.requests] == [UPSERT, NOTES]
    assert all(
        request.headers["Authorization"] == f"Bearer {TOKEN}" for request in hubspot.requests
    )
    await crm.aclose()


async def test_existing_contact_is_updated_not_duplicated(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()
    first = await crm.deliver_lead(_lead(inquiry=1))

    second = await crm.deliver_lead(
        _lead(
            "Jane.Doe@example.com",
            inquiry=2,
            contact=LeadContact(name="Jane Doe", email="Jane.Doe@example.com", phone="+1 555 777"),
        )
    )

    assert second.contact_id == first.contact_id
    assert second.record_id != first.record_id
    assert second.details["contact_created"] is False
    (contact,) = hubspot.contacts.values()
    assert contact["properties"]["phone"] == "+1 555 777"
    assert contact["properties"]["company"] == "Acme Corp", "an empty value never blanks a field"
    assert len(hubspot.notes) == 2


async def test_repeated_delivery_finds_the_note_and_creates_nothing(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()
    first = await crm.deliver_lead(_lead())

    repeat = await crm.deliver_lead(_lead(attempt=2))

    assert (repeat.contact_id, repeat.record_id) == (first.contact_id, first.record_id)
    assert repeat.details["record_created"] is False
    assert len(hubspot.contacts) == 1
    assert len(hubspot.notes) == 1
    assert len(hubspot.calls("POST", NOTES)) == 1


async def test_handoff_is_saved_as_a_note_with_the_question(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()
    lead = _lead(
        kind=InquiryKind.HANDOFF,
        product=None,
        quantity=None,
        timeline=None,
        notes="Do you offer on-site assembly in Alaska?",
        contact=LeadContact(name="Sam", email="sam.lee@example.com"),
    )

    await crm.deliver_lead(lead)

    (contact,) = hubspot.contacts.values()
    (note,) = hubspot.notes.values()
    assert contact["properties"] == {"email": "sam.lee@example.com", "firstname": "Sam"}
    body = note["properties"]["hs_note_body"]
    assert "Human handoff request" in body
    assert "Question: Do you offer on-site assembly in Alaska?" in body
    assert "Product" not in body
    assert "Quantity" not in body


def test_note_body_escapes_visitor_input() -> None:
    lead = _lead(product='<script>alert("x")</script>', notes="a < b & c")

    body = note_body(lead)

    assert "<script>" not in body
    assert "&lt;script&gt;" in body
    assert "a &lt; b &amp; c" in body


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jane Doe", ("Jane", "Doe")),
        ("Jane", ("Jane", None)),
        ("  Ana María  de la Cruz ", ("Ana", "María  de la Cruz")),
    ],
)
def test_name_is_split_into_first_and_last(name: str, expected: tuple[str, str | None]) -> None:
    assert split_name(name) == expected


def test_contact_properties_leave_out_empty_values() -> None:
    lead = _lead(contact=LeadContact(name="Jane", email="jane@example.com"))

    assert contact_properties(lead) == {"email": "jane@example.com", "firstname": "Jane"}


# --- No duplicates after a failure in the middle --------------------------------


async def test_contact_saved_but_note_failed_then_retry_creates_one_of_each(
    hubspot: FakeHubSpot,
) -> None:
    crm = hubspot.provider()
    hubspot.fail_once("POST", NOTES, _error(503, "SERVICE_UNAVAILABLE", "Try again later."))

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())
    assert error.value.retryable is True
    assert (len(hubspot.contacts), len(hubspot.notes)) == (1, 0)

    result = await crm.deliver_lead(_lead(attempt=2))

    assert (len(hubspot.contacts), len(hubspot.notes)) == (1, 1)
    assert result.details == {
        "record_type": "note",
        "contact_created": False,
        "record_created": True,
        "api_version": "2026-09",
    }


async def test_note_saved_but_answer_lost_then_retry_reuses_the_note(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()
    hubspot.fail_once("POST", NOTES, httpx.ReadTimeout("timed out"), after=True)

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())
    assert error.value.retryable is True
    assert len(hubspot.notes) == 1, "HubSpot stored the note although the call timed out"

    result = await crm.deliver_lead(_lead(attempt=2))

    (note,) = hubspot.notes.values()
    assert result.record_id == note["id"]
    assert result.details["record_created"] is False
    assert len(hubspot.calls("POST", NOTES)) == 1


async def test_contact_saved_but_answer_lost_then_retry_keeps_one_contact(
    hubspot: FakeHubSpot,
) -> None:
    crm = hubspot.provider()
    hubspot.fail_once("POST", UPSERT, httpx.ReadTimeout("timed out"), after=True)

    with pytest.raises(ProviderError):
        await crm.deliver_lead(_lead())
    await crm.deliver_lead(_lead(attempt=2))

    assert (len(hubspot.contacts), len(hubspot.notes)) == (1, 1)


async def test_note_of_this_inquiry_is_found_among_many_other_notes(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()
    first = await crm.deliver_lead(_lead(inquiry=1))
    for number in range(230):
        hubspot.add_note(first.contact_id, f"<p>Call log {number}</p>")
    hubspot.association_page_size = 100

    repeat = await crm.deliver_lead(_lead(inquiry=1, attempt=2))
    other = await crm.deliver_lead(_lead(inquiry=2))

    assert repeat.record_id == first.record_id
    assert other.record_id != first.record_id
    assert len(hubspot.notes) == 232
    listing = [r for r in hubspot.requests if r.url.path.endswith("/associations/notes")]
    assert [request.url.params.get("after") for request in listing[:3]] == [None, "100", "200"]
    assert len(hubspot.calls("POST", NOTES_READ)) == 6, "two lookups of three batches each"


# --- Errors ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "retryable", "summary"),
    [
        (_error(401, "INVALID_AUTHENTICATION", "Token expired."), False, "rejected the access"),
        (_error(403, "MISSING_SCOPES", "Missing scopes."), False, "lacks a required scope"),
        (_error(400, "VALIDATION_ERROR", "Property values were not valid."), False, "rejected"),
        (_error(404, "OBJECT_NOT_FOUND", "Not found."), False, "rejected the request"),
        (_error(409, "CONFLICT", "Conflict."), False, "rejected the request"),
        (
            _error(429, "RATE_LIMITS", "Rate limit hit.", policyName="TEN_SECONDLY_ROLLING"),
            True,
            "rate limit reached",
        ),
        (_error(423, "LOCKED", "Locked."), True, "temporarily unavailable"),
        (_error(477, "MIGRATION_IN_PROGRESS", "Migrating."), True, "temporarily unavailable"),
        (_error(500, "INTERNAL_ERROR", "Oops."), True, "temporarily unavailable"),
        (httpx.Response(502, text="<html>Bad Gateway</html>"), True, "temporarily unavailable"),
        (_error(503, "SERVICE_UNAVAILABLE", "Down."), True, "temporarily unavailable"),
        (httpx.Response(504, text=""), True, "temporarily unavailable"),
    ],
    ids=lambda value: str(value.status_code) if isinstance(value, httpx.Response) else None,
)
async def test_http_errors_are_classified(
    hubspot: FakeHubSpot, response: httpx.Response, retryable: bool, summary: str
) -> None:
    crm = hubspot.provider()
    hubspot.fail_once("POST", UPSERT, response)

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())

    assert error.value.retryable is retryable
    assert summary in str(error.value)
    assert f"HTTP {response.status_code}" in str(error.value)
    assert hubspot.contacts == {}


@pytest.mark.parametrize(
    ("failure", "text"),
    [
        (httpx.ReadTimeout("timed out"), "did not answer within 10 seconds"),
        (httpx.ConnectTimeout("timed out"), "did not answer within 10 seconds"),
        (httpx.ConnectError("no route"), "Could not reach HubSpot"),
        (httpx.RemoteProtocolError("closed"), "Could not reach HubSpot"),
    ],
    ids=["read-timeout", "connect-timeout", "connect-error", "protocol-error"],
)
async def test_timeouts_and_connection_problems_are_retryable(
    hubspot: FakeHubSpot, failure: Exception, text: str
) -> None:
    crm = hubspot.provider()
    hubspot.fail_once("POST", UPSERT, failure)

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())

    assert error.value.retryable is True
    assert text in str(error.value)


async def test_rate_limit_error_names_the_policy(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()
    hubspot.fail_once("POST", UPSERT, _error(429, "RATE_LIMITS", "Too many.", policyName="DAILY"))

    with pytest.raises(ProviderError, match=r"HTTP 429: RATE_LIMITS: DAILY: Too many\."):
        await crm.deliver_lead(_lead())


async def test_multi_status_upsert_without_a_result_is_a_permanent_error(
    hubspot: FakeHubSpot,
) -> None:
    crm = hubspot.provider()
    hubspot.fail_once(
        "POST",
        UPSERT,
        httpx.Response(
            207,
            json={
                "status": "COMPLETE",
                "results": [],
                "numErrors": 1,
                "errors": [
                    {
                        "status": "error",
                        "category": "VALIDATION_ERROR",
                        "message": "Email address jane.doe@example.com is invalid",
                    }
                ],
            },
        ),
    )

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())

    assert error.value.retryable is False
    assert "VALIDATION_ERROR: Email address [email] is invalid" in str(error.value)


async def test_unreadable_success_response_is_retryable(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()
    hubspot.fail_once("POST", UPSERT, httpx.Response(200, text="not json"))

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())

    assert error.value.retryable is True


async def test_errors_never_contain_the_token_or_an_email(
    hubspot: FakeHubSpot, caplog: pytest.LogCaptureFixture
) -> None:
    crm = hubspot.provider()
    hubspot.fail_once(
        "POST",
        UPSERT,
        _error(
            400,
            "VALIDATION_ERROR",
            f"Contact jane.doe@example.com rejected for key {TOKEN}. " + "x" * 1000,
        ),
    )

    with caplog.at_level(logging.DEBUG), pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())

    message = str(error.value)
    assert TOKEN not in message
    assert "jane.doe@example.com" not in message
    assert "[email]" in message
    assert "[token]" in message
    assert len(message) < 600
    assert "HubSpot reference 7b0c3f2a-1d4e-4f6a-9b8c-0d1e2f3a4b5c" in message
    assert TOKEN not in caplog.text
    assert TOKEN not in repr(crm.__dict__)


async def test_errors_never_contain_the_contact_name_company_or_phone(
    hubspot: FakeHubSpot,
) -> None:
    crm = hubspot.provider()
    hubspot.fail_once(
        "POST",
        UPSERT,
        _error(
            400,
            "VALIDATION_ERROR",
            'Property values were not valid: firstname "Jane", lastname "Doe", '
            "phone +1 555 010 2030 of Acme Corp (Jane Doe).",
        ),
    )

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())

    message = str(error.value)
    assert error.value.retryable is False
    for detail in ("Jane", "Doe", "+1 555 010 2030", "Acme Corp"):
        assert detail not in message
    assert "[contact detail]" in message
    assert message.startswith("HubSpot rejected the request while saving the contact")


async def test_wrong_token_is_a_permanent_error() -> None:
    hubspot = FakeHubSpot()
    crm = HubSpotCRMProvider(access_token=SecretStr("wrong"), transport=hubspot.transport())

    with pytest.raises(ProviderError) as error:
        await crm.deliver_lead(_lead())

    assert error.value.retryable is False
    assert "Check HUBSPOT_ACCESS_TOKEN" in str(error.value)


# --- Access check ---------------------------------------------------------------


async def test_access_check_passes_and_only_reads(hubspot: FakeHubSpot) -> None:
    crm = hubspot.provider()

    check = await crm.check_access()

    assert check.ok is True
    assert check.message == (
        "HubSpot account 24680 (DEVELOPER_TEST): contacts, notes and the required "
        "properties are available."
    )
    assert {request.method for request in hubspot.requests} == {"GET"}
    assert sorted(request.url.path for request in hubspot.requests) == sorted(
        [
            f"/account-info/{V}/details",
            f"/crm/objects/{V}/contacts",
            f"/crm/objects/{V}/notes",
            *(
                f"/crm/properties/{V}/contacts/{name}"
                for name in ("email", "firstname", "lastname", "phone", "company")
            ),
            f"/crm/properties/{V}/notes/hs_timestamp",
            f"/crm/properties/{V}/notes/hs_note_body",
        ]
    )


async def test_access_check_reports_missing_properties(hubspot: FakeHubSpot) -> None:
    hubspot.missing_properties = {"contacts.company", "notes.hs_note_body"}

    check = await hubspot.provider().check_access()

    assert check.ok is False
    assert check.message is not None
    assert "required properties are missing: contacts.company, notes.hs_note_body" in check.message


async def test_access_check_passes_when_property_definitions_cannot_be_read(
    hubspot: FakeHubSpot,
) -> None:
    hubspot.properties_forbidden = True

    check = await hubspot.provider().check_access()

    assert check.ok is True
    assert check.message is not None
    assert "Property definitions were not checked" in check.message


@pytest.mark.parametrize(
    ("path", "response", "text"),
    [
        (
            f"/account-info/{V}/details",
            _error(401, "INVALID_AUTHENTICATION", "The token is invalid."),
            "rejected the access token",
        ),
        (
            f"/crm/objects/{V}/contacts",
            _error(403, "MISSING_SCOPES", "Missing scopes."),
            "while reading contacts",
        ),
        (
            f"/crm/objects/{V}/notes",
            _error(403, "MISSING_SCOPES", "Missing scopes."),
            "while reading notes",
        ),
        (f"/account-info/{V}/details", httpx.ConnectError("offline"), "Could not reach HubSpot"),
    ],
    ids=["bad-token", "no-contacts-scope", "no-notes-scope", "offline"],
)
async def test_failed_access_check_is_reported_by_the_monitor(
    hubspot: FakeHubSpot, path: str, response: Outcome, text: str
) -> None:
    hubspot.fail_once("GET", path, response)
    monitor = CRMAccessMonitor(hubspot.provider())

    snapshot = await monitor.refresh()

    assert snapshot.state is CRMAccessState.FAILED
    assert snapshot.message is not None
    assert text in snapshot.message
    assert TOKEN not in snapshot.message


# --- Configuration --------------------------------------------------------------


def test_provider_is_built_from_settings() -> None:
    settings = make_settings(
        "postgresql+asyncpg://unused@localhost/unused",
        crm_provider=CRMProviderMode.HUBSPOT,
        hubspot_access_token=SecretStr(TOKEN),
        hubspot_base_url="https://hubspot.test",
        hubspot_api_version="2027-03",
        hubspot_timeout_seconds=3,
    )

    crm = build_providers(settings).crm

    assert isinstance(crm, HubSpotCRMProvider)
    assert crm.live is True
    assert str(crm._client.base_url) == "https://hubspot.test"
    assert crm._objects("notes", "/batch/read") == "/crm/objects/2027-03/notes/batch/read"
    assert crm._client.timeout == httpx.Timeout(3)
    assert "Authorization" not in crm._client.headers


def test_api_version_must_be_a_date_based_version() -> None:
    with pytest.raises(ValueError, match="hubspot_api_version"):
        make_settings("postgresql+asyncpg://unused@localhost/unused", hubspot_api_version="v3")


# --- Through the worker ---------------------------------------------------------


@pytest.mark.usefixtures("session_factory")
@pytest.mark.parametrize("body_factory", [purchase_body, handoff_body], ids=["purchase", "handoff"])
async def test_worker_delivers_to_hubspot_and_retries_without_duplicates(
    session_factory: SessionFactory,
    settings: Settings,
    hubspot: FakeHubSpot,
    body_factory: Callable[[], dict[str, Any]],
) -> None:
    hubspot.fail_once("POST", NOTES, httpx.ReadTimeout("timed out"), after=True)
    worker = delivery_worker(session_factory, settings, hubspot.provider())
    async with api_client(
        settings, crm_provider=CRMProviderMode.HUBSPOT, hubspot_access_token=SecretStr(TOKEN)
    ) as client:
        inquiry_id = await create_confirmed(client, body_factory())
        await worker.run_once()
        waiting = await get_delivery(client, inquiry_id)
        await make_jobs_due(session_factory)
        await worker.run_once()
        delivered = await get_delivery(client, inquiry_id)

    assert waiting["status"] == "pending"
    assert "did not answer within 10 seconds while saving the inquiry note" in waiting["last_error"]
    assert delivered["status"] == "delivered"
    assert (delivered["crm_mode"], delivered["live"]) == ("hubspot", True)
    (contact,) = hubspot.contacts.values()
    (note,) = hubspot.notes.values()
    assert (delivered["crm_contact_id"], delivered["crm_record_id"]) == (contact["id"], note["id"])
    assert f"Reference: inquiry:{inquiry_id}" in note["properties"]["hs_note_body"]
    assert [a["outcome"] for a in delivered["attempts"]] == ["failed", "succeeded"]


@pytest.mark.usefixtures("session_factory")
async def test_rejected_token_fails_the_delivery_at_once(
    session_factory: SessionFactory, settings: Settings
) -> None:
    hubspot = FakeHubSpot()
    crm = HubSpotCRMProvider(access_token=SecretStr("revoked"), transport=hubspot.transport())
    worker = delivery_worker(session_factory, settings, crm)
    async with api_client(
        settings, crm_provider=CRMProviderMode.HUBSPOT, hubspot_access_token=SecretStr("revoked")
    ) as client:
        inquiry_id = await create_confirmed(client, purchase_body())
        await worker.run_once()
        delivery = await get_delivery(client, inquiry_id)

    assert (delivery["status"], delivery["failure_reason"]) == ("failed", "permanent_error")
    assert "HubSpot rejected the access token" in delivery["last_error"]
    assert "revoked" not in delivery["last_error"]
    assert "jane.doe@example.com" not in delivery["last_error"]
    assert hubspot.contacts == {}


@pytest.mark.usefixtures("session_factory")
@pytest.mark.parametrize(
    ("status", "category", "summary"),
    [
        (429, "RATE_LIMITS", "HubSpot rate limit reached"),
        (502, "BAD_GATEWAY", "HubSpot is temporarily unavailable"),
        (503, "SERVICE_UNAVAILABLE", "HubSpot is temporarily unavailable"),
    ],
    ids=["429", "502", "503"],
)
async def test_temporary_hubspot_errors_are_retried_after_the_backoff(
    session_factory: SessionFactory,
    settings: Settings,
    hubspot: FakeHubSpot,
    status: int,
    category: str,
    summary: str,
) -> None:
    hubspot.fail_once("POST", UPSERT, _error(status, category, "Try again later."))
    worker = delivery_worker(session_factory, settings, hubspot.provider())
    async with api_client(
        settings, crm_provider=CRMProviderMode.HUBSPOT, hubspot_access_token=SecretStr(TOKEN)
    ) as client:
        inquiry_id = await create_confirmed(client, purchase_body())
        await worker.run_once()
        waiting = await get_delivery(client, inquiry_id)
        ran_before_the_backoff_passed = await worker.run_once()
        await make_jobs_due(session_factory)
        await worker.run_once()
        delivered = await get_delivery(client, inquiry_id)

    assert (waiting["status"], waiting["failure_reason"]) == ("pending", None)
    assert f"{summary} while saving the contact (HTTP {status}:" in waiting["last_error"]
    # The first retry waits for the configured base delay.
    wait = datetime.fromisoformat(waiting["next_attempt_at"]) - datetime.fromisoformat(
        waiting["attempts"][0]["finished_at"]
    )
    assert wait == timedelta(seconds=settings.job_backoff_base_seconds)
    assert ran_before_the_backoff_passed is False
    assert delivered["status"] == "delivered"
    assert [a["outcome"] for a in delivered["attempts"]] == ["failed", "succeeded"]
    assert (len(hubspot.contacts), len(hubspot.notes)) == (1, 1)


@pytest.mark.usefixtures("session_factory")
@pytest.mark.parametrize(
    ("path", "status", "category", "message", "summary"),
    [
        (
            UPSERT,
            400,
            "VALIDATION_ERROR",
            "Property values were not valid: jane.doe@example.com for Jane Doe of Acme Corp, "
            "phone +1 555 010 2030.",
            "HubSpot rejected the request",
        ),
        (
            NOTES,
            403,
            "MISSING_SCOPES",
            "This app hasn't been granted all required scopes.",
            "HubSpot denied access",
        ),
    ],
    ids=["400-on-the-contact", "403-on-the-note"],
)
async def test_permanent_hubspot_errors_fail_at_once_and_a_manual_retry_delivers(
    session_factory: SessionFactory,
    settings: Settings,
    hubspot: FakeHubSpot,
    path: str,
    status: int,
    category: str,
    message: str,
    summary: str,
) -> None:
    hubspot.fail_once("POST", path, _error(status, category, message))
    worker = delivery_worker(session_factory, settings, hubspot.provider())
    async with api_client(
        settings, crm_provider=CRMProviderMode.HUBSPOT, hubspot_access_token=SecretStr(TOKEN)
    ) as client:
        inquiry_id = await create_confirmed(client, purchase_body())
        await worker.run_once()
        failed = await get_delivery(client, inquiry_id)
        await make_jobs_due(session_factory)
        retried_on_its_own = await worker.run_once()

        # The cause is fixed on the HubSpot side; a person asks for another attempt.
        retry = await client.post(f"/api/inquiries/{inquiry_id}/delivery/retry")
        await worker.run_once()
        delivered = await get_delivery(client, inquiry_id)

    assert (failed["status"], failed["failure_reason"]) == ("failed", "permanent_error")
    assert (failed["attempt_count"], failed["next_attempt_at"]) == (1, None)
    assert f"{summary} while" in failed["last_error"]
    assert f"(HTTP {status}: {category}" in failed["last_error"]
    for stored in (failed["last_error"], failed["attempts"][0]["error"]):
        for private in (TOKEN, "jane.doe@example.com", "Jane Doe", "Acme Corp", "555 010 2030"):
            assert private not in stored
    assert retried_on_its_own is False
    assert retry.status_code == 202
    assert delivered["status"] == "delivered"
    assert [a["outcome"] for a in delivered["attempts"]] == ["failed", "succeeded"]
    assert (len(hubspot.contacts), len(hubspot.notes)) == (1, 1)


@pytest.mark.parametrize(
    ("token", "health_status", "access_state", "message"),
    [
        (TOKEN, "ok", "ok", "HubSpot"),
        ("revoked-service-key", "degraded", "failed", "HubSpot rejected the access token"),
    ],
    ids=["valid-token", "rejected-token"],
)
async def test_the_access_check_at_startup_is_reported_by_health(
    settings: Settings,
    hubspot: FakeHubSpot,
    monkeypatch: pytest.MonkeyPatch,
    token: str,
    health_status: str,
    access_state: str,
    message: str,
) -> None:
    """The real startup path: the provider is built from settings and checked before serving."""

    class WiredHubSpot(HubSpotCRMProvider):
        @classmethod
        def from_settings(cls, settings: Settings) -> "WiredHubSpot":
            assert settings.hubspot_access_token is not None
            return cls(access_token=settings.hubspot_access_token, transport=hubspot.transport())

    monkeypatch.setitem(factory.CRM_PROVIDERS, CRMProviderMode.HUBSPOT, WiredHubSpot)
    async with api_client(
        settings,
        crm_provider=CRMProviderMode.HUBSPOT,
        hubspot_access_token=SecretStr(token),
        crm_access_check_enabled=True,
    ) as client:
        checked_at_startup = len(hubspot.requests)
        health = await client.get("/api/health")
        conversation = await client.post("/api/conversations")

    body = health.json()
    crm = body["providers"]["crm"]
    assert checked_at_startup > 0
    assert health.status_code == 200
    assert body["status"] == health_status
    assert (crm["mode"], crm["live"]) == ("hubspot", True)
    assert crm["access"]["state"] == access_state
    assert message in crm["access"]["message"]
    assert token not in health.text
    # A failed check does not stop the API: visitors can still talk to the assistant.
    assert conversation.status_code == 201
