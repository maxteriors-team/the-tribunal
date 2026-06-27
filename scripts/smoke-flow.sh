#!/usr/bin/env bash
#
# smoke-flow.sh — exercise the critical authenticated user flow end-to-end.
#
# Unlike smoke-watch.sh (a curl-only liveness heartbeat), this script drives a
# real stateful journey against a running backend and asserts the new
# workspace-roles / field-service / bulk-member / forced-password-reset / Jobber
# import features behave correctly:
#
#   register → login → /auth/me → workspaces → contacts
#   → field-service reads + create crew (owner write)
#   → bulk-provision a member (temp password issued)
#   → temp password logs in AND is gated by must_change_password
#   → role gating: provisioned technician is blocked from privileged writes
#   → change-password clears the reset gate
#   → Jobber import template exposes the preset + address aliases
#
# It creates throwaway accounts on each run; it never mutates existing data
# beyond adding test users/crews to the caller's default workspace.
#
# Usage:
#   scripts/smoke-flow.sh                 # full flow against local backend
#   scripts/smoke-flow.sh --base URL      # target a different backend
#   scripts/smoke-flow.sh -h              # help
#
# Persistent settings (override via env; defaults are baked in so a bare run
# Just Works and survives exiting the session — nothing is hardcoded inline):
#   BACKEND_URL    (default http://127.0.0.1:8000)
#   SMOKE_EMAIL    (default smoke+<timestamp>@example.com — fresh user per run)
#   SMOKE_PASSWORD (default SmokeTest12345)
#   STATE_DIR      (default .ezcoder/eyes/out — gitignored run artifacts)
#
# Exit code is 0 only when every step passes, so it doubles as a CI gate.
set -uo pipefail

# --- persistent settings ---------------------------------------------------
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:8000}"
SMOKE_PASSWORD="${SMOKE_PASSWORD:-SmokeTest12345}"
STATE_DIR="${STATE_DIR:-.ezcoder/eyes/out}"
REQUEST_TIMEOUT="${REQUEST_TIMEOUT:-15}"
# Fresh per-run user unless the caller pins one. The default is computed once,
# here, so every step in a run shares the same identity.
SMOKE_EMAIL="${SMOKE_EMAIL:-smoke+$(date +%s)@example.com}"

while [ $# -gt 0 ]; do
  case "$1" in
    --base) BACKEND_URL="${2:?--base needs a URL}"; shift 2 ;;
    --email) SMOKE_EMAIL="${2:?--email needs a value}"; shift 2 ;;
    --password) SMOKE_PASSWORD="${2:?--password needs a value}"; shift 2 ;;
    -h|--help) sed -n '2,40p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 2; }
mkdir -p "$STATE_DIR"
RUN_DIR="$(mktemp -d "${STATE_DIR%/}/smoke-flow.XXXXXX")"
trap 'rm -rf "$RUN_DIR"' EXIT

# Colors only when attached to a terminal (keeps background logs clean).
if [ -t 1 ]; then
  GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
  GREEN=''; RED=''; DIM=''; BOLD=''; RESET=''
fi

PASS=0
FAIL=0

# chk <name> <expected> <actual> — tally and print a ✓/✗ line.
chk() {
  if [ "$2" = "$3" ]; then
    printf '  %s✓%s %s %s→ %s%s\n' "$GREEN" "$RESET" "$1" "$DIM" "$3" "$RESET"
    PASS=$((PASS + 1))
  else
    printf '  %s✗ %s%s %s(got %s, want %s)%s\n' "$RED" "$1" "$RESET" "$DIM" "$3" "$2" "$RESET"
    FAIL=$((FAIL + 1))
  fi
}

# api <method> <path> [data] [token] — perform a request, capture body+status.
# Echoes the HTTP status code; writes the body to $RUN_DIR/last.json. JSON body
# is sent unless the path is the form-encoded login endpoint.
api() {
  local method="$1" path="$2" data="${3:-}" token="${4:-}"
  local -a args=(-sS -m "$REQUEST_TIMEOUT" -o "$RUN_DIR/last.json" -w '%{http_code}'
    -X "$method" "$BACKEND_URL$path")
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  if [ "$path" = "/api/v1/auth/login" ]; then
    args+=(-H "Content-Type: application/x-www-form-urlencoded" --data "$data")
  elif [ -n "$data" ]; then
    args+=(-H "Content-Type: application/json" --data "$data")
  fi
  curl "${args[@]}" 2>/dev/null || echo "000"
}

# jget <key-path> — read a value from the last response body via python3.
# Supports dotted paths and [index]; prints empty string when absent.
jget() {
  python3 - "$1" "$RUN_DIR/last.json" <<'PY' 2>/dev/null
import json, re, sys
path, fp = sys.argv[1], sys.argv[2]
try:
    cur = json.load(open(fp))
except Exception:
    print(""); sys.exit()
for part in re.findall(r'[^.\[\]]+', path):
    try:
        cur = cur[int(part)] if part.isdigit() else cur[part]
    except (KeyError, IndexError, TypeError):
        print(""); sys.exit()
print("" if cur is None else cur)
PY
}

printf '%ssmoke-flow%s — %s\n' "$BOLD" "$RESET" "$BACKEND_URL"
printf '%suser:%s %s\n\n' "$DIM" "$RESET" "$SMOKE_EMAIL"

