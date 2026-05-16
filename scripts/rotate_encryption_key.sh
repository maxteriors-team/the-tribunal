#!/usr/bin/env bash
# Interactive rotation of the application's Fernet ENCRYPTION_KEY on Railway.
#
# What this does (in order):
#   1. Generates a fresh Fernet secret with cryptography.
#   2. Prompts you to confirm the Railway service/environment.
#   3. Sets the new secret on Railway via `railway variables --set`.
#   4. Prompts for the OLD key (so the re-encryption script can decrypt
#      existing rows) and offers a dry-run, then a live run, of
#      ``scripts/reencrypt_with_old_key.py`` against your *local* dev DB.
#
# This script never touches production data directly — it only mutates Railway
# *variables* and runs re-encryption against ``DATABASE_URL`` as configured in
# backend/.env. Point ``DATABASE_URL`` at the target DB before running step 4
# (e.g. tunnel to staging Postgres).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*" >&2; }

confirm() {
    local prompt="${1:-Continue?} [y/N] "
    local reply
    read -r -p "$prompt" reply
    [[ "${reply,,}" == "y" || "${reply,,}" == "yes" ]]
}

require() {
    command -v "$1" >/dev/null 2>&1 || {
        red "✗ missing required tool: $1"
        exit 1
    }
}

require railway
require uv

bold "▶ rotate.encryption-key — interactive"
echo
echo "This rotates ENCRYPTION_KEY on Railway and re-encrypts all Fernet-encrypted"
echo "columns. Read scripts/reencrypt_with_old_key.py before continuing."
echo

# ─── 1. Generate new Fernet key ────────────────────────────────────────────────

bold "1/4  Generating a new Fernet key…"
NEW_KEY="$(cd "${BACKEND_DIR}" && uv run --quiet python -c \
    'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
green "    ✓ generated ($(printf '%s' "${NEW_KEY}" | wc -c) chars)"
echo
echo "    The key is shown ONCE. Copy it to your password manager NOW."
echo "    ──────────────────────────────────────────────────────────────"
printf "    %s\n" "${NEW_KEY}"
echo "    ──────────────────────────────────────────────────────────────"
echo
confirm "Have you stored the new key somewhere safe?" \
    || { red "aborted — store the key, then re-run"; exit 1; }
echo

# ─── 2. Confirm Railway target ─────────────────────────────────────────────────

bold "2/4  Confirming the Railway target…"
railway status || {
    red "✗ railway status failed — run 'railway login' and 'railway link' first"
    exit 1
}
echo
yellow "    ⚠  the NEW key will be written to the service shown above."
confirm "Proceed?" || { red "aborted"; exit 1; }
echo

# ─── 3. Push the new key to Railway ────────────────────────────────────────────

bold "3/4  Setting ENCRYPTION_KEY on Railway…"
railway variables --set "ENCRYPTION_KEY=${NEW_KEY}"
green "    ✓ ENCRYPTION_KEY updated on Railway"
echo
yellow "    ⚠  Railway will redeploy the service. Wait for it to come up green"
yellow "       before continuing (the live app needs the NEW key in memory"
yellow "       before we re-encrypt rows)."
confirm "Has the Railway redeploy finished?" || {
    red "aborted — re-run this step after the deploy is healthy"
    exit 1
}
echo

# ─── 4. Re-encrypt existing rows ───────────────────────────────────────────────

bold "4/4  Re-encrypting existing rows with the new key…"
echo
echo "    Enter the OLD ENCRYPTION_KEY (the value that ENCRYPTION_KEY held"
echo "    BEFORE this rotation). Input is hidden."
read -r -s -p "    OLD_ENCRYPTION_KEY: " OLD_KEY
echo
if [[ -z "${OLD_KEY}" ]]; then
    red "✗ empty old key — aborted"
    exit 1
fi
if [[ "${OLD_KEY}" == "${NEW_KEY}" ]]; then
    red "✗ old key matches new key — nothing to rotate"
    exit 1
fi
echo
echo "    The re-encryption script reads DATABASE_URL from backend/.env."
echo "    Make sure that points at the DB whose rows you want to migrate"
echo "    (local dev, or a tunneled staging/prod connection)."
echo
confirm "Run a --dry-run pass first?" && {
    OLD_ENCRYPTION_KEY="${OLD_KEY}" \
    ENCRYPTION_KEY="${NEW_KEY}" \
        uv run --project "${BACKEND_DIR}" \
        python "${REPO_ROOT}/scripts/reencrypt_with_old_key.py" --dry-run
    echo
}
confirm "Run the LIVE re-encryption now?" || {
    yellow "skipped live run — re-encryption did NOT happen."
    yellow "Re-run later with:"
    echo
    echo "    OLD_ENCRYPTION_KEY=<old> ENCRYPTION_KEY=<new> \\"
    echo "        uv run --project backend python scripts/reencrypt_with_old_key.py"
    exit 0
}
OLD_ENCRYPTION_KEY="${OLD_KEY}" \
ENCRYPTION_KEY="${NEW_KEY}" \
    uv run --project "${BACKEND_DIR}" \
    python "${REPO_ROOT}/scripts/reencrypt_with_old_key.py"

echo
green "✓ rotation complete. Don't forget to:"
echo "    - update any local .env files with the new key"
echo "    - revoke the old key from your password manager once you've"
echo "      verified the app is healthy end-to-end"
