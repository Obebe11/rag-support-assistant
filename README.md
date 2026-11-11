# Handoff AI

An open-source demo of an AI support assistant that answers from company documents, cites its sources, and hands qualified leads to a CRM.

Status: in development. The repository has the project structure, the database schema, the API contract, provider interfaces, the background job queue and a frontend shell. The knowledge base (document upload, indexing, retrieval) and the chat with cited answers are implemented in the backend.

- [Architecture](docs/architecture.md)
- [API contract (OpenAPI)](docs/openapi.json)
- [Demo document corpus](demo-docs/README.md)
- [Sample demo questions](demo-docs/DEMO-QUESTIONS.md)

## Setup

Requirements: Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22 or later, [pnpm](https://pnpm.io/), GNU Make. Linux or macOS on x86-64 or ARM64.

```
make setup              # install backend and frontend dependencies
cp .env.example .env    # optional: every setting has a local default
make dev                # database, migrations, API, worker and frontend
make seed               # load the demo knowledge base (Northline Office Equipment)
make check              # linters, type checks, tests and the frontend build
```

`make dev` needs no Docker and no system PostgreSQL. It starts an embedded PostgreSQL with pgvector in `.local/postgres`, applies the migrations, and serves the frontend at `http://localhost:5173` and the API docs at `http://localhost:8000/api/docs`. Change the ports with `FRONTEND_PORT` and `BACKEND_PORT`.

The defaults run in demo mode: `LLM_PROVIDER=local`, `EMBEDDING_PROVIDER=local` and `CRM_PROVIDER=simulated` need no API keys. Local mode is not a working LLM, and simulated delivery is not a live CRM integration; the UI and `GET /api/health` label both. To call real services, set the provider settings described in [.env.example](.env.example).

Admin endpoints under `/api/admin` require `ADMIN_API_TOKEN` as a bearer token and reject every request while it is unset.

A [Docker Compose file](docker-compose.yml) for PostgreSQL with pgvector, the API, the worker and the frontend is included (`docker compose up --build`). It has not been run yet: it was written on a machine without Docker.

## License

Original Handoff AI code and documentation are released under the [MIT License](LICENSE). You may use, modify and distribute them, including for commercial purposes, as long as the copyright and license notice are kept.

## Third-Party Materials

The MIT License covers only original work in this repository. Third-party materials keep their own licenses:

- **Odoo documentation articles** in `demo-docs/odoo/` remain under **CC BY-SA 4.0**. Attribution, the original license and a source manifest are kept in that folder. See the [corpus licensing notice](demo-docs/odoo/README.md#attribution-and-license) and the [Odoo documentation license](demo-docs/odoo/LICENSE).

- **T3 Code interface code** in `frontend/src/t3code/` is copied or adapted from [T3 Code](https://github.com/pingdotgg/t3code) (`apps/web`, commit `be7d35aae`) and remains under the **MIT License**, Copyright (c) 2026 T3 Tools Inc. The license text, the list of files and the changes are kept in that folder: [LICENSE](frontend/src/t3code/LICENSE), [README](frontend/src/t3code/README.md). No T3 Code names, logos, icons or interface texts are used. The frontend dependencies added with it are under MIT, Apache-2.0 or ISC.
- **Dependencies** are not copied into this repository. They are installed from PyPI and npm and keep their own licenses. The direct dependencies listed in `backend/pyproject.toml` and `frontend/package.json` are under MIT, Apache-2.0, BSD-3-Clause or ISC.
- **PostgreSQL and pgvector** are used as the database and are under the PostgreSQL License. They are not part of this repository: Docker Compose pulls the `pgvector/pgvector` image, and local development uses the binaries bundled in the `pixeltable-pgserver` package (Apache-2.0), a development-only dependency.

Any third-party code added later will keep its original license file and be listed here.

## Trademarks

Odoo and HubSpot are trademarks of their respective owners. This is an independent portfolio project, not affiliated with or endorsed by them. Northline Office Equipment is a fictional company used for the demo.

## Contact

For custom implementations or freelance inquiries, contact Ivan Orlov (Obi) at [Ivan_orlov_00@pm.me](mailto:Ivan_orlov_00@pm.me).
