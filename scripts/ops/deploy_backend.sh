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
#   3. Runs ``railway up`` from the **repo root** so the stamp ships in the
#      upload. See "Where the upload runs from" below — this is not the
#      obvious choice, and getting it wrong fails the build outright.
#   4. Deletes the stamp again (EXIT trap, so it also cleans up on failure or
#      Ctrl-C). It must never be committed: a stale stamp makes ``/version``
#      lie, which is worse than ``"unknown"``. A pre-commit hook backstops this.
#
# The stamp is deliberately NOT gitignored — ``railway up`` skips gitignored
# paths when building the upload tarball, so an ignored stamp would never reach
# the builder. The same rule applies to the *directory being deployed from*,
# which is what the gitignored-checkout guard below exists to catch.
#
# Where the upload runs from
# --------------------------
# From the **repo root**, not from ``backend/``. The Railway service sets its
# own Root Directory to ``backend``, and that is applied to whatever tree gets
# uploaded. Uploading from inside ``backend/`` therefore makes the builder look
# for ``backend/backend/`` and the build dies before it starts:
#
#     Error: Failed to read app source directory
#         No such file or directory (os error 2)
#     nixpacks exited with an error
#
# That failure is safe but expensive to diagnose: the deploy fails at build
# time, so production keeps serving the previous release and ``/version`` still
# reports the *old* SHA — which reads exactly like a deploy that silently did
# nothing. It cost a release cycle before the cause was found, hence this note.
#
# Changing this back to ``cd "$BACKEND_DIR"`` will break every deploy. If the
# service's Root Directory is ever cleared in the Railway dashboard, this has to
# change with it.
#
# Usage:
#   make deploy.backend                       # deploys the service below
#   RAILWAY_SERVICE=other-svc make deploy.backend
#   scripts/ops/deploy_backend.sh --ci         # extra args pass through to `railway up`
#   DEPLOY_ALLOW_BEHIND=1 make deploy.backend  # deliberate rollback to older code
#   DEPLOY_ALLOW_IGNORED=1 make deploy.backend # deploy from a gitignored checkout
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

# ── Refuse to upload from a gitignored checkout ───────────────────────────
# `railway up` filters the upload through gitignore rules. Deploy from a
# directory an enclosing repository ignores and the tarball arrives stripped:
# Railway builds it (cached layers make that succeed), reports SUCCESS, and
# production keeps serving the previous image. `/version` reports "unknown"
# because the build stamp written further down never reached the builder.
# Nothing in the deploy output hints at any of it — it reads exactly like a
# deploy that worked.
#
# Not hypothetical: `.gitignore` here lists `.worktrees/`, so a deploy from a
# worktree checkout is a silent no-op. One reported success and left production
# on the previous release until /readyz was inspected by hand.
#
# The subtlety that makes this worth a guard rather than a habit: asked from
# *inside* such a checkout, git says "not ignored". A linked worktree is the
# root of its own working tree and never consults the main repo's .gitignore,
# and a clone carries its own. Only the main worktree (via --git-common-dir) or
# an enclosing repository can answer, so those are what this asks.
IGNORED_BY=""

# `--git-common-dir` resolves to the main repo's .git for a linked worktree and
# to this checkout's own .git otherwise. Older gits answer relatively, hence
# normalising by hand rather than using `--path-format=absolute`.
COMMON_DIR="$(git -C "$REPO_ROOT" rev-parse --git-common-dir 2>/dev/null || true)"
case "$COMMON_DIR" in
    "") ;;
    /*) ;;
    *) COMMON_DIR="${REPO_ROOT}/${COMMON_DIR}" ;;
esac
if [ -n "$COMMON_DIR" ] && [ -d "$COMMON_DIR" ]; then
    MAIN_WORKTREE="$(cd "$(dirname "$COMMON_DIR")" && pwd)"
    if [ "$MAIN_WORKTREE" != "$REPO_ROOT" ] &&
        git -C "$MAIN_WORKTREE" check-ignore -q "$REPO_ROOT" 2>/dev/null; then
        IGNORED_BY="$MAIN_WORKTREE"
    fi
fi

# A separate clone can also sit inside another repo's ignored directory, which
# --git-common-dir cannot see because that clone owns its own .git.
if [ -z "$IGNORED_BY" ]; then
    ENCLOSING="$(git -C "$(dirname "$REPO_ROOT")" rev-parse --show-toplevel 2>/dev/null || true)"
    if [ -n "$ENCLOSING" ] && [ "$ENCLOSING" != "$REPO_ROOT" ] &&
        git -C "$ENCLOSING" check-ignore -q "$REPO_ROOT" 2>/dev/null; then
        IGNORED_BY="$ENCLOSING"
    fi
fi

if [ -n "$IGNORED_BY" ]; then
    if [ "${DEPLOY_ALLOW_IGNORED:-0}" = "1" ]; then
        yellow "⚠  DEPLOY_ALLOW_IGNORED=1 — deploying from a checkout ignored by ${IGNORED_BY}."
        yellow "   If /version reports \"unknown\" after this, the upload was filtered and prod did not change."
    else
        red "✗ refusing to deploy: this checkout is gitignored by ${IGNORED_BY}"
        red "  ${REPO_ROOT}"
        red ""
        red "  \`railway up\` skips gitignored paths, so the upload would arrive stripped."
        red "  Railway reports SUCCESS, production keeps serving the old image, and"
        red "  /version reports \"unknown\" — a silent no-op rather than a visible failure."
        red ""
        red "  Fix: deploy from a checkout outside the ignored path, e.g."
        red "    git clone <repo> ~/the-tribunal-deploy"
        red "    cd ~/the-tribunal-deploy && git checkout origin/main && make deploy.backend"
        red ""
        red "  Certain the upload is intact? DEPLOY_ALLOW_IGNORED=1 make deploy.backend"
        exit 1
    fi
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

# The stamp alone is not enough. `railway up` builds its upload from git's view
# of the tree, and the stamp is deliberately untracked (a committed stamp would
# make /version report a stale SHA, which is worse than "unknown"), so it never
# reaches the builder and every manual deploy reported "unknown" — the exact
# blindness the stamp exists to prevent.
#
# `BUILD_COMMIT_SHA` is resolution step 2 in `app.core.build_info` and is read
# from the environment at runtime, so it does not depend on the upload carrying
# a file. `--skip-deploys` keeps this from shipping the *old* code with the new
# SHA attached; the `railway up` below is what actually deploys.
if ! railway variables --service "$SERVICE" --set "BUILD_COMMIT_SHA=${SHA}" --skip-deploys >/dev/null 2>&1; then
    yellow "⚠  could not set BUILD_COMMIT_SHA — /version may report \"unknown\"."
    yellow "   The deploy still proceeds; only build identification is affected."
fi

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
# Repo root, deliberately — the service's Root Directory is already `backend`.
# See "Where the upload runs from" at the top of this file before changing it.
cd "$REPO_ROOT"
railway up "${UP_ARGS[@]}"

green "✓ upload complete — build running on Railway"
echo
echo "Verify once the deploy goes live:"
echo "  curl -s https://the-tribunal-api-production.up.railway.app/version"
echo "  expected: {\"sha\":\"${SHA}\",\"source\":\"build_stamp\"}"
echo "  make smoke.backend SMOKE_BASE_URL=https://the-tribunal-api-production.up.railway.app"
