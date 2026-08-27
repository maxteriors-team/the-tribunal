# Quo historical backfill runbook

This command imports texts and completed calls from one selected Quo phone line into one
explicit CRM workspace. It discovers only conversations on that line; message/call processing
resolves its own contact, while standalone Quo contacts are never imported. The command uses
the encrypted `workspace_integrations` credential, stored organization ID, selected phone ID,
and normalized number; it does not accept or print an API key.

## Verified API versions (2026-08-26)

Quo's dated `2026-03-30` API supports the integration's webhook and single-contact
operations. Historical collection remains on the path-versioned v1 API:

| Resource | Pinned endpoint/version |
|---|---|
| Tenant validation | `GET /webhooks` + `Quo-Api-Version: 2026-03-30` |
| Webhook contact enrichment | `GET /contacts/{id}` + `Quo-Api-Version: 2026-03-30` |
| Workspace phone numbers | `GET /v1/phone-numbers` |
| Candidate conversations | `GET /v1/conversations` |
| Historical texts | `GET /v1/messages` |
| Historical calls | `GET /v1/calls` |

Do not add the dated header to `/v1/messages`: Quo's dated API does not currently
support historical message listing. Sources:

- <https://www.quo.com/docs/2026-03-30/introduction>
- <https://www.quo.com/docs/mdx/api-reference/conversations/list-conversations>
- <https://www.quo.com/docs/mdx/api-reference/messages/list-messages>
- <https://www.quo.com/docs/mdx/api-reference/calls/list-calls>
- <https://www.quo.com/docs/mdx/api-reference/rate-limits>

## Safe production run

Run from the repository root. Replace the UUID and timestamps, but do not change or
omit any flag. The wrapper keeps the backend service's encryption key while replacing
its private-network `DATABASE_URL` with Postgres's public proxy URL; a local process
cannot resolve `postgres.railway.internal`. The URL stays inside the subprocess and is
not printed or placed in argv.

The interval is UTC and half-open (`since <= timestamp < until`), both bounds are
required, future bounds are rejected, and one run cannot exceed 31 days. Use adjacent
windows for a larger import.

First run the default rollback-only dry run:

```bash
railway run --service the-tribunal-api --environment production --no-local -- bash -c '
  export DATABASE_URL="$(
    railway variables --service Postgres --environment production --json |
      python3 -c "import json,sys; print(json.load(sys.stdin)[\"DATABASE_PUBLIC_URL\"])"
  )"
  exec uv run --project backend python scripts/ops/backfill_quo.py "$@"
' -- \
  --workspace-id 00000000-0000-0000-0000-000000000000 \
  --since 2026-08-01T00:00:00Z \
  --until 2026-08-08T00:00:00Z
```

Review only the aggregate `seen`, `eligible`, `synced`, `skipped`, and `errors` counts.
The command exits `2` if any resource or API errors were counted. Resolve those errors
before applying.

Before `--apply`, create the repository's encrypted production backup:

```bash
make db.backup.prod DATABASE_URL='<public *.proxy.rlwy.net production URL>'
```

Then repeat the same command with the explicit write flag:

```bash
railway run --service the-tribunal-api --environment production --no-local -- bash -c '
  export DATABASE_URL="$(
    railway variables --service Postgres --environment production --json |
      python3 -c "import json,sys; print(json.load(sys.stdin)[\"DATABASE_PUBLIC_URL\"])"
  )"
  exec uv run --project backend python scripts/ops/backfill_quo.py "$@"
' -- \
  --workspace-id 00000000-0000-0000-0000-000000000000 \
  --since 2026-08-01T00:00:00Z \
  --until 2026-08-08T00:00:00Z \
  --apply
```

The script validates the API key's Quo organization and confirms the stored selected phone ID
still maps to the stored normalized number before any write. It aborts on HTTP 401/403,
tenant/phone-number scope mismatch, or invalid bounds. Other malformed provider resources are
isolated and counted without response bodies, contact names, phone numbers, message bodies, or
other PII in output.

Writes commit every 100 resources so an interrupted run can resume. Provider-message IDs use
the same atomic reconciliation as signed webhooks and outbound acceptance, making retries
idempotent. Historical status can only advance, sparse resources cannot erase richer data, and
older activity cannot replace a newer conversation preview.

Conversation discovery requests only the validated selected phone ID. Message and call requests
also include that ID, the participant, and the bounded dates; each returned resource is checked
again before synchronization. Resources from another line fail closed rather than importing.
