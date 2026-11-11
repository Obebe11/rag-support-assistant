import httpx
from pydantic import SecretStr

from app.core.config import CRMProviderMode, EmbeddingProviderMode, LLMProviderMode, Settings
from app.main import create_app
from tests.conftest import make_settings


async def _get_health(settings: Settings) -> httpx.Response:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get("/api/health")


async def test_health_reports_local_and_simulated_modes_as_not_live(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "database": "ok",
        "providers": {
            "llm": {"mode": "local", "live": False, "model": None},
            "embeddings": {"mode": "local", "live": False, "model": None},
            "crm": {
                "mode": "simulated",
                "live": False,
                "access": {"state": "unchecked", "message": None, "checked_at": None},
            },
        },
    }


async def test_health_reports_configured_api_providers_as_live(settings: Settings) -> None:
    live_settings = make_settings(
        settings.database_url,
        llm_provider=LLMProviderMode.OPENAI_COMPATIBLE,
        llm_base_url="https://llm.example.com/v1",
        llm_api_key=SecretStr("llm-key"),
        llm_model="example-chat-model",
        embedding_provider=EmbeddingProviderMode.OPENAI_COMPATIBLE,
        embedding_base_url="https://embeddings.example.com/v1",
        embedding_model="example-embedding-model",
        crm_provider=CRMProviderMode.HUBSPOT,
        hubspot_access_token=SecretStr("hubspot-token"),
    )

    response = await _get_health(live_settings)

    assert response.status_code == 200
    body = response.json()
    assert body["providers"] == {
        "llm": {"mode": "openai_compatible", "live": True, "model": "example-chat-model"},
        "embeddings": {
            "mode": "openai_compatible",
            "live": True,
            "model": "example-embedding-model",
        },
        "crm": {
            "mode": "hubspot",
            "live": True,
            "access": {"state": "unchecked", "message": None, "checked_at": None},
        },
    }
    assert "llm-key" not in response.text
    assert "hubspot-token" not in response.text


async def test_health_is_degraded_when_the_database_is_unreachable(tmp_path_factory) -> None:  # type: ignore[no-untyped-def]
    missing_socket_dir = tmp_path_factory.mktemp("no-postgres-here")
    unreachable = make_settings(f"postgresql+asyncpg://postgres@/handoff?host={missing_socket_dir}")

    response = await _get_health(unreachable)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
