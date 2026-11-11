"""Simulated CRM mode: no network calls, clearly labeled as not a real CRM.

Owner: T4.
"""

from typing import ClassVar, Self

from app.core.config import CRMProviderMode, Settings
from app.providers.crm.base import CRMAccessCheck, CRMProvider, LeadPayload, LeadResult
from app.providers.errors import ProviderNotImplementedError


class SimulatedCRMProvider(CRMProvider):
    mode: ClassVar[CRMProviderMode] = CRMProviderMode.SIMULATED
    live: ClassVar[bool] = False

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls()

    async def check_access(self) -> CRMAccessCheck:
        raise ProviderNotImplementedError("The simulated CRM provider")

    async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
        raise ProviderNotImplementedError("The simulated CRM provider")
