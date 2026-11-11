# Evaluation reports

Each folder here is one run of the [evaluation cases](../README.md) that was kept. `make eval` writes to `latest/`, which Git ignores; a run is kept by giving it its own folder with `--output-dir`.

| Folder | Run mode | What it is |
| --- | --- | --- |
| [`local-baseline/`](local-baseline/report.md) | LLM `local`, embeddings `local` (no API calls) | The system before any fix prompted by the evaluation. Includes a manual review of every open check. |

## Fix round after the baseline

The plan allows one round of fixes after the baseline, for failures caused by a code defect or by an error in a case. The review of the baseline found none: every expected source resolves to an indexed passage, the case validator passes, and each failed turn is explained by how the local modes work (see the notes in the baseline report). No threshold, pattern or wording was changed to make a case pass, so there is no second run to compare with.

The backend cleanup made in the same task (status of abandoned jobs, model names in `/api/health`, access tests) does not touch retrieval or replies. A run after it gave the same verdict digest as the baseline: `5219ab9fa26060bca57e96253631ef57f9efc33f868f6c45a3e4e41e80c36db7`.

## Checks outside the 40 cases

Document replacement and deletion, inquiry confirmation, HubSpot failure handling, retries without duplicates and blocked visitor access are proven by automated tests, not by evaluation cases. [`acceptance-checks.md`](acceptance-checks.md) maps each check to its tests.

## How to read a report

Every report names its run mode at the top. A run in the local demo modes measures retrieval by shared words and the rules that assemble a reply from quotes. It does not measure a live LLM or a live embedding model: no such run has been made yet, because no API key was available.

These results describe this system on 40 questions about one demo corpus. They are not a guarantee and do not predict behavior on other questions or other documents.

## Files in a run folder

| File | Written by | Content |
| --- | --- | --- |
| `results.json` | the runner | Every reply, citation, retrieved passage, check and total of the run. |
| `report.md` | the runner | The same run for a reader. Rebuilt by `--render-only`. |
| `manual-review.json` | a reviewer | Verdicts on the checks a substring match cannot settle. The report shows them under "After manual review", apart from the measured numbers. |
| `notes.md` | a reviewer | Analysis of the run. The report includes it under "Notes". |

To check that a kept run still reproduces in the local modes, run `make eval` and compare `run.verdict_digest` in `latest/results.json` with the digest in the kept `results.json`.
