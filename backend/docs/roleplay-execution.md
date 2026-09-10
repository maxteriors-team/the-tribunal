# Rehearsal execution (F02–F03)

## Contract

- `POST /api/v1/workspaces/{workspace}/roleplay/runs` requires a UUID `idempotency_key`.
  It commits an immutable prompt/persona snapshot and run ID, then returns **202** without
  calling a provider. Repeating a key/settings pair returns the same run; different settings
  with the same key are rejected. Deleted identities remain tombstoned, not reusable.
- Poll `GET .../runs/{id}` or recover through `GET .../runs`. Practice Arena lists saved runs
  and polls executing ones; an unresolved creation key survives browser reload in session
  storage (in-memory fallback when browser storage is denied).
- `status=pending` is queued; `running` plus `pending_action` is executing. Human runs with
  `running` and no pending action are waiting for the rep. `attempt_count` counts claimed
  provider steps, not HTTP retries. `completed` requires a valid score; zero is a valid score.
- Human turns require `expected_turn_count` (the observed transcript length) and are saved
  once before queuing the reply. `/score` queues once rather than rescoring on HTTP replay.
- `/retry` requires the observed `expected_attempt_count`. It resumes only that failed
  step if `retryable=true`; delayed or duplicate retry requests cannot retry a later failure.

## Execution and interruption

The existing `BaseWorker`/`WorkerRegistry` starts `roleplay_worker` **inside backend-api**.
There is no separate worker service to deploy. It polls every two seconds and runs at most
three calls concurrently per process. Database `SKIP LOCKED` claims and single-use claim
identities prevent duplicate execution, including during overlapping deployments. Heartbeats
continue independently of slow calls. Do not add replicas or multiple uvicorn workers without
also reviewing the app-wide worker deployment/concurrency assumptions.

Each successful utterance commits before the next paid step. No database transaction stays
open across a provider call. SDK retries are disabled. Provider calls allow 60 seconds; the
whole credential/provider step has a 90-second deadline. A three-minute stale claim becomes
**failed and unscored**, never automatically replayed. Graceful worker shutdown drains using
BaseWorker's existing 30-second window; cancellation records the same interrupted state.

**Exactly-once provider billing cannot be guaranteed across a network/process failure.**
An uncertain response (timeout, connection loss, cancellation, lost checkpoint) disables
retry rather than guessing whether the call ran. Definite provider rejections and invalid
returned output permit an explicit retry of the failed step only. That new attempt may cost
money; already saved dialogue is never regenerated. The operator sees this distinction in
`error` and `retryable`. Failed/unscored runs have null grades, no fabricated dialogue, and no
completion events or notifications. Successful reports and automation events commit together;
notifications are attempted only after that commit. Sentiment comes from the same validated,
workspace-bound scoring response, not a second globally credentialed provider call.

The additive migration leaves legacy reports unchanged. Legacy human runs can obtain an
execution snapshot when advanced/scored. Legacy runs without execution metadata are not
automatically replayed.

## No-spend verification

Existing unit suite:

```sh
cd backend
.venv/bin/pytest tests/services/ai/test_roleplay_engine.py tests/api/test_roleplay_api.py \
  tests/services/test_actionable_event_notifications.py -q
```

Integration tests require an **isolated local** migrated database named `roleplay_test_*`.
They refuse other host/database names. Set `DATABASE_URL` and `ROLEPLAY_TEST_DATABASE_URL`
to that database in the test shell, run `alembic upgrade head`, then:

```sh
.venv/bin/pytest -m integration tests/integration/test_roleplay_execution.py -q
```

These tests use the real OpenAI SDK with `httpx.MockTransport`, real Postgres claims and
transactions, and captured notifications. They cover 31-second latency, concurrent creation
and delivery, provider/scorer failures, zero scores, versioned retries, human turns, stale
recovery, cancellation and workspace isolation. They never call a paid provider.

Frontend checks: `npm test -- src/lib/api/roleplay.test.ts
src/components/agents/practice-arena.test.tsx`, plus `npm run typecheck`.
