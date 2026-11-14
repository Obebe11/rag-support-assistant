### What this run is

The 40 cases in the local demo modes on the release code: commit `efc8036`, with a clean working tree, run with `LLM_PROVIDER=local EMBEDDING_PROVIDER=local CRM_PROVIDER=simulated` in the environment. It repeats [`local-after-integration`](../local-after-integration/report.md) after every change since then, so that the current numbers come from a run of the current code.

### What changed against local-after-integration

Nothing in the measured results. The verdict digest is the same, `3a248a3f…`, and `results.json` differs only in timings: every reply, citation, retrieval result and check outcome is identical.

The changes in between do not reach the local modes. The re-indexing on a new embedding model runs only when the model changes, the reasoning effort setting and the citations of clarifying questions and knowledge gaps apply to the LLM mode, and the rest touches setup, CI, the frontend and the documents.

### Review of the open checks

The verdicts of the `local-after-integration` review were carried over unchanged, because they judge the same replies. That review, and this carry-over, were made by an AI coding agent, not by a person. No reply was judged again.

For why each failed turn failed, see the notes of the [baseline](../local-baseline/report.md) and of [`local-after-integration`](../local-after-integration/report.md): they apply to this run unchanged.

### What was not measured

No live LLM and no live embedding model: this run measures retrieval by shared words and the rules that assemble a reply from quotes. The live run is [`live-glm-5.3-flash`](../live-glm-5.3-flash/report.md).
