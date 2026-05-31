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
BACKUP_DIR   := backend/backups
DB_USER      := aicrm
DB_NAME      := aicrm
DB_CONTAINER := aicrm-postgres

# ─── Help ──────────────────────────────────────────────────────────────────────

.PHONY: help
help: ## Show this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make \033[36m<target>\033[0m\n\nTargets:\n"} \
		/^[a-zA-Z_.-]+:.*##/ { printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

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
migrate.check: ## Run CI-shaped migration safety check against local backend DB.
	cd $(BACKEND_DIR) && uv run alembic upgrade head
	cd $(BACKEND_DIR) && uv run alembic check
	cd $(BACKEND_DIR) && uv run alembic downgrade -1
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
	@./scripts/rotate_encryption_key.sh

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
