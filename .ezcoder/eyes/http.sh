#!/usr/bin/env bash
# impl: curl
# Universal HTTP probe. Works for any backend/API regardless of language —
# Express, FastAPI, Rails, Spring, Gin, Actix, Phoenix, Laravel, etc.
#
# Usage:
#   http.sh <url> [method] [body-or-@file] [-H "Header: value" ...]
#
# Prints JSON to stdout: {"status":200,"size":1234,"headers":"<path>","body":"<path>","time_ms":45}
# Body is redacted before writing.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

URL="${1:-}"
[ -z "$URL" ] && eyes_die "usage: http.sh <url> [method] [body-or-@file] [-H ...]"
METHOD="${2:-GET}"
BODY="${3:-}"

EXTRA_HEADERS=""
if [ "$#" -gt 3 ]; then
  shift 3
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -H) EXTRA_HEADERS="$EXTRA_HEADERS
$2"; shift 2;;
      *) eyes_die "unknown arg: $1";;
    esac
  done
fi

eyes_require curl

TS="$(eyes_timestamp)"
HEADERS="$(eyes_out_dir)/http-$TS.headers"
BODY_OUT="$(eyes_out_dir)/http-$TS.body"

# Build curl args
ARGS=(-sS -D "$HEADERS" -o - -X "$METHOD" --max-time 20)
if [ -n "$EXTRA_HEADERS" ]; then
  while IFS= read -r header; do
    [ -n "$header" ] && ARGS+=(-H "$header")
  done <<EOF
$EXTRA_HEADERS
EOF
fi
if [ -n "$BODY" ]; then
  case "$BODY" in
    @*) ARGS+=(--data-binary "$BODY");;
    *)  ARGS+=(-H "Content-Type: application/json" --data-binary "$BODY");;
  esac
fi

START_MS=$(python3 -c 'import time; print(int(time.time()*1000))' 2>/dev/null || date +%s%3N 2>/dev/null || echo 0)

# Pipe body through redactor, then measure size after redaction.
if ! curl "${ARGS[@]}" "$URL" | "$(eyes_root)/_redact.sh" > "$BODY_OUT"; then
  eyes_die "curl failed to reach $URL"
fi
END_MS=$(python3 -c 'import time; print(int(time.time()*1000))' 2>/dev/null || date +%s%3N 2>/dev/null || echo 0)

STATUS="$(grep -m1 -oE 'HTTP/[0-9.]+ [0-9]+' "$HEADERS" | awk '{print $2}' || echo 0)"
SIZE=$(wc -c < "$BODY_OUT" | awk '{print $1}')
TIME_MS=$(( END_MS - START_MS ))

# Also redact headers file in place (authorization, cookie)
tmp="$(mktemp)"
"$(eyes_root)/_redact.sh" < "$HEADERS" > "$tmp" && mv "$tmp" "$HEADERS"

printf '{"status":%s,"size":%s,"time_ms":%s,"headers":"%s","body":"%s"}\n' \
  "${STATUS:-0}" "$SIZE" "$TIME_MS" "$HEADERS" "$BODY_OUT"
