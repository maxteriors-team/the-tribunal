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
