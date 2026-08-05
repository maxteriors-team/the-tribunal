# The Tribunal

The Tribunal is a proprietary AI-powered CRM command center for capturing leads, running AI voice/SMS follow-up, booking appointments, and giving operators a Next.js dashboard for human-in-the-loop decisions.

## Apps and stable structure

- `frontend/` — Next.js 16 + React 19 + TypeScript dashboard. Key folders: `src/app/` routes, `src/components/` feature/UI components, `src/lib/api/` API clients and generated OpenAPI types, `src/providers/` auth/workspace providers, `src/types/` shared domain types, `src/widget/` embeddable chat widget.
- `backend/` — FastAPI + SQLAlchemy async API. Key folders: `app/api/v1/` authenticated/public API routers, `app/api/webhooks/` Telnyx/Cal.com/Resend webhooks, `app/services/` domain logic, `app/models/` ORM models, `app/schemas/` Pydantic schemas, `app/workers/` in-process background jobs, `app/websockets/` voice/realtime bridges, `alembic/versions/` migrations, `tests/` pytest suites.
- `scripts/` — operational/demo scripts such as prompt updates, lead-magnet PDF generation/upload, encryption-key rotation, and stress/adversarial tests.
- `docs/` and `backend/docs/` — strategy, architecture, migration, and operational notes.

## Product domains and integrations

- Core domains include workspaces, contacts/leads, conversations, AI agents, SMS and voice campaigns, appointments, offers, lead magnets/forms, opportunities, pending approvals, nudges, automations, billing, and onboarding.
- The product targets home-service businesses (exterior cleaning, pressure washing, gutters, landscape/holiday lighting, and similar trades); onboarding seeds a lead-reactivation agent + campaign for re-engaging past customers.
- External integrations include OpenAI Realtime, Telnyx voice/SMS, Cal.com booking/webhooks, Resend email/webhooks, and Stripe billing.
- Address autocomplete (`/api/v1/workspaces/{id}/addresses/*`) proxies **Google Places when `GOOGLE_PLACES_API_KEY` is set, and the keyless US Census geocoder otherwise** — never call a provider from the browser, the key stays server-side. The Google path is billed per request, so the endpoints are rate limited per workspace and the field debounces; a provider failure returns an empty candidate list so the address stays hand-typeable.
- Frontend root redirects to `/contacts`; the app also exposes public surfaces under routes such as `embed`, offers, lead magnets, demos, and lead forms.

## Project-specific architecture notes

- The backend is multi-tenant by workspace; most domain routes and services are scoped through workspace-aware APIs.
- Background workers run inside the single FastAPI `backend-api` process via `start_all_workers()` in the app lifespan. There is no separate worker service or Celery process; deploying uvicorn/gunicorn with `--workers > 1` or multiple backend replicas multiplies every poll loop unless workers are extracted or leader-elected.
- `backend/static/` is served unauthenticated at `/static` for public marketing collateral such as lead-magnet PDFs only. Do not put customer files, exports, PII, credentials, or per-workspace assets there.
- Frontend typed API contracts derive from `backend/openapi.json`; when backend public routes/schemas change, run `make ci.codegen` and commit both `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`.
- Shared local primitives: use `backend/app/services/contacts/contact_filters.py` for rule-based contact/list filtering, `frontend/src/lib/query-keys.ts` for React Query keys, `frontend/src/lib/query-options.ts` for query presets, and `frontend/src/components/ui/page-state.tsx` for page-level loading/error/empty states.

## Local commands

- Install all deps: `make install` (`backend: uv sync`, `frontend: npm ci`).
- Start everything locally: `make dev` (Postgres/Redis via backend Docker Compose, FastAPI on `:8000`, Next.js on `:3000`).
- Start pieces: `make dev.db`, `make dev.backend`, `make dev.frontend`.
- Apply migrations: `make migrate`; create migration: `make migrate.new m="message"`.
- Backend checks used by CI: `make ci.backend`.
- Frontend checks used by CI: `make ci.frontend`.
- Codegen checks used by CI: `make ci.codegen`.
- Migration CI shape for model/migration changes: `make ci.migrations`.
- Full local CI parity: `make ci.all`.
- Frontend e2e on PRs: `cd frontend && npm run e2e` after installing Playwright Chromium.
- Local DB backup/restore targets: `make db.backup.local`; `make db.restore.local f=backend/backups/<file>.dump.enc`.
- **Database dumps are encrypted at creation** (AES-256-CBC + PBKDF2) and written `.dump.enc` mode 600. The key lives OUTSIDE the repo at `$(BACKUP_KEY)`, default `~/.the-tribunal-backup-keys/backups.key`, and is auto-generated on first backup. Losing that key makes every dump unrecoverable, so keep a copy in a password manager. Never write a plaintext `pg_dump` into `backend/backups/` — a prod dump is a full cleartext copy of customer PII and predates the field-level encryption inside the database, which makes it strictly more sensitive than the database itself.
- Encryption-key rotation workflow: `make rotate.encryption-key`. The rotation script fails loudly (non-zero exit) if a declared target column is not actually an `EncryptedString`, or if every row in a table was skipped — a rotation that silently no-ops is a failure, not a success.

