#!/usr/bin/env bash
# Finish the Jobber cutover against PROD: technicians sync + assignment re-link.
# Pulls the prod DSN and crypto keys from Railway at runtime — no secrets here.
# Usage: JOBBER_ACCESS_TOKEN=<token> bash backend/scripts/ops/jobber_finish_import.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

[ -n "${JOBBER_ACCESS_TOKEN:-}" ] || { echo "error: set JOBBER_ACCESS_TOKEN"; exit 2; }

# Prod DB + prod crypto keys so encrypted writes/hashes match Railway exactly.
raw_url=$(railway variables --service Postgres --json | python3 -c "import json,sys; print(json.load(sys.stdin)['DATABASE_PUBLIC_URL'])")
# App engine is asyncpg; Railway hands out a plain postgresql:// DSN.
export DATABASE_URL="${raw_url/postgresql:\/\//postgresql+asyncpg://}"
api_vars=$(railway variables --service the-tribunal-api --json)
export ENCRYPTION_KEY=$(echo "$api_vars" | python3 -c "import json,sys; print(json.load(sys.stdin)['ENCRYPTION_KEY'])")
export SECRET_KEY=$(echo "$api_vars" | python3 -c "import json,sys; print(json.load(sys.stdin)['SECRET_KEY'])")

echo "== 1/4 technicians dry-run =="
uv run jobber-sync technicians --workspace default --dry-run
echo "== 2/4 technicians for real =="
uv run jobber-sync technicians --workspace default
echo "== 3/4 import dry-run (re-links job assignments; idempotent) =="
uv run jobber-sync import --workspace default --dry-run
echo "== 4/4 import for real =="
uv run jobber-sync import --workspace default
echo "== done =="
