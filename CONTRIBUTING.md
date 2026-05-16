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

## Shared UI Primitives — Discover Before You Build

Before adding a new loading spinner, error screen, empty state, or button variant in the frontend, check the canonical primitives under [`frontend/src/components/ui/`](./frontend/src/components/ui) — especially `PageLoadingState`, `PageErrorState`, and `PageEmptyState` in [`page-state.tsx`](./frontend/src/components/ui/page-state.tsx), which are the canonical loading / error / empty surfaces for every page. Run `npm run dev` in `frontend/` and visit <http://localhost:3000/dev/components> for a living style guide that renders every shared primitive side-by-side with idiomatic usage. The route is gated to `NODE_ENV !== "production"` and is unreachable on deployed builds.

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

## Pre-Commit Hooks

This repo runs two layers of pre-commit automation. Install both before your first commit.

### 1. `pre-commit` framework (repo-wide)

Runs generic hygiene checks, `ruff check` + `ruff format` on the backend, and `gitleaks` for secret scanning. Configured in [`.pre-commit-config.yaml`](./.pre-commit-config.yaml).

```bash
pipx install pre-commit          # or: brew install pre-commit
pre-commit install               # installs the git hook into frontend/.husky
pre-commit run --all-files       # one-time sweep of the whole repo (optional)
pre-commit autoupdate            # bump hook versions periodically
```

Included hooks:

- `end-of-file-fixer`, `trailing-whitespace`, `check-yaml`, `check-toml`, `check-merge-conflict`
- `check-added-large-files` — rejects anything over **500 KB**
- `ruff` (`--fix`) and `ruff-format` — scoped to `backend/`
- `gitleaks` — secret scanner
- Local hooks that run `npm run lint` and `npm run typecheck` when staged files match `frontend/**/*.{ts,tsx}`

### 2. Husky + lint-staged (frontend)

Layered on top of `pre-commit` to give the frontend fast, file-scoped fix-on-save behavior. Configured under `lint-staged` in [`frontend/package.json`](./frontend/package.json) and the hook script in [`frontend/.husky/pre-commit`](./frontend/.husky/pre-commit).

Install (one-time, from the repo root):

```bash
cd frontend
npm install                      # installs husky + lint-staged + prettier as devDeps
npm run prepare                  # wires git core.hooksPath to frontend/.husky
```

The husky `pre-commit` script (1) invokes the `pre-commit` framework against the whole repo, then (2) runs `lint-staged` from `frontend/`, which executes:

- `eslint --fix` on staged `*.ts` / `*.tsx`
- `prettier --write` on staged `*.json` / `*.md`

If you ever need to skip the hooks for a one-off commit (rare — only for emergency hotfixes), use `git commit --no-verify`.

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

## Frontend API Mocking with MSW