## Runtime and deployment facts

- Backend local services are defined in `backend/docker-compose.yml` using PostgreSQL 17 and Redis 7 with `aicrm` database/container names.
- Frontend uses Node `24.18.0` from `frontend/.nvmrc`, `npm@10.9.0`, and deploys from `frontend/` on Vercel with `npm ci` + `npm run build`. Build settings are pinned in `frontend/vercel.json` (framework, install/build/output, region `iad1`), which also enables **git auto-deploy on push to `main`** (`git.deploymentEnabled.main`). Vercel's **Root Directory must be set to `frontend`** in the dashboard (not expressible in `vercel.json`) or git builds run `npm ci` at the repo root and fail — there is no root `package.json`/lockfile.
- Backend deploys on Railway via `backend/railway.toml`; pre-deploy runs `alembic upgrade head`, start command runs `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fd00::/8`, and healthcheck is `/readyz`. **Never set `--forwarded-allow-ips=*`** — that makes uvicorn trust the leftmost `X-Forwarded-For` entry, so any client can forge its own IP, defeating every IP-based rate limit (login brute force, demo/lead-form telephony spend caps) and poisoning audit records.
- `GET /version` reports the deployed commit. Railway injects `RAILWAY_GIT_COMMIT_SHA` only for **git-triggered** builds, so manual `railway up` deploys resolve it from `backend/app/build_info.json` — a stamp `scripts/ops/deploy_backend.sh` writes before upload and deletes after. Keep that stamp **out of `.gitignore`** (`railway up` skips gitignored paths, so an ignored stamp never reaches the builder) and **out of git** (a committed stamp makes `/version` report a stale SHA — worse than `"unknown"`; a pre-commit hook blocks it).
- Production contains live CRM/contact data. Test migrations locally first and back up data before schema changes that touch contact/lead tables.
- Production URLs: backend `https://the-tribunal-api-production.up.railway.app` (Railway project `the-tribunal`, service `the-tribunal-api`), frontend `https://the-tribunal-two.vercel.app` (Vercel project `the-tribunal`, team `maxteriors`).
- Production Postgres is **18.x** (local dev compose is 17): `make db.backup.prod` uses the `postgres:18` docker client; restoring a prod dump locally may need a newer client than the dev container.
- **Customer-facing links come from two env vars, and a wrong value fails silently.** `PUBLIC_BASE_URL` prefixes every tracked short link in outbound **SMS** (`/r/{code}`, redirected by the backend); `FRONTEND_URL` prefixes links in outbound **email** plus the public invoice/proposal pages. Both default to `localhost`, and a bad value still sends fine — the provider reports `delivered` and only the customer sees a dead link. `PUBLIC_BASE_URL` was unset in Railway until 2026-08-03, so texted proposals shipped `http://localhost:8000/r/...`. `_validate_public_urls()` in `backend/app/main.py` now refuses to boot a deployed environment when either value is blank, localhost, or missing its `https://` scheme — but it only engages when `ENVIRONMENT` is set to something other than `development`/`local`/`test`.
- **When the domain changes**, update together: Railway `PUBLIC_BASE_URL` (scheme included) and `FRONTEND_URL`, `CORS_ORIGINS`, the Vercel domain, and any Telnyx/Resend/Stripe/Cal.com webhook URLs. `short_links.target_url` stores **absolute** URLs, so links already texted keep pointing at the old frontend origin — keep it resolving (or backfill that column) or previously-sent links break.

## Release process (production changes)

Follow in order; do not skip. Verified against this repo 2026-07-29.

