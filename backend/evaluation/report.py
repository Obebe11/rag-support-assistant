"""Render the results of a run as a Markdown report.

The report is built only from the results document, plus two optional files a
person may put next to it:

- `manual-review.json`: verdicts of a reviewer on the checks that need review;
- `notes.md`: free-form analysis, included as written.

Both are labeled as such in the report, so measured results, LLM judge output
and human judgment stay apart.
"""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evaluation.scoring import FAIL, PASS, REVIEW, case_status, turn_status

RESULTS_FILE = "results.json"
REPORT_FILE = "report.md"
REVIEW_FILE = "manual-review.json"
NOTES_FILE = "notes.md"

_CATEGORY_LABELS = {
    "answerable": "Answerable",
    "unanswerable": "Knowledge gap",
    "multi_turn": "Multi-turn",
    "instruction_override": "Instruction override",
}
_KIND_LABELS = {
    "must_include_miss": "expected fact not matched",
    "must_not_include_flag": "forbidden string matched",
    "no_match_any": "no automated check",
}


class ReviewFileError(Exception):
    """The manual review file cannot be used."""


def _share(ratio: Mapping[str, int]) -> str:
    total = ratio["total"]
    if not total:
        return "n/a"
    return f"{ratio['passed']}/{total} ({round(100 * ratio['passed'] / total)}%)"


def _cell(text: object) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def _shorten(text: str, limit: int = 320) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return lines


def _ms(value: object) -> str:
    return "n/a" if value is None else f"{value} ms"


def _source_label(source: Mapping[str, Any]) -> str:
    label = str(source["doc_id"])
    if source.get("page") is not None or source.get("page_number") is not None:
        label += f", page {source.get('page', source.get('page_number'))}"
    if source.get("section"):
        label += f", section “{source['section']}”"
    return label


# --- Manual review ------------------------------------------------------------


