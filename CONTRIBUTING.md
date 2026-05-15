# Contributing to The Tribunal

Thanks for your interest in contributing! This guide covers local setup, branching, commits, and the checks you need to run before opening a pull request.

## Prerequisites

- **Docker** + Docker Compose (for PostgreSQL 17 and Redis 7)
- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/) for the backend
- **Node.js 20+** and **npm** for the frontend
- A `.env` file in `backend/` (see `backend/.env.example`) and `frontend/.env.local` (see `frontend/.env.example`)

## Development Setup

### Backend (`backend/`)

```bash
cd backend
docker compose up -d              # PostgreSQL + Redis
uv sync                           # Install Python dependencies
uv run alembic upgrade head       # Apply database migrations
uv run uvicorn app.main:app --reload --port 8000
```

The API will be available at <http://localhost:8000> and the OpenAPI docs at <http://localhost:8000/docs>.

### Frontend (`frontend/`)

```bash
cd frontend
npm ci                            # Clean install of locked dependencies
npm run dev                       # Dev server on :3000
```

The app will be available at <http://localhost:3000>.

## Branch Naming

Create a branch off `main` using one of the following prefixes:

| Prefix      | Use for                                       | Example                              |
| ----------- | --------------------------------------------- | ------------------------------------ |
| `feat/`     | New features or user-visible capabilities     | `feat/sms-campaign-scheduler`        |
| `fix/`      | Bug fixes                                     | `fix/contact-filter-pagination`      |
| `refactor/` | Internal restructuring without behavior change | `refactor/extract-contact-filters`   |
| `chore/`    | Tooling, deps, build, CI, docs-only changes   | `chore/bump-react-query`             |

Keep branch names short, lowercase, and hyphen-separated.

## Commit Style — Conventional Commits

We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/). Format:

```
<type>(<optional scope>): <short description>

<optional body>

<optional footer (e.g. BREAKING CHANGE:, Closes #123)>
```

Allowed types: `feat`, `fix`, `refactor`, `chore`, `docs`, `test`, `perf`, `build`, `ci`, `style`, `revert`.

Examples:

```
feat(campaigns): add weekday-only sending window
fix(contacts): handle null phone in segment filter
refactor(api): extract apply_contact_filters helper
chore(deps): bump fastapi to 0.115
```

- Use the imperative mood ("add", not "added").
- Keep the subject line ≤ 72 characters.
- Append `!` after the type/scope or include `BREAKING CHANGE:` in the footer for breaking changes.

## Lint, Typecheck, and Test

Run the relevant checks **before pushing**. CI runs the same commands and will fail the PR otherwise.

### Backend

```bash
cd backend
uv run ruff check app             # Lint
uv run ruff format --check app    # Formatting
uv run mypy app                   # Type-check
uv run pytest                     # Test suite
uv run pytest tests/api/test_contacts.py::test_list  # Single test
```

### Frontend

```bash
cd frontend
npm run lint                      # ESLint
npm run typecheck                 # tsc --noEmit (if defined; otherwise npm run build)
npm run build                     # Production build — must pass
npm test                          # Unit tests (if defined for the touched area)
```

Fix **all** errors and warnings before opening a PR. There is zero tolerance for failing lint, type, or build steps on `main`.

## Database Migrations

If your change modifies a SQLAlchemy model:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Review the generated migration by hand — autogenerate is a starting point, not the answer. Never edit a migration that has already shipped; add a new one instead.

## Pull Requests

- Fill out every section of the PR template.
- Keep PRs focused — one logical change per PR.
- Include screenshots or screen recordings for any user-visible frontend change.
- Link the issue you're closing with `Closes #123`.
- Request review from a code owner (see `.github/CODEOWNERS`).

## Code of Conduct

Be respectful, assume good faith, and keep discussions focused on the work. Harassment of any kind is not tolerated.
