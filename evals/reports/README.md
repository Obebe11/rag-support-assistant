# Evaluation reports

Each folder here is one run of the [evaluation cases](../README.md) that was kept. `make eval` writes to `latest/`, which Git ignores; a run is kept by giving it its own folder with `--output-dir`.

| Folder | Run mode | What it is |
| --- | --- | --- |
| [`local-baseline/`](local-baseline/report.md) | LLM `local`, embeddings `local` (no API calls) | The system before any fix prompted by the evaluation. Includes a review of every open check by an AI coding agent. |
| [`local-after-integration/`](local-after-integration/report.md) | LLM `local`, embeddings `local` (no API calls) | The same cases after the chat learned to answer a question inside a purchase request before it offers the inquiry. One reply of 50 changed; the notes in the report compare the two runs. |
| [`local-release/`](local-release/report.md) | LLM `local`, embeddings `local` (no API calls) | The current run in the local modes, on the release code (commit `efc8036`, clean working tree). Same verdict digest as `local-after-integration`; the review verdicts were carried over by an AI coding agent. |
| [`live-glm-5.3-flash/`](live-glm-5.3-flash/report.md) | LLM `z-ai/glm-5.3-flash`, embeddings `amazon/titan-embed-text-v2` (live, through OpenRouter), LLM judge on | The first run with a live LLM and live embeddings, after clarifying questions and knowledge gaps started to cite the facts they name. Includes a review of every open check by an AI coding agent. |

## Changes after the baseline

The review of the baseline found no failure caused by a code defect or by an error in a case: every expected source resolves to an indexed passage, the case validator passes, and each failed turn is explained by how the local modes work (see the notes in the baseline report). No threshold, pattern or wording was changed to make a case pass.

One product change after the baseline touches replies. The baseline notes describe it as an open product decision for case ans-16: a message with both a purchase request and a question got an inquiry offer and no answer. The chat now answers the question first and offers the inquiry after it. `local-after-integration/` is the run after that change:

| | `local-baseline` | `local-after-integration` |
| --- | --- | --- |
| Cases after the automated first pass | 8 pass, 20 fail, 12 need review | 8 pass, 20 fail, 12 need review |
| Cases after the review by an AI coding agent | 20 pass, 20 fail | 20 pass, 20 fail |
| Response type as expected | 30 of 50 turns | 31 of 50 turns |
| Expected source in the top five | 21 of 33 turns | 21 of 33 turns |
| Required facts found | 18 of 68 | 20 of 68 |
| Verdict digest | `5219ab9f…` | `3a248a3f…` |

Only the reply of ans-16 differs. The case still fails: the reply now quotes and cites the free-freight rule, but not the discount. The case totals of the baseline therefore still describe the current system in the local modes; [`local-release/`](local-release/report.md) confirms it on the release code.

## Live run

[`live-glm-5.3-flash/`](live-glm-5.3-flash/report.md) runs the same 40 cases with a live LLM and live embeddings. It was made after one more change: a clarifying question or a knowledge gap that names documented facts now cites them, as a grounded answer does. The local modes do not ask clarifying questions with options, so this change does not alter the local runs.

| | `local-baseline` | `live-glm-5.3-flash` |
| --- | --- | --- |
| Cases after the automated first pass | 8 pass, 20 fail, 12 need review | 15 pass, 3 fail, 22 need review |
| Cases after the review by an AI coding agent | 20 pass, 20 fail | 37 pass, 3 fail |
| Response type as expected | 30 of 50 turns | 48 of 50 turns |
| Expected source in the top five | 21 of 33 turns | 29 of 33 turns |
| Required facts found | 18 of 68 | 63 of 68 |

The reviews of both runs were made by an AI coding agent, not by an independent person. The notes in the live report explain the three failed cases and the LLM judge's verdicts.

## Checks outside the 40 cases

Document replacement and deletion, inquiry confirmation, HubSpot failure handling, retries without duplicates and blocked visitor access are proven by automated tests, not by evaluation cases. [`acceptance-checks.md`](acceptance-checks.md) maps each check to its tests.

## How to read a report

Every report names its run mode at the top. A run in the local demo modes measures retrieval by shared words and the rules that assemble a reply from quotes. It does not measure a live LLM or a live embedding model; [`live-glm-5.3-flash/`](live-glm-5.3-flash/report.md) does, for one model.

These results describe this system on 40 questions about one demo corpus. They are not a guarantee and do not predict behavior on other questions or other documents.

## Files in a run folder

| File | Written by | Content |
| --- | --- | --- |
| `results.json` | the runner | Every reply, citation, retrieved passage, check and total of the run. |
| `report.md` | the runner | The same run for a reader. Rebuilt by `--render-only`. |
| `manual-review.json` | a reviewer; in every kept run, an AI coding agent | Verdicts on the checks a substring match cannot settle. The report shows them under "After manual review", apart from the measured numbers. |
| `notes.md` | a reviewer | Analysis of the run. The report includes it under "Notes". |

To check that the current code still reproduces a kept run in the local modes, run `make eval` and compare `run.verdict_digest` in `latest/results.json` with the digest in the kept `results.json`. The release code reproduces `local-release`, which has the same digest as `local-after-integration`.
