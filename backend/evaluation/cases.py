"""Load the evaluation cases and the rules they are checked with.

The case files are validated by `evals/validate_cases.py`, which uses only the
standard library so that it runs without the backend environment. The runner
loads that module from its file and reuses its text rules (`normalize` and
`matches`), so the validator and the runner can never disagree about what a
`match_any` string matches.
"""

import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from app.core.config import REPO_ROOT

EVALS_DIR = REPO_ROOT / "evals"
CASES_DIR = EVALS_DIR / "cases"
CORPUS_MANIFEST = REPO_ROOT / "knowledge-base" / "northline" / "manifest.json"
FIXTURES_MANIFEST = EVALS_DIR / "fixtures" / "manifest.json"
CASE_FILES = (
    "answerable.json",
    "unanswerable.json",
    "multi_turn.json",
    "instruction_override.json",
)


class CasesError(Exception):
    """The case files cannot be used."""


def _load_validator() -> ModuleType:
    path = EVALS_DIR / "validate_cases.py"
    spec = importlib.util.spec_from_file_location("handoff_validate_cases", path)
    if spec is None or spec.loader is None:
        raise CasesError(f"Cannot load the case validator from {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_validator = _load_validator()


def normalize(text: str) -> str:
    """The validator's text normalization: emphasis, table pipes, quotes, whitespace."""
    result: str = _validator.normalize(text)
    return result


def matches(pattern: str, text: str) -> bool:
    """The `match_any` rule: a case-insensitive substring match on normalized text."""
    result: bool = _validator.matches(pattern, text)
    return result


def validate_case_files() -> subprocess.CompletedProcess[str]:
    """Run the validator on the committed cases, as `python3 evals/validate_cases.py` does."""
    return subprocess.run(  # noqa: S603 - fixed arguments, no shell
        [sys.executable, str(EVALS_DIR / "validate_cases.py")],
        capture_output=True,
        text=True,
        check=False,
    )


@dataclass(frozen=True, slots=True)
class ExpectedSource:
    doc_id: str
    section: str | None
    page: int | None
    quote: str


@dataclass(frozen=True, slots=True)
class IncludeCheck:
    fact: str
    match_any: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExcludeCheck:
    claim: str
    match_any: tuple[str, ...]
    """Empty when the claim can be checked only by a reviewer or a judge."""


@dataclass(frozen=True, slots=True)
class Expectation:
    response_type: str
    reference_answer: str
    must_include: tuple[IncludeCheck, ...]
    must_not_include: tuple[ExcludeCheck, ...]
    sources: tuple[ExpectedSource, ...]
    require_all_sources: bool
    offer_handoff: bool


@dataclass(frozen=True, slots=True)
class Turn:
    user: str
    expect: Expectation


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    category: str
    title: str
    topics: tuple[str, ...]
    turns: tuple[Turn, ...]
    attack_vector: str | None
    fixtures: tuple[str, ...]
    """`doc_id` values from the fixtures manifest to add to the knowledge base."""


def _expectation(raw: dict[str, Any]) -> Expectation:
    return Expectation(
        response_type=str(raw["response_type"]),
        reference_answer=str(raw["reference_answer"]),
        must_include=tuple(
            IncludeCheck(fact=str(item["fact"]), match_any=tuple(item["match_any"]))
            for item in raw["must_include"]
        ),
        must_not_include=tuple(
            ExcludeCheck(claim=str(item["claim"]), match_any=tuple(item.get("match_any") or ()))
            for item in raw["must_not_include"]
        ),
        sources=tuple(
            ExpectedSource(
                doc_id=str(source["doc_id"]),
                section=source.get("section"),
                page=source.get("page"),
                quote=str(source["quote"]),
            )
            for source in raw["sources"]
        ),
        require_all_sources=bool(raw.get("require_all_sources", False)),
        offer_handoff=bool(raw.get("offer_handoff", False)),
    )


def load_cases(cases_dir: Path = CASES_DIR) -> list[Case]:
    """Every case of the four case files, in file order."""
    cases: list[Case] = []
    for name in CASE_FILES:
        path = cases_dir / name
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            for raw in document["cases"]:
                cases.append(
                    Case(
                        id=str(raw["id"]),
                        category=str(raw["category"]),
                        title=str(raw["title"]),
                        topics=tuple(raw["topics"]),
                        turns=tuple(
                            Turn(user=str(turn["user"]), expect=_expectation(turn["expect"]))
                            for turn in raw["turns"]
                        ),
                        attack_vector=raw.get("attack_vector"),
                        fixtures=tuple(sorted(raw.get("fixtures") or ())),
                    )
                )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CasesError(f"Cannot read the cases in {path}: {exc}") from exc
    return cases
