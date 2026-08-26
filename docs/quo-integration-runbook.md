# Quo integration operations runbook

**Interim source of truth:** communicate in **Quo**. Tribunal mirrors Quo texts and calls into the contact timeline and owns CRM fields such as contact details, pipeline state, notes, tasks, consent, and reporting. Do not reply from Tribunal: the Quo timeline is read-only and its reply action opens the matching conversation in Quo. A Quo `STOP` reply is the exception that also updates Tribunal consent so every Tribunal SMS path suppresses later sends.

This runbook uses Quo API version `2026-03-30`. Quo API keys have full workspace API access, so treat each key like an admin password and never put one in source, logs, tickets, shell history, or an AI prompt.

## 1. Create and connect the key

1. In Quo, open **Workspace Settings → API** as an owner or admin.
2. Generate one dedicated key named for its environment, for example `tribunal-production`. Keep production and non-production keys separate.
3. In Tribunal, select the exact destination workspace, then open **Settings → Integrations → Quo → Connect**. Paste the key into the password field and choose **Test Connection**, then **Save**.
4. Confirm the Quo card says **Connected**. Tribunal validates the key's Quo organization, stores the key encrypted, and creates a signed webhook bound to that one Tribunal workspace.
5. In Quo, confirm the new Tribunal webhook is `enabled`, points to the intended backend origin, uses API version `2026-03-30`, and subscribes to message, call, transcript, summary, and contact events.

A key belongs to exactly one Tribunal workspace connection. Never reuse it to connect another tenant. If the wrong workspace was selected, disconnect immediately and reconnect from the correct workspace rather than moving mirrored records.

Quo reference: <https://www.quo.com/docs/2026-03-30/authentication>

## 2. Check webhook status and deliver a test event

Quo's dated API provides these operator endpoints:

- `GET https://api.quo.com/webhooks/{webhookId}` — expect `200`, `data.status: "enabled"`, the intended URL, and `apiVersion: "2026-03-30"`.
- `POST https://api.quo.com/webhooks/{webhookId}/events/test` with `{"eventType":"call.completed"}` — expect `200`; this only confirms Quo accepted the asynchronous test.
- `GET https://api.quo.com/webhooks/{webhookId}/events` — find the new event and expect `status: "success"`.
- `GET https://api.quo.com/webhooks/{webhookId}/events/{eventId}` — expect an attempt with `responseStatusCode` in the `200`–`299` range and Tribunal response `{"status":"ok"}`.

Authenticate each request with the Quo key in its required `Authorization` header and send `Quo-Api-Version: 2026-03-30`. Read the key from a secrets manager or hidden prompt; do not paste it directly into a command line because process lists and shell history can retain arguments. Delivery is not proven until the event detail shows a 2xx attempt.

Then open the matching Tribunal contact and confirm the fixture activity is labelled **Quo** and **Open in Quo** reaches the Quo conversation. Quo's canonical test payload may use sample phone numbers, so it can create a clearly synthetic CRM contact; delete that test contact only after confirming no real activity is attached.

### Execution record — 2026-08-26

No `QUO_API_KEY` or `QUO_WEBHOOK_ID` was available in the execution environment. Quo's external test-event delivery therefore remains **unverified**; local signed webhook probes are not a substitute for Quo delivery.

The local webhook probe observed `200 {"status":"ok"}` for a signed inbound fixture, `200` with `already_processed` for its replay, and `400` for a malformed signature. The focused backend fixture suite also observed the same signed event through the HTTP boundary and database.

## 3. Rotate an API key without an event gap

1. Generate a new dedicated key in **Quo Workspace Settings → API**; keep the old key active.
2. In the connected Tribunal workspace, open the Quo integration, replace the key, run **Test Connection**, and save. Tribunal validates the same Quo organization and provisions a replacement signed webhook before retiring the old webhook.
3. Run the test-event procedure above against the replacement webhook and confirm a 2xx delivery plus mirrored Quo activity.
4. In Quo, delete any old Tribunal webhook that remains after the best-effort cleanup, then delete the old API key. Access ends immediately.
5. Watch failures for at least one normal message and call cycle. If replacement validation or delivery fails, leave the old key active and restore it in Tribunal.

Rotate immediately when a key may have been exposed or when someone with access leaves. Never log either old or new key while comparing configurations.

## 4. Disconnect and clean up

1. Record the Quo webhook label/URL in Quo, then choose **Disconnect** on the Tribunal Quo integration.
2. Confirm the Tribunal card is disconnected. The encrypted credential is deleted; previously mirrored contacts and timeline history remain because Tribunal owns CRM history.
3. Confirm the corresponding webhook no longer appears in Quo. Disconnect cleanup is best-effort after the local credential deletion, so manually delete an orphaned webhook if it remains.
4. Delete the dedicated Quo API key after the webhook is gone. Do not delete a reused key until every consumer has been identified; dedicated keys avoid this ambiguity.
5. Search backend logs for `quo_webhook_cleanup_failed`. An orphaned webhook should receive `404` from its old unguessable Tribunal URL, but it must still be removed to stop retries and noise.

Disconnecting does not delete or rewrite Quo data, Tribunal CRM fields, consent records, or mirrored timeline items.

## 5. Backfill safely

Use [`docs/quo-historical-backfill.md`](./quo-historical-backfill.md) for the exact command and version split. The required sequence is:

1. Choose one explicit Tribunal workspace and a half-open UTC window no longer than 31 days.
2. Run the command without `--apply`; the default dry run validates the stored Quo organization, processes the full window, prints aggregate counts only, and rolls back.
3. Stop on any API/resource errors or an implausible count. Confirm the workspace UUID and date bounds before writing.
4. Create and verify the encrypted production database backup, then repeat the identical command with `--apply`.
5. Re-run the same bounded window if interrupted. Commits occur every 100 resources, while provider IDs and monotonic upserts make retries idempotent and prevent older history from replacing newer webhook content.

Never run an unbounded import, accept an API key as a script argument, or backfill multiple workspaces in one invocation. Keep the backup until counts, representative timelines, STOP consent, and Quo deep links are checked.

## 6. Monitor and respond to failures

Alert or investigate when any of these occur:

- Quo webhook status becomes `disabled`, delivery status becomes terminal `failed`, or retries show non-2xx responses.
- Backend logs contain `quo_webhook_verification_failed`, `quo_webhook_credentials_unavailable`, `webhook_pipeline_dispatch_failed`, or `quo_webhook_cleanup_failed`.
- `webhook_pipeline_received` has no matching `webhook_pipeline_completed`, allowing for duplicate events logged as `webhook_pipeline_duplicate_skipped`.
- A Quo conversation has activity missing from Tribunal for more than the normal webhook retry window, or a Tribunal Quo deep link no longer opens the matching conversation.
- Tribunal sends SMS after a mirrored exact STOP keyword. Pause Tribunal SMS for that workspace and treat this as a compliance incident until the global opt-out record and all sending paths are confirmed.

For a failed delivery, inspect Quo's event detail without copying customer message bodies or transcripts into logs. Fix authentication, tenant binding, or payload handling first; then use Quo's delivery retry endpoint or replay the bounded backfill window. Duplicate and out-of-order retries are expected and must not create extra timeline items or regress delivery/call status.

For diagnosis, correlate only provider, event type, bounded event ID, workspace integration ID, status, and timing. Never log API keys, webhook signing secrets, phone numbers, message bodies, summaries, transcripts, or full provider responses.
