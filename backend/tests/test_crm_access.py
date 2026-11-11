"""The CRM access check: run at startup, remembered, reported by /api/health."""

import asyncio
from typing import ClassVar, Self

import httpx
import pytest

from app.core.config import CRMProviderMode, Settings
from app.main import create_app
from app.providers.crm.access import CRMAccessMonitor
from app.providers.crm.base import CRMAccessCheck, CRMProvider, LeadPayload, LeadResult
from app.providers.errors import ProviderError
from app.schemas.health import CRMAccessState
from tests.inquiry_support import api_client


class CheckedCRM(CRMProvider):
    """A CRM whose access check returns scripted results."""

    mode: ClassVar[CRMProviderMode] = CRMProviderMode.HUBSPOT
    live: ClassVar[bool] = True

    def __init__(self, *results: CRMAccessCheck | BaseException | float) -> None:
        self.results = list(results)
        self.checks = 0

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls()

    async def check_access(self) -> CRMAccessCheck:
        self.checks += 1
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, float):
            await asyncio.sleep(result)
            return CRMAccessCheck(ok=True)
        return result

    async def deliver_lead(self, lead: LeadPayload) -> LeadResult:
        raise NotImplementedError


async def test_monitor_starts_unchecked_and_remembers_a_passed_check() -> None:
    monitor = CRMAccessMonitor(CheckedCRM(CRMAccessCheck(ok=True, message="All good.")))
    assert monitor.snapshot().state is CRMAccessState.UNCHECKED
    await monitor.aclose()

    snapshot = await monitor.refresh()

    assert (snapshot.state, snapshot.message) == (CRMAccessState.OK, "All good.")
    assert snapshot.checked_at is not None
    assert monitor.snapshot() == snapshot


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (CRMAccessCheck(ok=False, message="Missing scope."), "Missing scope."),
        (
            ProviderError("The CRM rejected the token.", retryable=False),
            "The CRM rejected the token.",
        ),
        (RuntimeError("secret detail"), "The access check failed unexpectedly (RuntimeError)."),
        (5.0, "The CRM did not answer within 0.05 seconds."),
    ],
    ids=["not-ok", "provider-error", "crash", "timeout"],
)
async def test_failed_checks_never_raise(
    result: CRMAccessCheck | BaseException | float, message: str
) -> None:
    monitor = CRMAccessMonitor(CheckedCRM(result), timeout_seconds=0.05)

    snapshot = await monitor.refresh()

    assert (snapshot.state, snapshot.message) == (CRMAccessState.FAILED, message)


async def test_stale_result_is_refreshed_in_the_background() -> None:
    crm = CheckedCRM(CRMAccessCheck(ok=False, message="Down."), CRMAccessCheck(ok=True))
    monitor = CRMAccessMonitor(crm, interval_seconds=0.0)
    await monitor.refresh()

    stale = monitor.snapshot()
    await asyncio.sleep(0.05)
    fresh = monitor.snapshot()
    await monitor.aclose()

    assert stale.state is CRMAccessState.FAILED
    assert fresh.state is CRMAccessState.OK
    assert crm.checks >= 2


async def test_fresh_result_is_not_checked_again() -> None:
    crm = CheckedCRM(CRMAccessCheck(ok=True))
    monitor = CRMAccessMonitor(crm, interval_seconds=3600)
    await monitor.refresh()

    for _ in range(3):
        monitor.snapshot()
    await asyncio.sleep(0)

    assert crm.checks == 1


async def test_disabled_monitor_does_not_check_on_its_own() -> None:
    crm = CheckedCRM(CRMAccessCheck(ok=True))
    monitor = CRMAccessMonitor(crm, enabled=False)

    snapshot = monitor.snapshot()
    await asyncio.sleep(0)

    assert snapshot.state is CRMAccessState.UNCHECKED
    assert crm.checks == 0


async def test_health_reports_the_simulated_crm_check_at_startup(settings: Settings) -> None:
    async with api_client(settings, crm_access_check_enabled=True) as client:
        response = await client.get("/api/health")

    body = response.json()
    crm = body["providers"]["crm"]
    assert body["status"] == "ok"
    assert (crm["mode"], crm["live"]) == ("simulated", False)
    assert crm["access"]["state"] == "ok"
    assert "Simulated" in crm["access"]["message"]
    assert crm["access"]["checked_at"] is not None


async def test_health_is_degraded_when_the_crm_access_check_fails(settings: Settings) -> None:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        monitor = CRMAccessMonitor(
            CheckedCRM(CRMAccessCheck(ok=False, message="The token lacks a required scope.")),
            interval_seconds=3600,
        )
        await monitor.refresh()
        app.state.crm_access = monitor
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/api/health")

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "degraded"
    assert body["database"] == "ok"
    assert body["providers"]["crm"]["access"]["state"] == "failed"
    assert body["providers"]["crm"]["access"]["message"] == "The token lacks a required scope."
