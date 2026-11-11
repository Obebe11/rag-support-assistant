"""Build providers from settings. Each provider is selected independently."""

from dataclasses import dataclass

from app.core.config import CRMProviderMode, EmbeddingProviderMode, LLMProviderMode, Settings
from app.providers.crm.base import CRMProvider
from app.providers.crm.hubspot import HubSpotCRMProvider
from app.providers.crm.simulated import SimulatedCRMProvider
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.embeddings.local import LocalEmbeddingProvider
from app.providers.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.local import LocalLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

LLM_PROVIDERS: dict[LLMProviderMode, type[LLMProvider]] = {
    LLMProviderMode.LOCAL: LocalLLMProvider,
    LLMProviderMode.OPENAI_COMPATIBLE: OpenAICompatibleLLMProvider,
}
EMBEDDING_PROVIDERS: dict[EmbeddingProviderMode, type[EmbeddingProvider]] = {
    EmbeddingProviderMode.LOCAL: LocalEmbeddingProvider,
    EmbeddingProviderMode.OPENAI_COMPATIBLE: OpenAICompatibleEmbeddingProvider,
}
CRM_PROVIDERS: dict[CRMProviderMode, type[CRMProvider]] = {
    CRMProviderMode.SIMULATED: SimulatedCRMProvider,
    CRMProviderMode.HUBSPOT: HubSpotCRMProvider,
}


@dataclass(frozen=True, slots=True)
class Providers:
    llm: LLMProvider
    embeddings: EmbeddingProvider
    crm: CRMProvider

    async def aclose(self) -> None:
        await self.llm.aclose()
        await self.embeddings.aclose()
        await self.crm.aclose()


def build_llm_provider(settings: Settings) -> LLMProvider:
    return LLM_PROVIDERS[settings.llm_provider].from_settings(settings)


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    return EMBEDDING_PROVIDERS[settings.embedding_provider].from_settings(settings)


def build_crm_provider(settings: Settings) -> CRMProvider:
    return CRM_PROVIDERS[settings.crm_provider].from_settings(settings)


def build_providers(settings: Settings) -> Providers:
    return Providers(
        llm=build_llm_provider(settings),
        embeddings=build_embedding_provider(settings),
        crm=build_crm_provider(settings),
    )
