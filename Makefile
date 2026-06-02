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

BACKEND_DIR       := backend
FRONTEND_DIR      := frontend
OPENAPI_ARTIFACTS := $(BACKEND_DIR)/openapi.json $(FRONTEND_DIR)/src/lib/api/_generated.ts
BACKUP_DIR        := backend/backups
DB_USER           := aicrm
DB_NAME           := aicrm
DB_CONTAINER      := aicrm-postgres

CI_BACKEND_COVERAGE_FLOOR ?= 48
CI_OPENAPI_SECRET_KEY     ?= ci-openapi-export-secret-key-not-used-for-signing-0123
CI_OPENAPI_ENCRYPTION_KEY ?= ci-openapi-export-encryption-key-not-used-for-crypto-01
CI_PYTEST_SECRET_KEY      ?= ci-pytest-secret-key-not-used-for-signing-0123456789
CI_PYTEST_ENCRYPTION_KEY  ?= ci-pytest-encryption-key-not-used-for-crypto-012
CI_PYTEST_OPENAI_API_KEY  ?= sk-ci-pytest-placeholder-not-a-real-key

# ─── Help ──────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z0-9_.\/-]+:.*##/ { printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# ─── Dev loop ──────────────────────────────────────────────────────────────────

.PHONY: dev
dev: dev.db ## Run db + backend + frontend together (Ctrl-C stops all).
	@echo "▶ starting backend and frontend in parallel — Ctrl-C to stop"
	@trap 'kill 0' INT TERM EXIT; \
		$(MAKE) -j2 --no-print-directory dev.backend dev.frontend

.PHONY: dev.backend
dev.backend: ## Run FastAPI with --reload on :8000.
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload --port 8000

.PHONY: dev.workers
dev.workers: ## Run backend background workers without the API server.
	cd $(BACKEND_DIR) && RUN_BACKGROUND_WORKERS=true uv run backend-workers

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

.PHONY: migrate.heads
migrate.heads: ## Verify the Alembic graph has exactly one head.
	@cd $(BACKEND_DIR) && \
		heads_output=$$(mktemp); \
		trap 'rm -f "$$heads_output"' EXIT; \
		uv run alembic heads --resolve-dependencies >"$$heads_output"; \
		cat "$$heads_output"; \
		count=$$(sed '/^[[:space:]]*$$/d' "$$heads_output" | wc -l | tr -d ' '); \
		if [ "$$count" -ne 1 ]; then \
			echo "✗ expected exactly 1 Alembic head, found $$count"; \
			exit 1; \
		fi

.PHONY: migrate.history
migrate.history: ## Show Alembic migration history.
	cd $(BACKEND_DIR) && uv run alembic history --verbose

.PHONY: migrate.check
migrate.check: ci.migrations ## Alias for ci.migrations.

.PHONY: migrate.new
migrate.new: ## Autogenerate a new migration: make migrate.new m="add foo column".
	@if [ -z "$(m)" ]; then echo "✗ missing message — usage: make migrate.new m=\"...\""; exit 1; fi
	cd $(BACKEND_DIR) && uv run alembic revision --autogenerate -m "$(m)"

# ─── CI parity ─────────────────────────────────────────────────────────────────

.PHONY: ci.backend.deps
ci.backend.deps:
	cd $(BACKEND_DIR) && uv lock --check
	cd $(BACKEND_DIR) && uv sync --frozen

.PHONY: ci.frontend.deps
ci.frontend.deps:
	@if [ ! -f "$(FRONTEND_DIR)/package-lock.json" ]; then \
		echo "✗ $(FRONTEND_DIR)/package-lock.json is missing. Run 'cd $(FRONTEND_DIR) && npm install' and commit it."; \
		exit 1; \
	fi
	@cd $(FRONTEND_DIR) && \
		if ! npm ci --dry-run --ignore-scripts >/dev/null 2>&1; then \
			echo "✗ package-lock.json is out of sync with package.json. Run 'cd $(FRONTEND_DIR) && npm install' and commit the lockfile."; \
			exit 1; \
		fi
	cd $(FRONTEND_DIR) && npm ci

.PHONY: ci.env
ci.env: ## Verify env templates match backend config and frontend env usage.
	python3 scripts/dev/check_env_drift.py

.PHONY: ci.backend
ci.backend: ci.backend.deps ci.env ## Run backend CI parity: env drift, lint, format, type-check, and coverage.
	cd $(BACKEND_DIR) && uv run ruff check app
	cd $(BACKEND_DIR) && uv run ruff format --check app
	cd $(BACKEND_DIR) && uv run mypy app
	cd $(BACKEND_DIR) && \
		SECRET_KEY="$(CI_PYTEST_SECRET_KEY)" \
		ENCRYPTION_KEY="$(CI_PYTEST_ENCRYPTION_KEY)" \
		OPENAI_API_KEY="$(CI_PYTEST_OPENAI_API_KEY)" \
		CORS_ALLOW_VERCEL_PREVIEWS="true" \
		SKIP_WEBHOOK_VERIFICATION="false" \
		uv run pytest --cov=app --cov-report=term --cov-fail-under=$(CI_BACKEND_COVERAGE_FLOOR)

