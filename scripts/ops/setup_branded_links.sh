#!/usr/bin/env bash
# Create the Cloudflare DNS records that put customer-facing links on our own
# domain instead of the shared *.up.railway.app / *.vercel.app hosts.
#
# Why this exists: every tracked link in an outbound SMS is prefixed with
# PUBLIC_BASE_URL, and on a shared Railway host that link is 60 characters of
# somebody else's domain -- 38% of a 160-character segment, on a hostname whose
# sending reputation we do not control. US carriers treat unbranded shortener
# domains as a filtering signal, so this is a deliverability fix that happens to
# also look better.
#
# What it creates (all DNS-only -- see the proxy note below):
#   CNAME  go                    -> <railway target>     backend, serves /r/{code}
#   TXT    _railway-verify.go    -> <railway token>      Railway ownership proof
#   A      app                   -> 76.76.21.21          Vercel, serves /p/quotes/*
#
# Deliberately NOT proxied (grey cloud). An orange-clouded record makes
# Cloudflare terminate TLS itself, which blocks Railway's and Vercel's ACME
# ownership challenge: the cert never issues and the domain fails with an SSL
# handshake error that reads exactly like a broken deploy. The zone is already
# DNS-only today, so this matches what is there.
#
# Idempotent: an existing record with the same name/type is updated in place,
# so a re-run after a typo is safe.
#
# Usage:
#   CLOUDFLARE_API_TOKEN=... scripts/ops/setup_branded_links.sh
#   CLOUDFLARE_API_TOKEN=... ZONE=example.com scripts/ops/setup_branded_links.sh
#
# The token needs exactly one permission: Zone -> DNS -> Edit, scoped to the
# zone below. It is read from the environment and never written to disk.

set -euo pipefail
IFS=$'\n\t'

ZONE="${ZONE:-maxteriorslighting.com}"
API="https://api.cloudflare.com/client/v4"

# Railway prints these when a custom domain is added (`railway domain <host>`).
# They are per-domain, so re-adding a domain invalidates the old pair.
RAILWAY_TARGET="${RAILWAY_TARGET:-6kwf67sa.up.railway.app}"
RAILWAY_VERIFY="${RAILWAY_VERIFY:-railway-verify=cf15f531a3c6d0bd9c7d99a32483e00e34086a23a955575936303af12481a57d}"
VERCEL_IP="${VERCEL_IP:-76.76.21.21}"

bold()   { printf '\033[1m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*" >&2; }

require() {
    command -v "$1" >/dev/null 2>&1 || { red "✗ missing required tool: $1"; exit 1; }
}
require curl
require python3

if [[ -z "${CLOUDFLARE_API_TOKEN:-}" ]]; then
    red "✗ CLOUDFLARE_API_TOKEN is not set."
    red "  Create one at https://dash.cloudflare.com/profile/api-tokens"
    red "  Template: 'Edit zone DNS'  ->  Zone Resources: Include -> Specific zone -> ${ZONE}"
    exit 1
fi

auth=(-H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json")

# Pull one field out of a Cloudflare envelope without depending on jq.
cf_field() { python3 -c "import sys,json;d=json.load(sys.stdin);print(d${1} if d.get('success') else '')" 2>/dev/null || true; }

cf_errors() {
    python3 -c "
import sys, json
d = json.load(sys.stdin)
for e in d.get('errors', []):
    print('  cloudflare %s: %s' % (e.get('code'), e.get('message')))
" 2>/dev/null || true
}

bold "Resolving zone ${ZONE}…"
zone_json="$(curl -sS "${auth[@]}" "${API}/zones?name=${ZONE}")"
zone_id="$(printf '%s' "$zone_json" | cf_field "['result'][0]['id']")"

if [[ -z "$zone_id" ]]; then
    red "✗ Could not resolve a zone id for ${ZONE}."
    printf '%s' "$zone_json" | cf_errors
    red "  Check the token has Zone:DNS:Edit on this zone, and that the zone is"
    red "  active in Cloudflare (a pending zone whose nameservers were never"
    red "  switched at the registrar will not serve these records)."
    exit 1
fi
green "✓ zone ${ZONE} = ${zone_id}"

# Create, or update in place when a record of the same name+type already exists.
upsert() {
    local type="$1" name="$2" content="$3"
    local fqdn="${name}.${ZONE}"

    local existing_id
    existing_id="$(curl -sS "${auth[@]}" \
        "${API}/zones/${zone_id}/dns_records?type=${type}&name=${fqdn}" \
        | cf_field "['result'][0]['id']")"

    # proxied:false is the whole point -- see the header comment.
    local payload
    payload="$(python3 -c "
import json, sys
print(json.dumps({
    'type': sys.argv[1],
    'name': sys.argv[2],
    'content': sys.argv[3],
    'ttl': 60,
    'proxied': False,
}))" "$type" "$fqdn" "$content")"

    local resp verb
    if [[ -n "$existing_id" ]]; then
        verb="updated"
        resp="$(curl -sS -X PUT "${auth[@]}" \
            "${API}/zones/${zone_id}/dns_records/${existing_id}" --data "$payload")"
    else
        verb="created"
        resp="$(curl -sS -X POST "${auth[@]}" \
            "${API}/zones/${zone_id}/dns_records" --data "$payload")"
    fi

    if [[ "$(printf '%s' "$resp" | cf_field "['success']")" == "True" ]]; then
        green "✓ ${verb}  ${type}  ${fqdn}  ->  ${content}"
    else
        red "✗ failed   ${type}  ${fqdn}"
        printf '%s' "$resp" | cf_errors
        exit 1
    fi
}

bold "Writing records…"
upsert CNAME "go"                 "$RAILWAY_TARGET"
upsert TXT   "_railway-verify.go" "$RAILWAY_VERIFY"
upsert A     "app"                "$VERCEL_IP"

bold ""
green "Done. Next:"
cat <<'NEXT'
  1. Wait for certs to issue (usually < 2 min):
       railway domain list --service the-tribunal-api
       npx vercel domains inspect app.maxteriorslighting.com --scope maxteriors
  2. Only once both serve HTTPS, flip the env vars together:
       PUBLIC_BASE_URL=https://go.maxteriorslighting.com     (SMS short links)
       FRONTEND_URL=https://app.maxteriorslighting.com       (email + public pages)
       CORS_ORIGINS  += https://app.maxteriorslighting.com
     Flipping before the certs are live puts dead links in outbound texts --
     the provider still reports "delivered" and only the customer sees it.
NEXT
