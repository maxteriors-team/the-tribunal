# Deployment smoke tests

Fast, dependency-light checks that answer one question after a deploy: **is the
deployment actually live and correctly wired?** They run against a real,
network-reachable environment — they do not boot the app in-process or touch a
test database.

## What they cover

**Backend** — `backend/tests/smoke/test_deployment_smoke.py` (pytest, `-m smoke`):

| Probe | Proves |
|---|---|
| `GET /livez` → `200 {"status":"ok"}` | Process up, event loop responsive |
| `GET /readyz` → `200`, all checks `ok` | Startup finished; Postgres + Redis + worker heartbeats healthy |
| `GET /version` → `200`, `sha` is a real commit | The expected commit is live — `"unknown"` fails the test (deploy with `make deploy.backend`) |
| `GET /api/v1/auth/me` (no token) → `401` | API router mounted **and** auth enforced (no anonymous data leak) |
| Security headers on `/livez` | Response came from the app middleware, not an upstream error page |

**Frontend** — `frontend/e2e/smoke.spec.ts` (Playwright, title tag `@smoke`):

- Root URL serves the app and routes to a known page (`/login`, `/contacts`, …) — not a build error or blank shell.
- `/login` renders the app shell (React mounted, not a white screen).

## Running them

Both suites are **skipped/inert by default** so normal CI stays green. They
activate only when you point them at a target URL.

```bash
# Backend — against Railway (or any live backend)
make smoke.backend SMOKE_BASE_URL=https://<app>.railway.app

# Frontend — against Vercel (or any live frontend)
make smoke.frontend PLAYWRIGHT_BASE_URL=https://<app>.vercel.app

# Both at once
make smoke SMOKE_BASE_URL=https://<app>.railway.app PLAYWRIGHT_BASE_URL=https://<app>.vercel.app
```

Direct invocations (equivalent):

```bash
cd backend  && SMOKE_BASE_URL=http://127.0.0.1:8000 uv run pytest tests/smoke -m smoke -v
cd frontend && PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 npx playwright test smoke.spec.ts
```

> Frontend smoke needs the Playwright browser once: `cd frontend && npx playwright install chromium`.

## When to run

- After every production deploy (Railway backend, Vercel frontend) as a
  post-deploy gate.
- Against a Vercel preview / staging backend before promoting.

## Notes

- `SMOKE_BASE_URL` unset ⇒ the backend module is skipped (won't fail unit CI).
- `/readyz` returning `503` means the app booted but a dependency is unhealthy;
  the response body names which check failed (`postgres`, `redis`, or a worker
  heartbeat label).
- `/openapi.json` and `/docs` are **debug-only** and intentionally 404 in
  production, so the smoke suite does not probe them.
