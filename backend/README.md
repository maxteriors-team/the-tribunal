# AI CRM Backend

AI-powered CRM backend with voice agents, SMS campaigns, and Cal.com integration.

## Features

- Multi-tenant workspace architecture
- AI voice agents via OpenAI Realtime
- SMS campaigns with AI takeover
- Cal.com appointment booking
- Telnyx telephony integration

## Setup

```bash
# Install dependencies
uv sync

# Start database
docker compose up -d

# Run migrations
uv run alembic upgrade head

# Start server
uv run uvicorn app.main:app --reload
```

## API Documentation

When running in debug mode, API docs are available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Static assets

The FastAPI app mounts `backend/static/` at the `/static` URL prefix
(see `app/main.py` — `app.mount("/static", StaticFiles(directory=...))`).
The mount path is anchored to the `app` package's parent directory so it
resolves the same way regardless of the CWD uvicorn is launched from
(local dev, Docker, Railway).

**Purpose:** lead-magnet PDFs and other public marketing collateral served
directly by the backend. `LeadMagnet.content_url` rows reference paths under
this prefix (e.g. `/static/lead-magnets/<slug>.pdf`).

```
backend/static/
└── lead-magnets/        # Downloadable lead-magnet PDFs
```

Rules for this directory:

- **Public-only content.** Anything placed here is served unauthenticated at
  `/static/...`. Never put customer files, exports, PII, credentials, or
  per-workspace assets here. Use object storage with signed URLs for those.
- **Kebab-case filenames** (`dead-lead-reactivation-scripts.pdf`), matching
  the kebab-case directory convention used by the `lead-magnets/` subfolder
  and the `/api/v1/.../lead-magnets` route segment.
- **No duplicate roots.** There was previously a stray `static/` at the repo
  root that was not served by the app (the mount is relative to the backend
  package). It has been removed; only `backend/static/` exists. The helper
  scripts under `scripts/generate_lead_magnet_pdf.py` and
  `scripts/upload_lead_magnet.py` write into and reference
  `backend/static/lead-magnets/`.

## Workers

By default, background workers still run **inside the single `backend-api`
FastAPI process** for local/dev parity. On startup, `app/main.py`'s lifespan
handler checks `settings.run_background_workers` (`RUN_BACKGROUND_WORKERS` in
the environment). When it is `true`, the API process calls `start_all_workers()`
(defined in `app/workers/__init__.py`), which iterates `ALL_REGISTRIES` and
starts each worker as an `asyncio.Task` on the same event loop that serves
HTTP/WebSocket traffic. Shutdown calls `stop_all_workers()` to drain in-flight
work in reverse order.

Set `RUN_BACKGROUND_WORKERS=false` for **API-only mode**. In that mode the
FastAPI app still validates startup configuration, serves HTTP/WebSocket routes,
and marks `/readyz` healthy after Postgres/Redis checks, but it logs
`background_workers_disabled` and does not start or stop polling loops in the
lifespan. If workers are disabled on the API service, run exactly one separate
worker process with:

```bash
cd backend
uv run backend-workers
# equivalent: uv run python -m app.workers.runner
```

The standalone runner validates the same startup config, starts every registry,
waits for SIGINT/SIGTERM, then stops workers, closes Redis, and disposes the SQL
Alchemy engine.

Each worker subclasses `BaseWorker` (`app/workers/base.py`) and exposes a
`POLL_INTERVAL_SECONDS` class variable plus a `_process_items()` coroutine.
The base class runs the poll loop, writes a Redis heartbeat key
(`worker:<component_name>:heartbeat`) on every successful cycle so `/readyz`
can report per-worker liveness, and applies ≤10% jitter on every sleep to
desynchronize cycles across replicas.

### Workers and poll intervals

Startup order matches `ALL_REGISTRIES` in `app/workers/__init__.py`.

