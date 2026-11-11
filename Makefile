.DEFAULT_GOAL := help
.PHONY: help setup dev db migrate openapi check check-backend check-frontend

help: ## Show the available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-16s %s\n", $$1, $$2}'

setup: ## Install backend and frontend dependencies
	cd backend && uv sync --locked
	cd frontend && pnpm install --frozen-lockfile

dev: ## Run the database, migrations, API, worker and frontend
	cd backend && uv run python -m scripts.dev up

db: ## Run only the embedded PostgreSQL and print its DATABASE_URL
	cd backend && uv run python -m scripts.dev db

migrate: ## Apply database migrations
	cd backend && uv run python -m scripts.dev migrate

openapi: ## Regenerate docs/openapi.json and the frontend API types
	cd backend && uv run python -m scripts.export_openapi
	cd frontend && pnpm run api:generate

check: check-backend check-frontend ## Run every check

check-backend: ## Lint, type-check and test the backend
	cd backend && uv run ruff check .
	cd backend && uv run ruff format --check .
	cd backend && uv run mypy
	cd backend && uv run pytest

check-frontend: ## Check API types, lint, type-check, test and build the frontend
	cd frontend && pnpm run api:check
	cd frontend && pnpm run lint
	cd frontend && pnpm run typecheck
	cd frontend && pnpm run test
	cd frontend && pnpm run build
