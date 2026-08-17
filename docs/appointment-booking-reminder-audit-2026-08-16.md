# Chatbot appointment-booking and reminder-delivery audit

**Snapshot:** 2026-08-16

**Production backend:** `e229d64584be7cfae81613d1f19ef630a9e1eb81`

**Review type:** production read-back + provider read + source trace + targeted tests

**Legal note:** engineering guidance, **not legal advice** and not a compliance certification.

## Verdict

- **Calendar creation works for the currently connected workflow.** I read the one post-connection chatbot booking back from the Google Calendar API. It exists on the connected workspace owner's **primary calendar**, is organized by that account, has exactly one attendee, carries Tribunal's source marker, and its start/end match the CRM appointment. The attendee is invited with `needsAction`, and the event has a Meet link.
- **Reminder delivery is not reliable.** Production has **11 automatic SMS reminder markers**. Only **7 correlate to a Telnyx `delivered` reminder**, **3 correlate to failed sends**, and **1 has no SMS record at all**. The worker still marked all 11 offsets as sent.
- **The dashboard's markers prove an attempt was consumed, not that a user received it.** The code marks a reminder offset after `send_message()` returns even when that returned `Message` has status `failed`.
- **Email reminders are not enabled in production.** Current agent configuration is SMS-only and there are zero email-reminder markers. Booking-confirmation emails were accepted by Resend, but the intentionally send-only production key and uncorrelated email path prevent inbox-delivery verification.

## What I verified without contacting customers

No appointment, calendar event, SMS, or email was created, changed, or sent during this audit. Production queries retained only aggregate counts and one-way-hashed appointment references; no customer name, email, phone number, message body, token, or provider event ID is in this report or its evidence artifact.

| Check | Result | Evidence |
|---|---|---|
| Deployed source identity | pass | `/version` reported `e229d645…`; the audit used that exact git commit. |
| Google connection ownership | pass | One active login-linked staff record belongs to the workspace owner and points at one connected Google account. |
| Live calendar event exists | pass | Google API `GET`: one event found on the primary calendar; organizer is self; source marker, start, end, attendee, and Meet link match. |
| Google invitation issued | pass | One attendee exists with `needsAction`; booking code creates the event with `sendUpdates=all`. This proves invitation issuance, not inbox placement. |
| Booking emails accepted | pass at provider-acceptance level | Railway logs contain one attendee confirmation and one representative notification with provider IDs for the verified booking. |
| Booking emails delivered | **unverified** | Resend retrieval returned `validation_error` because the production key is intentionally send-only; direct booking emails are not persisted as `Message` rows for webhook correlation. |
| Automatic SMS reminders delivered | **fail** | 7 delivered / 3 failed / 1 missing across 11 consumed offset markers. |
| Manual reminder path observed | partial pass | Two rows with the deterministic manual-reminder key are both `delivered`; code can still falsely return success for a future failed send. |
| Email reminders delivered | n-a in current production config | Reminder channels are SMS-only; zero email reminder offsets have fired. |
| Reminder worker alive | pass | The final deployment emitted one start record and four completed loops with zero errors/items; the preceding same-code deployment's latest 500 sampled loops also had zero loop errors. No reminder was due in either sample. |
| Failure queue catches reminder errors | **fail** | Zero reminder dead-letter rows despite failed production reminders. |
| Canonical deployed-source verification | **PASSED** | Repository command `make ci.backend` exited 0 on exact commit `e229d645…`: dependency lock/sync, env drift, Ruff lint/format, mypy, **4,448 passed tests**, and 60.73% coverage. |

The redacted machine-readable evidence is at `.ezcoder/eyes/out/appointment-delivery-audit-2026-08-16.json` (gitignored).

## Workflow trace

### Chatbot booking → CRM → Google Calendar

