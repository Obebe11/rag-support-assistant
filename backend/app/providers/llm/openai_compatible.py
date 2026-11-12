"""LLM provider for any API that implements OpenAI-style chat completions.

Base URL, API key and model come from configuration only.
"""

from collections.abc import Sequence
from typing import Any, ClassVar, Self

import httpx
from pydantic import SecretStr

from app.core.config import LLMProviderMode, Settings
from app.providers.llm.base import ChatMessage, LLMProvider, LLMResponse, TokenUsage
from app.providers.openai_http import OpenAICompatibleClient


class OpenAICompatibleLLMProvider(LLMProvider):
    mode: ClassVar[LLMProviderMode] = LLMProviderMode.OPENAI_COMPATIBLE
    live: ClassVar[bool] = True

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr | None,
        model: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        self._http = OpenAICompatibleClient(
            label="LLM", base_url=base_url, api_key=api_key, transport=transport
        )

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
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        body = await self._http.post_json("chat/completions", payload)

        choices = body.get("choices")
        first = choices[0] if isinstance(choices, list) and choices else None
        message = first.get("message") if isinstance(first, dict) else None
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise self._http.malformed("the first choice has no text.")
        model = body.get("model")
        return LLMResponse(
            text=text,
            model=model if isinstance(model, str) and model else self._model,
            usage=_read_usage(body.get("usage")),
        )

    async def aclose(self) -> None:
        await self._http.aclose()


def _read_usage(usage: Any) -> TokenUsage | None:
    if not isinstance(usage, dict):
        return None
    input_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    return TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens)
