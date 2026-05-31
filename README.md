# The Tribunal

This is where the decisions happen.

Every lead that comes through your door ends up here. Every conversation, every follow-up, every "let me think about it" — it all flows through The Tribunal. This is your business's command center, the place where prospects become customers and deals get closed.

## What Happens Here

**Leads arrive.** They come in through calls, messages, campaigns. The Tribunal captures them all.

**AI takes the first swing.** Voice agents handle incoming calls. SMS campaigns run on autopilot. Your AI doesn't sleep, doesn't take breaks, doesn't forget to follow up.

**You make the call.** When it's time for a human touch, you step in. Review conversations, check the history, and close the deal. The Tribunal gives you everything you need to make the right decision at the right moment.

**Appointments get booked.** Cal.com integration means leads can book time with you directly. No back-and-forth. No missed opportunities.

## The Setup

This is a monorepo with two parts:

```
the-tribunal/
├── frontend/    → Next.js dashboard (where you command)
├── backend/     → FastAPI API (where the magic happens)
```

### One-shot: everything at once

A root `Makefile` orchestrates both sides. From the repo root:

```bash
make install   # uv sync + npm ci
cp backend/.env.example backend/.env   # configure your secrets
make migrate   # alembic upgrade head
make dev       # docker compose + backend uvicorn + frontend dev (parallel)
```

Dashboard at http://localhost:3000 · API docs at http://localhost:8000/docs.

### Make targets

Run `make help` for the full list. Cheat sheet:

| Target | What it does |
| --- | --- |
| `make dev` | Start db (detached) + backend + frontend in parallel. Ctrl-C stops all. |
| `make dev.backend` | FastAPI with `--reload` on :8000. |
| `make dev.frontend` | Next.js dev server on :3000. |
| `make dev.db` | `docker compose up -d` (Postgres + Redis). |
| `make db.down` | Stop docker compose services (keeps volumes). |
| `make db.reset` | **Destructive.** Drop volumes, restart, re-migrate. |
| `make migrate` | `alembic upgrade head`. |
| `make migrate.check` | CI-shaped local migration safety check: upgrade head, check, downgrade -1, upgrade head. |
| `make migrate.heads` | Verify the Alembic graph has exactly one head. |
| `make migrate.history` | Show verbose Alembic migration history. |
| `make migrate.new m="..."` | Autogenerate a new Alembic revision. |
| `make test` / `test.backend` / `test.frontend` | Run tests. |
| `make lint` | Ruff + ESLint. |
| `make format` | Ruff format + Prettier. |
| `make typecheck` | mypy + `tsc --noEmit`. |
| `make install` | `uv sync` + `npm ci`. |
| `make audit` | `uv pip list --outdated` + `npm audit`. |
| `make clean` | Remove caches, build artifacts, coverage. |

### Manual: backend only

```bash
cd backend
uv sync
docker compose up -d
cp .env.example .env   # configure your secrets
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
# Optional split mode: RUN_BACKGROUND_WORKERS=false uv run uvicorn ...
# then run workers separately with: uv run backend-workers
```

### Manual: frontend only

```bash
cd frontend
npm install
npm run dev
```

## The Arsenal

**Frontend**: Next.js 16, React 19, TailwindCSS, React Query, Zustand

**Backend**: FastAPI, SQLAlchemy (async), PostgreSQL, Redis, OpenAI Realtime, Telnyx

## The Bottom Line

Your leads deserve better than spreadsheets and sticky notes. The Tribunal is where you take control — where every interaction is tracked, every opportunity is surfaced, and every decision is informed.

Welcome to the command center. Time to close some deals.
