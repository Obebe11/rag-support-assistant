"""HubSpot CRM provider: delivers confirmed inquiries to a HubSpot account.

Owner: T4. Not verified against a live HubSpot account: the behavior below
follows the official documentation and is tested with a mock transport only.
See docs/inquiries.md for the sources, the required scopes and the limits.

One delivery:

1. Create or update the contact by email with one batch upsert call.
2. Unless the contact is new, look for a note of this inquiry among the notes
   already associated with the contact. The note body carries the delivery's
   idempotency key, so a repeated delivery finds the note instead of adding one.
3. Otherwise create a note with the inquiry details, associated with the contact.

HubSpot has no idempotency key for record creation, so step 2 and step 3 are a
check followed by a create, not one atomic operation. The job queue runs one
delivery of an inquiry at a time, which closes that gap in normal operation.
"""

import asyncio
import html
import re
from datetime import UTC, datetime
from typing import Any, ClassVar, Self

import httpx
from pydantic import SecretStr

from app.core.config import CRMProviderMode, Settings
from app.models.enums import InquiryKind
from app.providers.crm.base import CRMAccessCheck, CRMProvider, LeadPayload, LeadResult
from app.providers.errors import ProviderError

NOTE_TO_CONTACT_ASSOCIATION_TYPE_ID = 202
ASSOCIATION_PAGE_SIZE = 500
MAX_ASSOCIATION_PAGES = 4
BATCH_READ_SIZE = 100
MAX_NOTES_CHECKED = 300
"""How many of the contact's newest notes are searched for an earlier delivery."""
MAX_ERROR_DETAIL_CHARS = 300

CONTACT_PROPERTIES = ("email", "firstname", "lastname", "phone", "company")
NOTE_PROPERTIES = ("hs_timestamp", "hs_note_body")
"""HubSpot default properties the integration writes. No custom property is needed."""

_RETRYABLE_STATUS = frozenset({408, 423, 429, 477})
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def split_name(name: str) -> tuple[str, str | None]:
    """Split a full name into HubSpot's first name and last name."""
    first, _, last = name.strip().partition(" ")
    return first, last.strip() or None


def contact_properties(lead: LeadPayload) -> dict[str, str]:
    """Contact properties to write. Empty values are left out, so an update
    never blanks what the CRM already knows."""
    first, last = split_name(lead.contact.name)
    values = {
        "email": lead.contact.email,
        "firstname": first,
        "lastname": last,
        "company": lead.contact.company,
        "phone": lead.contact.phone,
    }
    return {name: value for name, value in values.items() if value}


def note_body(lead: LeadPayload) -> str:
    """The note text, as HTML. Visitor input is escaped."""

    def row(label: str, value: object | None) -> str:
        return f"<li>{label}: {html.escape(str(value))}</li>" if value not in (None, "") else ""

    if lead.kind is InquiryKind.HANDOFF:
        title = "Human handoff request"
        details = row("Question", lead.notes)
    else:
        title = "Purchase inquiry"
        details = (
            row("Product", lead.product)
            + row("Quantity", lead.quantity)
            + row("Timeline", lead.timeline)
            + row("Notes", lead.notes)
        )
    contact = (
        row("Name", lead.contact.name)
        + row("Email", lead.contact.email)
        + row("Company", lead.contact.company)
        + row("Phone", lead.contact.phone)
    )
    return (
        f"<p><strong>{title}</strong> (confirmed by the visitor in the website chat)</p>"
        f"<ul>{details}</ul>"
        f"<p>Contact</p><ul>{contact}</ul>"
        f"<p>Reference: {html.escape(lead.idempotency_key)}</p>"
    )


def without_contact_details(text: str, lead: LeadPayload) -> str:
    """Replace the lead's name, company and phone in an error text."""
    first, last = split_name(lead.contact.name)
    values = {lead.contact.name.strip(), first, last, lead.contact.company, lead.contact.phone}
    for value in sorted((v for v in values if v and len(v) >= 2), key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(value)}(?!\w)", "[contact detail]", text)
    return text


def _hubspot_timestamp(moment: datetime | None) -> str:
    moment = (moment or datetime.now(UTC)).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