| Worker | `COMPONENT_NAME` | Poll interval | Purpose |
|---|---|---|---|
| `CampaignWorker` | `campaign_worker` | `settings.campaign_poll_interval` (default **5s**) | Processes running SMS campaigns: enforces sending hours and Redis rate limits, sends initial outreach + follow-ups, rotates the number pool, respects the global opt-out list. |
| `VoiceCampaignWorker` | `voice_campaign_worker` | **10s** | Processes running voice campaigns: initiates outbound calls with SMS fallback, derives idempotency keys, tracks outcomes via Telnyx webhooks. |
| `FollowupWorker` | `followup_worker` | **60s** | Picks up conversations with a scheduled follow-up, generates the AI reply, sends it via Telnyx, updates follow-up tracking. Capped at `MAX_FOLLOWUPS_PER_TICK = 10`. |
| `ReminderWorker` | `reminder_worker` | **60s** | Sends SMS reminders before scheduled appointments using the original conversation's phone number. Supports multi-offset sequences (`agent.reminder_offsets`) and a value-reinforcement pre-appointment SMS, deduped via `appointment.reminders_sent`. |
| `MessageTestWorker` | `message_test_worker` | `settings.campaign_poll_interval` (default **5s**) | Drives A/B message tests: round-robin assigns variants, sends one message per contact, updates variant stats, enforces opt-out. |
| `ReputationWorker` | `reputation_worker` | `settings.reputation_poll_interval` (default **300s** / 5m) | Refreshes phone-number reputation metrics, advances warming stages via `WarmingScheduler`, logs quarantine events. |
| `EnrichmentWorker` | `enrichment_worker` | `settings.enrichment_poll_interval` (default **30s**) | Scrapes websites for contacts with `enrichment_status = pending` to populate `linkedin_url` and `business_intel`. |
| `PromptStatsWorker` | `prompt_stats` | **3600s** (hourly) | Aggregates yesterday's `CallOutcome` rows into `PromptVersionStats` for dashboard trend queries. |
| `PromptImprovementWorker` | `prompt_improvement` | **86400s** (daily) | Generates improvement suggestions for agents with `auto_suggest=True`; auto-activates winners when `auto_activate=True` and no pending suggestion exists. |
| `ExperimentEvaluationWorker` | `experiment_evaluation` | **3600s** (hourly) | Walks agents with active A/B experiments, declares statistical winners via `compare_prompt_versions`, eliminates underperforming versions. |
| `AutomationWorker` | `automation_worker` | **60s** | Evaluates trigger-based automations (`appointment_booked`, `no_show`, `contact_tagged`, `never_booked`), executes their action list, writes `AutomationExecution` rows for idempotency, bumps `automation.last_evaluated_at`. |
| `NoShowReengagementWorker` | `noshow_reengagement_worker` | **3600s** (hourly) | Multi-day drip for missed appointments — Day 3 and Day 7 templates, progress tracked via `noshow-day3-sent` / `noshow-day7-sent` / `reengaged-booked` tags. |
| `NeverBookedWorker` | `never_booked_worker` | **3600s** (hourly) | Sends one re-engagement SMS to contacts who replied but never booked (≥1 inbound message, no `appointment-scheduled` tag, last activity older than `agent.never_booked_delay_days`); tags `never-booked-reengaged` to prevent re-fire. |
| `NudgeWorker` | `nudge_worker` | **3600s** (hourly) | For each workspace with nudge settings enabled: `NudgeGeneratorService` creates `HumanNudge` rows from upcoming dates, `NudgeDeliveryService` ships them via SMS/push to workspace members. |
| `ApprovalWorker` | `approval_worker` | **30s** | Drives HITL `PendingAction` lifecycle: notifies approvers of new actions, executes approved ones (book appointment, send SMS, …), auto-approves past timeout, expires stale rows. |
| `DripCampaignWorker` | `drip_campaign_worker` | **900s** (15m) | Advances enrollments across active drip campaigns via `process_active_drip_campaigns()`. Single conceptual job per cycle (`MAX_CONCURRENCY = 1`). |
| `TranscriptAnalysisWorker` | `transcript_analysis_worker` | **30s** | Picks voice-call `Message` rows with a transcript but no sentiment, runs `analyze_transcript`, merges results into the linked `CallOutcome.signals`. Batches of 10. |
| `AuthRateLimitCleanupWorker` | `auth_rate_limit_cleanup` | **3600s** (hourly) | Deletes `auth_rate_limits` rows older than 24h so the append-only table doesn't bloat the hot windowed-count queries that gate every auth request. |

### Operational implications

Because worker loops can run in the API process, the deployment topology is
constrained in ways that aren't obvious from the file layout:

1. **Run with exactly one process per worker-enabled replica.** Launching
   uvicorn/gunicorn with `--workers > 1` while `RUN_BACKGROUND_WORKERS=true`
   forks the lifespan handler in every worker process, so every poll loop runs
   `N` times in parallel against the same database. That means duplicate SMS
   sends, duplicate calls, duplicate appointment reminders, and racing approval
   execution. Keep `--workers 1` (or omit the flag) on worker-enabled services
   and scale CPU by giving the container more cores; the loops are I/O-bound so
   a single event loop saturates well past one core.

2. **Use API-only mode before horizontally scaling the API.** Multiple
   `backend-api` replicas with `RUN_BACKGROUND_WORKERS=true` multiply every poll
   loop by the replica count. To scale HTTP/WebSocket capacity safely, set
   `RUN_BACKGROUND_WORKERS=false` on the API service and deploy a single
   `backend-workers` Railway service running `uv run backend-workers` (or
   `python -m app.workers.runner`). Keep the worker service replica count fixed
   at 1 until leader election or external queueing exists.

