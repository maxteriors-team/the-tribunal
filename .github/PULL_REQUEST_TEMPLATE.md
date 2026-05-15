# Pull Request

## Summary

<!-- One or two sentences describing what this PR does and why. Link related issues with `Closes #123`. -->

## Changes

<!-- Bullet list of the concrete changes in this PR. Group by area (backend / frontend / infra) if helpful. -->

-
-
-

## Testing

<!-- How did you verify this works? Include commands run and their outcomes. -->

- [ ] `cd backend && uv run ruff check app && uv run mypy app` passes
- [ ] `cd backend && uv run pytest` passes (relevant tests)
- [ ] `cd frontend && npm run lint && npm run build` passes
- [ ] Manually verified locally (describe steps below)

**Manual verification steps:**

1.
2.

## Screenshots

<!-- Required for any user-visible frontend change. Include before/after if applicable. Drop images or recordings here. -->

| Before | After |
| ------ | ----- |
|        |       |

## Checklist

- [ ] Branch name follows `feat/`, `fix/`, `refactor/`, or `chore/` convention
- [ ] Commits follow [Conventional Commits](https://www.conventionalcommits.org/)
- [ ] No commented-out code, debug prints, or `TODO`s without an issue link
- [ ] New/changed code has appropriate types and error handling
- [ ] Database migration added if models changed, and reviewed by hand
- [ ] Docs / `CLAUDE.md` / `README.md` updated if behavior or setup changed
- [ ] No secrets, API keys, or production data in diffs, logs, or fixtures
- [ ] Reviewed by a code owner from `.github/CODEOWNERS`
