# The Tribunal - AI CRM

AI-powered CRM platform that manages leads through calls, SMS, and messages with AI voice agents and SMS campaigns, featuring a Next.js dashboard with Cal.com appointment booking integration and human-in-the-loop approval gates.

## Project Structure

```
frontend/                           # Next.js 16 React frontend
  src/
    app/                            # App Router pages (27 route groups)
      agents/, campaigns/, contacts/, calls/, dashboard/, settings/
      offers/, experiments/, suggestions/, lead-magnets/, opportunities/
      automations/, calendar/, find-leads/, phone-numbers/, voice-test/
      pending-actions/, billing/, nudges/, onboarding/
    components/                     # React components (one per file, 29 feature groups)
      ui/                           # shadcn/ui primitives (Radix-based)
      agents/, campaigns/, contacts/, calls/, conversation/, settings/
      opportunities/, automations/, calcom/, layout/, auth/, wizard/
      pending-actions/, nudges/, suggestions/, tags/, segments/
    lib/
      api/                          # API client functions (one per resource)
      api.ts                        # Axios fetch wrapper
      utils/                        # Utility functions
      contact-store.ts              # Zustand store
    hooks/                          # Custom React hooks (useContacts, useWizard, etc.)
    providers/                      # Auth, workspace, combined providers
    types/                          # TypeScript type definitions
    widget/                         # Embeddable chat widget

backend/                            # FastAPI Python backend
  app/
    main.py                         # FastAPI app entrypoint
    api/v1/                         # Versioned API routes (43 resource modules)
    api/webhooks/                   # Incoming webhook handlers (Telnyx, Cal.com)
    models/                         # SQLAlchemy ORM models (43 files)
    schemas/                        # Pydantic schemas (39 files)
    services/                       # Business logic by domain (24 service groups)
      ai/, telephony/, calendar/, campaigns/, contacts/
      conversations/, opportunities/, segments/, tags/, tools/
      approval/, knowledge/, nudges/, appointments/
    core/                           # Config, security, logging, encryption
    db/                             # Session factory, Redis, pagination
    utils/                          # Calendar, phone, datetime helpers
    workers/                        # Background jobs (17 worker types)
    websockets/                     # Voice bridge, real-time handlers
  alembic/versions/                 # Database migrations
  tests/                            # Pytest test suite (api/, schemas/, services/, workers/)
```

## Tech Stack

**Frontend:** Next.js 16, React 19, TypeScript 5 (strict), TailwindCSS 4, shadcn/ui, React Query 5, Zustand 5, Zod 4, Framer Motion, Three.js/R3F
**Backend:** FastAPI, Python 3.12+, SQLAlchemy 2 (async), PostgreSQL 17, Redis 7, Alembic, uv
**Integrations:** OpenAI Realtime API, Telnyx (VoIP/SMS), Cal.com, ElevenLabs, SendGrid

## Organization Rules

**Frontend:**
- Pages → `src/app/` (Next.js App Router)
- Components → `src/components/`, one per file, grouped by feature
- API clients → `src/lib/api/`, one file per resource
- Utilities → `src/lib/utils/`, grouped by functionality
- Types → `src/types/` or co-located

**Backend:**
- API routes → `app/api/v1/`, one file per resource
- Models → `app/models/`, one model per file
- Schemas → `app/schemas/`, matching model structure
- Services → `app/services/`, grouped by domain (ai, telephony, calendar, approval, knowledge)
- Workers → `app/workers/`, one worker per job type
- Migrations → `alembic/versions/`

## Code Quality - Zero Tolerance

After editing ANY frontend file:
```bash
cd frontend && npm run lint && npm run build
```

After editing ANY backend file:
```bash
cd backend && uv run ruff check app && uv run mypy app
```

Fix ALL errors/warnings before continuing.

## Shared primitives

Prefer these canonical patterns over rolling new ones:

- `backend/app/services/contacts/contact_filters.py` — gold-standard filter engine. Reuse `apply_contact_filters()` and the `FilterDefinition` shape for any list endpoint that needs rule-based filtering.
- `frontend/src/lib/query-keys.ts` — canonical React Query key factory. All new hooks should pull keys from here rather than inlining tuples.
- `frontend/src/lib/query-options.ts` — shared query option presets (stale times, retry policies). Compose these instead of hand-tuning per-hook.
- `frontend/src/components/ui/page-state.tsx` — `PageLoadingState`, `PageErrorState`, `PageEmptyState`. Use for every page-level loading/error/empty surface so the app renders consistent states.

## Development

