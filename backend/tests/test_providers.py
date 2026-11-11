"""Provider selection by settings, and the chat-inquiry seam."""

import uuid

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import CRMProviderMode, EmbeddingProviderMode, LLMProviderMode
from app.core.db import SessionFactory
from app.models.enums import MessageRole
from app.providers.crm.hubspot import HubSpotCRMProvider
from app.providers.crm.simulated import SimulatedCRMProvider
from app.providers.embeddings.local import LocalEmbeddingProvider
from app.providers.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from app.providers.factory import (
    CRM_PROVIDERS,
    EMBEDDING_PROVIDERS,
    LLM_PROVIDERS,
    build_providers,
)
from app.providers.llm.local import LocalLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider
from app.services.inquiry_intent import (
    NO_INQUIRY_INTENT,
    ConversationTurn,
    NoOpInquiryIntentDetector,
)
from tests.conftest import make_settings

DATABASE_URL = "postgresql+asyncpg://unused@localhost/unused"


def test_defaults_select_local_and_simulated_providers() -> None:
    providers = build_providers(make_settings(DATABASE_URL))

    assert isinstance(providers.llm, LocalLLMProvider)
    assert isinstance(providers.embeddings, LocalEmbeddingProvider)
    assert isinstance(providers.crm, SimulatedCRMProvider)
    assert (providers.llm.live, providers.embeddings.live, providers.crm.live) == (
        False,
        False,
        False,
    )


def test_each_provider_is_selected_independently() -> None:
    providers = build_providers(
        make_settings(
            DATABASE_URL,
            llm_provider=LLMProviderMode.OPENAI_COMPATIBLE,
            llm_base_url="https://llm.example.com/v1",
            llm_model="example-chat-model",
        )
    )

    assert isinstance(providers.llm, OpenAICompatibleLLMProvider)
    assert providers.llm.model_name == "example-chat-model"
    assert isinstance(providers.embeddings, LocalEmbeddingProvider)
    assert isinstance(providers.crm, SimulatedCRMProvider)


def test_api_providers_take_their_model_from_settings() -> None:
    providers = build_providers(
        make_settings(
            DATABASE_URL,
            embedding_provider=EmbeddingProviderMode.OPENAI_COMPATIBLE,
            embedding_base_url="https://embeddings.example.com/v1",
            embedding_api_key=SecretStr("key"),
            embedding_model="example-embedding-model",
            crm_provider=CRMProviderMode.HUBSPOT,
            hubspot_access_token=SecretStr("token"),
        )
    )

    assert isinstance(providers.embeddings, OpenAICompatibleEmbeddingProvider)
    assert providers.embeddings.model_name == "example-embedding-model"
    assert isinstance(providers.crm, HubSpotCRMProvider)
    assert (providers.embeddings.live, providers.crm.live) == (True, True)


def test_every_mode_has_a_provider_labeled_with_that_mode() -> None:
    for registry, modes in (
        (LLM_PROVIDERS, LLMProviderMode),
        (EMBEDDING_PROVIDERS, EmbeddingProviderMode),
        (CRM_PROVIDERS, CRMProviderMode),
    ):
        assert set(registry) == set(modes)
        for mode, provider in registry.items():
            assert provider.mode is mode


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"llm_provider": "openai_compatible"}, "LLM_BASE_URL, LLM_MODEL"),
        (
            {"llm_provider": "openai_compatible", "llm_base_url": "https://llm.example.com/v1"},
            "LLM_MODEL",
        ),
        ({"embedding_provider": "openai_compatible"}, "EMBEDDING_BASE_URL, EMBEDDING_MODEL"),
        ({"crm_provider": "hubspot"}, "HUBSPOT_ACCESS_TOKEN"),
    ],
)
def test_settings_reject_a_provider_without_its_configuration(
    overrides: dict[str, object], missing: str
) -> None:
    with pytest.raises(ValidationError, match=missing):
        make_settings(DATABASE_URL, **overrides)


def test_settings_reject_unknown_provider_modes_and_other_drivers() -> None:
    with pytest.raises(ValidationError):
        make_settings(DATABASE_URL, llm_provider="some_vendor")
    with pytest.raises(ValidationError, match="asyncpg"):
        make_settings("postgresql+psycopg://user@localhost/db")


def test_settings_parse_comma_separated_origins() -> None:
    settings = make_settings(
        DATABASE_URL, cors_allowed_origins="http://localhost:5173, https://demo.example.com"
    )

    assert settings.cors_allowed_origins == ["http://localhost:5173", "https://demo.example.com"]


def test_secrets_are_not_printed() -> None:
    settings = make_settings(
        DATABASE_URL, crm_provider="hubspot", hubspot_access_token=SecretStr("super-secret")
    )

    assert "super-secret" not in repr(settings)


async def test_no_op_inquiry_intent_detector_reports_no_intent(
    session_factory: SessionFactory,
) -> None:
    """The seam's fallback. The application wires the real detector (see
    tests/test_inquiry_intent.py)."""
    detector = NoOpInquiryIntentDetector()

    async with session_factory() as session:
        intent = await detector.assess(
            session,
            conversation_id=uuid.uuid4(),
            turns=[ConversationTurn(MessageRole.USER, "I need 20 standing desks by March.")],
        )

    assert intent is NO_INQUIRY_INTENT
    assert intent.detected is False
    assert intent.missing_fields == ()
