"""LLM provider for any API that implements OpenAI-style chat completions.

Base URL, API key and model come from configuration only. Owner: T3.
"""

from collections.abc import Sequence
from typing import ClassVar, Self

from pydantic import SecretStr

from app.core.config import LLMProviderMode, Settings
from app.providers.errors import ProviderNotImplementedError
from app.providers.llm.base import ChatMessage, LLMProvider, LLMResponse


class OpenAICompatibleLLMProvider(LLMProvider):
    mode: ClassVar[LLMProviderMode] = LLMProviderMode.OPENAI_COMPATIBLE
    live: ClassVar[bool] = True

    def __init__(self, *, base_url: str, api_key: SecretStr | None, model: str) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        if settings.llm_base_url is None or settings.llm_model is None:
            raise ValueError("LLM_BASE_URL and LLM_MODEL are required for openai_compatible.")
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )

    @property
    def model_name(self) -> str | None:
        return self._model

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        json_output: bool = False,
    ) -> LLMResponse:
        raise ProviderNotImplementedError("The OpenAI-compatible LLM provider")
