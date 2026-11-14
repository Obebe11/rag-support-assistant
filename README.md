# Handoff AI

An open-source demo of a support assistant for a company website. It answers visitor questions from the company's documents and shows the passages it used. When the documents have no answer, it says so and offers to pass the question to a person. When a visitor wants to buy, it collects a purchase inquiry, shows it for confirmation and delivers it to a CRM.

It is for people who evaluate or build this kind of assistant: the repository shows the whole path from a document upload to a CRM record, with the limits stated. The demo company, Northline Office Equipment, is fictional.

## What the demo shows

1. A visitor asks about shipping, returns or warranty. The reply quotes the documents and lists its sources: document, version, section or page, and the excerpt.
2. A follow-up question ("And for the P-240?") is answered in the context of the conversation.
3. A question the documents do not answer gets no guess. The assistant admits the gap and offers a human handoff: the visitor reviews the question and the contact details, confirms, and follows the delivery status.
4. A purchase request ("I want 12 LP-420 printers") opens an inquiry form filled from the conversation. If the same message asks a question, the reply answers it first. Nothing is sent until the visitor confirms the preview.
5. The confirmed inquiry is delivered to the CRM by a background worker. A temporary error is retried automatically; a failed delivery can be sent again. Confirming twice or retrying does not start a second delivery.
6. An administrator signs in with a token, uploads, replaces and deletes documents, and sees every inquiry with its delivery log. After a replacement, answers come from the new version only; a deleted document is no longer cited.

## Status

Version 1. The scenario above works end to end in the demo modes and is covered by automated tests, a smoke check over HTTP and an evaluation run.

| Part | State |
| --- | --- |
| Knowledge base: upload, replacement, deletion, indexing of Markdown and text PDF | Works. Tested on PostgreSQL with pgvector. |
| Chat with citations, knowledge gaps, follow-up questions, refusal of instruction overrides | Works in the local mode. The LLM mode is tested against a mock API only. |
| Purchase inquiries and human handoff: draft, preview, confirmation, delivery, retries | Works with the simulated CRM. The HubSpot provider is tested against an in-memory fake of the HubSpot API only. |
| Visitor chat and admin page | Work. Checked in a browser on a real backend at 390 by 844 and 1440 by 1000 pixels. |

**Checked once with live models.** Through OpenRouter, with `z-ai/glm-5.3-flash` and `amazon/titan-embed-text-v2`: the demo documents were indexed, and three questions got a cited answer, a reply that the documents do not say, and an answer followed by an inquiry offer. The evaluation has not been run with a live LLM.

**Not verified.** No HubSpot account and no Docker host were available, so these have never been run by hand:

