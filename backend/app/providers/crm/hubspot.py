"""HubSpot CRM provider: delivers confirmed inquiries to a HubSpot account.

Owner: T4.
"""

from typing import ClassVar, Self

from pydantic import SecretStr

from app.core.config import CRMProviderMode, Settings
from app.providers.crm.base import CRMAccessCheck, CRMProvider, LeadPayload, LeadResult
from app.providers.errors import ProviderNotImplementedError


class HubSpotCRMProvider(CRMProvider):
    mode: ClassVar[CRMProviderMode] = CRMProviderMode.HUBSPOT
    live: ClassVar[bool] = True

    def __init__(self, *, access_token: SecretStr) -> None:
        self._access_token = access_token

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        if settings.hubspot_access_token is None:
            raise ValueError("HUBSPOT_ACCESS_TOKEN is required for the hubspot CRM provider.")
        return cls(access_token=settings.hubspot_access_token)

    async def check_access(self) -> CRMAccessCheck:
        raise ProviderNotImplementedError("The HubSpot CRM provider")

    async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
        raise ProviderNotImplementedError("The HubSpot CRM provider")
