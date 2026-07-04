# The Tribunal

The Tribunal is a proprietary AI-powered CRM command center for capturing leads, running AI voice/SMS follow-up, booking appointments, and giving operators a Next.js dashboard for human-in-the-loop decisions.

## Apps and stable structure

- `frontend/` — Next.js 16 + React 19 + TypeScript dashboard. Key folders: `src/app/` routes, `src/components/` feature/UI components, `src/lib/api/` API clients and generated OpenAPI types, `src/providers/` auth/workspace providers, `src/types/` shared domain types, `src/widget/` embeddable chat widget.
- `backend/` — FastAPI + SQLAlchemy async API. Key folders: `app/api/v1/` authenticated/public API routers, `app/api/webhooks/` Telnyx/Cal.com/Resend webhooks, `app/services/` domain logic, `app/models/` ORM models, `app/schemas/` Pydantic schemas, `app/workers/` in-process background jobs, `app/websockets/` voice/realtime bridges, `alembic/versions/` migrations, `tests/` pytest suites.
- `scripts/` — operational/demo scripts such as prompt updates, lead-magnet PDF generation/upload, encryption-key rotation, and stress/adversarial tests.
- `docs/` and `backend/docs/` — strategy, architecture, migration, and operational notes.

## Product domains and integrations

- Core domains include workspaces, contacts/leads, conversations, AI agents, SMS and voice campaigns, appointments, offers, lead magnets/forms, opportunities, pending approvals, nudges, automations, billing, and onboarding.
- External integrations include OpenAI Realtime, Telnyx voice/SMS, Cal.com booking/webhooks, Resend email/webhooks, Stripe billing, and Follow Up Boss/realtor workflows.
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
- Local DB backup/restore targets: `make db.backup.local`; `make db.restore.local f=backend/backups/<file>.dump`.
- Encryption-key rotation workflow: `make rotate.encryption-key`.

## Runtime and deployment facts

- Backend local services are defined in `backend/docker-compose.yml` using PostgreSQL 17 and Redis 7 with `aicrm` database/container names.
- Frontend uses Node `24.18.0` from `frontend/.nvmrc`, `npm@10.9.0`, and deploys from `frontend/` on Vercel with `npm ci` + `npm run build`. Build settings are pinned in `frontend/vercel.json` (framework, install/build/output, region `iad1`), which also enables **git auto-deploy on push to `main`** (`git.deploymentEnabled.main`). Vercel's **Root Directory must be set to `frontend`** in the dashboard (not expressible in `vercel.json`) or git builds run `npm ci` at the repo root and fail — there is no root `package.json`/lockfile.
- Backend deploys on Railway via `backend/railway.toml`; pre-deploy runs `alembic upgrade head`, start command runs `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*`, and healthcheck is `/readyz`.
- Production contains live CRM/contact data. Test migrations locally first and back up data before schema changes that touch contact/lead tables.
- Production URLs: backend `https://the-tribunal-api-production.up.railway.app` (Railway project `the-tribunal`, service `the-tribunal-api`), frontend `https://the-tribunal-two.vercel.app` (Vercel project `the-tribunal`, team `maxteriors`).
- Production Postgres is **18.x** (local dev compose is 17): `make db.backup.prod` uses the `postgres:18` docker client; restoring a prod dump locally may need a newer client than the dev container.

## Release process (production changes)

Follow in order; do not skip. Verified against this repo 2026-07-02.

1. **Build locally**: `make dev`; schema changes via `make migrate.new m="..."` then `make migrate` locally; public API contract changes require `make codegen` and committing `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` **in the same commit** (`codegen/check` diffs against HEAD, so it fails on uncommitted artifacts — commit first, then run `make ci.all`).
2. **Prove it**: `make ci.all` must exit 0 (codegen drift, backend lint/type/tests, frontend lint/type/tests/build, migration up→check→down→up).
3. **Protect prod data**: if a migration touches contact/lead/invoice tables, run `make db.backup.prod DATABASE_URL='<public *.proxy.rlwy.net url>'` first (read-only; verify the dump is non-empty). Keep the dump until the release is proven.
4. **Ship**: `git push origin main` (GitHub CI runs 7 workflows). **Frontend auto-deploys** on push to `main` via Vercel git integration (`frontend/vercel.json` → `git.deploymentEnabled.main`, Root Directory = `frontend`). **Backend does NOT auto-deploy** — deploy it manually: `railway up --service the-tribunal-api --detach`. When both change, deploy the **backend first** (via `railway up`) and let it go live **before** the frontend auto-deploy lands (old frontend + new API is safe; the reverse often isn't) — for a backend-breaking change, deploy backend and confirm `/readyz` before pushing the frontend commit.
5. **Verify live**: `make smoke.backend SMOKE_BASE_URL=https://the-tribunal-api-production.up.railway.app` and `make smoke.frontend PLAYWRIGHT_BASE_URL=https://the-tribunal-two.vercel.app`; then eyeball the changed feature logged in and watch Sentry/Railway logs.
6. **Rollback**: backend `railway redeploy` (previous deployment), frontend `npx vercel rollback <deployment-url>`; bad migration → `alembic downgrade -1` against prod or restore the pre-deploy dump from `backend/backups/`.

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
