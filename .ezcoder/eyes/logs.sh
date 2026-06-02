#!/usr/bin/env bash
# impl: tail
# Generic log probe. By convention, up.sh redirects every started process's
# stdout+stderr into .ezcoder/eyes/out/<service>.log. This probe reads from there OR
# any arbitrary file path the caller gives it.
#
# Usage:
#   logs.sh [--file <path>] [--service <name>] [--lines N] [--follow --timeout S] [--grep <pattern>]
#
# Prints the (redacted) tail to stdout.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

FILE=""
SERVICE=""
LINES=100
FOLLOW=0
FTIMEOUT=5
PATTERN=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --file) FILE="$2"; shift 2;;
    --service) SERVICE="$2"; shift 2;;
    --lines) LINES="$2"; shift 2;;
    --follow) FOLLOW=1; shift;;
    --timeout) FTIMEOUT="$2"; shift 2;;
    --grep) PATTERN="$2"; shift 2;;
    *) eyes_die "unknown arg: $1";;
  esac
done

if [ -z "$FILE" ]; then
  if [ -n "$SERVICE" ]; then
    FILE="$(eyes_out_dir)/$SERVICE.log"
  else
    eyes_die "provide --file <path> or --service <name>"
  fi
fi
[ -f "$FILE" ] || eyes_die "log file not found: $FILE (did you start the service via .ezcoder/eyes/up.sh?)"

if [ "$FOLLOW" -eq 1 ]; then
  if [ -n "$PATTERN" ]; then
    eyes_timeout "$FTIMEOUT" tail -n "$LINES" -f "$FILE" | grep --line-buffered -E "$PATTERN" | eyes_redact
  else
    eyes_timeout "$FTIMEOUT" tail -n "$LINES" -f "$FILE" | eyes_redact
  fi
else
  if [ -n "$PATTERN" ]; then
    tail -n "$LINES" "$FILE" | grep -E "$PATTERN" | eyes_redact || true
  else
    tail -n "$LINES" "$FILE" | eyes_redact
  fi
fi
