"""Local LLM mode: offline, deterministic, clearly labeled as not a real LLM.

Owner: T3.
"""

from collections.abc import Sequence
from typing import ClassVar, Self

from app.core.config import LLMProviderMode, Settings
from app.providers.errors import ProviderNotImplementedError
from app.providers.llm.base import ChatMessage, LLMProvider, LLMResponse


class LocalLLMProvider(LLMProvider):
    mode: ClassVar[LLMProviderMode] = LLMProviderMode.LOCAL
    live: ClassVar[bool] = False

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls()

    @property
    def model_name(self) -> str | None:
        return None

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        json_output: bool = False,
    ) -> LLMResponse:
        raise ProviderNotImplementedError("The local LLM provider")
