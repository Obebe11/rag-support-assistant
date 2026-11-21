"""The rules the evaluation runner scores a reply with."""

from collections import Counter

import pytest

from evaluation.cases import (
    ExcludeCheck,
    Expectation,
    ExpectedSource,
    IncludeCheck,
    load_cases,
    matches,
)
from evaluation.scoring import (
    FAIL,
    NOT_APPLICABLE,
    PASS,
    REVIEW,
    Passage,
    case_status,
    match_sources,
    offers_handoff,
    review_items,
    score_turn,
    source_matches,
    summarize_group,
    timing_stats,
    turn_status,
    verdict_digest,
)

RETURNS = ExpectedSource("returns", "Return window", None, "30 days")
WARRANTY_PAGE = ExpectedSource("warranty", "Advance replacement", 3, "next business day")


def _expectation(**changes: object) -> Expectation:
    values: dict[str, object] = {
        "response_type": "grounded",
        "reference_answer": "You have 30 days.",
        "must_include": (IncludeCheck("The window is 30 days.", ("30 days", "30-day")),),
        "must_not_include": (),
        "sources": (RETURNS,),
        "require_all_sources": False,
        "offer_handoff": False,
    }
    values.update(changes)
    return Expectation(**values)  # type: ignore[arg-type]


def _score(expect: Expectation, text: str, **changes: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "answer_type": expect.response_type,
        "text": text,
        "citations": [],
        "search_top": [],
        "reply_top": [],
    }
    arguments.update(changes)
    return score_turn(expect, **arguments)  # type: ignore[arg-type]


def test_the_committed_cases_load_with_the_planned_counts() -> None:
    cases = load_cases()

    assert Counter(case.category for case in cases) == {
        "answerable": 20,
        "unanswerable": 10,
        "multi_turn": 5,
        "instruction_override": 5,
    }
    assert len({case.id for case in cases}) == 40
    fixtures = {case.id: case.fixtures for case in cases if case.fixtures}
    assert fixtures == {
        "override-04": ("fixture-returns-holiday-notice",),
        "override-05": ("fixture-lp420-setup-notes",),
    }


def test_every_reference_answer_passes_its_own_match_any_checks() -> None:
    """The runner and the validator share one `match_any` rule."""
    for case in load_cases():
        for turn in case.turns:
            for item in turn.expect.must_include:
                assert any(
                    matches(pattern, turn.expect.reference_answer) for pattern in item.match_any
                ), f"{case.id}: {item.fact}"


@pytest.mark.parametrize(
    ("passage", "expected"),
    [
        (Passage("returns", "Return window", None), True),
        (Passage("returns", "Returns > Return window", None), True),
        # A subsection belongs to the section above it, as in the validator.
        (Passage("returns", "Return window > Exceptions", None), True),
        (Passage("returns", "**Return  window**", None), True),
        (Passage("returns", "Return shipping", None), False),
        (Passage("returns", None, None), False),
        (Passage("faq", "Return window", None), False),
        (Passage(None, "Return window", None), False),
    ],
)
def test_a_section_source_matches_the_heading_path(passage: Passage, expected: bool) -> None:
    assert source_matches(RETURNS, passage) is expected


def test_a_pdf_source_with_a_page_is_matched_by_the_page() -> None:
    assert source_matches(WARRANTY_PAGE, Passage("warranty", "Any heading", 3))
    assert source_matches(WARRANTY_PAGE, Passage("warranty", None, 3))
    assert not source_matches(WARRANTY_PAGE, Passage("warranty", "Advance replacement", 2))


def test_a_source_without_section_or_page_matches_the_document() -> None:
    assert source_matches(ExpectedSource("faq", None, None, "x"), Passage("faq", "Anything", 2))


