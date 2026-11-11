"""LLM provider contract."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal, Self

from app.core.config import LLMProviderMode, Settings


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str | None
    usage: TokenUsage | None


class LLMProvider(ABC):
    """Text generation behind one interface.

    `live` is False for the local mode. Local mode works offline and must never be
    presented as a working LLM: services may check `live` and build an extractive
    reply from retrieved excerpts instead of prompting.

    Failures raise `app.providers.errors.ProviderError`.
    """

    mode: ClassVar[LLMProviderMode]
    live: ClassVar[bool]

    @classmethod
    @abstractmethod
    def from_settings(cls, settings: Settings) -> Self: ...

    @property
    @abstractmethod
    def model_name(self) -> str | None:
        """Model identifier from configuration, or None when no model is involved."""

    @abstractmethod
    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        json_output: bool = False,
    ) -> LLMResponse:
        """Generate one reply. With `json_output`, the reply text is a JSON object."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook, no-op by default
        """Release network resources. Called once on shutdown."""
