# Architecture

Handoff AI answers visitor questions from company documents, shows its sources, and sends confirmed purchase inquiries to a CRM. This document describes the foundation: the repository layout, the data model, the API contract, the provider modes, background jobs, and who owns which module.

Status: the knowledge base and chat endpoints are implemented and described in [Knowledge base and chat](#knowledge-base-and-chat); inquiries and CRM delivery are described in [inquiries.md](inquiries.md).

## Repository layout

```
backend/
  app/
    api/          routes, dependencies, the common error format
    core/         settings, database engine, logging
    models/       SQLAlchemy models
    schemas/      Pydantic request and response schemas (the API contract)
    providers/    LLM, embedding and CRM providers behind interfaces
    services/     business logic (chat, documents, inquiries)
    worker/       background jobs on PostgreSQL
  migrations/     Alembic migrations
  scripts/        development runner, embedded PostgreSQL, OpenAPI export
  tests/
frontend/
  src/
    api/          typed API client; schema.d.ts is generated from docs/openapi.json
    app/          page frame (header, mode banner, footer)
    components/   shared components
    hooks/        shared hooks
    pages/        one file per route
    styles/       design tokens and base styles
docs/
  architecture.md
  inquiries.md    inquiry kinds, delivery, the simulated CRM, HubSpot
  openapi.json    the API contract, exported from the backend
knowledge-base/   demo document corpus (separate task)
evals/            evaluation cases and reports (separate task)
docker-compose.yml, Makefile, .env.example
```

Stack: Python 3.13, FastAPI, async SQLAlchemy 2 with asyncpg, Alembic, uv; React, TypeScript, Vite, pnpm; PostgreSQL with pgvector.

## Processes

| Process | Command | Role |
| --- | --- | --- |
| API | `uvicorn app.main:create_app --factory` | Serves `/api`. |
| Worker | `python -m app.worker` | Runs background jobs: document indexing and inquiry delivery. |
| Frontend | Vite dev server, or static files behind nginx in Docker | Serves the UI and proxies `/api` to the API. |
| Database | PostgreSQL with the `vector` extension | Stores everything, including the job queue. |

There is no Redis, Celery or workflow engine. Inquiry delivery to the CRM runs in the worker.

## Data model

Migration `0001` creates the whole schema. Migration `0002` adds `inquiries.kind`.

| Table | Purpose |
| --- | --- |
| `documents` | A knowledge base document: title, `deleted_at`. |
| `document_versions` | One upload of a document: version number and label, file name, media type, size, SHA-256 checksum, the original file, `is_active`, indexing status and error, page and chunk counts. |
| `chunks` | A retrievable passage of one version: text, section heading or page number, `embedding`, `embedding_model`. |
| `conversations` | A visitor chat. |
| `messages` | A visitor or assistant message: role, text, `answer_type`, `citations` (JSON snapshot), the offered inquiry, usage facts. `seq` gives the order. |
| `inquiries` | A purchase request or a human handoff request (`kind`): product, quantity, timeline, contact details, notes, status `draft` → `confirmed`. See [inquiries.md](inquiries.md). |
| `inquiry_deliveries` | Delivery of one confirmed inquiry to the CRM: status, CRM mode, idempotency key, attempt count, last error, next attempt time, CRM contact and record IDs. One row per inquiry. |
| `inquiry_delivery_attempts` | One row per delivery attempt: outcome, error, start and finish time. |
| `jobs` | The background job queue. |

Rules built into the schema:

- **Active retrieval.** A chunk takes part in retrieval only while its version has `is_active = true`. A partial unique index allows one active version per document.
- **Replacement.** A new upload becomes a new version with `is_active = false`. When indexing succeeds, one transaction deactivates the old version and activates the new one. Until then the old version keeps answering. If indexing fails, the old version stays active.
- **Deletion.** Deleting a document sets `deleted_at` and deactivates every version. A hard delete also works: versions and chunks are removed by `ON DELETE CASCADE`.
- **Citations are snapshots.** A message stores its citations as JSON, so the sources of an old answer stay readable after the document is replaced or deleted.
- **Embeddings.** `chunks.embedding` is a pgvector column without a fixed dimension, because the embedding model is configuration. Every query must filter by `embedding_model` before comparing distances; vectors of different models never mix. Changing the model requires re-indexing. There is no approximate index: exact search is enough for a demo corpus. Add one only if evaluation shows a need.
- **Enumerations** are stored as `VARCHAR(32)` without `CHECK` constraints. Adding a value to an enum in `app/models/enums.py` needs no migration.
- **Uploaded files** are stored in `document_versions.content`, so the API and the worker need no shared volume.

## API

The contract lives in `backend/app/schemas` and is exported to `docs/openapi.json`. Interactive docs: `/api/docs`.

| Method and path | Purpose | Owner |
| --- | --- | --- |
| `GET /api/health` | Database status and provider modes | Foundation |
| `POST /api/conversations` | Start a conversation | T3 |
| `GET /api/conversations/{id}` | Conversation with messages | T3 |
| `POST /api/conversations/{id}/messages` | Send a message, get the assistant's reply | T3 |
| `POST /api/inquiries` | Create an inquiry draft | T4 |
| `GET /api/inquiries/{id}` | Read an inquiry | T4 |
| `PATCH /api/inquiries/{id}` | Update a draft | T4 |
| `POST /api/inquiries/{id}/confirm` | Confirm and queue delivery | T4 |
| `GET /api/inquiries/{id}/delivery` | Delivery status | T4 |
| `POST /api/inquiries/{id}/delivery/retry` | Retry a failed delivery | T4 |
| `GET /api/admin/documents` | List documents | T3 |
| `POST /api/admin/documents` | Upload a document | T3 |
| `GET /api/admin/documents/{id}` | Versions and indexing status | T3 |
| `POST /api/admin/documents/{id}/versions` | Replace a document | T3 |
| `DELETE /api/admin/documents/{id}` | Delete a document | T3 |
| `POST /api/admin/documents/search` | Retrieval on its own: the top passages for a query, without an answer | T3 |
| `GET /api/admin/inquiries` | Inquiries with delivery status | T4 |

**Assistant replies.** `answer_type` tells the UI what to render:

- `grounded`: an answer with `citations` (document, version, page or section, excerpt).
- `knowledge_gap`: the documents do not answer the question; the UI offers a human handoff.
- `clarification`: the assistant asks for more detail.
- `inquiry_offer`: the visitor wants to buy; `inquiry` may carry a draft to review and confirm.
- `refusal`: the message tried to override the assistant's instructions or role; the assistant declines.

An assistant message also carries `usage`: provider modes and models, token counts when a live LLM reports them, response, retrieval and LLM time in milliseconds, and `retrieved`, the ranked passages the reply was built from.

**Errors.** Every error has the same shape:

```json
{ "error": { "code": "not_found", "message": "...", "details": [{ "field": "body.quantity", "message": "..." }] } }
```

Raise `ApiError` (or `NotFoundError`, `ConflictError`, `ValidationApiError`) from `app/api/errors.py`. Declare the possible errors of a route with `responses=error_responses(404, 422)`.

**Stubs.** An endpoint that is not implemented raises `NotImplementedApiError` and returns `501`. The `501` is deliberately absent from OpenAPI, so implementing an endpoint does not change the contract or the generated frontend types. `backend/tests/api_cases.py` lists the remaining stubs (none at the moment); remove a case when you implement its endpoint.

**Admin access.** Everything under `/api/admin` requires `Authorization: Bearer <ADMIN_API_TOKEN>`. No token: `401`. Wrong token, or no token configured on the server: `403`. There are no users or roles.

**Visitor access.** Conversations and inquiries are addressed by random UUIDs and need no login. This is a demo limitation, not an access control model.

**Sessions.** `SessionDep` gives a route one database session. Nothing commits automatically: the service that owns the unit of work calls `session.commit()`.

## Provider modes

Each provider is selected by its own setting. Model IDs, base URLs and keys come from configuration only.

| Provider | Setting | Modes | Implemented by |
| --- | --- | --- | --- |
| LLM | `LLM_PROVIDER` | `local`, `openai_compatible` | T3 |
| Embeddings | `EMBEDDING_PROVIDER` | `local`, `openai_compatible` | T3 |
| CRM | `CRM_PROVIDER` | `simulated`, `hubspot` | T4 |

`openai_compatible` works with any API that implements OpenAI-style chat completions and embeddings; it needs `*_BASE_URL` and `*_MODEL`, and `*_API_KEY` if the API requires one. `hubspot` needs `HUBSPOT_ACCESS_TOKEN`. Missing settings stop the application at startup.

`local` and `simulated` work offline, without API keys. They are demo modes: `local` is not a working LLM and `simulated` is not a live CRM integration. Each provider class has a `live` flag; `GET /api/health` reports it, and the UI shows a "Demo mode" banner for every provider that is not live. Deliveries record the CRM mode they ran in.

Interfaces: `app/providers/llm/base.py`, `app/providers/embeddings/base.py`, `app/providers/crm/base.py`. The factory in `app/providers/factory.py` calls `from_settings` on the class for the selected mode, so a provider can read new settings without a factory change. Provider failures raise `ProviderError` with a `retryable` flag.

The LLM and embedding providers are implemented. The `openai_compatible` classes share the HTTP client in `app/providers/openai_http.py`: timeouts, connection errors and the statuses 408, 409, 425, 429 and 5xx are retryable `ProviderError`s, other statuses and malformed replies are not. They are tested against a mock transport only and have not been run against a live API. [Knowledge base and chat](#knowledge-base-and-chat) describes the local modes.

## Chat and inquiries

The chat service (T3) never imports inquiry internals. After each visitor message it calls the seam in `app/services/inquiry_intent.py`:

```python
intent = await detector.assess(session, conversation_id=..., turns=[...])
```

`InquiryIntent` says whether the visitor wants to buy, which fields are already extracted, which required fields are missing, and which draft the inquiry module saved. The detector may write through the chat's session but must not commit, so the draft and the reply are stored together.

The detector comes from `app/services/inquiries/intent.py`; routes receive it as `InquiryIntentDetectorDep`. It keeps one purchase draft per conversation up to date and never confirms it. `NoOpInquiryIntentDetector` in the seam module reports no intent and is there for tests.

To put an inquiry into a reply, the chat can serialize it with `read_inquiries` or `inquiry_to_read` from `app/services/inquiries/service.py`.

Inquiry kinds, delivery statuses, retries, the simulated CRM and the HubSpot integration with its limits are described in [inquiries.md](inquiries.md).

## Knowledge base and chat

### Ingestion

An upload is checked and stored by the API, then indexed by the `documents.index_version` job (`app/services/documents/`).

- **Formats.** Markdown, and PDF with a text layer (pypdf). A PDF without text fails indexing with a clear error; there is no OCR. The format is taken from the file content first (`%PDF`), then from the file name.
- **Upload checks.** `app/api/upload_guard.py` is an ASGI middleware in front of the two upload routes. It checks the admin token and stops a body larger than `MAX_UPLOAD_BYTES` before the application reads it, with or without a `Content-Length` header. The service checks the file size again, the type (`415`) and that the file can be parsed (`422`).
- **Sections.** A Markdown chunk keeps its heading path below the document title, joined by `" > "`, for example `Returns > How long do I have to return an item?`. HTML comments are removed. A PDF chunk keeps its page number (1-based) and the headings found by font size and weight; lines that repeat at the top or bottom of every page are dropped and tables are rebuilt as Markdown tables.
- **Chunks.** A chunk never crosses a heading or a page. A section longer than 1,200 characters is split at paragraphs, list items, table rows or sentences; a split table repeats its header row. The text that is embedded is the document title, the heading path and the chunk.
- **Status.** A version moves through `pending` → `indexing` → `ready` or `failed`. The status and the error text are committed as they change, so `GET /api/admin/documents/{id}` shows them while the job runs or waits for a retry. A parse error fails the job at once; a retryable provider error is retried by the queue, and the version shows `pending` with the last error until the final attempt.
- **Activation.** The chunks, the `ready` status and the switch of the active version are one transaction under a lock on the document row. A version indexed late does not replace a newer active one. Replacement and deletion keep the old rows: citations of earlier replies point at them, and retrieval skips them.

### Retrieval

`app/services/documents/retrieval.py` runs an exact cosine search over chunks whose version is active, whose document is not deleted and whose `embedding_model` is the current one. There is no hybrid search and no reranker. The score ranks passages; it does not say whether a passage answers the question.

Retrieval is available without an answer in two ways:

- `POST /api/admin/documents/search` with `{"query": "...", "top_k": 5}` returns the ranked passages with document, version, section, page and text. In code: `retrieval.search(session, embeddings, query, limit=5)`.
- Every assistant message stores `usage.retrieved`: the passages its reply was built from, best first. For a follow-up question this search also uses the earlier visitor messages, so it can differ from a search for the message alone.

### Embedding and LLM modes

- **`EMBEDDING_PROVIDER=local`** hashes stemmed words and adjacent word pairs into a 1,024-dimension vector (`local-hashing-v1-1024`). It is deterministic, needs no model download, and matches words, not meaning: a synonym is not found.
- **`LLM_PROVIDER=local`** generates no text. The reply quotes the retrieved passages that share the most informative words with the question, and ends with a notice that it was not written by an AI model. `LocalLLMProvider.complete` raises; the chat service checks `llm.live`.
- **`LLM_PROVIDER=openai_compatible`** sends the system prompt, recent messages and numbered excerpts to the chat completions API and asks for a JSON object with the answer type, the answer and the excerpt numbers it used.

### How a reply is chosen

`app/services/chat/service.py` handles one visitor message in this order and commits the message and the reply together:

1. **Override guard** (`guard.py`). A message that tries to override the instructions, extract the prompt, change the role, dictate the reply or change the knowledge base gets a fixed `refusal`. Nothing is searched and no LLM is called. A refused message is left out of the context of later messages.
2. **Inquiry seam.** The detector described in [Chat and inquiries](#chat-and-inquiries) is asked next. Detected intent gives an `inquiry_offer`.
3. **Retrieval.** The message is embedded and searched. Earlier visitor messages (the last two) are added to the query with a lower weight, or with the same weight when the new message is too short to stand alone ("And for the P-240?").
4. **Document instructions are data.** Before a passage is quoted or sent to an LLM, blocks that address the assistant or try to override instructions are removed (`strip_embedded_instructions`), and a section whose heading does so is dropped whole. The LLM prompt repeats the rule.
5. **Answer.**
   - Local mode: each content word of the question is weighted by how rare it is among the retrieved passages. The reply is `grounded` only if the quoted passages cover at least half of that weight; otherwise it is a `knowledge_gap`. A message without any content word gets a `clarification`. The retrieval score alone never makes a reply grounded.
   - LLM mode: the model chooses the answer type. A `grounded` reply must cite at least one excerpt that was really sent; if it does not, the reply is replaced by a `knowledge_gap`, and `usage.note` records why. A knowledge gap that does not already mention a person or the team gets an offer to pass the question on.

A provider failure, or an LLM reply that is not the expected JSON, returns `503`; nothing is stored, and the visitor can send the message again.

The guards are deterministic patterns for explicit attempts. They are a first line of defense, not proof against every phrasing.

Known limits of the local mode: it cannot paraphrase, compare or compute; it finds an answer only when the question and the document share words; an ambiguous question usually gets the closest quote instead of a clarifying question.

### Seeding

`make seed` loads `knowledge-base/northline/manifest.json` and returns when every document is searchable. It indexes in-process, so no worker has to run. The command is idempotent: an entry is matched to a stored document by its `title`, a file with a new checksum becomes a new version, and a document that is not searchable with the current embedding model is indexed again.

A manifest entry maps to the stored document as follows: `title` → `documents.title`, `version` → `document_versions.version_label`, the file name of `path` → `source_filename`. `python -m scripts.seed_knowledge_base --map-file map.json` writes `doc_id` with the stored document ID for every entry, and `--manifest` loads another manifest of the same format, such as `evals/fixtures/manifest.json`.

## Background jobs

Jobs live in the `jobs` table. API code enqueues a job in the same transaction as the change that needs it:

```python
await queue.enqueue(session, job_types.DELIVER_INQUIRY, {"inquiry_id": str(inquiry.id)},
                    idempotency_key=f"inquiries.deliver:{inquiry.id}")
await session.commit()
```

- **Idempotency.** Enqueueing an existing `idempotency_key` returns the existing job.
- **Claiming.** The worker locks the next due job with `FOR UPDATE SKIP LOCKED`, so several workers never take the same job or wait on each other.
- **Retries.** A handler that raises is retried after a backoff of base, 2× base, 4× base and so on, up to a maximum, until `max_attempts` is reached. `PermanentJobError` fails the job at once. `queue.requeue` gives a failed job a fresh set of attempts (manual retry).
- **Leases.** A job that stays `running` longer than `JOB_LEASE_SECONDS` is taken over by another worker. A worker that lost its lease cannot record a result, and its handler's writes are rolled back.
- **Transactions.** A handler gets `JobContext` with a session. Its writes are committed together with the job's success and rolled back on failure. To keep a record of a failed attempt, commit before raising.
- **Handlers must be idempotent.** A job can run more than once.

Handlers register in `app/worker/handlers/indexing.py` (T3) and `app/worker/handlers/delivery.py` (T4). Job type names are in `app/worker/job_types.py`.

## Frontend

Routes: `/` (chat) and `/admin`. Both are placeholders until T5 builds the screens.

- `src/api/client.ts` exports `api` (visitor endpoints), `createAdminApi(token)`, and `unwrap`, which returns data or throws an `ApiError` in the common format.
- `src/api/schema.d.ts` is generated; never edit it by hand.
- `HealthProvider` loads `/api/health` once; `useHealth()` gives it to any component. `ModeBanner` labels demo modes and reports an unreachable server or database.
- `src/styles/tokens.css` holds the design tokens of the single light theme. Components use tokens only: no hardcoded colors, sizes or fonts. The font stack is system fonts, so no font files are shipped.

## Ownership

Three tasks build on the foundation in parallel. Each module has one owner.

| Area | T3: knowledge base and chat | T4: inquiries and CRM | T5: frontend |
| --- | --- | --- | --- |
| Routes | `api/routes/conversations.py`, `api/routes/admin_documents.py` | `api/routes/inquiries.py`, `api/routes/admin_inquiries.py` | |
| Services | `services/chat/`, `services/documents/` | `services/inquiries/` (including `intent.py`) | |
| Providers | `providers/llm/local.py`, `providers/llm/openai_compatible.py`, `providers/embeddings/local.py`, `providers/embeddings/openai_compatible.py` | `providers/crm/simulated.py`, `providers/crm/hubspot.py` | |
| Jobs | `worker/handlers/indexing.py` | `worker/handlers/delivery.py` | |
| Tests | new test files for the modules above | new test files for the modules above | |
| Frontend | | | everything under `frontend/src` except `api/schema.d.ts` |

**Shared files** change only additively (new fields, new values, new functions; no renames or removals), and every such change is listed in the task report:

- `backend/app/schemas/`, `backend/app/models/`, `backend/migrations/`
- `backend/app/core/` (settings), `backend/app/api/deps.py`, `backend/app/api/errors.py`, `backend/app/api/router.py`, `backend/app/main.py`
- provider interfaces (`providers/*/base.py`, `providers/factory.py`, `providers/errors.py`)
- `backend/app/services/inquiry_intent.py`, `backend/app/worker/` outside `handlers/indexing.py` and `handlers/delivery.py`
- `backend/tests/conftest.py`, `backend/tests/api_cases.py` (removing your own stub cases is expected)
- `.env.example`, `Makefile`, `docker-compose.yml`, `backend/pyproject.toml`, `frontend/package.json`

**Generated files** (`docs/openapi.json`, `frontend/src/api/schema.d.ts`, `backend/uv.lock`, `frontend/pnpm-lock.yaml`) are never merged by hand. On a conflict, take either side and regenerate: `make openapi`, `uv lock`, `pnpm install`.

**Migrations.** The initial migration is meant to cover T3 and T4. If a task still needs a schema change, it adds one migration on top of the current head and says so in its report. `test_migrations_have_a_single_head` fails when two tasks add migrations in parallel; rebase one on the other.

## Development

```
make setup    # install backend and frontend dependencies
make dev      # database, migrations, API, worker, frontend
make check    # ruff, mypy, pytest, frontend API types, lint, type check, tests, build
make openapi  # regenerate docs/openapi.json and frontend/src/api/schema.d.ts
make migrate  # apply migrations
make seed     # load the Northline knowledge base (idempotent)
make db       # run only the embedded PostgreSQL and print its DATABASE_URL
```

Without `DATABASE_URL`, `make dev` and the tests start an embedded PostgreSQL with pgvector from the `pixeltable-pgserver` development dependency, so no Docker, system PostgreSQL or root access is needed. Development data is kept in `.local/postgres`. Tests always run on real PostgreSQL with pgvector; set `TEST_DATABASE_URL` to use an existing disposable database instead of the embedded one.

`pixeltable-pgserver` is pinned to 0.5.1. Its 0.7.x wheels ship a pgvector build that needs AVX-512 and crashes on CPUs without it.

Ports come from `BACKEND_PORT` and `FRONTEND_PORT` (environment or `.env`).

## Known limits of the foundation

- The Docker Compose setup was written without a Docker host and has not been run yet.
- FastAPI reads a request body before it checks the admin token. The document upload routes are protected by `app/api/upload_guard.py`, which checks the token and `MAX_UPLOAD_BYTES` before the body is read. Other admin routes take small JSON bodies; the nginx configuration caps the body size for them.
- A human handoff is an inquiry with `kind: "handoff"`: the UI creates it after a knowledge gap, the visitor confirms it, and it is delivered to the CRM like a purchase inquiry. Nobody is notified by email.
- The HubSpot integration has not been verified on a live account; see [inquiries.md](inquiries.md).