.PHONY: ci.frontend
ci.frontend: ci.frontend.deps ci.env ## Run frontend CI parity: env drift, lint, type-check, unit tests, and build.
	cd $(FRONTEND_DIR) && npm run lint
	cd $(FRONTEND_DIR) && npm run typecheck
	cd $(FRONTEND_DIR) && npm test -- --run
	cd $(FRONTEND_DIR) && npm run build

.PHONY: codegen
codegen: ci.backend.deps ci.frontend.deps ## Regenerate OpenAPI schema and frontend API client.
	SECRET_KEY="$(CI_OPENAPI_SECRET_KEY)" \
	ENCRYPTION_KEY="$(CI_OPENAPI_ENCRYPTION_KEY)" \
	uv run --project $(BACKEND_DIR) export-openapi
	cd $(FRONTEND_DIR) && npm run codegen

.PHONY: codegen/check
codegen/check: codegen ## Regenerate OpenAPI/client artifacts and fail on drift.
	@if ! git diff --exit-code -- $(OPENAPI_ARTIFACTS); then \
		echo "✗ Generated API artifacts are out of date. Run 'make codegen' and commit $(OPENAPI_ARTIFACTS)."; \
		exit 1; \
	fi

.PHONY: ci.codegen
ci.codegen: codegen/check ## Alias for codegen/check.

.PHONY: ci.migrations
ci.migrations: ci.backend.deps ## Run migration CI parity against the configured backend database.
	cd $(BACKEND_DIR) && uv run alembic upgrade head
	cd $(BACKEND_DIR) && uv run alembic check
	cd $(BACKEND_DIR) && uv run alembic downgrade -1
	cd $(BACKEND_DIR) && uv run alembic upgrade head

.PHONY: ci.all
ci.all: codegen/check ci.backend ci.frontend ci.migrations ## Run all CI parity targets.

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

# ─── Audit ─────────────────────────────────────────────────────────────────────

.PHONY: audit
audit: audit.deps audit.security audit.secrets ## Run all audit checks (deps + security + secrets).

.PHONY: audit.deps
audit.deps: ## List outdated backend (uv tree) and frontend (npm) deps.
	@echo "▶ backend — uv tree --outdated"
	cd $(BACKEND_DIR) && uv tree --outdated --depth 1
	@echo
	@echo "▶ frontend — npm outdated"
	@cd $(FRONTEND_DIR) && npm outdated || true   # npm outdated exits 1 when results exist

.PHONY: audit.security
audit.security: ## Scan for known CVEs in backend (pip-audit) and frontend prod deps (npm audit).
	@echo "▶ backend — pip-audit against the exported lockfile (excludes the editable project itself)"
	@cd $(BACKEND_DIR) && \
		tmp=$$(mktemp) && \
		uv export --no-emit-project --format requirements-txt > "$$tmp" && \
		trap 'rm -f "$$tmp"' EXIT && \
		uv run pip-audit --strict -r "$$tmp"
	@echo
	@echo "▶ frontend — npm audit --omit=dev"
	cd $(FRONTEND_DIR) && npm audit --omit=dev

.PHONY: audit.secrets
audit.secrets: ## Scan the working tree for committed secrets (gitleaks).
	@if command -v gitleaks >/dev/null 2>&1; then \
		echo "▶ gitleaks detect (binary)"; \
		gitleaks detect --no-banner --redact --verbose; \
	elif command -v pre-commit >/dev/null 2>&1; then \
		echo "▶ gitleaks (via pre-commit)"; \
		pre-commit run gitleaks --all-files; \
	else \
		echo "✗ neither gitleaks nor pre-commit is installed — see CONTRIBUTING.md#audit"; \
		exit 1; \
	fi

# ─── Ops ───────────────────────────────────────────────────────────────────────

.PHONY: rotate.encryption-key
rotate.encryption-key: ## Interactive rotation of ENCRYPTION_KEY on Railway + re-encrypt rows.
	@./scripts/ops/rotate_encryption_key.sh

.PHONY: db.backup.local
db.backup.local: ## pg_dump the local dev Postgres (custom format) into backend/backups/.
	@mkdir -p $(BACKUP_DIR)
	@stamp=$$(date +%Y%m%d-%H%M%S); \
		out="$(BACKUP_DIR)/$(DB_NAME)-$$stamp.dump"; \
		echo "▶ dumping $(DB_NAME) from container $(DB_CONTAINER) → $$out"; \
		docker exec $(DB_CONTAINER) pg_dump -Fc -U $(DB_USER) -d $(DB_NAME) > "$$out"; \
		echo "✓ wrote $$out ($$(du -h "$$out" | cut -f1))"

.PHONY: db.restore.local
db.restore.local: ## Restore a pg_dump file into local dev DB. Usage: make db.restore.local f=backend/backups/<file>.dump
	@if [ -z "$(f)" ]; then echo "✗ missing file — usage: make db.restore.local f=path/to/dump"; exit 1; fi
	@if [ ! -f "$(f)" ]; then echo "✗ file not found: $(f)"; exit 1; fi
	@echo "⚠  this will OVERWRITE the local $(DB_NAME) database with $(f)"
	@read -r -p "continue? [y/N] " reply; \
		case "$$reply" in [yY]|[yY][eE][sS]) ;; *) echo "aborted"; exit 1 ;; esac
	@docker exec -i $(DB_CONTAINER) pg_restore --clean --if-exists \
		-U $(DB_USER) -d $(DB_NAME) < "$(f)"
	@echo "✓ restored $(f)"

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
