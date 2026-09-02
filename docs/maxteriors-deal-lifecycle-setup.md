# Maxteriors deal-lifecycle setup

This command configures the workspace containing the single active member
`admin@maxteriors.com`. It never accepts workspace, member, pipeline, or stage IDs.
It aborts unless every required stage name resolves exactly once and all stages
belong to one active pipeline.

Required stage names:

- `New Lead`
- `Contacted (No Answer)`
- `Visit/Demo Scheduled/Call`
- `Qualified and No Show`
- `Quote Sent / Follow Up`
- `Won`
- `Job Completed`
- `Unqualified (archived)`

The resulting lifecycle configuration selects `admin@maxteriors.com` as the
follow-up assignee. That configuration activates invoice stage transitions,
24-hour and 72-hour no-response call tasks, seven-day unpaid-invoice expiry,
installation completion, and the daily New Lead cleanup.

## Preview production

Run this exact read-only command from the repository root:

```bash
PRODUCTION_DATABASE_URL="$(railway variables --service Postgres --environment production --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["DATABASE_PUBLIC_URL"])')" \
  railway run --service the-tribunal-api --environment production --no-local -- \
  uv run --project backend python scripts/ops/setup_maxteriors_deal_lifecycle.py --env production
```

Confirm the displayed workspace, member, pipeline, every stage mapping, and
before/after lifecycle values. No database write occurs without `--apply`.

## Apply production

Run the same command with the explicit write flag:

```bash
PRODUCTION_DATABASE_URL="$(railway variables --service Postgres --environment production --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["DATABASE_PUBLIC_URL"])')" \
  railway run --service the-tribunal-api --environment production --no-local -- \
  uv run --project backend python scripts/ops/setup_maxteriors_deal_lifecycle.py --env production --apply
```

The command previews again, then requires typing `production`. It writes the
configuration and its exact previous value in one transaction. Re-running the
command is a no-op when the desired configuration is already present.

## Rollback

Preview the exact restoration first:

```bash
PRODUCTION_DATABASE_URL="$(railway variables --service Postgres --environment production --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["DATABASE_PUBLIC_URL"])')" \
  railway run --service the-tribunal-api --environment production --no-local -- \
  uv run --project backend python scripts/ops/setup_maxteriors_deal_lifecycle.py --env production --rollback
```

Apply that restoration:

```bash
PRODUCTION_DATABASE_URL="$(railway variables --service Postgres --environment production --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["DATABASE_PUBLIC_URL"])')" \
  railway run --service the-tribunal-api --environment production --no-local -- \
  uv run --project backend python scripts/ops/setup_maxteriors_deal_lifecycle.py --env production --rollback --apply
```

Rollback restores the exact lifecycle value captured by setup and removes the
snapshot atomically. It aborts rather than overwrite lifecycle settings changed
since setup. A repeated rollback is a no-op.
