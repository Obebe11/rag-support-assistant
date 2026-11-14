#!/usr/bin/env python3
"""Validate the RAG Support Assistant evaluation cases against the Northline corpus.

Usage (from the repository root, Python 3.10+ standard library only):

    python3 evals/validate_cases.py

The validator checks:

* the corpus manifest and the fixture manifest (fields, unique ``doc_id``,
  existing files);
* the case schema described in ``evals/README.md``, including unknown keys;
* unique case ``id`` values and the required counts per category
  (20 answerable, 10 unanswerable, 5 multi-turn, 5 instruction override);
* every expected source: the ``doc_id`` exists in the corpus manifest, the
  ``section`` heading or PDF ``page`` exists, and the ``quote`` appears in
  that section or on that page;
* every ``fixtures`` entry exists in the fixture manifest;
* every ``reference_answer`` passes the ``match_any`` checks of its own turn.

PDF quotes are checked against the Markdown source of the PDF, split on its
page-break markers. ``knowledge-base/northline/pdf-source/build_pdfs.py
--check`` confirms that each source page matches the text layer of the same
PDF page.

The exit code is 0 when everything passes and 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = REPO_ROOT / "evals" / "cases"
DEFAULT_CORPUS = REPO_ROOT / "knowledge-base" / "northline"
DEFAULT_FIXTURES = REPO_ROOT / "evals" / "fixtures"

EXPECTED_COUNTS = {
    "answerable": 20,
    "unanswerable": 10,
    "multi_turn": 5,
    "instruction_override": 5,
}
ID_PREFIXES = {
    "answerable": "ans",
    "unanswerable": "gap",
    "multi_turn": "multi",
    "instruction_override": "override",
}
RESPONSE_TYPES = {"grounded", "knowledge_gap", "clarification", "refusal"}
ATTACK_VECTORS = {"user_message", "document"}
DOCUMENT_FORMATS = {"markdown", "pdf"}

MANIFEST_KEYS = {"schema_version", "corpus_id", "title", "language", "documents"}
DOCUMENT_REQUIRED = {
    "doc_id",
    "title",
    "version",
    "effective_date",
    "category",
    "format",
    "path",
}
DOCUMENT_PDF_ONLY = {"page_count", "source_path"}
FILE_KEYS = {"schema_version", "category", "cases"}
CASE_REQUIRED = {"id", "category", "title", "topics", "turns"}
CASE_OPTIONAL = {"notes", "attack_vector", "fixtures"}
TURN_KEYS = {"user", "expect"}
EXPECT_REQUIRED = {
    "response_type",
    "reference_answer",
    "must_include",
    "must_not_include",
    "sources",
}
EXPECT_OPTIONAL = {"offer_handoff", "require_all_sources"}
SOURCE_REQUIRED = {"doc_id", "quote"}
SOURCE_OPTIONAL = {"section", "page"}

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
VERSION_RE = re.compile(r"^\d+\.\d+$")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
PAGE_BREAK = "<!-- pagebreak -->"


def normalize(text: str) -> str:
    """Normalize document text and quotes before comparing them.

    Markdown emphasis and table pipes are removed, typographic quotes are
    replaced with plain ones, and runs of whitespace collapse to one space.
    """
    text = text.replace("**", "").replace("|", " ")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def matches(pattern: str, answer: str) -> bool:
    """The deterministic ``match_any`` rule: case-insensitive substring match."""
    return normalize(pattern).lower() in normalize(answer).lower()


def section_text(text: str, heading: str) -> str | None:
    """Return the text under ``heading`` up to the next heading of the same or
    a higher level. Returns None when the heading does not exist."""
    lines = text.splitlines()
    collected: list[str] = []
    found = False
    index = 0
    while index < len(lines):
        match = HEADING_RE.match(lines[index])
        if match and match.group(2) == heading:
            found = True
            level = len(match.group(1))
            index += 1
            while index < len(lines):
                inner = HEADING_RE.match(lines[index])
                if inner and len(inner.group(1)) <= level:
                    break
                collected.append(lines[index])
                index += 1
            continue
        index += 1
    return "\n".join(collected) if found else None


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def check_keys(
        self, where: str, value: dict, required: set[str], optional: set[str] = frozenset()
    ) -> bool:
        missing = required - value.keys()
        unknown = value.keys() - required - optional
        if missing:
            self.error(where, f"missing keys {sorted(missing)}")
        if unknown:
            self.error(where, f"unknown keys {sorted(unknown)}")
        return not missing

    def load_json(self, path: Path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.error(str(path), "file not found")
        except json.JSONDecodeError as exc:
            self.error(str(path), f"invalid JSON: {exc}")
        return None

    # ----- manifests -------------------------------------------------------

    def load_manifest(self, base: Path) -> dict[str, dict]:
        """Validate ``manifest.json`` in ``base`` and index it by ``doc_id``."""
        path = base / "manifest.json"
        manifest = self.load_json(path)
        documents: dict[str, dict] = {}
        if not isinstance(manifest, dict):
            return documents
        where = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
        self.check_keys(where, manifest, MANIFEST_KEYS)
        for position, entry in enumerate(manifest.get("documents", [])):
            entry_where = f"{where} documents[{position}]"
            if not isinstance(entry, dict):
                self.error(entry_where, "must be an object")
                continue
            is_pdf = entry.get("format") == "pdf"
            required = DOCUMENT_REQUIRED | (DOCUMENT_PDF_ONLY if is_pdf else set())
            if not self.check_keys(entry_where, entry, required):
                continue
            doc_id = entry["doc_id"]
            entry_where = f"{where} {doc_id}"
            if not SLUG_RE.match(str(doc_id)):
                self.error(entry_where, "doc_id must be a lowercase hyphenated slug")
            if doc_id in documents:
                self.error(entry_where, "duplicate doc_id")
            if entry["format"] not in DOCUMENT_FORMATS:
                self.error(entry_where, f"format must be one of {sorted(DOCUMENT_FORMATS)}")
            if not VERSION_RE.match(str(entry["version"])):
                self.error(entry_where, "version must look like 1.0")
            if not DATE_RE.match(str(entry["effective_date"])):
                self.error(entry_where, "effective_date must be YYYY-MM-DD")
            for key in ("title", "category"):
                if not isinstance(entry[key], str) or not entry[key].strip():
                    self.error(entry_where, f"{key} must be a non-empty string")
            file_path = base / entry["path"]
            if not file_path.is_file():
                self.error(entry_where, f"file {entry['path']} does not exist")
                continue
            if is_pdf:
                source = base / entry["source_path"]
                if not file_path.read_bytes().startswith(b"%PDF-"):
                    self.error(entry_where, f"{entry['path']} is not a PDF file")
                if not source.is_file():
                    self.error(entry_where, f"source {entry['source_path']} does not exist")
                    continue
                pages = source.read_text(encoding="utf-8").split(PAGE_BREAK)
                if entry["page_count"] != len(pages):
                    self.error(
                        entry_where,
                        f"page_count is {entry['page_count']}, source has {len(pages)} pages",
                    )
                if len(pages) < 2:
                    self.error(entry_where, "a PDF document must have more than one page")
                entry = {**entry, "_pages": pages}
            else:
                entry = {**entry, "_text": file_path.read_text(encoding="utf-8")}
            documents[doc_id] = entry
        return documents

    # ----- cases -----------------------------------------------------------

    def check_matchers(self, where: str, items, label_key: str, patterns_required: bool) -> None:
        if not isinstance(items, list):
            self.error(where, "must be a list")
            return
        for position, item in enumerate(items):
            item_where = f"{where}[{position}]"
            if not isinstance(item, dict):
                self.error(item_where, "must be an object")
                continue
            required = {label_key, "match_any"} if patterns_required else {label_key}
            optional = set() if patterns_required else {"match_any"}
            self.check_keys(item_where, item, required, optional)
            label = item.get(label_key)
            if not isinstance(label, str) or not label.strip():
                self.error(item_where, f"{label_key} must be a non-empty string")
            if "match_any" in item:
                patterns = item["match_any"]
                if (
                    not isinstance(patterns, list)
                    or not patterns
                    or not all(isinstance(p, str) and p.strip() for p in patterns)
                ):
                    self.error(item_where, "match_any must be a non-empty list of strings")

    def check_source(self, where: str, source, corpus: dict[str, dict]) -> str | None:
        if not isinstance(source, dict):
            self.error(where, "must be an object")
            return None
        if not self.check_keys(where, source, SOURCE_REQUIRED, SOURCE_OPTIONAL):
            return None
        doc_id = source["doc_id"]
        document = corpus.get(doc_id)
        if document is None:
            self.error(where, f"doc_id {doc_id!r} is not in the corpus manifest")
            return None
        quote = source["quote"]
        if not isinstance(quote, str) or not quote.strip():
            self.error(where, "quote must be a non-empty string")
            return doc_id
        section = source.get("section")
        if document["format"] == "pdf":
            page = source.get("page")
            if not isinstance(page, int) or isinstance(page, bool):
                self.error(where, "page (integer) is required for a PDF source")
                return doc_id
            if not 1 <= page <= document["page_count"]:
                self.error(where, f"page {page} is outside 1..{document['page_count']}")
                return doc_id
            scope = document["_pages"][page - 1]
            scope_name = f"page {page}"
        else:
            if "page" in source:
                self.error(where, "page is only valid for a PDF source")
            if not isinstance(section, str) or not section.strip():
                self.error(where, "section (heading text) is required for a Markdown source")
                return doc_id
            scope = document["_text"]
            scope_name = "the document"
        if section is not None:
            scoped = section_text(scope, section)
            if scoped is None:
                self.error(where, f"heading {section!r} not found in {scope_name} of {doc_id}")
                return doc_id
            scope = scoped
            scope_name = f"section {section!r}"
        if normalize(quote) not in normalize(scope):
            self.error(where, f"quote not found in {scope_name} of {doc_id}: {quote[:60]!r}")
        return doc_id

    def check_expect(self, where: str, expect, corpus: dict[str, dict]) -> set[str]:
        cited: set[str] = set()
        if not isinstance(expect, dict):
            self.error(where, "expect must be an object")
            return cited
        if not self.check_keys(where, expect, EXPECT_REQUIRED, EXPECT_OPTIONAL):
            return cited
        response_type = expect["response_type"]
        if response_type not in RESPONSE_TYPES:
            self.error(where, f"response_type must be one of {sorted(RESPONSE_TYPES)}")
        reference = expect["reference_answer"]
        if not isinstance(reference, str) or not reference.strip():
            self.error(where, "reference_answer must be a non-empty string")
            reference = ""
        self.check_matchers(f"{where} must_include", expect["must_include"], "fact", True)
        self.check_matchers(
            f"{where} must_not_include", expect["must_not_include"], "claim", False
        )
        for key in EXPECT_OPTIONAL:
            if key in expect and not isinstance(expect[key], bool):
                self.error(where, f"{key} must be true or false")

        sources = expect["sources"]
        if not isinstance(sources, list):
            self.error(where, "sources must be a list")
            sources = []
        for position, source in enumerate(sources):
            doc_id = self.check_source(f"{where} sources[{position}]", source, corpus)
            if doc_id:
                cited.add(doc_id)

        if response_type == "grounded":
            if not sources:
                self.error(where, "a grounded turn needs at least one source")
            if not expect["must_include"]:
                self.error(where, "a grounded turn needs at least one must_include fact")
        if response_type in ("knowledge_gap", "clarification") and sources:
            self.error(where, f"a {response_type} turn must have no sources")
        if response_type == "knowledge_gap" and expect.get("offer_handoff") is not True:
            self.error(where, "a knowledge_gap turn must set offer_handoff to true")
        if expect.get("require_all_sources") and len(cited) < 2:
            self.error(where, "require_all_sources needs sources from at least two documents")

        # The reference answer must pass its own deterministic checks.
        if isinstance(expect["must_include"], list):
            for item in expect["must_include"]:
                patterns = item.get("match_any", []) if isinstance(item, dict) else []
                if isinstance(patterns, list) and patterns and not any(
                    isinstance(p, str) and matches(p, reference) for p in patterns
                ):
                    self.error(
                        where,
                        f"reference_answer matches none of {patterns} "
                        f"for fact {item.get('fact', '')[:50]!r}",
                    )
        if isinstance(expect["must_not_include"], list):
            for item in expect["must_not_include"]:
                patterns = item.get("match_any", []) if isinstance(item, dict) else []
                for pattern in patterns if isinstance(patterns, list) else []:
                    if isinstance(pattern, str) and matches(pattern, reference):
                        self.error(
                            where, f"reference_answer contains forbidden pattern {pattern!r}"
                        )
        return cited

    def check_case(
        self, where: str, case, file_category: str, corpus: dict[str, dict], fixtures: dict[str, dict]
    ) -> set[str]:
        cited: set[str] = set()
        if not isinstance(case, dict):
            self.error(where, "case must be an object")
            return cited
        if not self.check_keys(where, case, CASE_REQUIRED, CASE_OPTIONAL):
            return cited
        case_id = case["id"]
        where = f"{where} {case_id}"
        category = case["category"]
        if category != file_category:
            self.error(where, f"category {category!r} differs from the file category")
        prefix = ID_PREFIXES.get(category)
        if prefix and not re.fullmatch(rf"{prefix}-\d{{2}}", str(case_id)):
            self.error(where, f"id must look like {prefix}-01")
        if not isinstance(case["title"], str) or not case["title"].strip():
            self.error(where, "title must be a non-empty string")
        topics = case["topics"]
        if not isinstance(topics, list) or not topics or not all(
            isinstance(t, str) and SLUG_RE.match(t) for t in topics
        ):
            self.error(where, "topics must be a non-empty list of lowercase slugs")
        if "notes" in case and (not isinstance(case["notes"], str) or not case["notes"].strip()):
            self.error(where, "notes must be a non-empty string")

        turns = case["turns"]
        if not isinstance(turns, list) or not turns:
            self.error(where, "turns must be a non-empty list")
            return cited
        types: list[str] = []
        for position, turn in enumerate(turns, start=1):
            turn_where = f"{where} turn {position}"
            if not isinstance(turn, dict) or not self.check_keys(turn_where, turn, TURN_KEYS):
                continue
            if not isinstance(turn["user"], str) or not turn["user"].strip():
                self.error(turn_where, "user must be a non-empty string")
            cited |= self.check_expect(turn_where, turn["expect"], corpus)
            if isinstance(turn["expect"], dict):
                types.append(turn["expect"].get("response_type"))

        if category == "answerable" and (len(turns) != 1 or types != ["grounded"]):
            self.error(where, "an answerable case has exactly one grounded turn")
        if category == "unanswerable" and (len(turns) != 1 or types != ["knowledge_gap"]):
            self.error(where, "an unanswerable case has exactly one knowledge_gap turn")
        if category == "multi_turn" and len(turns) < 2:
            self.error(where, "a multi_turn case has at least two turns")

        fixture_ids = case.get("fixtures", [])
        if not isinstance(fixture_ids, list) or not all(isinstance(f, str) for f in fixture_ids):
            self.error(where, "fixtures must be a list of fixture doc_id strings")
            fixture_ids = []
        for fixture_id in fixture_ids:
            if fixture_id not in fixtures:
                self.error(where, f"fixture {fixture_id!r} is not in the fixture manifest")
        if category == "instruction_override":
            vector = case.get("attack_vector")
            if vector not in ATTACK_VECTORS:
                self.error(where, f"attack_vector must be one of {sorted(ATTACK_VECTORS)}")
            if vector == "document" and not fixture_ids:
                self.error(where, "a document attack needs at least one fixture")
            if vector == "user_message" and fixture_ids:
                self.error(where, "a user_message attack must not list fixtures")
        else:
            if "attack_vector" in case:
                self.error(where, "attack_vector is only valid for instruction_override cases")
            if fixture_ids:
                self.error(where, "fixtures are only valid for instruction_override cases")
        return cited


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES, help="directory with case files")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="corpus directory with manifest.json")
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES, help="fixture directory with manifest.json")
    args = parser.parse_args()

    validator = Validator()
    corpus = validator.load_manifest(args.corpus.resolve())
    fixtures = validator.load_manifest(args.fixtures.resolve())
    for doc_id in corpus.keys() & fixtures.keys():
        validator.error("fixtures", f"fixture doc_id {doc_id!r} collides with a corpus doc_id")

    counts = dict.fromkeys(EXPECTED_COUNTS, 0)
    vectors = dict.fromkeys(sorted(ATTACK_VECTORS), 0)
    seen_ids: dict[str, str] = {}
    cited: set[str] = set()
    case_files = sorted(args.cases.resolve().glob("*.json"))
    if not case_files:
        validator.error(str(args.cases), "no case files found")
    for path in case_files:
        data = validator.load_json(path)
        if not isinstance(data, dict) or not validator.check_keys(path.name, data, FILE_KEYS):
            continue
        file_category = data["category"]
        if file_category not in EXPECTED_COUNTS:
            validator.error(path.name, f"unknown category {file_category!r}")
            continue
        if not isinstance(data["cases"], list):
            validator.error(path.name, "cases must be a list")
            continue
        for case in data["cases"]:
            cited |= validator.check_case(path.name, case, file_category, corpus, fixtures)
            if not isinstance(case, dict) or "id" not in case:
                continue
            case_id = str(case["id"])
            if case_id in seen_ids:
                validator.error(path.name, f"duplicate id {case_id!r} (also in {seen_ids[case_id]})")
            seen_ids[case_id] = path.name
            counts[file_category] += 1
            if case.get("attack_vector") in vectors:
                vectors[case["attack_vector"]] += 1

    for category, expected in EXPECTED_COUNTS.items():
        if counts[category] != expected:
            validator.error("counts", f"{category}: expected {expected} cases, found {counts[category]}")
    for vector, count in vectors.items():
        if count == 0:
            validator.error("counts", f"no instruction_override case uses attack_vector {vector!r}")

    print(f"Corpus documents: {len(corpus)}; fixture documents: {len(fixtures)}")
    print(f"Cases: {sum(counts.values())} in {len(case_files)} files")
    for category, expected in EXPECTED_COUNTS.items():
        print(f"  {category}: {counts[category]} (expected {expected})")
    print("  instruction_override by attack vector: " + ", ".join(f"{k}={v}" for k, v in vectors.items()))
    uncited = sorted(corpus.keys() - cited)
    print(f"Corpus documents cited as an expected source: {len(corpus) - len(uncited)} of {len(corpus)}")
    if uncited:
        print("  not cited by any case: " + ", ".join(uncited))

    if validator.errors:
        print(f"\nFAILED: {len(validator.errors)} problem(s)")
        for message in validator.errors:
            print(f"  - {message}")
        return 1
    print("\nOK: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
