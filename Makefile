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
# Kept outside the repo so a dump key can never be committed. Override to point
# at a shared secret store.
BACKUP_KEY        ?= $(HOME)/.the-tribunal-backup-keys/backups.key
# Sentinel proving the key was copied somewhere off this machine. Absent = every
# backup prints a loud banner; `make db.key.escrowed` records it and goes quiet.
BACKUP_KEY_ESCROW ?= $(dir $(BACKUP_KEY)).escrowed
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
	# alembic/env.py imports app.core.config, and migrations that touch encrypted
	# columns import app.core.encryption -- both fail closed without these. Locally
	# backend/.env supplies them; CI has no .env, so set the same throwaway values
	# the pytest target uses. Neither key protects real data here.
	cd $(BACKEND_DIR) && SECRET_KEY="$(CI_PYTEST_SECRET_KEY)" ENCRYPTION_KEY="$(CI_PYTEST_ENCRYPTION_KEY)" uv run alembic upgrade head
	cd $(BACKEND_DIR) && SECRET_KEY="$(CI_PYTEST_SECRET_KEY)" ENCRYPTION_KEY="$(CI_PYTEST_ENCRYPTION_KEY)" uv run alembic check
	cd $(BACKEND_DIR) && SECRET_KEY="$(CI_PYTEST_SECRET_KEY)" ENCRYPTION_KEY="$(CI_PYTEST_ENCRYPTION_KEY)" uv run alembic downgrade -1
	cd $(BACKEND_DIR) && SECRET_KEY="$(CI_PYTEST_SECRET_KEY)" ENCRYPTION_KEY="$(CI_PYTEST_ENCRYPTION_KEY)" uv run alembic upgrade head

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

# ─── Smoke (live deployment) ─────────────────────────────────────────────────────

.PHONY: smoke
smoke: smoke.backend smoke.frontend ## Smoke-test a live deployment (set SMOKE_BASE_URL + PLAYWRIGHT_BASE_URL).

.PHONY: smoke.backend
smoke.backend: ## Smoke-test a live backend. Usage: make smoke.backend SMOKE_BASE_URL=https://<app>.railway.app
	cd $(BACKEND_DIR) && $(if $(SMOKE_BASE_URL),SMOKE_BASE_URL="$(SMOKE_BASE_URL)" )uv run pytest tests/smoke -m smoke -v

.PHONY: smoke.frontend
smoke.frontend: ## Smoke-test a live frontend. Usage: make smoke.frontend PLAYWRIGHT_BASE_URL=https://<app>.vercel.app
	cd $(FRONTEND_DIR) && $(if $(PLAYWRIGHT_BASE_URL),PLAYWRIGHT_BASE_URL="$(PLAYWRIGHT_BASE_URL)" )npx playwright test smoke.spec.ts

.PHONY: smoke.watch
smoke.watch: ## Continuously verify a live deployment step-by-step (default: local dev). Override BACKEND_URL/FRONTEND_URL/INTERVAL.
	scripts/smoke-watch.sh

.PHONY: smoke.jobs
smoke.jobs: ## Seed a worker+technician and smoke the authed job-calendar flow. Usage: make smoke.jobs SEED_ADMIN_PASSWORD=<pw> [SMOKE_BASE_URL=http://localhost:8000]
	cd $(BACKEND_DIR) && uv run python -m scripts.smoke_jobs_calendar

# ─── Visual preview ──────────────────────────────────────────────────────────────

.PHONY: visual
visual: ## Capture the screenshot gallery + build it. Needs a running app (set PLAYWRIGHT_BASE_URL, or it boots `next start`). Set E2E_USER_EMAIL/PASSWORD for authed pages.
	cd $(FRONTEND_DIR) && npm run visual && npm run visual:gallery

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

.PHONY: deploy.backend
deploy.backend: ## Deploy the backend to Railway with the commit SHA baked in (so /version reports it). Extra args pass through to `railway up`.
	@./scripts/ops/deploy_backend.sh

