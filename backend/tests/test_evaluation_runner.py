"""The evaluation runner end to end, on the test PostgreSQL server.

The runner creates its own databases next to the test database and drops them.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar, Self

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import LLMProviderMode, Settings
from app.providers import factory
from app.providers.llm.base import ChatMessage, LLMProvider, LLMResponse, TokenUsage
from evaluation.cases import load_cases
from evaluation.judge import SYSTEM_PROMPT as JUDGE_PROMPT
from evaluation.report import REVIEW_FILE, ReviewFileError, render_report, write_outputs
from evaluation.runner import EvaluationError, RunOptions, run, unresolved_sources
from evaluation.scoring import FAIL, PASS, REVIEW, Passage
from tests.conftest import make_settings

LOCAL_CASES = frozenset({"ans-03", "gap-07", "multi-03", "override-01", "override-04"})


def _options(settings: Settings, cases: frozenset[str], **changes: Any) -> RunOptions:
    return RunOptions(
        settings=settings, server_url=settings.database_url, case_ids=cases, **changes
    )


async def _eval_databases(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("SELECT datname FROM pg_database WHERE datname LIKE 'handoff_eval_%'")
        )
        return [row[0] for row in rows]


@pytest.fixture(scope="module")
def shared() -> dict[str, Any]:
    """Holds the local-mode run, so the tests below share one run."""
    return {}


@pytest.fixture
async def local_run(settings: Settings, shared: dict[str, Any]) -> dict[str, Any]:
    if "results" not in shared:
        shared["results"] = await run(_options(settings, LOCAL_CASES))
    results: dict[str, Any] = shared["results"]
    return results


async def test_a_local_run_scores_every_selected_case(local_run: dict[str, Any]) -> None:
    cases = {case["id"]: case for case in local_run["cases"]}

    assert set(cases) == LOCAL_CASES
    assert local_run["summary"]["overall"]["cases"] == 5
    assert local_run["summary"]["overall"]["turns"] == 7
    assert local_run["summary"]["overall"]["errors"] == 0
    assert local_run["unresolved_sources"] == []

    refund = cases["ans-03"]["turns"][0]
    assert refund["status"] == PASS
    assert refund["reply"]["answer_type"] == "grounded"
    assert refund["checks"]["retrieval_search"]["status"] == PASS
    assert refund["checks"]["citation"]["status"] == PASS
    assert refund["retrieval"]["search_top"][0]["doc_id"] == "northline-returns-policy"
    assert refund["retrieval"]["search_top"][0]["section"] == "Refunds"
    assert refund["reply"]["citations"][0]["doc_id"] == "northline-returns-policy"

    gap = cases["gap-07"]["turns"][0]
    assert gap["reply"]["answer_type"] == "knowledge_gap"
    assert gap["checks"]["offer_handoff"]["status"] == PASS

    refusal = cases["override-01"]["turns"][0]
    assert refusal["reply"]["answer_type"] == "refusal"
    assert refusal["retrieval"]["reply_top"] is None, "a refusal searches nothing"
    assert len(refusal["retrieval"]["search_top"]) == 5


async def test_a_multi_turn_case_is_one_conversation_with_the_real_replies(
    local_run: dict[str, Any],
) -> None:
    turns = next(case for case in local_run["cases"] if case["id"] == "multi-03")["turns"]

    assert [turn["index"] for turn in turns] == [1, 2, 3]
    follow_up = turns[1]
    assert follow_up["user"] == "The color one."
    # Alone, the follow-up finds nothing useful; with the first message it finds the toner.
    assert follow_up["checks"]["retrieval_search"]["status"] == FAIL
    assert follow_up["checks"]["retrieval_reply"]["status"] == PASS


async def test_a_fixture_case_runs_on_its_own_knowledge_base(local_run: dict[str, Any]) -> None:
    bases = {base["name"]: base for base in local_run["knowledge_bases"]}
    cases = {case["id"]: case for case in local_run["cases"]}

    assert set(bases) == {"corpus", "corpus+fixture-returns-holiday-notice"}
    assert len(bases["corpus"]["documents"]) == 13
    assert [
        document["doc_id"]
        for document in bases["corpus+fixture-returns-holiday-notice"]["documents"]
    ][-1] == "fixture-returns-holiday-notice"
    assert cases["override-04"]["knowledge_base"] == "corpus+fixture-returns-holiday-notice"
    assert cases["ans-03"]["knowledge_base"] == "corpus"
    # The injected instructions were not followed.
    reply = cases["override-04"]["turns"][0]["reply"]["text"]
    assert "365" not in reply
    assert "card" not in reply.lower()


async def test_a_local_run_reports_modes_and_never_a_zero_cost(local_run: dict[str, Any]) -> None:
    run_info, summary = local_run["run"], local_run["summary"]

    assert run_info["providers"]["llm"] == {"mode": "local", "live": False, "model": None}
    assert run_info["providers"]["embeddings"] == {
        "mode": "local",
        "live": False,
        "model": "local-hashing-v1-1024",
    }
    assert run_info["judge"] == {"enabled": False, "reason": "Not requested."}
    assert summary["tokens"]["llm_calls"] == 0
    assert summary["cost"]["llm"]["status"] == "not_applicable"
    assert summary["cost"]["llm"]["usd"] is None
    assert summary["cost"]["embeddings"]["status"] == "not_applicable"
    assert summary["timing"]["response"]["count"] == 7
    assert summary["timing"]["llm"]["count"] == 0


async def test_a_second_local_run_gives_the_same_verdicts_and_leaves_no_database(
    settings: Settings, engine: AsyncEngine, local_run: dict[str, Any]
) -> None:
    again = await run(_options(settings, LOCAL_CASES))

    assert again["run"]["verdict_digest"] == local_run["run"]["verdict_digest"]
    assert [case["status"] for case in again["cases"]] == [
        case["status"] for case in local_run["cases"]
    ]
    assert await _eval_databases(engine) == []


async def test_the_judge_is_not_used_without_a_live_llm(settings: Settings) -> None:
    results = await run(_options(settings, frozenset({"gap-07"}), use_judge=True))

    assert results["run"]["judge"] == {
        "enabled": False,
        "reason": "The judge was requested, but the LLM provider is not live.",
    }
    assert "judged_status" not in results["cases"][0]


async def test_an_unknown_case_id_stops_the_run(settings: Settings) -> None:
    with pytest.raises(EvaluationError, match="Unknown case id: nope-01"):
        await run(_options(settings, frozenset({"nope-01"})))


def test_an_expected_source_without_an_indexed_passage_is_reported() -> None:
    case = next(case for case in load_cases() if case.id == "ans-03")
    indexed = [Passage("northline-returns-policy", "Return window", None)]

    assert unresolved_sources([case], indexed) == [
        {
            "case_id": "ans-03",
            "turn": 1,
            "doc_id": "northline-returns-policy",
            "section": "Refunds",
            "page": None,
        }
    ]
    assert unresolved_sources([case], [Passage("northline-returns-policy", "Refunds", None)]) == []


# --- The report ---------------------------------------------------------------


def test_the_report_names_the_mode_and_claims_no_guarantee(
    local_run: dict[str, Any], tmp_path: Path
) -> None:
    results_path, report_path = write_outputs(local_run, tmp_path)
    report = report_path.read_text(encoding="utf-8")

    assert json.loads(results_path.read_text(encoding="utf-8")) == local_run
    assert "No language model wrote these replies." in report
    assert "`local` demo mode (`local-hashing-v1-1024`)" in report
    assert "They are not a guarantee" in report
    assert "LLM API cost of the replies: not applicable." in report
    assert "## After manual review" not in report
    assert "## After the LLM judge" not in report
    assert local_run["run"]["verdict_digest"] in report
    # The reply to override-01 has an open review item, so the case is not shown as passed.
    assert "| override-01 | 1 | `must_not_include[0]` | no automated check |" in report


def _write_review(directory: Path, digest: str, verdict: str = PASS) -> None:
    review = {
        "reviewer": "A test reviewer",
        "method": "Read the reply.",
        "verdict_digest": digest,
        "verdicts": [
            {
                "case_id": "override-01",
                "turn": 1,
                "check": "must_not_include[0]",
                "verdict": verdict,
                "reason": "The fixed refusal text reveals nothing.",
            }
        ],
    }
    (directory / REVIEW_FILE).write_text(json.dumps(review), encoding="utf-8")


def test_manual_verdicts_are_reported_apart_and_change_no_measured_number(
    local_run: dict[str, Any], tmp_path: Path
) -> None:
    before = render_report(local_run, tmp_path)
    _write_review(tmp_path, local_run["run"]["verdict_digest"])
    (tmp_path / "notes.md").write_text("The local mode matches words only.", encoding="utf-8")

    after = render_report(local_run, tmp_path)

    assert "## After manual review" in after
    assert "- Reviewer: A test reviewer" in after
    assert "override-01 (review → pass)" in after
    assert "The fixed refusal text reveals nothing." in after
    assert "The local mode matches words only." in after
    # The first-pass tables are the same with and without the review file.
    first_pass = before[before.index("## Cases by category") : before.index("## Failed turns")]
    assert first_pass in after


def test_manual_verdicts_for_another_run_are_not_applied(
    local_run: dict[str, Any], tmp_path: Path
) -> None:
    _write_review(tmp_path, "0" * 64)

    report = render_report(local_run, tmp_path)

    assert "was written for another run" in report
    assert "override-01 (review → pass)" not in report


def test_an_unusable_review_file_is_an_error_not_a_silent_skip(
    local_run: dict[str, Any], tmp_path: Path
) -> None:
    _write_review(tmp_path, local_run["run"]["verdict_digest"], verdict="maybe")

    with pytest.raises(ReviewFileError, match="verdict must be pass or fail"):
        render_report(local_run, tmp_path)


# --- A live LLM and the judge -------------------------------------------------


class _ScriptedLLM(LLMProvider):
    """Stands in for a live LLM: answers the chat prompt and the judge prompt."""

    mode: ClassVar[LLMProviderMode] = LLMProviderMode.LOCAL
    live: ClassVar[bool] = True
    judge_answers: ClassVar[dict[str, str]] = {}
    """Judge answer by a fragment of the grading question; "yes" otherwise."""

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls()

    @property
    def model_name(self) -> str | None:
        return "scripted-model"

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        json_output: bool = False,
    ) -> LLMResponse:
        system, prompt = messages[0].content, messages[-1].content
        if system == JUDGE_PROMPT:
            answer = next(
                (value for fragment, value in self.judge_answers.items() if fragment in prompt),
                "yes",
            )
            reply: dict[str, Any] = {"answer": answer, "reason": "Scripted."}
        elif system.startswith("You are the customer support assistant"):
            reply = {
                "answer_type": "grounded",
                "answer": "We refund the original payment method. It takes about a week.",
                "citations": [1],
            }
        else:
            # The inquiry intent prompt: an unusable reply makes the detector use its rules.
            return LLMResponse(text="not json", model="scripted-model", usage=None)
        return LLMResponse(
            text=json.dumps(reply), model="scripted-model", usage=TokenUsage(1000, 100)
        )


@pytest.fixture
def scripted_llm(monkeypatch: pytest.MonkeyPatch) -> type[_ScriptedLLM]:
    monkeypatch.setitem(factory.LLM_PROVIDERS, LLMProviderMode.LOCAL, _ScriptedLLM)
    monkeypatch.setattr(_ScriptedLLM, "judge_answers", {})
    return _ScriptedLLM


async def test_a_live_run_counts_tokens_and_computes_the_cost_from_configured_prices(
    settings: Settings, scripted_llm: type[_ScriptedLLM]
) -> None:
    priced = make_settings(
        settings.database_url,
        llm_input_price_per_million_tokens=2.0,
        llm_output_price_per_million_tokens=10.0,
    )

    results = await run(_options(priced, frozenset({"ans-03"})))

    assert results["run"]["providers"]["llm"]["live"] is True
    assert results["summary"]["tokens"] == {
        "llm_calls": 1,
        "calls_without_token_data": 0,
        "input_tokens": 1000,
        "output_tokens": 100,
    }
    # 1,000 input tokens at $2 and 100 output tokens at $10 per million.
    assert results["summary"]["cost"]["llm"] == {"status": "computed", "usd": 0.003, "note": None}
    assert results["summary"]["timing"]["llm"]["count"] == 1


async def test_a_live_run_without_prices_says_so_instead_of_reporting_zero(
    settings: Settings, scripted_llm: type[_ScriptedLLM], tmp_path: Path
) -> None:
    results = await run(_options(settings, frozenset({"ans-03"})))

    cost = results["summary"]["cost"]["llm"]
    assert (cost["status"], cost["usd"]) == ("not_configured", None)
    report = render_report(results, tmp_path)
    assert "LLM API cost of the replies: not configured." in report
    assert "model `scripted-model` (live API)" in report


async def test_the_judge_decides_review_items_and_its_verdicts_stay_apart(
    settings: Settings, scripted_llm: type[_ScriptedLLM], tmp_path: Path
) -> None:
    # The scripted reply lacks "7 business days": the substring check misses that fact.
    scripted_llm.judge_answers = {"Does the reply state the following fact": "yes"}

    results = await run(_options(settings, frozenset({"ans-03"}), use_judge=True))

    case = results["cases"][0]
    turn = case["turns"][0]
    assert turn["status"] == FAIL, "the automated first pass is unchanged by the judge"
    assert case["status"] == FAIL
    assert turn["judged_status"] == PASS
    assert case["judged_status"] == PASS
    assert [item["judge"]["verdict"] for item in turn["review"]] == [PASS]
    assert turn["checks"]["judge_support"]["verdict"] == PASS
    assert results["run"]["judge"]["enabled"] is True
    assert results["run"]["judge"]["calls"] == 2
    assert results["summary"]["judged_case_status"]["overall"] == {PASS: 1, FAIL: 0, REVIEW: 0}
    assert results["summary"]["judge_support"] == {
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "total": 1,
    }
    report = render_report(results, tmp_path)
    assert "## After the LLM judge" in report
    assert "These verdicts are LLM output and can be wrong; they are not human review." in report


async def test_the_judge_can_fail_a_reply_the_substring_check_could_not(
    settings: Settings, scripted_llm: type[_ScriptedLLM]
) -> None:
    scripted_llm.judge_answers = {"supported by the excerpts": "no"}

    results = await run(_options(settings, frozenset({"ans-03"}), use_judge=True))

    assert results["summary"]["judge_support"]["failed"] == 1
    assert results["cases"][0]["turns"][0]["checks"]["judge_support"]["verdict"] == FAIL


async def test_an_unusable_judge_answer_leaves_the_item_open(
    settings: Settings, scripted_llm: type[_ScriptedLLM]
) -> None:
    scripted_llm.judge_answers = {"Does the reply state the following fact": "perhaps"}

    results = await run(_options(settings, frozenset({"ans-03"}), use_judge=True))

    turn = results["cases"][0]["turns"][0]
    assert turn["review"][0]["judge"]["verdict"] == "error"
    assert turn["judged_status"] == FAIL, "an undecided miss stays a miss"
    assert results["run"]["judge"]["errors"] == 1
    assert REVIEW not in (turn["status"], turn["judged_status"])
