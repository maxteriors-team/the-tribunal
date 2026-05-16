# Changelog

All notable changes to The Tribunal will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each released version corresponds to a Git tag (`vX.Y.Z`), a GitHub Release, and a
Sentry release identified by the deploy commit SHA (`RAILWAY_GIT_COMMIT_SHA`). See
[CONTRIBUTING.md](./CONTRIBUTING.md#release-process) for the full process.

## [Unreleased]

### Added

- Repository `CHANGELOG.md` (Keep a Changelog format) tracking notable changes.
- `release-please` GitHub Actions workflow (`.github/workflows/release-please.yml`)
  that automates version bumps, changelog entries, and tag creation from
  conventional commits on `main`.
- Sentry frontend `release` configuration wired to `RAILWAY_GIT_COMMIT_SHA` so
  client, server, and edge runtimes report the same release identifier as the
  backend.
- Release process documentation in `CONTRIBUTING.md` covering changelog updates,
  semantic-version tagging, and GitHub Release creation.
- Operational `Makefile` targets: `audit.deps`, `audit.security`, `audit.secrets`,
  `rotate.encryption-key`, `db.backup.local`, `db.restore.local`, each surfaced
  in `make help` and documented in `CONTRIBUTING.md`.
- `scripts/rotate_encryption_key.sh` (interactive Fernet rotation against
  Railway) and `scripts/reencrypt_with_old_key.py` (idempotent re-encryption of
  `EncryptedString` / `EncryptedJSON` columns under a new `ENCRYPTION_KEY`).

### Changed

- _Nothing yet._

### Deprecated

- _Nothing yet._

### Removed

- _Nothing yet._

### Fixed

- _Nothing yet._

### Security

- _Nothing yet._

<!--
Versioned release sections are appended below by release-please as
conventional-commit PRs land on `main`. Manual edits should follow the same
section ordering (Added / Changed / Deprecated / Removed / Fixed / Security).
-->

[Unreleased]: https://github.com/the-tribunal/aicrm/compare/HEAD...HEAD