Frontend tests mock the backend at the **network boundary** with [Mock Service Worker](https://mswjs.io/) (`msw/node`) rather than stubbing `axios`/`fetch` directly. This lets components, hooks, and providers exercise their real data-fetching code paths against a deterministic API.

### Layout

```
frontend/src/test/
  setup.ts          # Vitest globals + MSW lifecycle (listen / reset / close)
  msw/
    server.ts       # setupServer(...handlers) — the Node interceptor
    handlers.ts     # Default "happy-path" stubs for common endpoints
```

The lifecycle is wired once in `setup.ts`:

- `beforeAll(() => server.listen({ onUnhandledRequest: "error" }))` — unhandled requests fail loudly.
- `afterEach(() => server.resetHandlers())` — per-test `server.use(...)` overrides do not leak.
- `afterAll(() => server.close())` — clean teardown.

### Adding a default handler

Default handlers in `handlers.ts` describe the "empty / happy path" — enough for a component to render without crashing. They should **not** encode test-specific data.

1. Identify the endpoint by looking at the matching API client in `frontend/src/lib/api/<resource>.ts`. Use the exact path, including the `:workspaceId` route param.
2. Add (or reuse) a fixture constant at the top of `handlers.ts`. Type it with the response interface from the API client so drift fails type-check, not runtime.
3. Register the handler via the `both(path)` helper so it matches both the proxied origin (`http://localhost:3000`) and the direct backend (`http://localhost:8000`):

   ```ts
   ...both("/api/v1/workspaces/:workspaceId/calls").map((url) =>
     http.get(url, () => HttpResponse.json(stubCallsList)),
   ),
   ```

4. Export any fixture a test might want to reuse (`export const stubCallsList = ...`).

### Overriding for a specific test

Never mutate `handlers.ts` to express test-specific data. Use `server.use(...)` inside the test — it's scoped and auto-reset:

```ts
import { http, HttpResponse } from "msw";
import { server } from "@/test/msw/server";

it("renders the error state when contacts 500", async () => {
  server.use(
    http.get("http://localhost:3000/api/v1/workspaces/:workspaceId/contacts", () =>
      HttpResponse.json({ detail: "boom" }, { status: 500 }),
    ),
  );
  // ...render and assert
});
```

### Conventions

- **Match by absolute URL.** The axios client uses a relative baseURL in jsdom, so requests resolve against `http://localhost:3000`. Register both origins via the `both()` helper to stay robust if a code path ever bypasses the Next.js proxy.
- **Type your fixtures.** Pull the response type from `src/lib/api/<resource>.ts` (e.g. `ContactsListResponse`). A schema change should break the fixture at compile time.
- **Empty by default.** Lists return `{ items: [], total: 0, ... }`. Tests that need populated data override per-test.
- **No `vi.mock("axios")` for API behavior.** If you find yourself reaching for `vi.mock` on `@/lib/api` or `axios`, prefer an MSW override unless you're specifically testing the axios client itself (see `src/lib/api.test.ts`).

## Backend Test Coverage Ratchet

CI enforces a minimum overall backend coverage via `pytest --cov-fail-under=<floor>` in `.github/workflows/backend-ci.yml`. The floor only ever moves **up** — never down.

### Current floor

**49%** (baseline measured at 44% + 5pts starter buffer).

### Policy

1. **Never lower the floor.** If a PR drops coverage below the current floor, fix the PR — do not relax the threshold.
2. **Raise by +5pts whenever a coverage-improvement task completes.** A "coverage task" is any PR whose primary goal is adding tests to lift overall coverage (typically tagged `test:` or `chore(tests):` in the commit). After the PR lands and CI is green on the new tests, bump the `--cov-fail-under=<n>` value in `backend-ci.yml` by 5 in a follow-up commit (or the same PR if it's already green at the new floor).
3. **Incidental coverage gains do not bump the floor.** Only deliberate coverage work moves the ratchet. This keeps the threshold a forcing function for explicit investment rather than a moving goalpost on every feature PR.
4. **Cap at 90%.** Above 90%, additional gains are usually not worth the test churn; revisit the policy before pushing higher.

### How to run coverage locally

```bash
cd backend
uv run pytest --cov=app --cov-report=term-missing
```

Coverage config lives in `backend/pyproject.toml` under `[tool.coverage.run]` and `[tool.coverage.report]`. Migrations, `__init__.py` files, and `app/main.py` are omitted.

## Backend Test Factories

Backend tests construct model instances with **factory_boy** factories defined
in [`backend/tests/factories.py`](backend/tests/factories.py). The factories
exist so test setup reads as "build this entity with these overrides" rather
than hand-rolling ``MagicMock`` shapes that drift from the real ORM schema.

### Available factories

One factory per model, exposed as both an importable class and a pytest
fixture:

| Model               | Factory                       | Fixture                         |
| ------------------- | ----------------------------- | ------------------------------- |
| `User`              | `UserFactory`                 | `user_factory`                  |
| `Workspace`         | `WorkspaceFactory`            | `workspace_factory`             |
| `WorkspaceMembership` | `WorkspaceMembershipFactory`| `workspace_membership_factory`  |
| `Contact`           | `ContactFactory`              | `contact_factory`               |
| `Tag`               | `TagFactory`                  | `tag_factory`                   |
| `ContactTag`        | `ContactTagFactory`           | `contact_tag_factory`           |
| `Agent`             | `AgentFactory`                | `agent_factory`                 |
| `PhoneNumber`       | `PhoneNumberFactory`          | `phone_number_factory`          |
| `Conversation`      | `ConversationFactory`         | `conversation_factory`          |
| `Message`           | `MessageFactory`              | `message_factory`               |
| `Campaign`          | `CampaignFactory`             | `campaign_factory`              |
| `CampaignContact`   | `CampaignContactFactory`      | `campaign_contact_factory`      |
| `Appointment`       | `AppointmentFactory`          | `appointment_factory`           |
| `Pipeline`          | `PipelineFactory`             | `pipeline_factory`              |
| `PipelineStage`     | `PipelineStageFactory`        | `pipeline_stage_factory`        |
| `Opportunity`       | `OpportunityFactory`          | `opportunity_factory`           |

### Build vs. create

The project's tests are predominantly unit tests with **mocked**
`AsyncSession` instances — no real database is touched. Factories support this
workflow via `build()`, which returns a transient (unpersisted) model
instance:

```python
from tests.factories import ContactFactory, WorkspaceFactory

workspace = WorkspaceFactory.build()
contact = ContactFactory.build(workspace=workspace, first_name="Alice")
assert contact.workspace_id == workspace.id
```

For tests backed by a real session, call `bind_factories_to_session(session)`
from your DB fixture, then use `.create()` (which `add()`s + flushes):

```python
from tests.factories import bind_factories_to_session, ContactFactory

bind_factories_to_session(sync_session)
contact = ContactFactory.create(first_name="Alice")  # persisted
```

### Relationships

Foreign keys are wired with `SubFactory`, so child factories auto-build
parents unless you pass one explicitly:

```python
campaign = CampaignFactory.build()  # builds its own workspace
# vs.
ws = WorkspaceFactory.build()
campaign = CampaignFactory.build(workspace=ws)  # shares ws
```

Many-to-many and one-to-many relations are exposed via `post_generation`
hooks:

```python
WorkspaceFactory.build(members=[user1, user2])           # WorkspaceMembership rows
ContactFactory.build(tag_objects=[tag1, tag2])           # ContactTag rows
CampaignFactory.build(contacts=[contact1, contact2])     # CampaignContact rows
ConversationFactory.build(messages=3)                    # 3 outbound Messages
PipelineFactory.build(stages=4)                          # 4 PipelineStages
```

### Encrypted columns

Factories with PII columns (`User`, `Contact`) automatically derive the
`*_hash` lookup columns via `LazyAttribute`, so a hand-set `email=` keeps
`email_hash` consistent without extra wiring.

### Sequence reset

The `_reset_factory_sequences` autouse fixture in `tests/conftest.py` resets
every factory's `Sequence` counter before each test. This means
`UserFactory.build().email` is `user0@example.com` for the first build in
every test regardless of execution order — required for deterministic
assertions.

### Proof-of-concept migration

See `backend/tests/services/test_nudge_generator.py` for an example of a test
file that was migrated from ad-hoc `MagicMock` builders to the factory
fixtures. The previous `_make_workspace` / `_make_contact` helpers are now
thin wrappers around `workspace_factory.build()` / `contact_factory.build()`
with only the test-specific overrides applied.

## Database Migrations

If your change modifies a SQLAlchemy model:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Review the generated migration by hand — autogenerate is a starting point, not the answer. Never edit a migration that has already shipped; add a new one instead.

## Operational Make Targets

The root [`Makefile`](./Makefile) exposes a small set of operational targets for routine maintenance. Run `make help` for the live list; the operational ones are documented in depth here because they touch dependencies, secrets, or the database.

### `make audit` — deps, CVEs, secrets

`make audit` runs three independent sub-targets. You can run them individually:

| Target              | What it runs                                                                                              | When to run                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| `audit.deps`        | `uv tree --outdated --depth 1` on the backend; `npm outdated` on the frontend                              | Weekly. Triage upgrades before they pile up.                 |
| `audit.security`    | `pip-audit --strict` against the exported uv lockfile; `npm audit --omit=dev` on the frontend prod tree   | Before every release and on a weekly cron.                   |
| `audit.secrets`     | `gitleaks detect --no-banner --redact --verbose`, falling back to `pre-commit run gitleaks --all-files`   | Before pushing a branch that touched config, CI, or secrets. |

Notes:

- `audit.security` exports `backend/uv.lock` to a temporary requirements file and feeds it to `pip-audit`. The local editable `aicrm-backend` package itself is excluded — we audit its dependencies, not the project under audit.
- `audit.secrets` prefers a system-installed `gitleaks` binary. If it isn't present, the target falls through to `pre-commit run gitleaks --all-files`, which uses the version pinned in [`.pre-commit-config.yaml`](./.pre-commit-config.yaml). Install one of the two before running:
  - macOS: `brew install gitleaks`
  - Linux: download the binary from <https://github.com/gitleaks/gitleaks/releases> or rely on `pipx install pre-commit` + `pre-commit install`.
- Each sub-target exits non-zero on findings so it can be wired into CI as-is.

### `make rotate.encryption-key` — rotate the Fernet secret

Interactive driver around [`scripts/rotate_encryption_key.sh`](./scripts/rotate_encryption_key.sh). It walks you through four steps:

1. **Generate** a fresh Fernet key with `cryptography` and print it to the terminal **once**. Copy it to your password manager before continuing.
2. **Confirm** the Railway target via `railway status`. Make sure you've already run `railway login` and `railway link` against the right environment.
3. **Push** `ENCRYPTION_KEY=<new>` to Railway via `railway variables --set`. Wait for the redeploy to come up healthy before continuing — the live app needs the new key in memory before any rows are re-encrypted.
4. **Re-encrypt** existing rows by invoking [`scripts/reencrypt_with_old_key.py`](./scripts/reencrypt_with_old_key.py). You'll be prompted (hidden input) for the OLD key. The script:
   - reads `DATABASE_URL` from `backend/.env` — point this at the DB you intend to migrate (local dev, or a tunneled staging connection) **before** running the step.
   - offers a `--dry-run` pass first (decrypt + re-encrypt in a transaction that's rolled back) so you can verify counts before committing writes.
   - is idempotent: rows already encrypted under the new key are skipped, so a re-run after a partial failure is safe.
   - re-derives `*_hash` lookup columns from plaintext so `email_hash`, `phone_hash`, etc. stay aligned with the new key.

If the live run aborts midway, just re-run the script with the same `OLD_ENCRYPTION_KEY` — already-rotated rows are detected and skipped.

> ⚠  **Never** run this against production without a fresh `make db.backup.local` (or its production equivalent) taken first. The script is designed to be safe, but key rotation is a one-way operation; the old ciphertext is overwritten in place.

### `make db.backup.local` and `make db.restore.local`

Local-only convenience wrappers around `pg_dump` / `pg_restore` against the dockerized Postgres started by `make dev.db`.

```bash
make db.backup.local                                    # writes backend/backups/aicrm-<timestamp>.dump
make db.restore.local f=backend/backups/aicrm-20260516-014700.dump
```

- Dumps use the `-Fc` custom format so they round-trip cleanly through `pg_restore --clean --if-exists`.
- `backend/backups/` is gitignored — dumps stay on your machine.
- `db.restore.local` prompts for confirmation because it overwrites the local database.
- **Production is out of scope** for these targets. Railway Postgres backups are managed through the Railway dashboard; do not point these targets at a production `DATABASE_URL`.

## Pull Requests

- Fill out every section of the PR template.
- Keep PRs focused — one logical change per PR.
- Include screenshots or screen recordings for any user-visible frontend change.
- Link the issue you're closing with `Closes #123`.
- Request review from a code owner (see `.github/CODEOWNERS`).

## Release Process

Releases are cut from `main` using [Semantic Versioning](https://semver.org/spec/v2.0.0.html) — `MAJOR.MINOR.PATCH`. Every release has three artifacts that must agree:

1. A `CHANGELOG.md` entry describing what changed.
2. A Git tag `vX.Y.Z` pointing at the release commit.
3. A GitHub Release tied to that tag.

At deploy time, Railway sets `RAILWAY_GIT_COMMIT_SHA` to the commit being deployed, and both the backend (`backend/app/main.py`) and frontend (`frontend/sentry.*.config.ts`) Sentry initializations forward that SHA as the Sentry `release`. The Sentry release for a deploy therefore equals the tagged commit SHA — events filed in Sentry can be traced back to the exact `vX.Y.Z` release and CHANGELOG entry without manual bookkeeping.

### Updating `CHANGELOG.md` on every PR

Every user-visible or operationally relevant change must add a bullet under `## [Unreleased]` in [`CHANGELOG.md`](./CHANGELOG.md). Pick the section that fits:

| Section      | Use for                                                         |
| ------------ | --------------------------------------------------------------- |
| `Added`      | New features, endpoints, components, configuration knobs.        |
| `Changed`    | Behavioral changes to existing functionality.                    |
| `Deprecated` | Features still working but slated for removal.                   |
| `Removed`    | Features deleted in this release.                                |
| `Fixed`      | Bug fixes.                                                       |
| `Security`   | Vulnerability fixes — link the CVE/advisory when public.         |

Guidelines:

- Write entries in the **past tense, third-person** so they read cleanly when promoted to a version section ("Added weekday-only sending window for SMS campaigns."; not "add" or "adds").
- Reference the user-facing surface, not the implementation detail. "Fixed contact filter pagination beyond page 10" beats "Refactored `apply_contact_filters`".
- Link the PR or issue when context is useful (`(#123)`).
- Pure refactors, test-only changes, and CI/tooling tweaks usually do **not** need an entry — use judgement. If a refactor changes observable behavior or performance, it does.

If you prefer not to hand-edit `CHANGELOG.md`, you can rely entirely on the `release-please` automation (see below) — it will populate the file from your conventional-commit messages on the next release PR. Either way, do not duplicate an entry the automation will generate.

### Semantic-version tagging

We bump versions according to the change types in the release:

| Change                                              | Bump      |
| --------------------------------------------------- | --------- |
| `BREAKING CHANGE:` footer or `feat!:` / `fix!:`     | `MAJOR`   |
| `feat:` (new functionality, backwards compatible)   | `MINOR`   |
| `fix:`, `perf:`, `refactor:` with user impact       | `PATCH`   |
| `chore:`, `docs:`, `test:`, `ci:`, `build:`, `style:` | no bump |

Tags are always prefixed with `v` (e.g. `v1.4.0`, not `1.4.0`). Tag the **merge commit on `main`**, never a branch commit:

```bash
git checkout main && git pull
git tag -a v1.4.0 -m "v1.4.0"
git push origin v1.4.0
```

Once a tag is pushed, the same SHA flows through Railway → `RAILWAY_GIT_COMMIT_SHA` → Sentry `release`, so the Sentry UI's release filter is automatically populated for the new version.

### Creating the GitHub Release

After the tag is on `main`:

1. Promote the `## [Unreleased]` section in `CHANGELOG.md` to a new `## [X.Y.Z] - YYYY-MM-DD` section. Reset `## [Unreleased]` to empty subsection stubs.
2. Update the compare links at the bottom of the file (`[X.Y.Z]: .../compare/vA.B.C...vX.Y.Z`, `[Unreleased]: .../compare/vX.Y.Z...HEAD`).
3. Open a GitHub Release against the tag: **Releases → Draft a new release → choose tag `vX.Y.Z`**. Title: `vX.Y.Z`. Body: paste the matching CHANGELOG section.
4. Publish. CI runs the deploy from the tag; Sentry will start seeing events under `release: <tag-sha>`.

Or with the `gh` CLI:

```bash
gh release create v1.4.0 \
  --title "v1.4.0" \
  --notes-file <(awk '/^## \[1\.4\.0\]/,/^## \[/' CHANGELOG.md | sed '$d')
```

### Automation: `release-please`

For everything above, [`.github/workflows/release-please.yml`](./.github/workflows/release-please.yml) automates the heavy lifting from our conventional commits:

- On every push to `main`, [`googleapis/release-please-action`](https://github.com/googleapis/release-please-action) opens (or updates) a single rolling **release PR** titled `chore(main): release vX.Y.Z`. The PR contains the version bump (computed from commit types since the last tag), the new `CHANGELOG.md` section, and the manifest update in `.release-please-manifest.json`.
- Merging that PR creates the Git tag `vX.Y.Z` **and** a matching GitHub Release whose body is the new CHANGELOG section.
- The tag's commit is what Railway deploys, so `RAILWAY_GIT_COMMIT_SHA` and the Sentry `release` are automatically aligned with the GitHub Release.

If you are using the automation:

- Keep commit subjects compliant — see [Commit Style — Conventional Commits](#commit-style--conventional-commits). Releases generated by release-please are only as good as the commit log.
- You do **not** need to hand-edit `## [Unreleased]` for changes already described by your conventional-commit subject. Add a hand-written entry only when the commit subject is too terse to be useful in a release note.
- Never rebase or amend a tag once release-please has pushed it. To correct a botched release, cut a new patch (`vX.Y.(Z+1)`) — never re-point an existing tag.

If the automation is paused (token expired, action disabled, etc.), fall back to the manual procedure described in the previous three subsections.

## Code of Conduct

Be respectful, assume good faith, and keep discussions focused on the work. Harassment of any kind is not tolerated.
