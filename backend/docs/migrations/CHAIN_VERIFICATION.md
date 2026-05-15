# Alembic Chain Verification

**Date:** 2026-05-14
**Verified by:** end-to-end fresh-DB upgrade.

## Procedure

```bash
cd backend && docker compose up -d
docker exec aicrm-postgres psql -U aicrm -d postgres \
  -c "DROP DATABASE IF EXISTS aicrm WITH (FORCE);" \
  -c "CREATE DATABASE aicrm OWNER aicrm;"
DATABASE_URL="postgresql+asyncpg://aicrm:aicrm_dev_password@localhost:5432/aicrm" \
  uv run alembic upgrade head
```

## Results

- **`alembic upgrade head`**: exit 0, 61 migrations applied cleanly on fresh PostgreSQL 17.
- **`alembic heads`**: single head `b4819c8748a9`.
- **`alembic check`**: reports model/schema drift (separate concern from chain integrity — many indexes/columns defined in models that aren't in migrations, e.g. `assistant_conversations.updated_at`, `opportunities.assigned_user_id` type mismatch INTEGER→UUID, `lead_magnet_leads` table removed in models but still present in schema). Not blocking the chain; tracked separately for follow-up.

## Merge revision created

Four heads existed prior to verification:
- `a9b0c1d2e3f4` — Add assistant conversation tables
- `a9b0c1d2e3f5` — Add SMS link click tracking
- `ed05a7b8c9d0` — `messages.provider_message_id` unique
- `f1a2b3c4d5e7` — Composite `(workspace_id, last_engaged_at)` index

Resolved with merge revision **`b4819c8748a9`** (`alembic/versions/b4819c8748a9_merge_four_heads_*.py`). The merge is a no-op DDL stitch; downstream behavior unchanged.

## Data-loss-risk migrations

Three migrations contain destructive operations in `upgrade()`. All are intentional and reviewed:

| Revision | File | Operation | Risk assessment |
|---|---|---|---|
| `c4d5e6f7a8b9` | `c4d5e6f7a8b9_encrypt_integration_credentials.py` | `drop_column('workspace_integrations', 'credentials')` after copying into encrypted column | **Safe** — transforms data into `credentials_encrypted`; the dropped JSONB is re-encoded, not lost. Verify `app.core.encryption.encrypt_json` is importable at migration time. |
| `eb03f4a5b6c7` | `eb03f4a5b6c7_email_events_provider_event_id_unique.py` | `DELETE FROM email_events` for duplicate `provider_event_id` rows | **Intentional dedup** — keeps the earliest event per `provider_event_id`, drops later duplicates, then adds `uq_email_events_provider_event_id`. Lossy but required for webhook idempotency. Back up `email_events` before applying in prod. |
| `ed05a7b8c9d0` | `ed05a7b8c9d0_messages_provider_message_id_unique.py` | `DELETE FROM messages` for duplicate `provider_message_id` rows | **Intentional dedup** — same pattern as above for inbound SMS idempotency. Back up `messages` before applying in prod. |

### Prod rollout recommendation

Before running these against production:
1. `pg_dump` the `messages` and `email_events` tables.
2. Run the DELETE statements with `EXPLAIN` to gauge row counts.
3. Confirm with the team that older duplicates can be discarded (the migrations keep the chronologically *earlier* row).

## History (top 80 lines)

See `alembic history` output captured at verification time. Single head, single linearized chain via two prior mergepoints (`1963647ee64e`, `b4819c8748a9`).