1. **Build locally**: `make dev`; schema changes via `make migrate.new m="..."` then `make migrate` locally; public API contract changes require `make codegen` and committing `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` **in the same commit** (`codegen/check` diffs against HEAD, so it fails on uncommitted artifacts — commit first, then run `make ci.all`).
2. **Prove it**: `make ci.all` must exit 0 (codegen drift, backend lint/type/tests, frontend lint/type/tests/build, migration up→check→down→up).
3. **Protect prod data**: if a migration touches contact/lead/invoice tables, run `make db.backup.prod DATABASE_URL='<public *.proxy.rlwy.net url>'` first (read-only; verify the dump is non-empty — `openssl enc -d ... | head -c 5` should read `PGDMP`). Keep the dump until the release is proven.
4. **Open a PR — `main` is protected and rejects direct pushes.** Required to merge: **4 status checks** (`Scan for secrets`, `Verify migration reversibility`, `Analyze (javascript-typescript)`, `Analyze (python)`), **linear history** (so merge with `--rebase` or `--squash`; a merge commit is refused), and **all review conversations resolved** — CodeQL auto-comments count, so a release can sit blocked on them. 0 approvals required. `gh pr create --base main` then `gh pr merge <n> --rebase --delete-branch`.
5. **Deploy the backend from the merged `main`, not from your branch.** `railway up` uploads the `backend/` **folder**, so whatever is on disk becomes production: deploying a checkout that is missing merged commits silently **reverts them in prod**. Always `git fetch && git reset --hard origin/main` (or `git pull --ff-only`) *first*, then `make deploy.backend`. The script now refuses to deploy when `origin/main` has backend commits the checkout lacks — override only for a deliberate rollback with `DEPLOY_ALLOW_BEHIND=1`. Note a rebase-merge **rewrites SHAs**, so the SHA you tested locally is not the SHA on `main`; deploy the rewritten one so `/version` matches a commit that actually exists.
6. **Frontend auto-deploys** on merge to `main` via Vercel git integration (`frontend/vercel.json` → `git.deploymentEnabled.main`, Root Directory = `frontend`). Vercel builds from **git**, so an unrelated dirty working tree cannot leak into it. **Backend does NOT auto-deploy.** When both change, get the backend live **before** the frontend deploy lands (old frontend + new API is safe; the reverse often isn't).
7. **Verify live**: `curl -s https://the-tribunal-api-production.up.railway.app/version` must report the SHA you deployed (not `"unknown"`, no `-dirty` suffix) **and that SHA must be an ancestor of `origin/main`** — `git branch -r --contains <sha>` proves you didn't ship orphaned code. Then `make smoke.backend SMOKE_BASE_URL=...` and `make smoke.frontend PLAYWRIGHT_BASE_URL=...`; then eyeball the changed feature logged in and watch Sentry/Railway logs.
8. **Rollback**: backend `railway redeploy` (previous deployment), frontend `npx vercel rollback <deployment-url>`; bad migration → `alembic downgrade -1` against prod or restore the pre-deploy dump from `backend/backups/`.

## Repo-local agent assets

- Canonical agent assets live under `.ezcoder/` (`commands/`, `plans/`, `skills/`, `agents/`, `eyes/`). Do not recreate legacy `.claude/commands/`, `.gg/commands/`, or `.gg/plans/`.
- Current local perception scripts are `.ezcoder/eyes/http.sh`, `.ezcoder/eyes/logs.sh`, and `.ezcoder/eyes/mail.sh`; probe state/artifacts under `.ezcoder/eyes/` are gitignored.

## Eyes

Perception probes live in `.ezcoder/eyes/`. All headless. Artifacts → `.ezcoder/eyes/out/` (gitignored). Invoke probes yourself; don't ask the user to verify what you can verify.

### Available probes

| Need | Run | Then |
|---|---|---|
| Hit a backend API or webhook endpoint | `.ezcoder/eyes/http.sh http://localhost:8000/api/v1/<resource> [GET\|POST\|PUT\|DELETE] [body-or-@file] [-H "Authorization: Bearer ..."]` | Read the JSON output, inspect the redacted `body`/`headers` files, and confirm status code plus response shape. |
| Hit public/static backend surfaces | `.ezcoder/eyes/http.sh http://localhost:8000/static/<asset>` or `.ezcoder/eyes/http.sh http://localhost:8000/readyz` | Confirm non-500 status, content-type/size, and body where applicable. |
| Check server or worker logs | `.ezcoder/eyes/logs.sh --file <path> --lines 100` or `.ezcoder/eyes/logs.sh --service backend --grep "ERROR|Traceback|<worker_name>"` | Scan the redacted output for tracebacks, worker activity, warnings, or the event you expected. |
| Inspect captured emails | `.ezcoder/eyes/mail.sh latest`, `.ezcoder/eyes/mail.sh list --limit 10`, or `.ezcoder/eyes/mail.sh read <id>` | Read the redacted subject/from/to/body and verify links, copy, recipients, and workspace-specific content. |
| Count or clear captured emails | `.ezcoder/eyes/mail.sh count` or `.ezcoder/eyes/mail.sh clear` | Use `clear` before email assertions, then compare `count` against the expected sends after triggering code. |

### When to use these eyes (automatically, without being asked)

Reach for probes ON YOUR OWN INITIATIVE when any of these apply:

- After adding or modifying a FastAPI route under `backend/app/api/v1/` or `backend/app/api/webhooks/`, start/use the local backend and hit the affected URL with `.ezcoder/eyes/http.sh`; inspect the saved body and confirm the status code and response schema match the route contract.
- After changing a Pydantic schema under `backend/app/schemas/` or OpenAPI-backed API client behavior under `frontend/src/lib/api/`, exercise a representative endpoint with `.ezcoder/eyes/http.sh` so boundary serialization/validation failures are caught outside type checks.
- After editing auth, workspace scoping, billing, or public lead-capture flows in `backend/app/api/v1/` or `backend/app/services/`, use `.ezcoder/eyes/http.sh` with the relevant headers/body to verify expected 2xx/4xx behavior and that no cross-workspace or unauthenticated data appears in the redacted response.
- After editing worker code under `backend/app/workers/` or startup/lifespan code in `backend/app/main.py`, inspect runtime output with `.ezcoder/eyes/logs.sh --file <backend-log-path> --grep "<worker_name>|ERROR|Traceback"` or `--service backend` when the process was started into `.ezcoder/eyes/out/backend.log`.
- After touching Telnyx, Cal.com, Stripe, or Resend webhook handlers under `backend/app/api/webhooks/`, replay a minimal representative payload with `.ezcoder/eyes/http.sh ... POST @payload.json` and inspect logs for signature, parsing, idempotency, and traceback behavior.
- After modifying email-sending code, templates, or notification flows in `backend/app/services/campaigns/`, `backend/app/services/nudges/`, `backend/app/services/approval/`, or SendGrid/Resend integration code, clear the inbox with `.ezcoder/eyes/mail.sh clear`, trigger the send, then use `.ezcoder/eyes/mail.sh count` and `.ezcoder/eyes/mail.sh latest` to verify recipients, subject, redacted body, and links.
- After editing migrations under `backend/alembic/versions/` or models under `backend/app/models/`, run migrations locally, then use `.ezcoder/eyes/http.sh` on a dependent endpoint such as contacts, opportunities, appointments, or `/readyz` to confirm the app does not return 500s.
- When a user reports a runtime bug that tests or type checks do not reproduce, combine `.ezcoder/eyes/http.sh` for the failing endpoint with `.ezcoder/eyes/logs.sh` for tracebacks before guessing from source.

If a probe fails or returns unexpected results, investigate the artifact directly before assuming the probe itself is broken.

### When NOT to use

- Docs-only changes, comments, formatting.
- Refactors fully covered by tests that pass.
- Dev server / simulator / sink isn't up AND the task doesn't require runtime verification.
- Same probe already ran this turn on the same artifact — reuse the output.
- Frontend-only visual/layout changes: no visual screenshot probe is currently verified in this checkout, so use existing lint/build/tests and escalate only if runtime visual proof is necessary.

### When to escalate a capability gap (the self-improvement loop)

If you're about to **guess**, **skip verification**, or **hand-wave** about something a better probe would show you — STOP and surface the tradeoff inline. Phrasing like:

> "I tried checking the endpoint, but the failure is only visible in the browser UI and there is no verified visual probe in this checkout. Two paths: (a) ~3 min to add/fix a visual probe, then I can diagnose properly. (b) Workaround: I'd infer from logs/API output. Your call?"

Wait for the user's choice. **Don't escalate more than once per request** — if the user picked the workaround, don't re-ask in the same turn.

For minor friction (worked around it but wished it were better), don't interrupt — log it for later review:
- `ezcoder eyes log rough "<reason>" [--probe <name>]` — minor friction, you handled it
- `ezcoder eyes log wish "<gap>"` — capability you wished existed
- `ezcoder eyes log blocked "<reason>"` — call this AFTER the user approves an inline-escalation fix, for the audit trail

These accumulate quietly. The user reviews them periodically. Open signals will appear in your context on future turns until they're acked.