def test_one_matched_source_is_enough_by_default() -> None:
    expect = _expectation(sources=(RETURNS, WARRANTY_PAGE))
    passages = [Passage("faq", "Other", None), Passage("warranty", None, 3)]

    result = match_sources(expect, passages)

    assert result["status"] == PASS
    assert [(source["matched"], source["rank"]) for source in result["sources"]] == [
        (False, None),
        (True, 2),
    ]


def test_require_all_sources_needs_every_listed_document() -> None:
    expect = _expectation(sources=(RETURNS, WARRANTY_PAGE), require_all_sources=True)

    one = match_sources(expect, [Passage("warranty", None, 3)])
    both = match_sources(
        expect, [Passage("warranty", None, 3), Passage("returns", "Return window", None)]
    )

    assert one["status"] == FAIL
    assert both["status"] == PASS


def test_the_right_document_with_the_wrong_section_is_a_miss_but_is_reported() -> None:
    result = match_sources(_expectation(), [Passage("returns", "Refunds", None)])

    assert result["status"] == FAIL
    assert result["sources"][0]["document_found"] is True


def test_a_turn_without_expected_sources_has_no_retrieval_verdict() -> None:
    assert match_sources(_expectation(sources=()), [])["status"] == NOT_APPLICABLE


def test_a_matched_fact_passes_and_a_missing_fact_fails_and_is_listed_for_review() -> None:
    expect = _expectation()

    hit = _score(expect, "You have a 30-DAY window.")
    miss = _score(expect, "You have one month.")

    assert turn_status(hit) == PASS
    assert turn_status(miss) == FAIL
    assert review_items(miss) == [
        {
            "check": "must_include[0]",
            "kind": "must_include_miss",
            "statement": "The window is 30 days.",
        }
    ]


def test_a_forbidden_string_is_a_flag_for_review_never_an_automatic_failure() -> None:
    expect = _expectation(
        must_not_include=(ExcludeCheck("Gives the old 45-day window.", ("45 days",)),)
    )

    checks = _score(expect, "You have 30 days. The 45 days of the old policy no longer apply.")

    assert turn_status(checks) == REVIEW
    assert review_items(checks) == [
        {
            "check": "must_not_include[0]",
            "kind": "must_not_include_flag",
            "statement": "Gives the old 45-day window.",
            "matched": "45 days",
        }
    ]
    assert turn_status(checks, {"must_not_include[0]": PASS}) == PASS
    assert turn_status(checks, {"must_not_include[0]": FAIL}) == FAIL


def test_a_claim_without_match_any_is_never_decided_automatically() -> None:
    expect = _expectation(must_not_include=(ExcludeCheck("Promises a refund.", ()),))

    checks = _score(expect, "You have 30 days.")

    assert turn_status(checks) == REVIEW
    assert review_items(checks)[0]["kind"] == "no_match_any"


def test_a_reviewer_can_confirm_a_fact_the_substring_missed() -> None:
    checks = _score(_expectation(), "You have one month, thirty days in all.")

    assert turn_status(checks) == FAIL
    assert turn_status(checks, {"must_include[0]": PASS}) == PASS


def test_a_wrong_response_type_fails_whatever_the_text_says() -> None:
    checks = _score(_expectation(), "You have 30 days.", answer_type="knowledge_gap")

    assert checks["response_type"] == {
        "status": FAIL,
        "expected": "grounded",
        "actual": "knowledge_gap",
    }
    assert turn_status(checks, {"must_include[0]": PASS}) == FAIL


def test_a_knowledge_gap_must_offer_a_human_handoff() -> None:
    expect = _expectation(
        response_type="knowledge_gap", must_include=(), sources=(), offer_handoff=True
    )

    offered = _score(expect, "The documents do not cover that. I can pass it to a person.")
    silent = _score(expect, "The documents do not cover that.")

    assert turn_status(offered) == PASS
    assert turn_status(silent) == FAIL


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I can pass your question to a member of the team.", True),
        ("Would you like me to connect you with a sales representative?", True),
        ("You can try the handoff form, but no person will receive your request.", True),
        ("Our team is great.", False),
        ("I will pass on that question.", False),
    ],
)
def test_the_handoff_pattern_needs_a_person_and_an_offer(text: str, expected: bool) -> None:
    assert offers_handoff(text) is expected