.PHONY: rotate.encryption-key
rotate.encryption-key: ## Interactive rotation of ENCRYPTION_KEY on Railway + re-encrypt rows.
	@./scripts/ops/rotate_encryption_key.sh

.PHONY: db.backup.local
db.backup.local: ## pg_dump the local dev Postgres, encrypted, into backend/backups/.
	@mkdir -p $(BACKUP_DIR)
	@$(MAKE) --no-print-directory _backup.keycheck
	@stamp=$$(date +%Y%m%d-%H%M%S); \
		out="$(BACKUP_DIR)/$(DB_NAME)-$$stamp.dump.enc"; \
		echo "▶ dumping $(DB_NAME) from container $(DB_CONTAINER) → $$out"; \
		docker exec $(DB_CONTAINER) pg_dump -Fc -U $(DB_USER) -d $(DB_NAME) \
			| openssl enc -aes-256-cbc -pbkdf2 -iter 250000 -salt -out "$$out" -pass file:$(BACKUP_KEY); \
		if [ ! -s "$$out" ]; then echo "✗ dump is empty"; rm -f "$$out"; exit 1; fi; \
		chmod 600 "$$out"; \
		echo "✓ wrote $$out ($$(du -h "$$out" | cut -f1)) — encrypted, mode 600"

.PHONY: db.backup.prod
db.backup.prod: ## pg_dump a remote/prod Postgres (read-only), encrypted, into backend/backups/. Usage: make db.backup.prod DATABASE_URL='postgresql://[REDACTED]@host:5432/db'
	@if [ -z "$(DATABASE_URL)" ]; then \
		echo "✗ missing DATABASE_URL — usage: make db.backup.prod DATABASE_URL='postgresql://[REDACTED]@host:port/db'"; \
		echo "  Use the PUBLIC url (Railway → Postgres → Connect → 'Public Network', host *.proxy.rlwy.net); the internal *.railway.internal host is unreachable from here."; \
		echo "  The +asyncpg suffix is stripped automatically."; \
		exit 1; \
	fi
	@mkdir -p $(BACKUP_DIR)
	@$(MAKE) --no-print-directory _backup.keycheck
	@stamp=$$(date +%Y%m%d-%H%M%S); \
		out="$(BACKUP_DIR)/prod-$$stamp.dump.enc"; \
		url="$$(echo '$(DATABASE_URL)' | sed -E 's#\+asyncpg##; s#\+psycopg2##')"; \
		echo "▶ pg_dump (read-only, custom format) of prod → $$out"; \
		docker run --rm -i postgres:18 pg_dump -Fc "$$url" \
			| openssl enc -aes-256-cbc -pbkdf2 -iter 250000 -salt -out "$$out" -pass file:$(BACKUP_KEY); \
		if [ ! -s "$$out" ]; then echo "✗ dump is empty — check DATABASE_URL / network"; rm -f "$$out"; exit 1; fi; \
		chmod 600 "$$out"; \
		echo "✓ wrote $$out ($$(du -h "$$out" | cut -f1)) — encrypted, mode 600"

# A prod dump is a full cleartext copy of customer PII, and it predates the
# field-level encryption inside the database — so an unencrypted dump on disk is
# strictly more sensitive than the database itself (audit C-3). Written
# encrypted at creation so a stolen laptop, a synced folder, or any local
# process cannot read it. The key lives outside the repo; losing it means losing
# the backups, so keep a copy in a password manager.
.PHONY: _backup.keycheck
_backup.keycheck:
	@if [ ! -f "$(BACKUP_KEY)" ]; then \
		mkdir -p "$$(dirname $(BACKUP_KEY))"; chmod 700 "$$(dirname $(BACKUP_KEY))"; \
		openssl rand -base64 48 > "$(BACKUP_KEY)"; chmod 600 "$(BACKUP_KEY)"; \
		echo "▶ generated a new backup encryption key at $(BACKUP_KEY)"; \
	fi
	@$(MAKE) --no-print-directory _backup.escrowcheck