1. `BaseToolExecutor.execute_book_appointment()` validates the proposed time and staff availability.
2. `TextToolExecutor._post_booking_success()` calls `finalize_booking()`.
3. `finalize_booking()` commits the local `Appointment` with `sync_status="pending"`.
4. It launches `deliver_booking_notifications()` with `spawn_background_task()` and returns to the chatbot immediately.
5. That in-memory task creates the Google event, writes the provider ID/URL, sends representative and attendee emails, and optionally sends lifecycle SMS.

The local appointment commit is durable; **calendar creation and notifications are not**. They run after the response in an in-process `asyncio.Task`. There is no persistent outbox, startup replay, periodic calendar-sync worker, or shutdown drain for those tasks.

### Appointment → automatic reminder → Telnyx delivery webhook

1. `ReminderWorker` polls every 60 seconds and fetches the first 20 upcoming appointments inside a fixed 25-hour window.
2. Python computes due channel/offset tuples.
3. `_send_reminder()` calls `TelnyxSMSService.send_message()`.
4. `send_message()` catches provider errors, commits a `Message(status="failed")`, and **returns it instead of raising**.
5. `_send_reminder()` does not inspect that status. It logs “sent,” appends the offset to `appointments.reminders_sent`, and commits.
6. If Telnyx accepted the SMS, signed delivery webhooks later update the `Message` to `delivered` or `failed`.

The failure is between steps 4 and 5: a locally failed provider request is consumed as if it were sent, so the reminder is not retried and never reaches the dead-letter queue.

## Findings

### BOOK-001 — HIGH — Calendar sync is fire-and-forget, so a successful chatbot reply does not guarantee a calendar event

**Evidence: CODE + RUNTIME**

`backend/app/services/appointments/booking_finalizer.py:194-198` commits the appointment and starts an in-memory background task. `backend/app/utils/background_tasks.py` retains a task reference only until completion; no durable job row or shutdown drain exists. Provider failures are converted to `sync_status="failed"` inside the task and are not scheduled for retry. A duplicate booking request can incidentally relaunch sync, but nothing systematically scans `pending` or `failed` rows.

The live post-connection booking succeeded, proving the happy path. It does **not** prove crash or transient-provider recovery.

**Real consequence:** a deploy, crash, cancelled task, expired token, or temporary Google error after the local commit leaves the CRM appointment present but the owner's calendar empty. The chatbot has already returned.

**Fix:** write a durable booking-outbox row in the same transaction as the appointment, then let a worker claim it with provider idempotency, retry transient failures, dead-letter permanent failures, and alert on stale `pending` rows.

### REM-001 — HIGH — Failed SMS reminders are marked sent and never retried

**Evidence: RUNTIME + CODE**

Production outcome for consumed automatic offsets:

| Outcome | Count | Share |
|---|---:|---:|
| Telnyx webhook reached `delivered` | 7 | 63.6% |
| Local/provider request failed before a provider ID existed | 3 | 27.3% |
| No matching SMS record | 1 | 9.1% |
| **Total marked sent** | **11** | **100%** |

`backend/app/services/telephony/telnyx.py:336-349` maps provider errors to `MessageStatus.FAILED` and returns the row. `backend/app/workers/reminder_worker.py:342-376` logs success and appends the offset without checking `message.status`. `backend/app/services/calendar/reminder_service.py:279-303` has the same bug and can return `{"success": true}` for a failed manual send. The value-reinforcement path repeats the pattern at `reminder_worker.py:485-500`.

Three marker-linked failures were provider rejections; one additional failed reminder-shaped SMS exists in the message table. No failed reminder has a provider ID, and no reminder failure reached the dead-letter table.

**Real consequence:** users miss reminders while operators see a sent marker and no retry occurs.

**Fix:** treat only `sent`/`delivered` as provider acceptance. A returned `failed` row must stay due, retry with the same provider idempotency key when retryable, or enter a visible permanent-failure state; it must never append a sent offset.

### REM-002 — HIGH — Idempotency permanently replays a failed row instead of retrying the provider

