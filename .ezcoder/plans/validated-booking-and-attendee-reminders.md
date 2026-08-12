# Validated AI booking + attendee reminders + notification preferences

## Goal

Three gaps, one feature:

1. **Validation before confirming** — the text/SMS agent books without re-checking the slot, so it can confirm a time that is already taken, outside business hours, or in the past.
2. **Attendee reminders** — the customer gets an SMS confirmation and SMS reminders, but never a calendar invite (`.ics`) or an email reminder. Only the *rep* gets an invite.
3. **Configurable preferences** — reminder settings exist per agent (enable, offsets, SMS template) but there is no channel choice (SMS vs email), no confirmation-email toggle, and agentless appointments use a hardcoded `[60]` offset.

## What exists today (verified)

- `backend/app/services/calendar/booking.py::BookingService.book_appointment` — validates only `strptime` format. Re-checks availability **only when `pre_validate=True`**.
- `backend/app/services/ai/base_tool_executor.py` — `pre_validate: bool = False`; `tool_executor.py:139` (voice) sets `True`. **`text_tool_executor.py` never overrides it**, so every SMS/chat booking skips the slot re-check.
- `base_tool_executor.execute_book_appointment` requires a non-empty `email` but does not validate its syntax; duration is an unchecked int; past datetimes are not rejected on the non-prevalidated path.
- `backend/app/services/appointments/booking_finalizer.py::deliver_booking_notifications` — sends customer confirmation **SMS** (`lifecycle_sms.build_confirmation_body`) and a rep **email + `.ics`** (`send_appointment_booked_notification`). No attendee email, no attendee `.ics`.
- `backend/app/workers/reminder_worker.py` — SMS-only, offsets from `agent.reminder_offsets`, dedupe via `appointments.reminders_sent` (`ARRAY(Integer)`, VR uses sentinel `-1`), agentless fallback `_AGENTLESS_DEFAULT_OFFSETS = [60]`.
- Config UI: `frontend/src/components/agents/tabs/advanced/reminders-section.tsx` (+ `reminder-offsets-input.tsx`), form mapping in `frontend/src/lib/agents/agent-form.ts`, types in `frontend/src/types/agent.ts` / `frontend/src/lib/api/agents.ts`.
- `backend/app/services/calendar/ics.py` already renders invites (`CalendarInvite`, `render_invite`, `appointment_uid`).

## Design decisions

- **One validation module, all three booking paths.** Voice, text, and the HITL approval handler all funnel through `BaseToolExecutor` / `finalize_booking`; validation lives in a new service so no path can skip it.
- **Validation failures are model-readable.** Each failure returns `{success: false, error, message, alternative_slots}` so the agent re-asks the customer instead of falsely confirming. This is the whole point — a booking must never be *confirmed to the customer* before it is validated.
- **`pre_validate` becomes always-on.** Keeping it a per-channel flag is what created the bug; remove the class attribute and always re-check.
- **Attendee email dedupe gets its own column** (`appointments.reminders_sent_email`), not another sentinel in `reminders_sent`. Sharing the array would make an SMS send suppress the email at the same offset.
- **Preferences live on the agent** (matches `noshow_sms_enabled` precedent), plus a workspace-level default offset list for agentless appointments in `workspace.settings["reminder_defaults"]` — no new table.
- Email reminders respect email presence only; **SMS keeps the TCPA opt-out check** unchanged. Every attendee email carries an unsubscribe-free, transactional framing (appointment-related), consistent with existing transactional sends.

## Risks

- Migration touches `appointments` (production CRM data) → additive nullable/`server_default` column only; back up per CLAUDE.md step 3.
- Always-on pre-validation can now *reject* bookings the text agent used to accept. Intended, but it means the agent prompt must handle the "slot taken, here are alternatives" branch — covered in step 6.
- New agent columns change public schemas → `make ci.codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` in the same commit.

## Verification

