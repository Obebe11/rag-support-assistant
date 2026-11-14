"""Set up `.env` step by step: `python -m scripts.configure [--init]`.

Without arguments the command asks which language model, embedding model and
CRM to use, checks every key with one small request, and writes the answers to
`.env`. Press Enter to keep the value shown in brackets. Other lines of `.env`,
comments included, are kept as they are.

`--init` asks nothing: it creates `.env` from `.env.example` when `.env` is
missing and puts a new admin token in it.
"""

import argparse
import asyncio
import getpass
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.config import REPO_ROOT, Settings
from app.providers.errors import ProviderError
from app.providers.factory import build_providers
from app.providers.llm.base import ChatMessage

ENV_PATH = REPO_ROOT / ".env"
EXAMPLE_PATH = REPO_ROOT / ".env.example"
# Settings need a database URL; the check connects to no database.
UNUSED_DATABASE_URL = "postgresql+asyncpg://unused@localhost/unused"
_LINE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=(.*)$")


@dataclass(frozen=True, slots=True)
class ApiPreset:
    label: str
    base_url: str | None
    """None asks for the URL."""
    llm_model: str
    embedding_model: str


OPENAI = ApiPreset("OpenAI", "https://api.openai.com/v1", "gpt-4.1-mini", "text-embedding-3-small")
OTHER_API = ApiPreset("Another OpenAI-compatible API", None, "", "")


def read_env_values(text: str) -> dict[str, str]:
    """`KEY=value` pairs of an env file. Comments and blank lines are skipped."""
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = _LINE.match(line)
        if match:
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            values[match.group(1)] = value
    return values


def set_env_values(text: str, values: Mapping[str, str]) -> str:
    """Replace the value of each key in place; append the keys the text lacks."""
    pending = dict(values)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = _LINE.match(line)
        if match and match.group(1) in pending:
            key = match.group(1)
            lines[index] = f"{key}={pending.pop(key)}"
    lines += [f"{key}={value}" for key, value in pending.items()]
    return "\n".join(lines) + "\n"


def new_admin_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_env_file() -> bool:
    """Create `.env` from `.env.example` with a new admin token. True when it was created."""
    if ENV_PATH.exists():
        return False
    text = set_env_values(
        EXAMPLE_PATH.read_text(encoding="utf-8"), {"ADMIN_API_TOKEN": new_admin_token()}
    )
    ENV_PATH.write_text(text, encoding="utf-8")
    ENV_PATH.chmod(0o600)
    return True


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        answer = input(f"{prompt}{suffix}: ").strip() or default
        if answer:
            return answer
        print("  A value is required.")


