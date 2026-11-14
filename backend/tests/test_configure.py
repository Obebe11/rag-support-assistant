"""The `.env` setup command: file editing and the questions it asks."""

from pathlib import Path

import pytest

from app.core.config import REPO_ROOT as REAL_REPO_ROOT
from app.core.config import EmbeddingProviderMode, LLMProviderMode, Settings
from scripts import configure

EXAMPLE = """# Comment kept as it is.
ADMIN_API_TOKEN=
LLM_PROVIDER=local
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
LLM_REASONING_EFFORT=

EMBEDDING_PROVIDER=local
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_MODEL=
CRM_PROVIDER=simulated
HUBSPOT_ACCESS_TOKEN=
"""


@pytest.fixture
def env_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env_path = tmp_path / ".env"
    example_path = tmp_path / ".env.example"
    example_path.write_text(EXAMPLE)
    monkeypatch.setattr(configure, "ENV_PATH", env_path)
    monkeypatch.setattr(configure, "EXAMPLE_PATH", example_path)
    return env_path


def _answer(monkeypatch: pytest.MonkeyPatch, answers: list[str], keys: list[str]) -> None:
    """Feed typed answers to `input` and hidden ones to `getpass`, in order."""
    typed, hidden = iter(answers), iter(keys)
    monkeypatch.setattr("builtins.input", lambda _prompt: next(typed))
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(hidden))


async def _no_problems(_settings: Settings) -> list[str]:
    return []


def test_values_are_replaced_in_place_and_comments_are_kept() -> None:
    text = "# Keep me\nLLM_MODEL=old\nOTHER='quoted'\n"

    updated = configure.set_env_values(text, {"LLM_MODEL": "new", "ADDED": "1"})

    assert updated == "# Keep me\nLLM_MODEL=new\nOTHER='quoted'\nADDED=1\n"
    assert configure.read_env_values(updated) == {
        "LLM_MODEL": "new",
        "OTHER": "quoted",
        "ADDED": "1",
    }


def test_the_example_file_lists_every_key_the_command_writes() -> None:
    example = configure.read_env_values((REAL_REPO_ROOT / ".env.example").read_text())

    for key in configure.read_env_values(EXAMPLE):
        assert key in example


def test_init_creates_env_with_an_admin_token_once(env_files: Path) -> None:
    assert configure.ensure_env_file() is True
    token = configure.read_env_values(env_files.read_text())["ADMIN_API_TOKEN"]
    assert len(token) >= 32
    assert env_files.read_text().startswith("# Comment kept as it is.\n")
    assert env_files.stat().st_mode & 0o077 == 0

    assert configure.ensure_env_file() is False
    assert configure.read_env_values(env_files.read_text())["ADMIN_API_TOKEN"] == token


def test_openai_for_both_providers_takes_one_key(
    env_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(configure, "check_providers", _no_problems)
    # LLM: OpenAI, default model. Embeddings: the same API (the default), default model.
    # HubSpot: no.
    _answer(monkeypatch, ["2", "", "", "", ""], ["sk-test-key"])

    assert configure.configure() == 0

    values = configure.read_env_values(env_files.read_text())
    assert values["LLM_PROVIDER"] == values["EMBEDDING_PROVIDER"] == "openai_compatible"
    assert values["LLM_BASE_URL"] == values["EMBEDDING_BASE_URL"] == "https://api.openai.com/v1"
    assert values["LLM_API_KEY"] == values["EMBEDDING_API_KEY"] == "sk-test-key"
    assert values["LLM_MODEL"] == configure.OPENAI.llm_model
    assert values["EMBEDDING_MODEL"] == configure.OPENAI.embedding_model
    assert values["CRM_PROVIDER"] == "simulated"
    assert values["ADMIN_API_TOKEN"]
    settings = configure.build_settings(values)
    assert settings.llm_provider is LLMProviderMode.OPENAI_COMPATIBLE
    assert settings.embedding_provider is EmbeddingProviderMode.OPENAI_COMPATIBLE


def test_enter_keeps_the_current_key_and_model(
    env_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_files.write_text(
        configure.set_env_values(
            EXAMPLE,
            {
                "ADMIN_API_TOKEN": "kept-token",
                "LLM_PROVIDER": "openai_compatible",
                "LLM_BASE_URL": "https://llm.example.com/v1",
                "LLM_API_KEY": "kept-key",
                "LLM_MODEL": "kept-model",
            },
        )
    )
    monkeypatch.setattr(configure, "check_providers", _no_problems)
    # Every answer is Enter: another API stays selected, embeddings stay in demo mode.
    _answer(monkeypatch, ["", "", "", "", ""], [""])

    assert configure.configure() == 0

    values = configure.read_env_values(env_files.read_text())
    assert values["LLM_BASE_URL"] == "https://llm.example.com/v1"
    assert values["LLM_API_KEY"] == "kept-key"
    assert values["LLM_MODEL"] == "kept-model"
    assert values["ADMIN_API_TOKEN"] == "kept-token"


def test_a_failed_check_leaves_env_unchanged_unless_confirmed(
    env_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure.ensure_env_file()
    before = env_files.read_text()

    async def failing(_settings: Settings) -> list[str]:
        return ["Language model: The LLM API returned HTTP 401: invalid key"]

    monkeypatch.setattr(configure, "check_providers", failing)
    # LLM: OpenAI, default model; embeddings: demo; HubSpot: no; save anyway: no.
    _answer(monkeypatch, ["2", "", "1", "", ""], ["sk-wrong"])

    assert configure.configure() == 1
    assert env_files.read_text() == before


def test_init_mode_needs_no_answers(env_files: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["configure", "--init"])

    assert configure.main() == 0
    assert env_files.exists()