class HubSpotCRMProvider(CRMProvider):
    mode: ClassVar[CRMProviderMode] = CRMProviderMode.HUBSPOT
    live: ClassVar[bool] = True

    def __init__(
        self,
        *,
        access_token: SecretStr,
        base_url: str = "https://api.hubapi.com",
        api_version: str = "2026-09",
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._access_token = access_token
        self._api_version = api_version
        self._timeout_seconds = timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            transport=transport,
            headers={"Accept": "application/json"},
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        if settings.hubspot_access_token is None:
            raise ValueError("HUBSPOT_ACCESS_TOKEN is required for the hubspot CRM provider.")
        return cls(
            access_token=settings.hubspot_access_token,
            base_url=settings.hubspot_base_url,
            api_version=settings.hubspot_api_version,
            timeout_seconds=settings.hubspot_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- Paths ----------------------------------------------------------------

    def _objects(self, object_type: str, suffix: str = "") -> str:
        return f"/crm/objects/{self._api_version}/{object_type}{suffix}"

    def _property(self, object_type: str, name: str) -> str:
        return f"/crm/properties/{self._api_version}/{object_type}/{name}"

    # --- HTTP -----------------------------------------------------------------

    def _safe(self, text: str) -> str:
        """Error text that is safe to store and show: no token, no email addresses."""
        text = text.replace(self._access_token.get_secret_value(), "[token]")
        return _EMAIL.sub("[email]", text)[:MAX_ERROR_DETAIL_CHARS]

    def _error(self, response: httpx.Response, action: str) -> ProviderError:
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        parts = [str(body[key]) for key in ("category", "policyName", "message") if body.get(key)]
        detail = self._safe(": ".join(parts)) if parts else "no details"
        reference = body.get("correlationId")
        suffix = f" (HubSpot reference {reference})" if isinstance(reference, str) else ""
        retryable = status in _RETRYABLE_STATUS or status >= 500

        hint = ""
        if status == 401:
            summary = "HubSpot rejected the access token"
            hint = " Check HUBSPOT_ACCESS_TOKEN."
        elif status == 403:
            summary = "HubSpot denied access"
            hint = " The key probably lacks a required scope."
        elif status == 429:
            summary = "HubSpot rate limit reached"
        elif retryable:
            summary = "HubSpot is temporarily unavailable"
        else:
            summary = "HubSpot rejected the request"
        return ProviderError(
            f"{summary} while {action} (HTTP {status}: {detail}){suffix}.{hint}",
            retryable=retryable,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        action: str,
        json: Any = None,
        params: dict[str, str | int] | None = None,
    ) -> dict[str, Any]:
        """Call HubSpot and return the JSON object of a 2xx response.

        Every failure becomes a `ProviderError`: timeouts, connection problems,
        429, 423, 477 and 5xx are retryable; other 4xx responses are not.
        """
        try:
            response = await self._client.request(
                method,
                path,
                json=json,
                params=params,
                headers={"Authorization": f"Bearer {self._access_token.get_secret_value()}"},
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"HubSpot did not answer within {self._timeout_seconds:g} seconds while {action}.",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Could not reach HubSpot while {action} ({type(exc).__name__}).", retryable=True
            ) from exc
        if not response.is_success:
            raise self._error(response, action)
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"HubSpot returned an unreadable response while {action}.", retryable=True
            ) from exc
        if not isinstance(body, dict):
            raise ProviderError(
                f"HubSpot returned an unexpected response while {action}.", retryable=True
            )
        return body

    # --- Access check ---------------------------------------------------------

    async def check_access(self) -> CRMAccessCheck:
        """Verify the token, access to contacts and notes, and the fields written.

        Read-only. Write permission cannot be checked without writing; a missing
        write scope shows up as a permanent error of the first delivery.
        """
        account = await self._request(
            "GET",
            f"/account-info/{self._api_version}/details",
            action="reading the account details",
        )
        await self._request(
            "GET",
            self._objects("contacts"),
            params={"limit": 1, "properties": "email"},
            action="reading contacts",
        )
        await self._request(
            "GET",
            self._objects("notes"),
            params={"limit": 1, "properties": "hs_timestamp"},
            action="reading notes",
        )
        fields = [("contacts", name) for name in CONTACT_PROPERTIES] + [
            ("notes", name) for name in NOTE_PROPERTIES
        ]
        outcomes = await asyncio.gather(*(self._field_status(*field) for field in fields))
        missing = [
            f"{object_type}.{name}"
            for (object_type, name), status in zip(fields, outcomes, strict=True)
            if status == 404
        ]
        described = f"HubSpot account {account.get('portalId', 'unknown')}"
        if account.get("accountType"):
            described += f" ({account['accountType']})"
        if missing:
            return CRMAccessCheck(
                ok=False,
                message=f"{described}: required properties are missing: {', '.join(missing)}.",
            )
        if 403 in outcomes:
            return CRMAccessCheck(
                ok=True,
                message=f"{described}: contacts and notes are readable. Property definitions "
                "were not checked because the key cannot read them; the integration writes "
                "HubSpot default properties only.",
            )
        return CRMAccessCheck(
            ok=True,
            message=f"{described}: contacts, notes and the required properties are available.",
        )

    async def _field_status(self, object_type: str, name: str) -> int:
        """200 when the property exists, 404 when it does not, 403 when it cannot be read."""
        try:
            await self._request(
                "GET",
                self._property(object_type, name),
                action=f"reading the {object_type} property {name}",
            )
        except ProviderError as exc:
            for status in (403, 404):
                if f"(HTTP {status}:" in str(exc):
                    return status
            raise
        return 200

    # --- Delivery -------------------------------------------------------------

    async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
        try:
            return await self._deliver(lead)
        except ProviderError as exc:
            # HubSpot may quote a rejected value. The error is stored and shown,
            # so it must not carry the visitor's contact details.
            raise ProviderError(
                without_contact_details(str(exc), lead), retryable=exc.retryable
            ) from exc

    async def _deliver(self, lead: LeadPayload) -> LeadResult:
        contact_id, contact_created = await self._upsert_contact(lead)
        note_id = None if contact_created else await self._find_note(contact_id, lead)
        note_created = note_id is None
        if note_id is None:
            note_id = await self._create_note(contact_id, lead)
        return LeadResult(
            contact_id=contact_id,
            record_id=note_id,
            details={
                "record_type": "note",
                "contact_created": contact_created,
                "record_created": note_created,
                "api_version": self._api_version,
            },
        )

    async def _upsert_contact(self, lead: LeadPayload) -> tuple[str, bool]:
        action = "saving the contact"
        body = await self._request(
            "POST",
            self._objects("contacts", "/batch/upsert"),
            json={
                "inputs": [
                    {
                        "id": lead.contact.email,
                        "idProperty": "email",
                        "properties": contact_properties(lead),
                    }
                ]
            },
            action=action,
        )
        results = body.get("results")
        if not isinstance(results, list) or not results or not results[0].get("id"):
            # A 207 response carries the reason in `errors` and no result.
            errors = body.get("errors")
            first = errors[0] if isinstance(errors, list) and errors else {}
            detail = self._safe(
                ": ".join(str(first[key]) for key in ("category", "message") if first.get(key))
                or "no details"
            )
            raise ProviderError(
                f"HubSpot did not save the contact while {action} ({detail}).", retryable=False
            )
        return str(results[0]["id"]), bool(results[0].get("new"))

    async def _associated_note_ids(self, contact_id: str) -> list[str]:
        ids: list[str] = []
        after: str | None = None
        for _ in range(MAX_ASSOCIATION_PAGES):
            params: dict[str, str | int] = {"limit": ASSOCIATION_PAGE_SIZE}
            if after:
                params["after"] = after
            page = await self._request(
                "GET",
                self._objects("contacts", f"/{contact_id}/associations/notes"),
                params=params,
                action="listing the contact's notes",
            )
            for item in page.get("results") or []:
                note_id = item.get("toObjectId", item.get("id"))
                if note_id is not None:
                    ids.append(str(note_id))
            next_page = (page.get("paging") or {}).get("next") or {}
            after = next_page.get("after")
            if not after:
                break
        return ids

    async def _find_note(self, contact_id: str, lead: LeadPayload) -> str | None:
        """The note an earlier attempt created for this inquiry, if there is one."""
        note_ids = await self._associated_note_ids(contact_id)
        # Record IDs grow over time, so the highest IDs are the newest notes.
        newest = sorted(set(note_ids), key=lambda value: (len(value), value), reverse=True)
        newest = newest[:MAX_NOTES_CHECKED]
        for start in range(0, len(newest), BATCH_READ_SIZE):
            batch = await self._request(
                "POST",
                self._objects("notes", "/batch/read"),
                json={
                    "inputs": [
                        {"id": note_id} for note_id in newest[start : start + BATCH_READ_SIZE]
                    ],
                    "properties": ["hs_note_body"],
                    "propertiesWithHistory": [],
                },
                action="reading the contact's notes",
            )
            for note in batch.get("results") or []:
                text = (note.get("properties") or {}).get("hs_note_body") or ""
                if lead.idempotency_key in html.unescape(text):
                    return str(note["id"])
        return None

    async def _create_note(self, contact_id: str, lead: LeadPayload) -> str:
        action = "saving the inquiry note"
        body = await self._request(
            "POST",
            self._objects("notes"),
            json={
                "properties": {
                    "hs_timestamp": _hubspot_timestamp(lead.confirmed_at),
                    "hs_note_body": note_body(lead),
                },
                "associations": [
                    {
                        "to": {"id": contact_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": NOTE_TO_CONTACT_ASSOCIATION_TYPE_ID,
                            }
                        ],
                    }
                ],
            },
            action=action,
        )
        note_id = body.get("id")
        if not note_id:
            raise ProviderError(f"HubSpot returned no record ID while {action}.", retryable=True)
        return str(note_id)