# --- 1. health -------------------------------------------------------------
printf '%shealth + auth%s\n' "$BOLD" "$RESET"
chk "GET /readyz" 200 "$(api GET /readyz)"

# --- 2. register + login ---------------------------------------------------
reg=$(api POST /api/v1/auth/register \
  "{\"email\":\"$SMOKE_EMAIL\",\"password\":\"$SMOKE_PASSWORD\",\"full_name\":\"Smoke Flow\"}")
chk "POST /auth/register" 201 "$reg"

login=$(api POST /api/v1/auth/login \
  "username=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$SMOKE_EMAIL")&password=$SMOKE_PASSWORD")
chk "POST /auth/login" 200 "$login"
OWNER_TOKEN="$(jget access_token)"

me=$(api GET /api/v1/auth/me "" "$OWNER_TOKEN")
chk "GET /auth/me" 200 "$me"
chk "  must_change_password=false for self-registered" "False" "$(jget must_change_password)"
WS="$(jget default_workspace_id)"

chk "GET /workspaces" 200 "$(api GET /api/v1/workspaces "" "$OWNER_TOKEN")"

# --- 3. core domain --------------------------------------------------------
printf '\n%score domain%s\n' "$BOLD" "$RESET"
chk "GET /contacts" 200 "$(api GET "/api/v1/workspaces/$WS/contacts" "" "$OWNER_TOKEN")"

# --- 4. field service ------------------------------------------------------
printf '\n%sfield service%s\n' "$BOLD" "$RESET"
for ep in service-locations crews technicians; do
  chk "GET /$ep" 200 "$(api GET "/api/v1/workspaces/$WS/$ep" "" "$OWNER_TOKEN")"
done
crc=$(api POST "/api/v1/workspaces/$WS/crews" '{"name":"Smoke Crew","color":"#ff8800"}' "$OWNER_TOKEN")
chk "POST /crews (owner write)" 201 "$crc"

# --- 5. bulk members + forced password reset -------------------------------
printf '\n%sbulk members + forced reset%s\n' "$BOLD" "$RESET"
TECH_EMAIL="tech+$(date +%s)@example.com"
bm=$(api POST "/api/v1/workspaces/$WS/members/bulk" \
  "{\"members\":[{\"email\":\"$TECH_EMAIL\",\"full_name\":\"Tech One\",\"role\":\"technician\"}]}" \
  "$OWNER_TOKEN")
chk "POST /members/bulk" 201 "$bm"
chk "  outcome=created" "created" "$(jget results[0].status)"
TEMP_PW="$(jget results[0].temporary_password)"

tl=$(api POST /api/v1/auth/login "username=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$TECH_EMAIL")&password=$TEMP_PW")
chk "technician login (temp pw)" 200 "$tl"
TECH_TOKEN="$(jget access_token)"

api GET /api/v1/auth/me "" "$TECH_TOKEN" >/dev/null
chk "  must_change_password=true (gate set)" "True" "$(jget must_change_password)"

# --- 6. role gating --------------------------------------------------------
printf '\n%srole gating%s\n' "$BOLD" "$RESET"
chk "technician CANNOT bulk-provision" 403 \
  "$(api POST "/api/v1/workspaces/$WS/members/bulk" '{"members":[{"email":"x@example.com","role":"member"}]}' "$TECH_TOKEN")"
chk "technician CANNOT create crew" 403 \
  "$(api POST "/api/v1/workspaces/$WS/crews" '{"name":"Nope"}' "$TECH_TOKEN")"

# --- 7. password reset clears the gate -------------------------------------
printf '\n%spassword reset clears gate%s\n' "$BOLD" "$RESET"
cpw=$(api POST /api/v1/auth/change-password \
  "{\"current_password\":\"$TEMP_PW\",\"new_password\":\"BrandNewPass9999\"}" "$TECH_TOKEN")
chk "POST /auth/change-password" 200 "$cpw"
api POST /api/v1/auth/login "username=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))' "$TECH_EMAIL")&password=BrandNewPass9999" >/dev/null
NEW_TOKEN="$(jget access_token)"
api GET /api/v1/auth/me "" "$NEW_TOKEN" >/dev/null
chk "  must_change_password cleared" "False" "$(jget must_change_password)"

# --- 8. jobber import template ---------------------------------------------
printf '\n%sjobber import%s\n' "$BOLD" "$RESET"
it=$(api GET "/api/v1/workspaces/$WS/contacts/import/template" "" "$OWNER_TOKEN")
chk "GET /contacts/import/template" 200 "$it"
chk "  jobber preset present" "address_line1" "$(jget presets.jobber.Street1)"
chk "  zip alias present" "address_zip" "$(jget presets.jobber['Zip Code'])"

# --- summary ---------------------------------------------------------------
total=$((PASS + FAIL))
if [ "$FAIL" -eq 0 ]; then
  printf '\n%s→ %d/%d passed%s\n' "$GREEN" "$PASS" "$total" "$RESET"
  exit 0
fi
printf '\n%s→ %d/%d passed, %d FAILED%s\n' "$RED" "$PASS" "$total" "$FAIL" "$RESET"
exit 1
