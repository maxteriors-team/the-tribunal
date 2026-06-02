#!/usr/bin/env bash
# impl: mailpit
# Talk to the running Mailpit HTTP API. Works for any app that can be pointed
# at a local SMTP server — language-agnostic.
#
# Usage:
#   mail.sh count                     — number of captured messages
#   mail.sh list [--limit N]          — JSON summary of recent messages
#   mail.sh latest                    — subject + from/to + redacted body of most recent
#   mail.sh read <id>                 — full (redacted) body of message by ID
#   mail.sh clear                     — delete all captured messages
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/_lib.sh"

PORT="$(eyes_state_get mailpit.http_port)"
[ -n "$PORT" ] || eyes_die "mailpit not installed; run capture_email install"
BASE="http://127.0.0.1:$PORT"
curl -sf "$BASE/api/v1/info" >/dev/null 2>&1 || eyes_die "mailpit not responding at $BASE"

CMD="${1:-}"
shift || true

case "$CMD" in
  count)
    curl -sf "$BASE/api/v1/messages?limit=1" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("total",0))'
    ;;
  list)
    LIMIT=20
    [ "${1:-}" = "--limit" ] && LIMIT="$2"
    curl -sf "$BASE/api/v1/messages?limit=$LIMIT" | python3 -c '
import sys, json
d = json.load(sys.stdin)
for m in d.get("messages", []):
    print(json.dumps({"id": m["ID"], "from": m["From"]["Address"], "to": [t["Address"] for t in m.get("To",[])], "subject": m["Subject"], "created": m["Created"]}))
' | "$SCRIPT_DIR/_redact.sh"
    ;;
  latest)
    ID="$(curl -sf "$BASE/api/v1/messages?limit=1" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["messages"][0]["ID"]) if d.get("messages") else None')"
    [ -n "$ID" ] && [ "$ID" != "None" ] || eyes_die "no messages"
    curl -sf "$BASE/api/v1/message/$ID" | python3 -c '
import sys, json
m = json.load(sys.stdin)
print("id:", m["ID"])
print("from:", m["From"]["Address"])
print("to:", ", ".join(t["Address"] for t in m.get("To",[])))
print("subject:", m["Subject"])
print("---")
print(m.get("Text") or m.get("HTML") or "")
' | "$SCRIPT_DIR/_redact.sh"
    ;;
  read)
    ID="${1:-}"
    [ -n "$ID" ] || eyes_die "usage: mail.sh read <id>"
    curl -sf "$BASE/api/v1/message/$ID" | python3 -c '
import sys, json
m = json.load(sys.stdin)
print("id:", m["ID"])
print("from:", m["From"]["Address"])
print("subject:", m["Subject"])
print("---")
print(m.get("Text") or m.get("HTML") or "")
' | "$SCRIPT_DIR/_redact.sh"
    ;;
  clear)
    curl -sf -X DELETE "$BASE/api/v1/messages" >/dev/null
    echo "cleared"
    ;;
  ""|help|-h|--help)
    cat <<USAGE
mail.sh <count|list|latest|read <id>|clear>
USAGE
    ;;
  *)
    eyes_die "unknown subcommand: $CMD"
    ;;
esac