def ask_yes_no(prompt: str, *, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{hint}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")
        print("  Answer y or n.")


def ask_secret(prompt: str, current: str, *, required: bool) -> str:
    """Read a key without echoing it. Enter keeps the current key."""
    hint = f" [Enter keeps ...{current[-4:]}]" if current else ""
    while True:
        answer = getpass.getpass(f"{prompt}{hint}: ").strip() or current
        if answer or not required:
            return answer
        print("  A key is required.")


def choose(title: str, options: list[str], default: int) -> int:
    """Ask for one of the numbered options. Returns its index."""
    print(f"\n{title}")
    for number, option in enumerate(options, start=1):
        print(f"  {number}) {option}")
    while True:
        answer = input(f"Choose [{default + 1}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print(f"  Enter a number from 1 to {len(options)}.")


def _current_api(values: Mapping[str, str], prefix: str) -> int:
    """Index of the current choice: 0 demo mode, 1 OpenAI, 2 another API."""
    if values.get(f"{prefix}_PROVIDER", "local") != "openai_compatible":
        return 0
    return 1 if values.get(f"{prefix}_BASE_URL", "").rstrip("/") == OPENAI.base_url else 2


def ask_api(
    values: Mapping[str, str],
    prefix: str,
    preset: ApiPreset,
    *,
    default_model: str,
    reuse: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Ask for the API settings of one provider, `LLM` or `EMBEDDING`.

    The current values are offered only when the provider already uses the same API.
    `reuse` takes the URL and key from another provider instead of asking.
    """
    if reuse is not None:
        base_url, api_key = reuse["base_url"], reuse["api_key"]
        same = values.get(f"{prefix}_BASE_URL") == base_url
    else:
        same = _current_api(values, prefix) == (1 if preset is OPENAI else 2)
    current = {
        name: values.get(f"{prefix}_{name}", "") if same else ""
        for name in ("BASE_URL", "API_KEY", "MODEL")
    }
    if reuse is None:
        base_url = preset.base_url or ask(
            "API base URL, for example https://api.example.com/v1", current["BASE_URL"]
        )
        api_key = ask_secret(
            "API key (hidden while you type)",
            current["API_KEY"],
            required=preset.base_url is not None,
        )
    return {
        f"{prefix}_PROVIDER": "openai_compatible",
        f"{prefix}_BASE_URL": base_url,
        f"{prefix}_API_KEY": api_key,
        f"{prefix}_MODEL": ask("Model", current["MODEL"] or default_model),
    }


def ask_llm(values: Mapping[str, str]) -> dict[str, str]:
    presets = [OPENAI, OTHER_API]
    choice = choose(
        "Language model: writes the answers.",
        ["Demo mode, no key (quotes the documents, writes nothing)"]
        + [preset.label for preset in presets],
        _current_api(values, "LLM"),
    )
    if choice == 0:
        return {"LLM_PROVIDER": "local"}
    preset = presets[choice - 1]
    return ask_api(values, "LLM", preset, default_model=preset.llm_model)


def ask_embeddings(values: Mapping[str, str], llm: Mapping[str, str]) -> dict[str, str]:
    presets = [OPENAI, OTHER_API]
    options = ["Demo mode, no key (matches words, not meaning)"]
    options += [preset.label for preset in presets]
    default = _current_api(values, "EMBEDDING")
    llm_is_live = llm.get("LLM_PROVIDER") == "openai_compatible"
    if llm_is_live:
        options.append("The same API and key as the language model")
        # Offered by default on the first switch from demo mode, and while it is the setup.
        first_switch = default == 0 and _current_api(values, "LLM") == 0
        if first_switch or (default and values.get("EMBEDDING_BASE_URL") == llm["LLM_BASE_URL"]):
            default = len(options) - 1
    choice = choose("Embeddings: find the passages that answer a question.", options, default)
    if choice == 0:
        return {"EMBEDDING_PROVIDER": "local"}
    if llm_is_live and choice == len(options) - 1:
        preset = OPENAI if llm["LLM_BASE_URL"].rstrip("/") == OPENAI.base_url else OTHER_API
        reuse = {"base_url": llm["LLM_BASE_URL"], "api_key": llm["LLM_API_KEY"]}
        return ask_api(
            values, "EMBEDDING", preset, default_model=preset.embedding_model, reuse=reuse
        )
    preset = presets[choice - 1]
    return ask_api(values, "EMBEDDING", preset, default_model=preset.embedding_model)


def ask_crm(values: Mapping[str, str]) -> dict[str, str]:
    print()
    if not ask_yes_no(
        "Send confirmed inquiries to HubSpot? (No keeps them in this app only)",
        default=values.get("CRM_PROVIDER") == "hubspot",
    ):
        return {"CRM_PROVIDER": "simulated"}
    print("  A private app token; the scopes are listed in docs/inquiries.md.")
    token = ask_secret(
        "HubSpot access token", values.get("HUBSPOT_ACCESS_TOKEN", ""), required=True
    )
    return {"CRM_PROVIDER": "hubspot", "HUBSPOT_ACCESS_TOKEN": token}


def build_settings(values: Mapping[str, str]) -> Settings:
    fields = {key.lower(): value for key, value in values.items() if value}
    fields["database_url"] = UNUSED_DATABASE_URL
    # `model_validate` reads no `.env` and no environment: only the answers count.
    return Settings.model_validate(fields)


async def check_providers(settings: Settings) -> list[str]:
    """Make one small request to each live provider. Returns the problems found."""
    providers = build_providers(settings)
    problems: list[str] = []
    try:
        if providers.llm.live:
            print("Checking the language model...", flush=True)
            try:
                # JSON output, as in the app: a model that cannot return it fails here.
                await providers.llm.complete(
                    [ChatMessage(role="user", content='Return the JSON object {"status": "ok"}.')],
                    temperature=0.0,
                    json_output=True,
                )
            except ProviderError as exc:
                problems.append(f"Language model: {exc}")
        if providers.embeddings.live:
            print("Checking the embeddings...", flush=True)
            try:
                await providers.embeddings.embed_query("office chair warranty")
            except ProviderError as exc:
                problems.append(f"Embeddings: {exc}")
        if providers.crm.live:
            print("Checking HubSpot...", flush=True)
            try:
                access = await providers.crm.check_access()
                if not access.ok:
                    problems.append(f"HubSpot: {access.message or 'access check failed'}")
            except ProviderError as exc:
                problems.append(f"HubSpot: {exc}")
    finally:
        await providers.aclose()
    return problems


def configure() -> int:
    created = ensure_env_file()
    text = ENV_PATH.read_text(encoding="utf-8")
    values = read_env_values(text)
    print(
        "Set up RAG Support Assistant. Press Enter to keep the value in brackets.\n"
        "Keys are saved only in .env, which git ignores."
    )
    if created:
        print("Created .env from .env.example.")

    answers: dict[str, str] = {}
    answers |= ask_llm(values)
    answers |= ask_embeddings(values, answers)
    answers |= ask_crm(values)
    if not values.get("ADMIN_API_TOKEN"):
        answers["ADMIN_API_TOKEN"] = new_admin_token()

    merged = {**values, **answers}
    try:
        settings = build_settings(merged)
    except ValidationError as exc:
        print("\nThese settings cannot be used:")
        for error in exc.errors():
            print(f"  - {error['msg'].removeprefix('Value error, ')}")
        return 1
    print()
    problems = asyncio.run(check_providers(settings))
    if problems:
        print("\nThe check failed:")
        for problem in problems:
            print(f"  - {problem}")
        if not ask_yes_no("Save these settings anyway?", default=False):
            print(".env is unchanged.")
            return 1

    ENV_PATH.write_text(set_env_values(text, answers), encoding="utf-8")
    ENV_PATH.chmod(0o600)
    print("\nSaved .env.")
    if not problems and (settings.llm_provider.value, settings.embedding_provider.value) != (
        "local",
        "local",
    ):
        print("The keys work.")
    if merged.get("EMBEDDING_MODEL") != values.get("EMBEDDING_MODEL") or merged.get(
        "EMBEDDING_PROVIDER"
    ) != values.get("EMBEDDING_PROVIDER"):
        print("The documents will be indexed again with the new embedding model on start.")
    print(f"Admin token, for {ENV_PATH.name} and the /admin page: {merged['ADMIN_API_TOKEN']}")
    print("Next: restart `make dev` if it is running, or run it now.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--init", action="store_true", help="Only create .env when it is missing.")
    if parser.parse_args().init:
        if ensure_env_file():
            print("Created .env with demo settings and an admin token.")
        else:
            print(".env already exists; left unchanged.")
        port = read_env_values(ENV_PATH.read_text(encoding="utf-8")).get("FRONTEND_PORT") or "5173"
        print(f"Next: run `make dev`, then open http://localhost:{port}")
        return 0
    try:
        return configure()
    except (KeyboardInterrupt, EOFError):
        print("\nCanceled. .env is unchanged.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