3. **A separate worker service is not leader election.** API-only mode prevents
   HTTP replicas from starting duplicate loops, but starting more than one
   `backend-workers` replica is still unsafe. Gate each worker's
   `_process_items()` behind a Redis lease (`SET worker:<name>:leader <pod-id>
   NX EX <interval*2>`) or move scheduling into a queue before increasing worker
   replicas.

### Railway deployment modes

The committed `backend/railway.toml` keeps the existing single-service default:

```toml
[deploy]
startCommand = "sh -c 'uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*'"
```

For one API service that also runs workers, leave `RUN_BACKGROUND_WORKERS=true`
(or unset) and keep the service replica count at 1. For API-only horizontal
scaling, set the `backend-api` Railway variable `RUN_BACKGROUND_WORKERS=false`,
then create a separate `backend-workers` service from the same repo/backend
root with the same pre-deploy migration command disabled or omitted and this
start command:

```bash
uv run backend-workers
```

Do not attach `/readyz` as an HTTP healthcheck to the worker-only service unless
it also runs an HTTP server; use Railway's process restart policy/logs for that
service.

### Cross-replica coordination state

If leader-election is added, the inputs are mostly already in Postgres or Redis
— workers do not rely on in-process memory for scheduling:

- Per-item idempotency is in the DB: `AutomationExecution` rows,
  `appointment.reminders_sent` arrays, `CampaignContactStatus`,
  `automation.last_evaluated_at`, the `noshow-day*-sent` /
  `never-booked-reengaged` tags. A second replica picking up the same item will
  short-circuit on these.
- Per-worker liveness is in Redis: `worker:<component_name>:heartbeat` keys with
  a `3 × poll_interval` TTL (see `app/workers/base.py`, `heartbeat_key()`).
  `/readyz` reads these to fail health checks when a loop wedges.
- Per-job retry/failure state is in the DB: `failed_jobs` rows written by
  `RetryableWorker._dead_letter` (see `backend/scripts/inspect_dlq.py`).

The remaining gap is a *scheduler-level* `next_run` lease — workers currently
rely on every replica polling on the same wall-clock cadence, which is fine when
there is exactly one replica and unsafe otherwise. Add a
`worker_schedule(component_name, next_run_at)` table or Redis lease before
turning the replica count up.

## Observability — OpenTelemetry tracing

The backend ships distributed traces via OTLP (gRPC). Tracing is **off by default**:
if `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, `app/core/telemetry.py` skips all
instrumentation so local dev and tests don't try to reach a non-existent
collector. When the endpoint is set the following spans flow automatically:

- FastAPI server requests (HTTP method, route, status)
- Outbound `httpx` calls (OpenAI, Telnyx, Cal.com, ElevenLabs, SendGrid)
- SQLAlchemy queries against Postgres
- Redis commands (cache + worker queues)

Health probes (`/health`, `/healthz`, `/readyz`, `/metrics`) are excluded so they
don't dominate sampling budgets.

### Environment variables

| Variable | Required | Notes |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | yes (to enable) | OTLP gRPC endpoint URL, e.g. `https://api.honeycomb.io:443` |
| `OTEL_EXPORTER_OTLP_HEADERS` | depends on backend | Comma-separated `key=value` pairs (auth tokens) |
| `OTEL_SERVICE_NAME` | no | Defaults to `aicrm-backend` |

### Collector targets

**Honeycomb** — send straight to their managed OTLP endpoint:

```bash
export OTEL_SERVICE_NAME=aicrm-backend
export OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io:443
export OTEL_EXPORTER_OTLP_HEADERS="x-honeycomb-team=YOUR_INGEST_KEY"
```

**Grafana Tempo** — run a local OpenTelemetry Collector (or Grafana Agent) and
point the backend at it:

```bash
export OTEL_SERVICE_NAME=aicrm-backend
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

A minimal `otel-collector-config.yaml` that forwards to Tempo's OTLP receiver:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
exporters:
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlp/tempo]
```

**Datadog** — run the Datadog Agent with its OTLP receiver enabled, then point
the backend at it:

```bash
export OTEL_SERVICE_NAME=aicrm-backend
export OTEL_EXPORTER_OTLP_ENDPOINT=http://datadog-agent:4317
# on the agent host:
export DD_OTLP_CONFIG_RECEIVER_PROTOCOLS_GRPC_ENDPOINT=0.0.0.0:4317
```

See Datadog's [OTLP ingest in the Agent](https://docs.datadoghq.com/opentelemetry/otlp_ingest_in_the_agent/)
for the full agent-side configuration.

### Disabling

Unset `OTEL_EXPORTER_OTLP_ENDPOINT` (or leave it blank). The startup log line
`otel_disabled` confirms tracing is off; `otel_enabled` confirms it's on.