.PHONY: _backup.escrowcheck
_backup.escrowcheck:
	@fp="$$(openssl dgst -sha256 "$(BACKUP_KEY)" 2>/dev/null | awk '{print $$NF}' | cut -c1-16 || true)"; \
	if [ -n "$$fp" ] && ! grep -qs "key-fingerprint $$fp" "$(BACKUP_KEY_ESCROW)"; then \
		n=$$(ls -1 $(BACKUP_DIR)/*.dump.enc 2>/dev/null | wc -l | tr -d ' '); \
		echo ""; \
		echo "  ┌──────────────────────────────────────────────────────────────────────┐"; \
		echo "  │  ⚠  BACKUP KEY EXISTS ON THIS MACHINE ONLY                           │"; \
		echo "  ├──────────────────────────────────────────────────────────────────────┤"; \
		printf "  │  %-68s│\n" "$$n encrypted dump(s) are unrecoverable if this Mac dies."; \
		echo "  │                                                                      │"; \
		echo "  │  Copy it into your password manager:                                 │"; \
		echo "  │      make db.key.show                                                │"; \
		echo "  │                                                                      │"; \
		echo "  │  Then silence this banner:                                           │"; \
		echo "  │      make db.key.escrowed                                            │"; \
		echo "  └──────────────────────────────────────────────────────────────────────┘"; \
		echo ""; \
	fi

.PHONY: db.key.show
db.key.show: ## Print the backup encryption key so it can be copied into a password manager.
	@if [ ! -f "$(BACKUP_KEY)" ]; then echo "✗ no key at $(BACKUP_KEY) — run a backup first"; exit 1; fi
	@echo "▶ backup encryption key ($(BACKUP_KEY)) — store in a password manager, never commit:"
	@echo ""
	@cat "$(BACKUP_KEY)"
	@echo ""
	@echo "  Then run: make db.key.escrowed"

.PHONY: db.key.escrowed
db.key.escrowed: ## Record that the backup key is stored off this machine (silences the banner).
	@if [ ! -f "$(BACKUP_KEY)" ]; then echo "✗ no key at $(BACKUP_KEY) — nothing to escrow"; exit 1; fi
	@mkdir -p "$$(dirname $(BACKUP_KEY_ESCROW))"
	@printf 'escrowed %s\nkey-fingerprint %s\n' \
		"$$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
		"$$(openssl dgst -sha256 "$(BACKUP_KEY)" | awk '{print $$NF}' | cut -c1-16)" \
		> "$(BACKUP_KEY_ESCROW)"
	@chmod 600 "$(BACKUP_KEY_ESCROW)"
	@echo "✓ recorded — backup banner silenced."
	@echo "  If you ever rotate the key, delete $(BACKUP_KEY_ESCROW) to bring the reminder back."

.PHONY: db.restore.local
db.restore.local: ## Restore a dump into local dev DB (handles .enc). Usage: make db.restore.local f=backend/backups/<file>.dump.enc
	@if [ -z "$(f)" ]; then echo "✗ missing file — usage: make db.restore.local f=path/to/dump[.enc]"; exit 1; fi
	@if [ ! -f "$(f)" ]; then echo "✗ file not found: $(f)"; exit 1; fi
	@case "$(f)" in *.enc) \
		if [ ! -f "$(BACKUP_KEY)" ]; then echo "✗ encrypted dump but no key at $(BACKUP_KEY)"; exit 1; fi ;; \
	esac
	@echo "⚠  this will OVERWRITE the local $(DB_NAME) database with $(f)"
	@read -r -p "continue? [y/N] " reply; \
		case "$$reply" in [yY]|[yY][eE][sS]) ;; *) echo "aborted"; exit 1 ;; esac
	@case "$(f)" in \
		*.enc) openssl enc -d -aes-256-cbc -pbkdf2 -iter 250000 -in "$(f)" -pass file:$(BACKUP_KEY) \
			| docker exec -i $(DB_CONTAINER) pg_restore --clean --if-exists -U $(DB_USER) -d $(DB_NAME) ;; \
		*) docker exec -i $(DB_CONTAINER) pg_restore --clean --if-exists -U $(DB_USER) -d $(DB_NAME) < "$(f)" ;; \
	esac
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
