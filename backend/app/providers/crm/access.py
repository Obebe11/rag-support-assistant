"""Keeps the latest CRM access check result for `/api/health`.

Owner: T4.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from app.providers.crm.base import CRMProvider
from app.providers.errors import ProviderError
from app.schemas.health import CRMAccessState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CRMAccessSnapshot:
    state: CRMAccessState
    message: str | None = None
    checked_at: datetime | None = None


UNCHECKED = CRMAccessSnapshot(state=CRMAccessState.UNCHECKED)


class CRMAccessMonitor:
    """Runs `CRMProvider.check_access` and remembers the result.

    `refresh` never raises: a failed or timed-out check becomes a `failed`
    snapshot. `snapshot` returns the remembered result at once and, when it is
    older than `interval_seconds`, starts a refresh in the background, so a CRM
    that was down at startup is reported as healthy again without a restart.
    """

    def __init__(
        self,
        provider: CRMProvider,
        *,
        enabled: bool = True,
        interval_seconds: float = 300.0,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._provider = provider
        self._enabled = enabled
        self._interval_seconds = interval_seconds
        self._timeout_seconds = timeout_seconds
        self._snapshot = UNCHECKED
        self._lock = asyncio.Lock()
        self._background: asyncio.Task[CRMAccessSnapshot] | None = None

    async def refresh(self) -> CRMAccessSnapshot:
        async with self._lock:
            self._snapshot = await self._check()
            return self._snapshot

    def snapshot(self) -> CRMAccessSnapshot:
        if self._enabled and self._is_stale() and not self._refreshing():
            self._background = asyncio.create_task(self.refresh())
        return self._snapshot

    async def aclose(self) -> None:
        if self._background is not None and not self._background.done():
            self._background.cancel()
            await asyncio.gather(self._background, return_exceptions=True)

    def _refreshing(self) -> bool:
        return self._background is not None and not self._background.done()

    def _is_stale(self) -> bool:
        checked_at = self._snapshot.checked_at
        if checked_at is None:
            return True
        return (datetime.now(UTC) - checked_at).total_seconds() >= self._interval_seconds

    async def _check(self) -> CRMAccessSnapshot:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._provider.check_access()
        except ProviderError as exc:
            state = CRMAccessState.FAILED
            message: str | None = str(exc)
        except TimeoutError:
            state = CRMAccessState.FAILED
            message = f"The CRM did not answer within {self._timeout_seconds:g} seconds."
        except Exception as exc:
            logger.exception("CRM access check crashed")
            state = CRMAccessState.FAILED
            message = f"The access check failed unexpectedly ({type(exc).__name__})."
        else:
            state = CRMAccessState.OK if result.ok else CRMAccessState.FAILED
            message = result.message
        if state is CRMAccessState.OK:
            logger.info("CRM access check (%s) passed", self._provider.mode.value)
        else:
            logger.warning("CRM access check (%s) failed: %s", self._provider.mode.value, message)
        return CRMAccessSnapshot(state=state, message=message, checked_at=datetime.now(UTC))
