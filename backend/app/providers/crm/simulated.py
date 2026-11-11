"""Simulated CRM mode: no network calls, clearly labeled as not a real CRM.

Owner: T4.

The simulated CRM keeps contacts and records in the memory of the process that
delivers (the worker). Record IDs are derived from the contact email and the
idempotency key, so the same inquiry always gets the same IDs, also after a
restart.

Failure triggers
----------------
A tag in the contact email makes deliveries fail on purpose, to show error
statuses and retries without a real CRM:

- `name+fail2@example.com`: the first 2 attempts fail with a temporary error,
  the third succeeds. `+fail` without a number fails every attempt.
- `name+reject1@example.com`: the first attempt fails with a permanent error,
  the next one (a manual retry) succeeds. `+reject` rejects every attempt.

The tags work in simulated mode only. Other providers treat them as ordinary
plus-addressing.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import ClassVar, Self

from app.core.config import CRMProviderMode, Settings
from app.providers.crm.base import CRMAccessCheck, CRMProvider, LeadPayload, LeadResult
from app.providers.errors import ProviderError

_FAILURE_TAG = re.compile(r"\+(?P<kind>fail|reject)(?P<count>\d*)@", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SimulatedFailure:
    retryable: bool
    attempts: int | None
    """How many first attempts fail; None means every attempt."""


def simulated_failure_for(email: str) -> SimulatedFailure | None:
    """Read the failure trigger from a contact email, if it has one."""
    match = _FAILURE_TAG.search(email)
    if match is None:
        return None
    count = match.group("count")
    return SimulatedFailure(
        retryable=match.group("kind").lower() == "fail",
        attempts=int(count) if count else None,
    )


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:12]}"


@dataclass(slots=True)
class SimulatedContact:
    id: str
    email: str
    name: str
    company: str | None = None
    phone: str | None = None


@dataclass(slots=True)
class SimulatedRecord:
    id: str
    contact_id: str
    idempotency_key: str
    lead: LeadPayload


@dataclass(slots=True)
class SimulatedCRMState:
    contacts: dict[str, SimulatedContact] = field(default_factory=dict)
    """By lowercase email: one contact per email."""
    records: dict[str, SimulatedRecord] = field(default_factory=dict)
    """By idempotency key: one record per confirmed inquiry."""


class SimulatedCRMProvider(CRMProvider):
    mode: ClassVar[CRMProviderMode] = CRMProviderMode.SIMULATED
    live: ClassVar[bool] = False

    def __init__(self) -> None:
        self.state = SimulatedCRMState()

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls()

    async def check_access(self) -> CRMAccessCheck:
        return CRMAccessCheck(
            ok=True, message="Simulated CRM: no external account is checked or written to."
        )

    async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
        failure = simulated_failure_for(lead.contact.email)
        if failure is not None and (failure.attempts is None or lead.attempt <= failure.attempts):
            if failure.retryable:
                raise ProviderError(
                    "Simulated CRM: temporary failure requested by the +fail tag "
                    f"(attempt {lead.attempt}).",
                    retryable=True,
                )
            raise ProviderError(
                "Simulated CRM: the request was rejected, as requested by the +reject tag "
                f"(attempt {lead.attempt}).",
                retryable=False,
            )

        email_key = lead.contact.email.lower()
        contact = self.state.contacts.get(email_key)
        contact_created = contact is None
        if contact is None:
            contact = SimulatedContact(
                id=_stable_id("sim-contact", email_key),
                email=lead.contact.email,
                name=lead.contact.name,
            )
            self.state.contacts[email_key] = contact
        contact.name = lead.contact.name
        contact.company = lead.contact.company or contact.company
        contact.phone = lead.contact.phone or contact.phone

        record = self.state.records.get(lead.idempotency_key)
        record_created = record is None
        if record is None:
            record = SimulatedRecord(
                id=_stable_id("sim-record", lead.idempotency_key),
                contact_id=contact.id,
                idempotency_key=lead.idempotency_key,
                lead=lead,
            )
            self.state.records[lead.idempotency_key] = record

        return LeadResult(
            contact_id=contact.id,
            record_id=record.id,
            details={
                "simulated": True,
                "record_type": "simulated_record",
                "contact_created": contact_created,
                "record_created": record_created,
            },
        )
