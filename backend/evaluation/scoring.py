"""Score one assistant reply against the expectation of its turn, and add up a run.

Everything here is a pure function over plain data, so the rules can be tested
without a database.

What the automated checks can and cannot decide:

- `response_type`, `offer_handoff`, retrieval and citation checks are decided.
- A `must_include` item is a first-pass filter: a hit passes, a miss fails, and
  the miss is listed for review because a correct reply can phrase the fact
  differently.
- A `must_not_include` item never fails on its own. A substring hit is a flag
  (the reply may mention the value in order to reject it), and an item without
  `match_any` cannot be checked at all. Both are listed for review, and the turn
  is reported as `review` until a reviewer or the LLM judge decides.
"""

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from evaluation.cases import Expectation, ExpectedSource, matches, normalize

PASS = "pass"  # noqa: S105 - a verdict, not a password
FAIL = "fail"
REVIEW = "review"
NOT_APPLICABLE = "not_applicable"

TOP_K = 5
"""Expected-source retrieval is measured in the top five results."""

HEADING_SEPARATOR = " > "
"""Joins the heading path of a chunk, as `app.services.documents.chunking` writes it."""

_PERSON = re.compile(
    r"\b(?:human|person|someone|somebody|team|colleague|agent|representative|specialist|staff)\b",
    re.IGNORECASE,
)
_OFFER = re.compile(
    r"\b(?:pass|forward|hand|connect|refer|route|escalate|transfer|follow up|reach out|"
    r"get back to you|contact you|put you in touch)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Passage:
    """A retrieved passage or a citation, reduced to what a source match needs."""

    doc_id: str | None
    section: str | None
    page_number: int | None


def source_matches(expected: ExpectedSource, passage: Passage) -> bool:
    """True when `passage` comes from the expected document and page or section.

    A PDF source with a page number is matched by the page. A source with a
    section is matched when the expected heading is one of the headings above
    the passage: the validator counts the text of a subsection as part of its
    parent section, and so does this rule.
    """
    if passage.doc_id != expected.doc_id:
        return False
    if expected.page is not None:
        return passage.page_number == expected.page
    if expected.section is not None:
        if not passage.section:
            return False
        wanted = normalize(expected.section)
        return any(normalize(part) == wanted for part in passage.section.split(HEADING_SEPARATOR))
    return True


def match_sources(expect: Expectation, passages: Sequence[Passage]) -> dict[str, Any]:
    """Compare `passages` (best first) with the expected sources of a turn.

    Default: one matched source is enough. With `require_all_sources`, every
    listed document needs a matched source.
    """
    if not expect.sources:
        return {"status": NOT_APPLICABLE, "sources": []}
    sources: list[dict[str, Any]] = []
    matched_documents: set[str] = set()
    for expected in expect.sources:
        rank = next(
            (
                position
                for position, passage in enumerate(passages, start=1)
                if source_matches(expected, passage)
            ),
            None,
        )
        if rank is not None:
            matched_documents.add(expected.doc_id)
        sources.append(
            {
                "doc_id": expected.doc_id,
                "section": expected.section,
                "page": expected.page,
                "matched": rank is not None,
                "rank": rank,
                "document_found": any(passage.doc_id == expected.doc_id for passage in passages),
            }
        )
    wanted_documents = {expected.doc_id for expected in expect.sources}
    if expect.require_all_sources:
        hit = matched_documents == wanted_documents
    else:
        hit = bool(matched_documents)
    return {"status": PASS if hit else FAIL, "sources": sources}


def offers_handoff(text: str) -> bool:
    """A first-pass pattern check: the reply names a person or team and offers to involve them."""
    return bool(_PERSON.search(text) and _OFFER.search(text))


def _first_match(patterns: Iterable[str], text: str) -> str | None:
    return next((pattern for pattern in patterns if matches(pattern, text)), None)


def score_turn(
    expect: Expectation,
    *,
    answer_type: str | None,
    text: str,
    citations: Sequence[tuple[Passage, str]],
    search_top: Sequence[Passage],
    reply_top: Sequence[Passage] | None,
) -> dict[str, Any]:
    """Every automated check of one reply.

    `citations` pairs each citation with its excerpt. `search_top` is the result
    of searching for the visitor message alone; `reply_top` is the retrieval the
    reply was built from, or None when the reply needed no retrieval.
    """
    response_type = {
        "status": PASS if answer_type == expect.response_type else FAIL,
        "expected": expect.response_type,
        "actual": answer_type,
    }
    handoff = {
        "status": (
            NOT_APPLICABLE if not expect.offer_handoff else PASS if offers_handoff(text) else FAIL
        )
    }

    retrieval_reply = match_sources(expect, list(reply_top or [])[:TOP_K])
    retrieval_reply["searched"] = reply_top is not None
    excerpts = " ".join(excerpt for _, excerpt in citations)

    must_include = []
    for index, item in enumerate(expect.must_include):
        matched = _first_match(item.match_any, text)
        must_include.append(
            {
                "id": f"must_include[{index}]",
                "fact": item.fact,
                "match_any": list(item.match_any),
                "status": PASS if matched else FAIL,
                "matched": matched,
                # The same string in a cited excerpt: the source states what the reply states.
                "in_cited_excerpt": (
                    _first_match(item.match_any, excerpts) is not None if matched else None
                ),
            }
        )

    must_not_include = []
    for index, claim in enumerate(expect.must_not_include):
        matched = _first_match(claim.match_any, text)
        if not claim.match_any:
            status, reason = REVIEW, "no_match_any"
        elif matched:
            status, reason = REVIEW, "flagged"
        else:
            status, reason = PASS, None
        must_not_include.append(
            {
                "id": f"must_not_include[{index}]",
                "claim": claim.claim,
                "match_any": list(claim.match_any),
                "status": status,
                "reason": reason,
                "matched": matched,
            }
        )

    return {
        "response_type": response_type,
        "offer_handoff": handoff,
        "retrieval_search": match_sources(expect, list(search_top)[:TOP_K]),
        "retrieval_reply": retrieval_reply,
        "citation": match_sources(expect, [passage for passage, _ in citations]),
        "must_include": must_include,
        "must_not_include": must_not_include,
    }


def review_items(checks: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The checks of a turn that a substring cannot settle."""
    items: list[dict[str, Any]] = []
    for item in checks["must_include"]:
        if item["status"] == FAIL:
            items.append(
                {"check": item["id"], "kind": "must_include_miss", "statement": item["fact"]}
            )
    for item in checks["must_not_include"]:
        if item["status"] == REVIEW:
            kind = "must_not_include_flag" if item["reason"] == "flagged" else "no_match_any"
            items.append(
                {
                    "check": item["id"],
                    "kind": kind,
                    "statement": item["claim"],
                    "matched": item["matched"],
                }
            )
    return items


def turn_status(checks: Mapping[str, Any], verdicts: Mapping[str, str] | None = None) -> str:
    """`pass`, `fail` or `review` for one turn.

    `verdicts` maps a check ID to `pass` or `fail`, as decided by a reviewer or a
    judge. Without them this is the automated first pass.
    """
    verdicts = verdicts or {}
    if checks["response_type"]["status"] == FAIL or checks["offer_handoff"]["status"] == FAIL:
        return FAIL
    statuses = [
        verdicts.get(item["id"], item["status"])
        for item in (*checks["must_include"], *checks["must_not_include"])
    ]
    if FAIL in statuses:
        return FAIL
    return REVIEW if REVIEW in statuses else PASS


def case_status(turn_statuses: Sequence[str]) -> str:
    if FAIL in turn_statuses:
        return FAIL
    return REVIEW if REVIEW in turn_statuses else PASS


# --- Totals -------------------------------------------------------------------


def _percentile(values: Sequence[int], share: float) -> int | None:
    """Nearest-rank percentile."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def timing_stats(values: Sequence[int | None]) -> dict[str, Any]:
    known = [value for value in values if value is not None]
    return {
        "count": len(known),
        "median_ms": _percentile(known, 0.5),
        "p95_ms": _percentile(known, 0.95),
        "max_ms": max(known) if known else None,
    }


def _ratio(statuses: Sequence[str]) -> dict[str, int]:
    applicable = [status for status in statuses if status != NOT_APPLICABLE]
    return {"passed": applicable.count(PASS), "total": len(applicable)}


def summarize_group(
    cases: Sequence[Mapping[str, Any]], status_key: str = "status"
) -> dict[str, Any]:
    """Totals for a group of case results. `status_key` selects first-pass or reviewed statuses."""
    turns = [turn for case in cases for turn in case["turns"]]
    checks = [turn["checks"] for turn in turns if turn.get("checks")]
    must_include = [item for check in checks for item in check["must_include"]]
    must_not = [item for check in checks for item in check["must_not_include"]]
    case_statuses = [case[status_key] for case in cases]
    return {
        "cases": len(cases),
        "turns": len(turns),
        "errors": sum(1 for turn in turns if turn.get("error")),
        "case_status": {
            PASS: case_statuses.count(PASS),
            FAIL: case_statuses.count(FAIL),
            REVIEW: case_statuses.count(REVIEW),
        },
        "response_type": _ratio([check["response_type"]["status"] for check in checks]),
        "offer_handoff": _ratio([check["offer_handoff"]["status"] for check in checks]),
        "retrieval_search": _ratio([check["retrieval_search"]["status"] for check in checks]),
        "retrieval_reply": _ratio([check["retrieval_reply"]["status"] for check in checks]),
        "citation": _ratio([check["citation"]["status"] for check in checks]),
        "must_include": _ratio([item["status"] for item in must_include]),
        "must_include_in_cited_excerpt": {
            "passed": sum(1 for item in must_include if item["in_cited_excerpt"]),
            "total": sum(1 for item in must_include if item["in_cited_excerpt"] is not None),
        },
        "must_not_include": {
            "total": len(must_not),
            "clear": sum(1 for item in must_not if item["status"] == PASS),
            "flagged": sum(1 for item in must_not if item["reason"] == "flagged"),
            "no_match_any": sum(1 for item in must_not if item["reason"] == "no_match_any"),
        },
    }


def verdict_digest(cases: Sequence[Mapping[str, Any]]) -> str:
    """A fingerprint of everything a verdict depends on, without times and database IDs.

    Two runs with the same digest gave the same replies, citations, retrieval
    results and check outcomes.
    """

    def passages(items: Sequence[Mapping[str, Any]] | None) -> list[list[Any]] | None:
        if items is None:
            return None
        return [[item["doc_id"], item["section"], item["page_number"]] for item in items]

    material: list[Any] = []
    for case in cases:
        for turn in case["turns"]:
            reply = turn.get("reply") or {}
            checks = turn.get("checks") or {}
            material.append(
                [
                    case["id"],
                    turn["index"],
                    turn.get("error"),
                    reply.get("answer_type"),
                    reply.get("text"),
                    passages(reply.get("citations") or []),
                    passages(turn["retrieval"]["search_top"]),
                    passages(turn["retrieval"]["reply_top"]),
                    turn["status"],
                    [
                        [item["id"], item["status"]]
                        for key in ("must_include", "must_not_include")
                        for item in checks.get(key, [])
                    ],
                    [
                        checks[key]["status"]
                        for key in (
                            "response_type",
                            "offer_handoff",
                            "retrieval_search",
                            "retrieval_reply",
                            "citation",
                        )
                        if key in checks
                    ],
                ]
            )
    encoded = json.dumps(material, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
