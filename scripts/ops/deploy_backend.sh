#!/usr/bin/env bash
# Deploy the backend to Railway with the deployed commit SHA baked in.
#
# Why this wrapper exists
# -----------------------
# Railway sets ``RAILWAY_GIT_COMMIT_SHA`` only for deploys originating from a
# GitHub trigger. This service is deployed manually (``railway up``), which
# uploads a tarball of ``backend/`` with no git metadata — ``.railwayignore``
# excludes ``.git/`` — so that variable is never set in production and
# ``/version`` reported ``{"sha": "unknown"}`` forever. Confirming which commit
# was live then meant correlating Railway log timestamps with worker poll
# cadence: slow and error-prone mid-incident.
#
# What this does (in order):
#   1. Resolves the commit being deployed from the local repo (marked
#      ``-dirty`` when ``backend/`` has uncommitted or untracked changes, since
#      those are uploaded too and the image would not match the commit).
#   2. Writes ``backend/app/build_info.json`` — the build stamp that
#      ``app.core.build_info`` reads at runtime.
#   3. Runs ``railway up`` from ``backend/`` so the stamp ships in the upload.
#   4. Deletes the stamp again (EXIT trap, so it also cleans up on failure or
#      Ctrl-C). It must never be committed: a stale stamp makes ``/version``
#      lie, which is worse than ``"unknown"``. A pre-commit hook backstops this.
#
# The stamp is deliberately NOT gitignored — ``railway up`` skips gitignored
# paths when building the upload tarball, so an ignored stamp would never reach
# the builder.
#
# Usage:
#   make deploy.backend                       # deploys the service below
#   RAILWAY_SERVICE=other-svc make deploy.backend
#   scripts/ops/deploy_backend.sh --ci         # extra args pass through to `railway up`
#
# This uploads and builds. It does not touch the database beyond the
# ``preDeployCommand`` (``alembic upgrade head``) configured in railway.toml.

set -euo pipefail
IFS=$'\n\t'

# This script lives at ``scripts/ops/deploy_backend.sh``; the repo root is
# therefore two directories up.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"
STAMP_PATH="${BACKEND_DIR}/app/build_info.json"
SERVICE="${RAILWAY_SERVICE:-the-tribunal-api}"

bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*" >&2; }

require() {
    command -v "$1" >/dev/null 2>&1 || {
        red "✗ missing required tool: $1"
        exit 1
    }
}

require railway
require git

cleanup() {
    rm -f "$STAMP_PATH"
}
trap cleanup EXIT INT TERM

if ! git -C "$REPO_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    red "✗ not a git repository: ${REPO_ROOT}"
    exit 1
fi

SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
REF="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"

# Untracked-but-not-ignored files under backend/ are uploaded by `railway up`
# as well, so `status --porcelain` (not `diff`) is the right dirtiness test.
if [ -n "$(git -C "$REPO_ROOT" status --porcelain -- backend)" ]; then
    SHA="${SHA}-dirty"
    yellow "⚠  backend/ has uncommitted changes — stamping ${SHA}"
    yellow "   /version will report the -dirty suffix so nobody trusts it as a clean build."
fi

# ── Refuse to ship a silent rollback ─────────────────────────────────────────
# `railway up` uploads the backend/ *folder*, not a git ref: whatever sits on
# disk becomes production. So deploying from a checkout that is missing commits
# already merged to the remote does not merely skip them — it **reverts them in
# production**, with no diff, no migration, and nothing in the deploy output to
# hint at it. Not hypothetical: a deploy from a pre-merge HEAD rolled an
# outbound-SMS cost fix out of prod for ~18 minutes before a SHA check caught it.
#
# Only backend/ is uploaded, so only backend-touching commits can regress.
# Deliberately shipping older code is legitimate — that is what the override is
# for; it just has to be a decision rather than an accident.
REMOTE_REF="${DEPLOY_BASE_REF:-origin/main}"
if [ "${DEPLOY_ALLOW_BEHIND:-0}" = "1" ]; then
    yellow "⚠  DEPLOY_ALLOW_BEHIND=1 — skipping the behind-${REMOTE_REF} check."
elif ! git -C "$REPO_ROOT" fetch --quiet origin 2>/dev/null; then
    # Offline is no reason to block a deploy, but it is a reason to say so out
    # loud: a check that passes and a check that never ran look identical.
    yellow "⚠  could not reach origin — behind-${REMOTE_REF} check did NOT run."
    yellow "   Confirm this checkout isn't missing merged backend work before trusting this deploy."
elif git -C "$REPO_ROOT" rev-parse --verify --quiet "$REMOTE_REF" >/dev/null; then
    MISSING_COMMITS="$(git -C "$REPO_ROOT" log --oneline "HEAD..${REMOTE_REF}" -- backend)"
    if [ -n "$MISSING_COMMITS" ]; then
        red "✗ refusing to deploy: ${REMOTE_REF} has backend commits this checkout is missing."
        red "  Deploying now would REVERT them in production:"
        printf '%s\n' "$MISSING_COMMITS" | sed 's/^/    /' >&2
        red ""
        red "  Fix:      git pull --ff-only     (or: git fetch && git reset --hard ${REMOTE_REF})"
        red "  Rollback? DEPLOY_ALLOW_BEHIND=1 make deploy.backend"
        exit 1
    fi
fi

BUILT_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat >"$STAMP_PATH" <<JSON
{
  "sha": "${SHA}",
  "ref": "${REF}",
  "built_at": "${BUILT_AT}"
}
JSON

# Default to a detached deploy (the documented release flow). Any argument
# given to this script replaces that default so callers can stream logs with
# `--ci` instead of fighting a hardcoded `--detach`. The array is never empty,
# so this stays safe under `set -u` on bash 3.2 (macOS default).
UP_ARGS=(--service "$SERVICE")
if [ "$#" -gt 0 ]; then
    UP_ARGS+=("$@")
else
    UP_ARGS+=(--detach)
fi

bold "▶ deploying ${SERVICE} @ ${SHA}"
cd "$BACKEND_DIR"
railway up "${UP_ARGS[@]}"

green "✓ upload complete — build running on Railway"
echo
echo "Verify once the deploy goes live:"
echo "  curl -s https://the-tribunal-api-production.up.railway.app/version"
echo "  expected: {\"sha\":\"${SHA}\",\"source\":\"build_stamp\"}"
echo "  make smoke.backend SMOKE_BASE_URL=https://the-tribunal-api-production.up.railway.app"