```bash
cd backend && docker compose up -d                              # PostgreSQL + Redis
cd frontend && npm run dev                                      # Frontend :3000
cd backend && uv run uvicorn app.main:app --reload --port 8000  # Backend :8000
cd backend && uv run alembic upgrade head                       # Migrations
cd backend && uv run pytest                                     # Tests
```

## Production

The app is deployed on Railway. Use `railway` CLI for logs, deploys, and environment management.
This is a live, actively used CRM with real contact data. Never run destructive database operations (DROP, TRUNCATE, DELETE without WHERE) against production. Always test migrations locally first and back up data before schema changes that touch contact/lead tables.

## Eyes

Perception probes live in `.gg/eyes/`. All headless. Artifacts → `.gg/eyes/out/` (gitignored). Invoke probes yourself; don't ask the user to verify what you can verify.

### Available probes

| Need | Run | Then |
|---|---|---|
| Screenshot a frontend page | `.gg/eyes/visual-web.sh http://localhost:3000/<path>` | Use `analyze_image` on the PNG path printed to stdout |
| Hit a backend API endpoint | `.gg/eyes/http.sh http://localhost:8000/api/v1/<resource> [GET\|POST\|PUT\|DELETE] [body-or-@file] [-H "Authorization: Bearer ..."]` | Read the body file from the JSON output; check status code |
| Check backend/server logs | `.gg/eyes/logs.sh --service backend --lines 50` or `--file /path/to/log` or `--grep "ERROR"` | Scan stdout for errors, warnings, or the pattern you need |
| Inspect captured emails | `.gg/eyes/mail.sh latest` or `mail.sh list` or `mail.sh read <id>` | Read the redacted email body/headers to confirm email content |
| Count captured emails | `.gg/eyes/mail.sh count` | Compare against expected count after triggering email-sending code |
| Clear email inbox | `.gg/eyes/mail.sh clear` | Run before tests that assert on email count/content |

### When to use these eyes (automatically, without being asked)

Reach for probes ON YOUR OWN INITIATIVE when any of these apply:

- **After editing any `.tsx` file under `frontend/src/components/` or `frontend/src/app/`**, screenshot the affected page with `.gg/eyes/visual-web.sh http://localhost:3000/<route>` and verify the render matches intent.
- **After adding or modifying a backend route under `backend/app/api/v1/`**, hit it with `.gg/eyes/http.sh http://localhost:8000/api/v1/<endpoint>` and confirm the response shape and status code.
- **After changing a Pydantic schema in `backend/app/schemas/`**, exercise the affected endpoint via `http.sh` to catch validation errors at the boundary.
- **After editing a worker in `backend/app/workers/`**, check `.gg/eyes/logs.sh --service backend --grep "<worker_name>"` to confirm it fires without tracebacks.
- **After modifying email-sending code in any service (campaigns, nudges, SendGrid templates)**, check `.gg/eyes/mail.sh latest` to verify the email was captured and the content/body is correct.
- **After editing a migration in `backend/alembic/versions/`**, run the migration then use `http.sh` to hit a dependent endpoint and confirm no 500s.
- **When the user reports a bug described in visual terms** ("the button is cut off", "the table looks wrong"), screenshot the page immediately with `visual-web.sh` and diagnose from the artifact.
- **When `npm run build` or `uv run ruff check` passes but the change involved runtime behavior**, use `http.sh` or `logs.sh` to confirm things actually work at runtime — type-checking alone isn't enough.

### When NOT to use

- Docs-only changes, comments, formatting.
- Refactors fully covered by existing tests that pass.
- Dev server isn't running AND the task doesn't require runtime verification.
- Same probe already ran this turn on the same artifact — reuse the output.
- Changes confined to `.css`/`tailwind.config` that are already visually verified.

### When to escalate a capability gap (the self-improvement loop)

If you're about to **guess**, **skip verification**, or **hand-wave** about something a better probe would show you — STOP and surface the tradeoff inline. Phrasing like:

> "I tried screenshotting but the failure is a JS error I can only see in the browser console — and there's no `browser_console` probe. Two paths: (a) ~3 min to add it, then I can diagnose properly. (b) Workaround: I'd guess from the DOM state. Your call?"

Wait for the user's choice. **Don't escalate more than once per request** — if the user picked the workaround, don't re-ask in the same turn.

For minor friction (worked around it but wished it were better), don't interrupt — log it for later review:
- `ezcoder eyes log rough "<reason>" [--probe <name>]` — minor friction, you handled it
- `ezcoder eyes log wish "<gap>"` — capability you wished existed
- `ezcoder eyes log blocked "<reason>"` — call this AFTER the user approves an inline-escalation fix, for the audit trail

These accumulate quietly. The user reviews them periodically. Open signals will appear in your context on future turns until they're acked.
