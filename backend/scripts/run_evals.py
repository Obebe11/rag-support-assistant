"""Run the evaluation cases and write a report: `python -m scripts.run_evals` (`make eval`).

The command validates the case files, starts an embedded PostgreSQL in a
temporary directory (or uses the server of EVAL_DATABASE_URL), runs every case
on a fresh database and writes `results.json` and `report.md` to the output
directory. Provider modes, models and prices come from the environment and
`.env`, as for the API. `evals/README.md` explains the metrics and the live mode.

`--render-only` rebuilds `report.md` from an existing `results.json`, for
example after `manual-review.json` or `notes.md` was added next to it.
"""

import argparse
import asyncio
import json
import logging
import os
import shlex
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.config import REPO_ROOT, Settings
from app.core.logging import configure_logging
from evaluation.cases import CasesError, validate_case_files
from evaluation.report import RESULTS_FILE, ReviewFileError, render_report, write_outputs
from evaluation.runner import EvaluationError, RunOptions, run
from evaluation.scoring import FAIL, PASS, REVIEW
from scripts.embedded_postgres import embedded_postgres

DEFAULT_OUTPUT_DIR = REPO_ROOT / "evals" / "reports" / "latest"


@contextmanager
def _server_url() -> Iterator[str]:
    """A database on the server the run may create its databases on."""
    external = os.environ.get("EVAL_DATABASE_URL")
    if external:
        yield external
        return
    with (
        tempfile.TemporaryDirectory(prefix="handoff-eval-pg-") as directory,
        embedded_postgres(Path(directory), database="handoff_eval") as url,
    ):
        yield url


def _print_summary(results: dict[str, Any]) -> None:
    run_info, summary = results["run"], results["summary"]
    providers = run_info["providers"]
    print(
        f"LLM: {providers['llm']['mode']} (live: {providers['llm']['live']}); "
        f"embeddings: {providers['embeddings']['mode']} "
        f"(live: {providers['embeddings']['live']}); "
        f"judge: {'on' if run_info['judge']['enabled'] else 'off'}"
    )
    for name, group in (*summary["by_category"].items(), ("all", summary["overall"])):
        status = group["case_status"]
        print(
            f"  {name:<22} cases {group['cases']:>2}  pass {status[PASS]:>2}  "
            f"fail {status[FAIL]:>2}  needs review {status[REVIEW]:>2}"
        )
    print(f"Checks that need review: {len(results['review'])}")
    print(f"Verdict digest: {run_info['verdict_digest']}")


def _render_only(output_dir: Path) -> int:
    results_path = output_dir / RESULTS_FILE
    try:
        results = json.loads(results_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Cannot read {results_path}: {exc}")
        return 1
    report_path = output_dir / "report.md"
    report_path.write_text(render_report(results, output_dir), encoding="utf-8")
    print(f"Wrote {report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Where results.json and report.md are written (default: evals/reports/latest).",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        metavar="ID",
        help="Run only this case; repeat for several. Default: all cases.",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Let the LLM judge the checks that need review. Needs a live LLM provider.",
    )
    parser.add_argument(
        "--render-only",
        action="store_true",
        help="Rebuild report.md from the results.json in the output directory.",
    )
    arguments = parser.parse_args()
    output_dir: Path = arguments.output_dir.resolve()
    # The run prints its own summary; provider and server logs stay out of the way.
    configure_logging(logging.WARNING)

    try:
        if arguments.render_only:
            return _render_only(output_dir)

        validation = validate_case_files()
        if validation.returncode != 0:
            print(validation.stdout + validation.stderr)
            print("The case files are not valid; nothing was run.")
            return 1

        with _server_url() as server_url:
            try:
                settings = Settings(database_url=server_url)
            except ValidationError as exc:
                print(f"The provider settings are not usable: {exc}")
                return 1
            options = RunOptions(
                settings=settings,
                server_url=server_url,
                case_ids=frozenset(arguments.cases) if arguments.cases else None,
                use_judge=arguments.judge,
                command=shlex.join(["python", "-m", "scripts.run_evals", *sys.argv[1:]]),
            )
            results = asyncio.run(run(options))
        results_path, report_path = write_outputs(results, output_dir)
    except (CasesError, EvaluationError, ReviewFileError) as exc:
        print(f"The evaluation run failed: {exc}")
        return 1

    _print_summary(results)
    print(f"Wrote {results_path}")
    print(f"Wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
