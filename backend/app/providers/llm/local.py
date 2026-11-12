"""Local LLM mode: offline, deterministic, clearly labeled as not a real LLM.

This mode generates no text. Services check `live` first: the chat service
builds an extractive reply from retrieved passages instead of prompting (see
`app.services.chat.extractive`). A direct call to `complete` is a programming
error and fails with a non-retryable `ProviderError`, so local mode can never
pass for a working LLM.
"""

from collections.abc import Sequence
from typing import ClassVar, Self

from app.core.config import LLMProviderMode, Settings
from app.providers.errors import ProviderError
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
        raise ProviderError(
            "The local LLM mode does not generate text. Check `live` and use an "
            "extractive reply instead.",
            retryable=False,
        )