- a live HubSpot account (`CRM_PROVIDER=hubspot`);
- the Docker Compose stack. The [CI workflow](.github/workflows/ci.yml) builds and starts it; see [Docker Compose](#docker-compose).

**The demo modes are not the product.** The defaults need no keys: `LLM_PROVIDER=local` writes no text and quotes the retrieved passages that share words with the question; `EMBEDDING_PROVIDER=local` matches words, not meaning; `CRM_PROVIDER=simulated` delivers to nobody. The interface and `GET /api/health` label each of them, and a simulated delivery is never shown as a CRM record.

## Quick start

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22.22 or later, [pnpm](https://pnpm.io/), GNU Make. Linux or macOS on x86-64 or ARM64. No Docker, no system PostgreSQL and no API key are needed. To install pnpm, run `corepack enable` (Corepack ships with Node.js 22 and 24) or `npm install --global pnpm`; `frontend/package.json` pins the version.

```
make setup    # install the dependencies and create .env with demo settings
make dev      # database, API, worker and frontend; loads the demo documents on the first run
```

Open `http://localhost:5173`. The API docs are at `http://localhost:8000/api/docs`. `make dev` starts an embedded PostgreSQL with pgvector in `.local/postgres` and, while the knowledge base is empty, loads the demo documents of Northline Office Equipment. Change the ports with `FRONTEND_PORT` and `BACKEND_PORT`.

To use your own API key, run `make configure` and restart `make dev`. See [Live LLM and embeddings](#live-llm-and-embeddings).

Things to try:

- "How much does shipping cost?", then "And how long does delivery take?"
- "Do you offer on-site installation in Brazil?" (not in the documents), then **Talk to a person**.
- "I want 12 LP-420 printers, what is the warranty?"
- In an inquiry, a contact email with `+fail2` before the `@` (two temporary errors, then delivered) or `+reject1` (a permanent error, then **Send again**). These tags work with the simulated CRM only.

Other commands:

```
make configure  # choose the LLM, embeddings and CRM, enter the keys and check them
make seed       # load the demo documents again, for example after editing them
make check      # linters, type checks, tests and the frontend build
make smoke      # the scenario above over HTTP, on an isolated database, in the demo modes
make eval       # the 40 evaluation cases on an isolated database
make openapi    # regenerate docs/openapi.json and the frontend API types
```

The [CI workflow](.github/workflows/ci.yml) runs `make check` and `make smoke` on every push and pull request, and builds and starts the Docker Compose stack.

### Admin page

Open `http://localhost:5173/admin` and enter the value of `ADMIN_API_TOKEN` from `.env`. `make setup` puts a random token there; `make configure` prints it. The token is sent as a bearer token and kept in the memory of the page only. While the variable is unset, every request under `/api/admin` is rejected.

### Live LLM and embeddings

Any API that implements OpenAI-style chat completions and embeddings can be used. The simplest way is:

```
make configure
```

It asks which API to use for the language model and for embeddings (demo mode, OpenAI, or another OpenAI-compatible API), reads each key without showing it, checks it with one small request and writes the answers to `.env`. Press Enter to keep a current value. With OpenAI, one key covers both, and the suggested models are `gpt-4.1-mini` and `text-embedding-3-small`.

To edit `.env` by hand instead:

```
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=...
LLM_API_KEY=...
LLM_MODEL=...
LLM_REASONING_EFFORT=

EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_BASE_URL=...
EMBEDDING_API_KEY=...
EMBEDDING_MODEL=...
```

`LLM_REASONING_EFFORT` is optional and only for reasoning models: `low` makes replies faster. The app sets no output token limit, so a reasoning model does not run out of tokens before its reply. Restart `make dev` after a change. When the embedding model changes, `make dev` indexes every document again before it starts, uploads included: stored vectors of another model are not searched. The two providers are independent, so one can stay local.

### HubSpot

Run `make configure` and answer yes to HubSpot, or set `CRM_PROVIDER=hubspot` and `HUBSPOT_ACCESS_TOKEN` in `.env`. A confirmed inquiry becomes a contact (found or created by email) with a note. The required scopes, the error handling, the limits and a step-by-step live check are in [docs/inquiries.md](docs/inquiries.md#hubspot). This path has not been run against a live account.

### Docker Compose

A [Compose file](docker-compose.yml) for PostgreSQL with pgvector, the migrations, the API, the worker and the frontend behind nginx is included:

```
sed "s/^ADMIN_API_TOKEN=$/ADMIN_API_TOKEN=$(openssl rand -hex 32)/" .env.example > .env
docker compose up --build
docker compose run --rm seed    # once: load the demo knowledge base
```

The first command copies `.env.example` to `.env` with a random admin token; it needs neither Python nor uv. Skip it if `make setup` has already created `.env`. Compose stops with a message while `ADMIN_API_TOKEN` is empty. Open `http://localhost:5173`; on `/admin`, enter the `ADMIN_API_TOKEN` value from `.env`.

The stack was written on a machine without Docker. The Compose file is validated against the Compose specification, and the CI workflow builds the images, starts the stack, loads the demo documents and checks the API and the admin token through nginx. It has not been run by hand.

## Architecture

- **Backend:** FastAPI, async SQLAlchemy, PostgreSQL with pgvector. One API process and one worker process; the job queue is a table, so there is no Redis or workflow engine.
- **Knowledge base:** an upload becomes a document version, is split into passages by headings and pages, embedded and searched by exact cosine distance. Only the active version of a document is searched. Citations are stored with the reply, so the sources of an old answer stay readable.
- **Chat:** each message passes an override guard, the purchase intent detector, retrieval and the answer step. A grounded reply must cite a passage that was really retrieved; otherwise it becomes a knowledge gap.
- **Inquiries:** a draft is confirmed by the visitor and delivered by a job with an idempotency key, retries with backoff and a log of attempts.
- **Providers:** the LLM, the embeddings and the CRM sit behind interfaces, each with a demo mode and a live mode selected by configuration.
- **Frontend:** React, TypeScript and Vite. API types are generated from the OpenAPI contract.

Details: [docs/architecture.md](docs/architecture.md) (data model, API, reply logic, jobs, frontend), [docs/inquiries.md](docs/inquiries.md) (delivery, the simulated CRM, HubSpot), [docs/openapi.json](docs/openapi.json) (the API contract).

## Configuration

Every setting has a default that runs the demo, and every setting is listed with a comment in [.env.example](.env.example): provider modes and their keys, the admin token, CORS origins, the upload size limit, delivery attempts, and the timing of the job queue. The application reads `.env` from the repository root; a missing required setting of a live mode stops it at startup with a message.

## Evaluation

`make eval` runs 40 evaluation cases on an isolated database and writes a report and a machine-readable results file to `evals/reports/latest/`. The cases cover answerable questions, questions the knowledge base cannot answer, multi-turn conversations and attempts to override instructions.

The baseline run is in [`evals/reports/local-baseline/`](evals/reports/local-baseline/report.md). It was made in the local demo modes, with no language model and no embedding model: 8 of 40 cases passed the automated first pass, 20 failed and 12 needed review; after a manual review of the open checks, 20 passed and 20 failed. The expected source was in the top five results for 21 of 33 turns. The report explains each failure. No run with a live LLM has been made yet.

One change after the baseline touches replies: a purchase request that also asks a question is now answered before the inquiry is offered. The run after it, [`evals/reports/local-after-integration/`](evals/reports/local-after-integration/report.md), differs in one reply of 50, and its case totals are the same as the baseline's.

These numbers describe this system on these questions and this demo corpus. They are not a guarantee for other documents.

Document replacement and deletion, inquiry confirmation, HubSpot failure handling, retries without duplicates and admin access are covered by automated tests: see [`evals/reports/acceptance-checks.md`](evals/reports/acceptance-checks.md). The HubSpot tests run against an in-memory fake of the HubSpot API, not a live account.

How to run the evaluation with a live LLM and the optional LLM judge: [`evals/README.md`](evals/README.md). The demo corpus and its deliberate gaps: [`knowledge-base/northline/README.md`](knowledge-base/northline/README.md).

## Limitations

- **The local mode is lexical and is not an LLM.** It finds an answer only when the question and the document share words, and it quotes; it cannot paraphrase, compare, compute or ask a clarifying question well. Half of the evaluation cases fail in this mode. Judge answer quality only with a live LLM and a live embedding model, and that has not been measured here.
- **The override guard is a set of patterns.** It refuses explicit attempts to change the assistant's instructions or role, in messages and in document text. It is a first line of defense and does not catch every phrasing.
- **Visitors are not authenticated.** A conversation and an inquiry are addressed by a random ID and need no login. Anyone who has the ID of an inquiry can read it, including the technical text of its last delivery error. The interface does not show that text to visitors; the API returns it.
- **Admin access is one shared token.** There are no users, roles or audit log.
- **HubSpot note deduplication is not atomic.** A retry looks for the note of the same inquiry before it creates one. Two notes are possible in rare cases, for example when a worker loses its lease while its request is in flight. [docs/inquiries.md](docs/inquiries.md#duplicates-what-is-and-is-not-guaranteed) lists the cases.
- **A human handoff notifies nobody.** It is delivered to the CRM like an inquiry; there is no email or chat alert.
- **Documents:** Markdown and PDF with a text layer. No OCR, no other formats, no crawling.
- **Not built:** streaming replies, a dark theme, languages other than English, other CRMs, rate limiting, analytics.

## Client handoff

The demo is deliberately narrow, and an implementation for a client keeps the same shape:

- **One document source.** The company's own documents, uploaded on the admin page or listed in a manifest like [`knowledge-base/northline/manifest.json`](knowledge-base/northline/manifest.json). The assistant answers from the active versions only.
- **One channel.** A web chat. Email, messengers and voice are not part of it.
- **One CRM process.** A confirmed inquiry becomes a contact with a note in HubSpot. Deals, pipelines, owners and custom properties are not written.

What is configured without code: the LLM and embedding API and models, the CRM mode and key, the admin token, the documents, the upload limit, delivery attempts and retry timing.

What is changed in code: the company name, the example questions and the interface texts (`frontend/src`), the fields of an inquiry (`backend/app/services/inquiries/` and the form), the rules that detect a purchase request without an LLM (`backend/app/services/inquiries/extraction.py`), the system prompt (`backend/app/services/chat/llm_answer.py`), and a CRM other than HubSpot (a new provider behind `backend/app/providers/crm/base.py`).

Before a client sees it, run the live check for the LLM, the embeddings and HubSpot, run the evaluation on questions about the client's documents, and decide who may read conversations and inquiries.

## License

Original Handoff AI code and documentation are released under the [MIT License](LICENSE). You may use, modify and distribute them, including for commercial purposes, as long as the copyright and license notice are kept.

## Third-Party Materials

The MIT License covers only original work in this repository. Third-party materials keep their own licenses:

- **Odoo documentation articles** in `demo-docs/odoo/` and `demo-docs/odoo-replacement-test/` remain under **CC BY-SA 4.0**. Attribution, the original license and a source manifest are kept in each folder. See the [corpus licensing notice](demo-docs/odoo/README.md#attribution-and-license) and the [Odoo documentation license](demo-docs/odoo/LICENSE). The application does not load these articles; they are an [alternative corpus](demo-docs/README.md).
- **T3 Code interface code** in `frontend/src/t3code/` is copied or adapted from [T3 Code](https://github.com/pingdotgg/t3code) (`apps/web`, commit `be7d35aae`) and remains under the **MIT License**, Copyright (c) 2026 T3 Tools Inc. The license text, the list of files and the changes are kept in that folder: [LICENSE](frontend/src/t3code/LICENSE), [README](frontend/src/t3code/README.md). No T3 Code names, logos, icons or interface texts are used. The direct frontend dependencies added with it are under MIT, Apache-2.0 or ISC.
- **Dependencies** are not copied into this repository. They are installed from PyPI and npm and keep their own licenses. The direct dependencies listed in `backend/pyproject.toml` and `frontend/package.json` are under MIT, Apache-2.0, BSD-3-Clause or ISC. Transitive ones include other permissive licenses, such as MPL-2.0 (`certifi` in the backend, `lightningcss` in the frontend build), PSF-2.0 (`typing_extensions`), and BlueOak-1.0.0 and Python-2.0 (frontend development tools such as `lru-cache` and `argparse`).
- **PostgreSQL and pgvector** are used as the database and are under the PostgreSQL License. They are not part of this repository: Docker Compose pulls the `pgvector/pgvector` image, and local development and the tests use the `pixeltable-pgserver` package, a development-only dependency. The package itself is under Apache-2.0; its Linux wheel bundles binaries of PostgreSQL and pgvector. The wheel's component list (`auditwheel.cdx.json`) also names the `readline` and `ncurses-libs` system libraries, without license data; GNU Readline is distributed under the GPL. None of them is copied into this repository or into the Docker images.
- **Docker base images** (`python`, `node`, `nginx`, `pgvector/pgvector`) are pulled at build time and keep their own licenses.
- **The PDF files of the demo knowledge base** were generated with ReportLab (BSD license), which is not a dependency of the application. See the [knowledge base README](knowledge-base/northline/README.md).

Any third-party code added later will keep its original license file and be listed here.

## Trademarks

Odoo, HubSpot and T3 Code are names or trademarks of their respective owners. This is an independent portfolio project, not affiliated with or endorsed by them. Northline Office Equipment is a fictional company used for the demo.

## Contact

For custom implementations or freelance inquiries, contact Ivan Orlov (Obi) at [Ivan_orlov_00@pm.me](mailto:Ivan_orlov_00@pm.me).
