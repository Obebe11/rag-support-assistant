"""HTTP client shared by the OpenAI-compatible LLM and embedding providers.

It turns transport failures and error responses into `ProviderError` with a
`retryable` flag, and never puts the API key into an error message.
"""

from typing import Any

import httpx
from pydantic import SecretStr

from app.providers.errors import ProviderError

DEFAULT_TIMEOUT_SECONDS = 60.0
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429})
_ERROR_BODY_LIMIT = 300


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        label: str,
        base_url: str,
        api_key: SecretStr | None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._label = label
        headers = {"Authorization": f"Bearer {api_key.get_secret_value()}"} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    async def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST `payload` to `path` (relative to the base URL) and return the JSON object."""
        try:
            response = await self._client.post(path, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"The {self._label} API timed out.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"The {self._label} API request failed: {type(exc).__name__}.", retryable=True
            ) from exc
        if response.status_code >= 400:
            detail = " ".join(response.text.split())[:_ERROR_BODY_LIMIT]
            raise ProviderError(
                f"The {self._label} API returned HTTP {response.status_code}: {detail}",
                retryable=response.status_code in _RETRYABLE_STATUS_CODES
                or response.status_code >= 500,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"The {self._label} API returned a body that is not JSON.", retryable=False
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                f"The {self._label} API returned JSON that is not an object.", retryable=False
            )
        return data

    def malformed(self, problem: str) -> ProviderError:
        return ProviderError(
            f"The {self._label} API returned an unexpected response: {problem}", retryable=False
        )

    async def aclose(self) -> None:
        await self._client.aclose()
