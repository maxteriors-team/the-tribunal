# Load tests

[k6](https://k6.io/) scripts that exercise the hot paths Telnyx and Cal.com
hit in production, plus the login rate limiter and the voice WebSocket
bridge.

All scripts target **staging**. Never run them against production.

## Layout

| Script | Endpoint | Profile |
|---|---|---|
| `telnyx_webhook.js` | `POST /webhooks/telnyx/sms` | 100 RPS × 60s |
| `calcom_webhook.js` | `POST /webhooks/calcom/booking` | 50 RPS × 60s |
| `auth_login.js` | `POST /api/v1/auth/login` | 10 RPS × 60s — expects 429s |
| `voice_ws.js` | `WS /voice/stream/{call_id}` | 50 concurrent × 5min hold |
| `lib/common.js` | shared helpers (signing, URLs) | — |

## Prerequisites

1. **Install k6**
   ```bash
   # macOS
   brew install k6
   # linux (Debian/Ubuntu)
   sudo gpg -k && sudo gpg --no-default-keyring \
     --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
     --keyserver hkp://keyserver.ubuntu.com:80 \
     --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
   echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
     | sudo tee /etc/apt/sources.list.d/k6.list
   sudo apt update && sudo apt install k6
   ```

2. **Staging environment flags.** The Telnyx script can't produce real
   ed25519 signatures (k6's stdlib doesn't expose ed25519 signing). Set
   `SKIP_WEBHOOK_VERIFICATION=true` on the staging service for the duration
   of the run, then turn it back off. The Cal.com script signs payloads
   with real HMAC-SHA256, so staging can keep verification on for that one.

3. **WS ticket.** The voice bridge requires a short-lived JWT ticket from
   `POST /api/v1/auth/ws-ticket`. Mint one against a staging user, copy
   the `ticket` value, and export it as `WS_TICKET` before running
   `voice_ws.js`.

## Running

### Telnyx — 100 RPS × 60s

```bash
BASE_URL=https://staging.thetribunal.app \
  k6 run backend/tests/load/telnyx_webhook.js
```

**Pass criteria:** `http_req_duration p95 < 500ms`, `p99 < 1500ms`,
`http_req_failed < 1%`.

### Cal.com — 50 RPS × 60s

```bash
BASE_URL=https://staging.thetribunal.app \
CALCOM_WEBHOOK_SECRET=<staging-secret> \
  k6 run backend/tests/load/calcom_webhook.js
```

**Pass criteria:** `http_req_duration p95 < 500ms`, `p99 < 2000ms`,
`http_req_failed < 1%`.

### Auth login — 10 RPS × 60s (rate-limit test)

```bash
BASE_URL=https://staging.thetribunal.app \
  k6 run backend/tests/load/auth_login.js
```

This script does NOT try to authenticate — it deliberately uses a bad
password. The contract is:

- Status codes are always 401 or 429 (never 5xx).
- After the first ~10 requests per source IP, **>50% of responses must
  be 429**. If they aren't, the rate limiter is leaking.

If the test source IP changes (e.g. behind a NAT pool), the limiter may
not engage. Run from a fixed egress IP or behind a single proxy.

### Voice WebSocket — 50 concurrent × 5min hold

```bash
BASE_URL=https://staging.thetribunal.app \
WS_TICKET=$(curl -s -X POST https://staging.thetribunal.app/api/v1/auth/ws-ticket \
  -H "Cookie: access_token=<staging-cookie>" | jq -r .ticket) \
  k6 run backend/tests/load/voice_ws.js
```

Tunables (env vars):

- `CONCURRENT` — number of parallel WS connections (default 50).
- `HOLD_SECONDS` — seconds to keep each connection open (default 300).
- `WS_PATH_TEMPLATE` — path template, default `/voice/stream/{call_id}`.
  If your edge mounts the route at `/ws/voice/stream/{call_id}`, set
  `WS_PATH_TEMPLATE=/ws/voice/stream/{call_id}`.

**Pass criteria:** `ws_connect_errors < 5` across the whole run,
`ws_session_duration p95` within 10s of the configured hold.

> The single ticket is reused across VUs for simplicity; tickets are
> single-purpose but the bridge accepts a valid signature regardless of
> first-use semantics. If staging enforces strict single-use, mint one
> ticket per VU upstream and feed them in via a CSV — see k6's
> [`SharedArray`](https://k6.io/docs/javascript-api/k6-data/sharedarray/)
> recipe.

## CI

A manual GitHub Actions workflow lives at
`.github/workflows/load-test.yml`. Trigger it from the Actions tab with
the staging URL and which script to run. There is **no schedule** — load
tests only run when a human kicks them off.

## Caveats

- `voice_ws.js` sends synthetic media frames (`event: media` with a
  3-byte silence payload). It exercises the WS plumbing, not the
  realtime-AI inference path.
- All scripts generate distinct phone numbers / booking UIDs per
  request so idempotency dedupe (Telnyx X-Idempotency-Key, Cal.com
  Redis dedupe) never short-circuits the real handler.
- Run order matters when chaining: a 100 RPS Telnyx burst fills the
  message DLQ if the downstream LLM tier can't keep up. Drain
  `pending_actions` and worker queues between consecutive runs.