def test_citations_and_cited_excerpts_are_checked_against_the_expected_source() -> None:
    expect = _expectation()
    cited = [(Passage("returns", "Return window", None), "You have 30 days from delivery.")]
    elsewhere = [(Passage("faq", "Other", None), "Returns need an RMA number.")]

    supported = _score(expect, "You have 30 days.", citations=cited)
    unsupported = _score(expect, "You have 30 days.", citations=elsewhere)

    assert supported["citation"]["status"] == PASS  # type: ignore[index]
    assert supported["must_include"][0]["in_cited_excerpt"] is True  # type: ignore[index]
    assert unsupported["citation"]["status"] == FAIL  # type: ignore[index]
    assert unsupported["must_include"][0]["in_cited_excerpt"] is False  # type: ignore[index]


def test_a_reply_that_did_not_search_counts_as_a_retrieval_miss() -> None:
    checks = _score(_expectation(), "I can't help with that.", reply_top=None)

    assert checks["retrieval_reply"]["status"] == FAIL  # type: ignore[index]
    assert checks["retrieval_reply"]["searched"] is False  # type: ignore[index]


def test_only_the_top_five_passages_count() -> None:
    passages = [Passage("faq", f"Other {index}", None) for index in range(5)]
    passages.append(Passage("returns", "Return window", None))

    checks = _score(_expectation(), "You have 30 days.", search_top=passages, reply_top=passages)

    assert checks["retrieval_search"]["status"] == FAIL  # type: ignore[index]
    assert checks["retrieval_reply"]["status"] == FAIL  # type: ignore[index]


def test_a_case_is_as_good_as_its_worst_turn() -> None:
    assert case_status([PASS, PASS]) == PASS
    assert case_status([PASS, REVIEW]) == REVIEW
    assert case_status([REVIEW, FAIL, PASS]) == FAIL


def test_timing_uses_nearest_rank_percentiles_and_skips_missing_values() -> None:
    assert timing_stats([10, None, 30, 20, 40]) == {
        "count": 4,
        "median_ms": 20,
        "p95_ms": 40,
        "max_ms": 40,
    }
    assert timing_stats([None]) == {"count": 0, "median_ms": None, "p95_ms": None, "max_ms": None}


def _case(text: str, *, time_ms: int = 5) -> dict[str, object]:
    checks = _score(_expectation(), text)
    return {
        "id": "ans-01",
        "category": "answerable",
        "status": turn_status(checks),
        "turns": [
            {
                "index": 1,
                "error": None,
                "status": turn_status(checks),
                "checks": checks,
                "review": review_items(checks),
                "reply": {
                    "answer_type": "grounded",
                    "text": text,
                    "citations": [],
                    "usage": {"response_time_ms": time_ms},
                },
                "retrieval": {"search_top": [], "reply_top": None},
            }
        ],
    }


def test_the_digest_ignores_times_and_changes_with_the_reply() -> None:
    base = verdict_digest([_case("You have 30 days.")])

    assert verdict_digest([_case("You have 30 days.", time_ms=900)]) == base
    assert verdict_digest([_case("You have 30 days!")]) != base


def test_totals_count_cases_turns_and_check_outcomes() -> None:
    summary = summarize_group([_case("You have 30 days."), _case("You have one month.")])

    assert summary["cases"] == 2
    assert summary["case_status"] == {PASS: 1, FAIL: 1, REVIEW: 0}
    assert summary["response_type"] == {"passed": 2, "total": 2}
    assert summary["must_include"] == {"passed": 1, "total": 2}
    assert summary["retrieval_search"] == {"passed": 0, "total": 2}
    assert summary["offer_handoff"] == {"passed": 0, "total": 0}