def load_review(directory: Path, results: Mapping[str, Any]) -> dict[str, Any] | None:
    """Read `manual-review.json` next to the results, if there is one.

    The file names the `verdict_digest` of the run it was written for. Verdicts
    for another run are not applied: the replies they judged may have changed.
    """
    path = directory / REVIEW_FILE
    if not path.is_file():
        return None
    try:
        review = json.loads(path.read_text(encoding="utf-8"))
        verdicts = {
            (str(item["case_id"]), int(item["turn"]), str(item["check"])): item
            for item in review["verdicts"]
        }
        for item in verdicts.values():
            if item["verdict"] not in (PASS, FAIL):
                raise ValueError(f"verdict must be pass or fail, got {item['verdict']!r}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReviewFileError(f"Cannot read {path}: {exc}") from exc
    return {
        "reviewer": str(review.get("reviewer", "not stated")),
        "method": str(review.get("method", "not stated")),
        "verdicts": verdicts,
        "current": review.get("verdict_digest") == results["run"]["verdict_digest"],
    }


def _reviewed_statuses(
    results: Mapping[str, Any], verdicts: Mapping[tuple[str, int, str], Mapping[str, Any]]
) -> dict[str, str]:
    """Case statuses after the reviewer's verdicts replace the open review items."""
    statuses: dict[str, str] = {}
    for case in results["cases"]:
        turn_statuses = []
        for turn in case["turns"]:
            if not turn["checks"]:
                turn_statuses.append(FAIL)
                continue
            decided = {
                check: item["verdict"]
                for (case_id, index, check), item in verdicts.items()
                if case_id == case["id"] and index == turn["index"]
            }
            turn_statuses.append(turn_status(turn["checks"], decided))
        statuses[case["id"]] = case_status(turn_statuses)
    return statuses


# --- Sections -----------------------------------------------------------------


def _mode_lines(run: Mapping[str, Any]) -> list[str]:
    llm, embeddings = run["providers"]["llm"], run["providers"]["embeddings"]
    lines = []
    if llm["live"]:
        lines.append(
            f"- **LLM: `{llm['mode']}`, model `{llm['model']}` (live API).** "
            "The replies were written by this model."
        )
    else:
        lines.append(
            f"- **LLM: `{llm['mode']}` demo mode. No language model wrote these replies.** "
            "Each grounded reply quotes retrieved passages word for word, and the other "
            "reply types are fixed texts. This run measures retrieval and the rules of the "
            "local mode. It does not measure the answer quality of a live LLM."
        )
    if embeddings["live"]:
        lines.append(
            f"- **Embeddings: `{embeddings['mode']}`, model `{embeddings['model']}` (live API).**"
        )
    else:
        lines.append(
            f"- **Embeddings: `{embeddings['mode']}` demo mode (`{embeddings['model']}`).** "
            "Passages are matched by shared word stems, not by meaning: a synonym or a "
            "paraphrase is not found."
        )
    lines.append(
        "- **CRM: simulated, not exercised.** The cases confirm no inquiry, so nothing is "
        "sent to a CRM."
    )
    judge = run["judge"]
    if judge["enabled"]:
        lines.append(
            f"- **LLM judge: on, model `{judge['model']}`.** Its verdicts are LLM output, "
            "not human review, and are reported separately."
        )
    else:
        lines.append(f"- **LLM judge: off.** {judge['reason']}")
    return lines


def _metric_rows(summary: Mapping[str, Any]) -> list[list[object]]:
    groups = [*summary["by_category"].values(), summary["overall"]]

    def row(label: str, key: str) -> list[object]:
        return [label, *(_share(group[key]) for group in groups)]

    def forbidden(group: Mapping[str, Any]) -> str:
        counts = group["must_not_include"]
        if not counts["total"]:
            return "n/a"
        return (
            f"{counts['flagged']} flagged, {counts['no_match_any']} unchecked, "
            f"{counts['clear']} clear"
        )

    return [
        row("Response type matches (turns)", "response_type"),
        row("Human handoff offered (knowledge-gap turns)", "offer_handoff"),
        row("Expected source in top 5: search for the message alone", "retrieval_search"),
        row("Expected source in top 5: retrieval behind the reply", "retrieval_reply"),
        row("Reply cites an expected source", "citation"),
        row("`must_include` items matched", "must_include"),
        row("Matched items also found in a cited excerpt", "must_include_in_cited_excerpt"),
        ["`must_not_include` items", *(forbidden(group) for group in groups)],
    ]


def _cost_line(label: str, cost: Mapping[str, Any]) -> str:
    if cost["status"] == "computed":
        return f"- {label}: ${cost['usd']:.6f}"
    status = cost["status"].replace("_", " ")
    return f"- {label}: {status}. {cost['note']}"


def _failure_lines(results: Mapping[str, Any]) -> list[str]:
    cases = {case["id"]: case for case in results["cases"]}
    lines: list[str] = []
    for failure in results["failures"]:
        case = cases[failure["case_id"]]
        turn = case["turns"][failure["turn"] - 1]
        lines.append(f"### {case['id']}, turn {turn['index']}: {case['title']}")
        lines.append("")
        lines.append(f"- Visitor: {_shorten(turn['user'])}")
        lines += [f"- Failed: {_shorten(reason, 400)}" for reason in failure["reasons"]]
        if turn["reply"] is not None:
            lines.append(
                f"- Reply (`{turn['reply']['answer_type']}`): {_shorten(turn['reply']['text'])}"
            )
        lines.append("")
    return lines


def _ranked(passages: Sequence[Mapping[str, Any]]) -> str:
    return "; ".join(f"{item['rank']}. {_source_label(item)}" for item in passages)


def _retrieval_miss_lines(results: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for case in results["cases"]:
        for turn in case["turns"]:
            checks = turn["checks"]
            if not checks:
                continue
            missed = [
                label
                for label, key in (
                    ("search for the message alone", "retrieval_search"),
                    ("retrieval behind the reply", "retrieval_reply"),
                )
                if checks[key]["status"] == FAIL
            ]
            if not missed:
                continue
            lines.append(f"- **{case['id']}, turn {turn['index']}** ({'; '.join(missed)})")
            lines.append(f"  - Visitor: {_shorten(turn['user'], 200)}")
            expected = "; ".join(
                dict.fromkeys(_source_label(source) for source in turn["expected"]["sources"])
            )
            lines.append(f"  - Expected: {expected}")
            search_top, reply_top = turn["retrieval"]["search_top"], turn["retrieval"]["reply_top"]
            lines.append(f"  - Search top 5: {_ranked(search_top)}")
            if reply_top is None:
                lines.append("  - Reply top 5: the reply did not search")
            elif _ranked(reply_top) == _ranked(search_top):
                lines.append("  - Reply top 5: the same passages")
            else:
                lines.append(f"  - Reply top 5: {_ranked(reply_top)}")
    return lines


def _review_rows(
    results: Mapping[str, Any], review: Mapping[str, Any] | None
) -> tuple[list[str], list[list[object]]]:
    judged = results["run"]["judge"]["enabled"]
    apply_review = review is not None and review["current"]
    header = ["Case", "Turn", "Check", "Why", "Statement to confirm", "Matched"]
    if judged:
        header.append("LLM judge")
    if apply_review:
        header += ["Manual verdict", "Reviewer's reason"]
    rows: list[list[object]] = []
    for item in results["review"]:
        row: list[object] = [
            item["case_id"],
            item["turn"],
            f"`{item['check']}`",
            _KIND_LABELS[item["kind"]],
            item["statement"],
            f"`{item['matched']}`" if item.get("matched") else "",
        ]
        if judged:
            verdict = item.get("judge")
            row.append(f"{verdict['verdict']}: {verdict['reason']}" if verdict else "")
        if apply_review and review is not None:
            decided = review["verdicts"].get((item["case_id"], item["turn"], item["check"]))
            row += [decided["verdict"], decided.get("reason", "")] if decided else ["open", ""]
        rows.append(row)
    return header, rows


def render_report(results: Mapping[str, Any], directory: Path) -> str:
    """The Markdown report for `results`, with the optional files found in `directory`."""
    run, summary = results["run"], results["summary"]
    review = load_review(directory, results)
    notes_path = directory / NOTES_FILE
    categories = list(summary["by_category"])
    labels = [_CATEGORY_LABELS.get(category, category) for category in categories]

    lines: list[str] = ["# Evaluation report", ""]
    selection = (
        f"{summary['overall']['cases']} selected cases ({', '.join(run['case_filter'])})"
        if run["case_filter"]
        else f"all {summary['overall']['cases']} cases"
    )
    commit = run["git_commit"] or "unknown"
    if run["git_dirty"]:
        commit += " with uncommitted changes"
    lines += [
        f"- Run: {run['started_at']} to {run['finished_at']} (UTC), {selection}, "
        f"{summary['overall']['turns']} turns.",
        f"- Command: `{run['command']}`",
        f"- Source: commit `{commit}`.",
        f"- Verdict digest: `{run['verdict_digest']}`. Two runs with the same digest gave the "
        "same replies, citations, retrieval results and check outcomes.",
        f"- Machine-readable results: [`{RESULTS_FILE}`]({RESULTS_FILE}).",
        "",
        "## Run mode",
        "",
        *_mode_lines(run),
        "",
        "## What these numbers are",
        "",
        "These are measurements of one run on the evaluation cases in `evals/cases`, which "
        "were written against the Northline demo corpus. They describe this system on these "
        "questions and these documents. They are not a guarantee, and they do not predict "
        "behavior on other questions or other documents.",
        "",
        "The automated checks are a first pass. `match_any` is a substring match: a correct "
        "reply can word a fact differently, and a reply can mention a forbidden value in "
        "order to reject it. Checks that a substring cannot settle are listed under "
        "[Needs review](#needs-review) and are not counted as passed.",
        "",
        "## Cases by category (automated first pass)",
        "",
        "A case passes when every turn has the expected response type, offers a human "
        "handoff where one is expected, and matches every `must_include` item. A case is "
        "`needs review` when nothing failed but a `must_not_include` item is flagged or has "
        "no automated check.",
        "",
    ]
    groups = [*(summary["by_category"][category] for category in categories), summary["overall"]]
    lines += _table(
        ["Category", "Cases", "Turns", "Pass", "Fail", "Needs review"],
        [
            [
                label,
                group["cases"],
                group["turns"],
                group["case_status"][PASS],
                group["case_status"][FAIL],
                group["case_status"][REVIEW],
            ]
            for label, group in zip([*labels, "All"], groups, strict=True)
        ],
    )
    if summary["overall"]["errors"]:
        lines += [
            "",
            f"{summary['overall']['errors']} turn(s) ended with an error and are counted as "
            "failed. See [Failed turns](#failed-turns-automated-first-pass).",
        ]

    lines += ["", "## Metrics", ""]
    lines += _table(["Metric", *labels, "All"], _metric_rows(summary))
    lines += [
        "",
        "- *Search for the message alone* is `POST /api/admin/documents/search` with the "
        "visitor message as the query.",
        "- *Retrieval behind the reply* is the top five of the passages the reply was built "
        "from. For a follow-up it also uses the earlier visitor messages. A reply that did "
        "not search (a refusal or an inquiry offer) counts as a miss.",
        "- A passage matches an expected source when it comes from the same document and the "
        "same page (PDF) or section. With `require_all_sources`, every listed document must "
        "be matched.",
        "- *Reply cites an expected source* and *found in a cited excerpt* are the automated "
        "part of source support: the reply cites the passage the case expects, and the "
        "matched string is in a cited excerpt.",
        "- *Human handoff offered* is a pattern check on the reply text: it names a person or "
        "team and offers to involve them.",
    ]

    timing, tokens, cost = summary["timing"], summary["tokens"], summary["cost"]
    lines += ["", "## Response time, tokens and cost", ""]
    lines += _table(
        ["Time per reply", "Replies", "Median", "95th percentile", "Maximum"],
        [
            [
                label,
                timing[key]["count"],
                _ms(timing[key]["median_ms"]),
                _ms(timing[key]["p95_ms"]),
                _ms(timing[key]["max_ms"]),
            ]
            for label, key in (
                ("Whole reply", "response"),
                ("Retrieval (embedding and search)", "retrieval"),
                ("LLM call", "llm"),
            )
        ],
    )
    lines += [
        "",
        "Times are measured by the application inside one process, without a network hop "
        "between the client and the API.",
        "",
    ]
    if tokens["llm_calls"]:
        lines.append(
            f"- LLM tokens for replies: {tokens['input_tokens']} input, "
            f"{tokens['output_tokens']} output, over {tokens['llm_calls']} LLM call(s)"
            + (
                f"; {tokens['calls_without_token_data']} call(s) reported no token counts."
                if tokens["calls_without_token_data"]
                else "."
            )
        )
    else:
        lines.append("- LLM tokens for replies: not applicable. No LLM call was made.")
    lines.append(_cost_line("LLM API cost of the replies", cost["llm"]))
    lines.append(_cost_line("Embedding API cost", cost["embeddings"]))
    judge = run["judge"]
    if judge["enabled"]:
        judge_tokens = judge["tokens"]
        lines.append(
            f"- LLM judge: {judge['calls']} call(s), {judge['errors']} without a usable "
            f"verdict, {judge_tokens['input_tokens']} input and "
            f"{judge_tokens['output_tokens']} output tokens."
        )
        lines.append(_cost_line("LLM API cost of the judge", judge["cost"]))

    if judge["enabled"]:
        judged = summary["judged_case_status"]
        support = summary["judge_support"]
        lines += [
            "",
            "## After the LLM judge",
            "",
            "The judge decided the review items below. These verdicts are LLM output and can "
            "be wrong; they are not human review.",
            "",
        ]
        lines += _table(
            ["Category", "Pass", "Fail", "Needs review"],
            [
                [label, status[PASS], status[FAIL], status[REVIEW]]
                for label, status in zip(
                    [*labels, "All"],
                    [
                        *(judged["by_category"][category] for category in categories),
                        judged["overall"],
                    ],
                    strict=True,
                )
            ],
        )
        lines += [
            "",
            f"Source support of grounded replies, as judged from the cited excerpts: "
            f"{support['passed']} of {support['total']} supported, {support['failed']} not "
            f"supported, {support['errors']} without a verdict. A cited excerpt is at most "
            "500 characters of its passage, so a fact can be in the passage and still be "
            "missing from the excerpt.",
        ]

    if review is not None:
        lines += ["", "## After manual review", ""]
        if not review["current"]:
            lines += [
                f"`{REVIEW_FILE}` was written for another run (its verdict digest differs), "
                "so its verdicts are not applied here.",
            ]
        else:
            statuses = _reviewed_statuses(results, review["verdicts"])
            lines += [
                f"`{REVIEW_FILE}` holds a reviewer's verdicts on the review items of this "
                "run. They are judgment, not measurement.",
                "",
                f"- Reviewer: {review['reviewer']}",
                f"- Method: {review['method']}",
                "",
            ]
            rows = []
            for label, category in zip([*labels, "All"], [*categories, None], strict=True):
                selected = [
                    statuses[case["id"]]
                    for case in results["cases"]
                    if category is None or case["category"] == category
                ]
                rows.append(
                    [label, selected.count(PASS), selected.count(FAIL), selected.count(REVIEW)]
                )
            lines += _table(["Category", "Pass", "Fail", "Open"], rows)
            changed = [
                f"{case['id']} ({case['status']} → {statuses[case['id']]})"
                for case in results["cases"]
                if statuses[case["id"]] != case["status"]
            ]
            if changed:
                lines += ["", "Cases whose status changed: " + ", ".join(changed) + "."]

    lines += ["", "## Failed turns (automated first pass)", ""]
    lines += _failure_lines(results) or ["None.", ""]

    lines += ["## Retrieval misses", ""]
    lines += _retrieval_miss_lines(results) or [
        "None: every turn with an expected source had it in both top-five lists."
    ]

    unresolved = results["unresolved_sources"]
    lines += ["", "## Expected sources that are not in the index", ""]
    if unresolved:
        lines += [
            f"{len(unresolved)} expected source(s) match no indexed passage. No search can "
            "retrieve them: the case names a section or page the indexed document does not "
            "have. This is an error in the case or in the chunking, not a retrieval result.",
            "",
        ]
        lines += [
            f"- {source['case_id']}, turn {source['turn']}: {_source_label(source)}"
            for source in unresolved
        ]
    else:
        lines.append(
            "None: every expected source of every case matches at least one indexed passage, "
            "so a retrieval miss above is a ranking result, not a broken reference."
        )

    lines += ["", "## Needs review", ""]
    header, rows = _review_rows(results, review)
    if rows:
        lines += [
            f"{len(rows)} check(s) cannot be settled by a substring match. Until someone "
            "decides them, they count as open, not as passed.",
            "",
        ]
        lines += _table(header, rows)
    else:
        lines.append("None.")

    lines += ["", "## Knowledge bases", ""]
    lines += _table(
        ["Knowledge base", "Documents", "Chunks", "Fixtures added"],
        [
            [
                f"`{base['name']}`",
                len(base["documents"]),
                sum(document["chunks"] for document in base["documents"]),
                ", ".join(base["fixtures"]) or "none",
            ]
            for base in results["knowledge_bases"]
        ],
    )
    lines += [
        "",
        "Each knowledge base is a separate database that is created for the run and dropped "
        "afterwards.",
    ]

    if notes_path.is_file():
        lines += [
            "",
            "## Notes",
            "",
            f"Written by a person or an agent after the run (`{NOTES_FILE}`); not generated "
            "from the results.",
            "",
            notes_path.read_text(encoding="utf-8").strip(),
        ]
    return "\n".join(lines) + "\n"


def write_outputs(results: Mapping[str, Any], directory: Path) -> tuple[Path, Path]:
    """Write `results.json` and `report.md` into `directory`. Returns both paths."""
    directory.mkdir(parents=True, exist_ok=True)
    results_path = directory / RESULTS_FILE
    results_path.write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    report_path = directory / REPORT_FILE
    report_path.write_text(render_report(results, directory), encoding="utf-8")
    return results_path, report_path