**Evidence: CODE**

`resolve_message_idempotency()` currently skips every existing status except `queued`. A retry using the same key therefore returns the original `failed` row without calling Telnyx again. Even after REM-001 adds a status check, retry would still be inert unless this behavior changes.

**Real consequence:** transient failures are permanent under the exact key intended to make retries safe.

**Fix:** distinguish provider-accepted terminal states from retryable local failures. Resume a failed row with the same Telnyx idempotency key when the error is retryable; record permanent failures separately and stop with an operator-visible reason.

### REM-003 — HIGH — The reminder fetch can starve due appointments after row 20

**Evidence: CODE; not currently triggered at production volume**

`reminder_worker.py:132-150` orders all upcoming appointments and applies `LIMIT 20` **before** filtering already-sent offsets. Fully consumed appointments still occupy the batch. With more than 20 overlapping appointments, later due reminders may never be examined before their appointment time.

**Real consequence:** reminder delivery degrades silently exactly when booking volume grows.

**Fix:** query a touch ledger of due unsent reminders, or page through appointments until the due set is exhausted. Add a regression with 21 fully consumed rows followed by one due unsent row.

### CAL-005 — MEDIUM — Four historical rows say `synced` but contain no calendar event identifier

**Evidence: RUNTIME + CODE**

Production has five rows labeled `synced`; only one has a Google event ID. Migration `6f50d2e7a9c1_google_calendar_per_user_oauth.py` dropped the old Cal.com booking IDs while leaving `sync_status` untouched. The four unlinked rows are historical and cannot be read, updated, or cancelled through either provider from Tribunal.

**Real consequence:** `sync_status="synced"` is not trustworthy for migrated records. Those rows may have existed in Cal.com, but the repository no longer retains proof.

**Fix:** backfill them to an explicit `legacy_unlinked` state and prevent future `synced` rows without a provider event ID. This is a production appointment-table migration, so follow the repository's backup and migration-release procedure.

### OBS-001 — HIGH — Email acceptance is logged, but booking/reminder delivery cannot be reconciled

**Evidence: RUNTIME + CODE**

Booking emails received Resend provider IDs. However, these direct send paths do not create `Message`/delivery-attempt rows. The Resend webhook service looks up a `Message` by `provider_message_id`; these emails therefore cannot be correlated. The send-only production API key correctly prevents retrospective provider reads.

**Real consequence:** the system can prove “Resend accepted it,” not “Resend delivered/bounced it,” and cannot alert or retry from a bounce.

**Fix:** persist one outbound delivery-attempt row before each transactional email, save the provider ID, and reconcile signed Resend events to it. Keep provider acceptance and final delivery as separate statuses.

### MSG-001 — HIGH — Reminder SMS has opt-out handling but no recorded consent or quiet-hours gate

**Evidence: RUNTIME + CODE; legal interpretation needs counsel**

Every production appointment inspected had `sms_consent_status="unknown"`; reminder sends check only the opt-out manager. The worker does not use the shared outbound compliance/quiet-hours service. An appointment reminder may be transactional rather than marketing, but the code does not retain the source or scope of consent needed to demonstrate why automated texts are permitted.

**Real consequence:** reminders can be sent at an inappropriate local hour, and the business cannot produce a clear consent record if challenged.

**Fix:** capture consent source/time/scope at the booking entry point, enforce the shared messaging gate, and defer rather than consume reminders during quiet hours. Counsel should confirm the intended transactional-reminder policy for the states/countries served.

### LOG-001 — MEDIUM — Reminder and booking logs include customer contact data

**Evidence: CODE + RUNTIME**

Reminder logs bind phone/from-number fields, booking availability logs include email, and email helpers log recipient addresses. Railway log access therefore exposes additional personal data beyond the IDs needed to operate the workflow.

**Real consequence:** a log-reader or exported log archive can reveal customer contact information; retention and incident scope become larger.