- `make ci.backend`, `make ci.frontend`, `make ci.codegen`, `make ci.migrations`.
- New pytest suites (below) for validation, attendee email dispatch, and channel-aware reminder dedupe.
- Eyes: `.ezcoder/eyes/mail.sh clear` → trigger a booking → `mail.sh count` / `mail.sh latest` to confirm the attendee invite email and its `.ics`; `.ezcoder/eyes/logs.sh --service backend --grep "reminder_worker|ERROR|Traceback"` after worker changes; `.ezcoder/eyes/http.sh` against `/api/v1/agents/{id}` after the schema change.

## Steps

1. Add `backend/app/services/appointments/booking_validation.py` with `validate_booking_request(...) -> BookingValidation` covering: RFC-shaped email, timezone-aware future datetime, duration within an allowed range, required `service_type`, and (for on-site service types) a non-empty contact address via `booking_finalizer.format_contact_address`.
2. Wire that validation into `BaseToolExecutor.execute_book_appointment` in `backend/app/services/ai/base_tool_executor.py` before `booking_service.book_appointment`, returning the structured failure through `format_booking_failure` so each channel renders it.
3. Remove the `pre_validate` class flag from `base_tool_executor.py` and `tool_executor.py:139`, and default `BookingService.book_appointment(pre_validate=True)` in `backend/app/services/calendar/booking.py` so the text path re-checks availability and returns `alternative_slots`.
4. Add an alembic migration adding `appointments.reminders_sent_email INTEGER[] NOT NULL DEFAULT '{}'` and agent columns `reminder_channels TEXT[] NOT NULL DEFAULT '{sms}'` and `confirmation_email_enabled BOOLEAN NOT NULL DEFAULT true`; mirror them in `backend/app/models/appointment.py` and `backend/app/models/agent.py`.
5. Add `send_appointment_confirmation_to_attendee(...)` to `backend/app/services/email.py` (customer-facing copy, `.ics` attachment built with `CalendarInvite`/`render_invite`, idempotency via `derive_outbound_key("attendee_booking_invite_email", appointment.id)`).
6. Call it from `deliver_booking_notifications` in `backend/app/services/appointments/booking_finalizer.py`, gated on `agent.confirmation_email_enabled` and a present `contact.email`, guarded so a failure cannot affect the SMS or rep invite.
7. Extend `backend/app/workers/reminder_worker.py` to dispatch per channel from `agent.reminder_channels`: keep the SMS path, add an email reminder send deduped against `reminders_sent_email`, and read the agentless offset default from `workspace.settings["reminder_defaults"]["offsets"]` falling back to `[60]`.
8. Add `send_appointment_reminder_email(...)` rendering to `backend/app/services/calendar/reminder_service.py` reusing `render_reminder_body`'s placeholder set so SMS and email quote the same workspace-local time.
9. Update `backend/app/schemas/agent.py` (Create/Update/Read) with `reminder_channels` and `confirmation_email_enabled`, including a validator rejecting unknown channel values.
10. Update the AI prompts in `backend/app/services/ai/text_prompt_builder.py` and `backend/app/services/ai/prompt_builder.py` to instruct the model to confirm only after `book_appointment` returns success and to offer `alternative_slots` on failure.
11. Add backend tests: `backend/tests/services/appointments/test_booking_validation.py`, an attendee-email case in the booking-finalizer tests, and channel-dedupe cases in the reminder-worker tests.
12. Extend `frontend/src/components/agents/tabs/advanced/reminders-section.tsx` with reminder-channel checkboxes (SMS / Email) and a "Send confirmation email with calendar invite" switch.
13. Wire the new fields through `frontend/src/lib/agents/agent-form.ts` (schema, defaults, dirty-field list, to-payload, from-agent), `frontend/src/types/agent.ts`, and `frontend/src/lib/api/agents.ts`.
14. Run `make ci.codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
15. Run `make migrate` locally, then verify with the eyes probes (`mail.sh clear`/`count`/`latest` for the attendee invite, `http.sh` on `/api/v1/agents/{id}`, `logs.sh --grep reminder_worker`).
16. Run `make ci.all` and fix any failures.
