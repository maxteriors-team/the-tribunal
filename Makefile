# The Tribunal — Makefile
#
# Run `make help` for a list of targets.
#
# Conventions:
#   - Each public target is annotated with `## description` and appears in `make help`.
#   - Parallel targets (`dev`) use `-j` and trap Ctrl-C so children exit cleanly.
#   - All Python work shells into ./backend; all Node work shells into ./frontend.

SHELL        := /usr/bin/env bash
.SHELLFLAGS  := -eu -o pipefail -c
.DEFAULT_GOAL := help

BACKEND_DIR  := backend
FRONTEND_DIR := frontend

# ─── Help ──────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_.-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ─── Dev loop ──────────────────────────────────────────────────────────────────

.PHONY: dev
dev: dev.db ## Run db + backend + frontend together (Ctrl-C stops all).
	@echo "▶ starting backend and frontend in parallel — Ctrl-C to stop"
	@trap 'kill 0' INT TERM EXIT; \
		$(MAKE) -j2 --no-print-directory dev.backend dev.frontend

.PHONY: dev.backend
dev.backend: ## Run FastAPI with --reload on :8000.
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload --port 8000

.PHONY: dev.frontend
dev.frontend: ## Run Next.js dev server on :3000.
	cd $(FRONTEND_DIR) && npm run dev

.PHONY: dev.db
dev.db: ## Start Postgres + Redis via docker compose (detached).
	cd $(BACKEND_DIR) && docker compose up -d

.PHONY: db.down
db.down: ## Stop docker compose services (keeps volumes).
	cd $(BACKEND_DIR) && docker compose down

.PHONY: db.reset
db.reset: ## Stop services, drop volumes, restart, re-run migrations. Destructive.
	@echo "⚠  this wipes local Postgres + Redis volumes"
	cd $(BACKEND_DIR) && docker compose down -v
	cd $(BACKEND_DIR) && docker compose up -d
	@echo "▶ waiting for Postgres…"
	@sleep 3
	$(MAKE) --no-print-directory migrate

# ─── Migrations ────────────────────────────────────────────────────────────────

.PHONY: migrate
migrate: ## Apply pending Alembic migrations.
	cd $(BACKEND_DIR) && uv run alembic upgrade head

.PHONY: migrate.new
migrate.new: ## Autogenerate a new migration: make migrate.new m="add foo column".
	@if [ -z "$(m)" ]; then echo "✗ missing message — usage: make migrate.new m=\"...\""; exit 1; fi
	cd $(BACKEND_DIR) && uv run alembic revision --autogenerate -m "$(m)"

# ─── Tests ─────────────────────────────────────────────────────────────────────

.PHONY: test
test: test.backend test.frontend ## Run all tests (backend + frontend).

.PHONY: test.backend
test.backend: ## Run pytest.
	cd $(BACKEND_DIR) && uv run pytest

.PHONY: test.frontend
test.frontend: ## Run frontend tests.
	cd $(FRONTEND_DIR) && npm test

# ─── Quality ───────────────────────────────────────────────────────────────────

.PHONY: lint
lint: ## Ruff (backend) + ESLint (frontend).
	cd $(BACKEND_DIR) && uv run ruff check app
	cd $(FRONTEND_DIR) && npm run lint

.PHONY: format
format: ## Ruff format (backend) + Prettier (frontend).
	cd $(BACKEND_DIR) && uv run ruff format app
	cd $(FRONTEND_DIR) && npx prettier --write .

.PHONY: typecheck
typecheck: ## mypy (backend) + tsc --noEmit (frontend).
	cd $(BACKEND_DIR) && uv run mypy app
	cd $(FRONTEND_DIR) && npx tsc --noEmit

# ─── Deps ──────────────────────────────────────────────────────────────────────

.PHONY: install
install: ## Install backend (uv sync) and frontend (npm ci) deps.
	cd $(BACKEND_DIR) && uv sync
	cd $(FRONTEND_DIR) && npm ci

.PHONY: audit
audit: ## Check for outdated/insecure deps.
	cd $(BACKEND_DIR) && uv pip list --outdated
	cd $(FRONTEND_DIR) && npm audit

# ─── Housekeeping ──────────────────────────────────────────────────────────────

.PHONY: clean
clean: ## Remove caches, build artifacts, and coverage output.
	@echo "▶ cleaning backend caches"
	find $(BACKEND_DIR) -type d -name __pycache__ -prune -exec rm -rf {} +
	find $(BACKEND_DIR) -type d -name .pytest_cache -prune -exec rm -rf {} +
	find $(BACKEND_DIR) -type d -name .mypy_cache -prune -exec rm -rf {} +
	find $(BACKEND_DIR) -type d -name .ruff_cache -prune -exec rm -rf {} +
	rm -rf $(BACKEND_DIR)/.coverage $(BACKEND_DIR)/htmlcov $(BACKEND_DIR)/dist $(BACKEND_DIR)/build
	@echo "▶ cleaning frontend artifacts"
	rm -rf $(FRONTEND_DIR)/.next $(FRONTEND_DIR)/.turbo $(FRONTEND_DIR)/coverage $(FRONTEND_DIR)/dist