**Fix:** retain appointment/contact/provider IDs and masked destinations only. Never bind the full phone, email, message body, token, or calendar event identifier.

## What works today

- The chatbot's local appointment write is committed before any notification is attempted.
- The post-connection live booking is genuinely present on the connected owner's primary Google Calendar with correct timing and attendee metadata.
- Google event creation uses a deterministic event ID, reducing duplicate events on safe retry.
- Telnyx signed delivery webhooks correctly promote accepted messages to `delivered`/`failed`; targeted contract and monotonic-status tests pass.
- Automatic reminder SMS honors explicit opt-outs.
- Current production reminder channels are SMS-only, so zero email reminder sends is expected rather than a worker outage.
- The reminder worker is running continuously in the single backend process.
- Two observed manual-reminder messages with deterministic keys reached `delivered`.

## Required remediation order

1. **Stop false success:** do not mark automatic, manual, or value-reinforcement reminders sent when `Message.status == failed`; repair failed-row retry semantics and add dead-letter/alert behavior.
2. **Make booking side effects durable:** transactional outbox + calendar/email/SMS delivery-attempt rows + a retrying worker.
3. **Remove silent starvation:** fetch due unsent touchpoints with pagination, not the first 20 appointments.
4. **Make delivery observable:** correlate Telnyx and Resend provider events to appointment/touchpoint records and display accepted/delivered/failed separately.
5. **Clean data and messaging controls:** label legacy unlinked calendar rows, remove PII from logs, and enforce documented consent/quiet-hour rules.

## Acceptance checks for the fix

- A mocked Telnyx 4xx/5xx returning `Message(status="failed")` leaves the offset due; retryable errors re-POST with the same provider key, permanent errors dead-letter visibly.
- Twenty-one consumed appointments followed by one due unsent appointment still sends the final reminder.
- Killing the API process immediately after the local booking commit still produces exactly one calendar event after restart.
- A temporary Google failure moves `pending → failed → synced` through retries without a second event.
- Telnyx `delivered`/`failed` and Resend `delivered`/`bounced` events update one appointment touchpoint, and the UI never labels provider acceptance as delivery.
- Unknown/withdrawn consent and quiet hours block or defer SMS without consuming the reminder.
- A controlled canary booking to a designated test calendar/phone receives the calendar event and all configured reminders before release.

## Verification record

Production-safe checks:

- `/version` and readiness read.
- Read-only aggregate SQL over appointments, contacts, messages, worker dead letters, calendar connections, and configuration.
- Google Calendar API read for the sole linked event; no event mutation. Normal OAuth refresh may update the encrypted access token.
- Historical Railway log aggregation with destination values redacted before output.
- Resend read-back attempt; correctly denied by the send-only key.
- No Telnyx/Resend send call and no production write to appointments/messages.

Canonical project verification against the exact deployed commit `e229d64584be7cfae81613d1f19ef630a9e1eb81`:

| Project verification command | PASSED evidence |
|---|---|
| `make ci.backend` | **PASSED — exit 0; dependency lock/sync, env drift, Ruff lint/format, mypy, 4,448 passed tests, and 60.73% coverage** |

This canonical CI run includes the appointment-booking, reminder-worker, Telnyx delivery-status, and Resend webhook suites. It validates the checked-in tests and static checks; the production failures above remain separate runtime evidence for behavior the suite does not currently assert.

## Assumptions and limits

- The product is public and uses real customer data, as confirmed by deployment and production records.
- Worldwide reach, possible under-18 access without an age gate, and exact legal-entity details remain cautious assumptions; none changes the functional verdict.
- “Delivered” means the provider's signed delivery status, not proof that a person read the message or that an email appeared in the inbox.
- Historical Cal.com events cannot be verified after their provider identifiers were dropped.
- This audit did not send a new canary because no designated test phone/email was available and messaging a real customer would be an irreversible external action.
