# Quo historical backfill runbook

This command imports Quo contacts changed in a recent window, texts created in that
window, and calls completed in that window into one explicit Tribunal workspace. It
uses the encrypted `workspace_integrations` credential and stored Quo organization ID;
it does not accept or print an API key.

## Verified API versions (2026-08-26)

Quo's dated `2026-03-30` API supports the integration's webhook and single-contact
operations. Historical collection remains on the path-versioned v1 API:

| Resource | Pinned endpoint/version |
|---|---|
| Tenant validation | `GET /webhooks` + `Quo-Api-Version: 2026-03-30` |
| Webhook contact enrichment | `GET /contacts/{id}` + `Quo-Api-Version: 2026-03-30` |
| Workspace phone numbers | `GET /v1/phone-numbers` |
| Contacts | `GET /v1/contacts` |
| Candidate conversations | `GET /v1/conversations` |
| Historical texts | `GET /v1/messages` |
| Historical calls | `GET /v1/calls` |

Do not add the dated header to `/v1/messages`: Quo's dated API does not currently
support historical message listing. Sources:

- <https://www.quo.com/docs/2026-03-30/introduction>
- <https://www.quo.com/docs/mdx/api-reference/contacts/list-contacts>
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

The script validates the API key's Quo organization against the stored encrypted
tenant binding before any write. It aborts on HTTP 401/403, tenant/phone-number scope
mismatch, or invalid bounds. Other malformed provider resources are isolated and
counted without response bodies, contact names, phone numbers, message bodies, or
other PII in output.

Writes commit every 100 resources so an interrupted run can resume. Provider IDs and
the existing Quo sync upserts make retries idempotent; historical message statuses only
advance, and historical resources do not overwrite newer message bodies, links,
delivery timestamps, call status, transcript, or summary fields.

Quo's contact-list v1 endpoint has no date filter, so the command must paginate the
list and applies the requested date window locally to `createdAt`/`updatedAt`. Text and
call requests pass API date bounds directly; conversation discovery is also scoped to
validated workspace phone-number IDs.
