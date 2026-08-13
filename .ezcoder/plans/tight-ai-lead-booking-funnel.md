# Tight AI Lead-to-Booking Funnel

## Objective

Turn every **brand-new public form lead** into one traceable CRM journey:

`Form submitted → New lead → First outreach sent → AI qualifies → Qualified opportunity → Phone/video call booked → Follow-up stops`

The funnel must reuse the existing public lead-source endpoint, consent/opt-out gates, AI text agent, workflow engine, self-contained scheduler, and assigned-rep Google Calendar sync. It must not restore the Cal.com integration currently being removed.

## Product Decisions

- **One first-outreach owner:** a `lead_created` automation sends the initial SMS. The lead source itself stays `collect`, preventing `lead_form._action_auto_text()` and an automation from double-texting the same submission.
- **New leads only:** the existing phone-hash dedupe and `is_new_lead` guard remain authoritative. A returning contact submission updates attribution/contact fields but does not restart the funnel or send another welcome text.
- **Consent is enforced:** first outreach and all automated nurture SMS set `require_consent=true` and continue through `OutboundDeliveryService`; STOP/global opt-out and the `no-automation` contact tag remain hard stops. The public form must send `sms_consent: true` only when its optional, unchecked checkbox is actually selected.
- **AI owns the live conversation after first contact:** the welcome SMS creates/updates an SMS conversation assigned to the selected AI agent with `ai_enabled=true`; inbound replies use the existing text agent. AI gathers the configured checklist, persists evidence and score, and unlocks booking only after `mark_lead_qualified` succeeds.
- **Booking is the conversion target:** a qualified lead may choose a `phone_call` or `video_call`. A video call creates Google Meet on the assigned rep’s connected Google Calendar; a phone call clearly records the lead’s phone as the meeting method and does not claim a video link.
- **No false bookings:** AI booking must be configured to auto-approve for this funnel. `ask` leaves a pending action and is not “booked”; `never` blocks it. Funnel readiness must expose this requirement rather than reporting ready from tools alone.
- **CRM organization follows sales reality:** raw form leads remain in Contacts as `new`; a provider-accepted first outreach moves them to `contacted`; successful qualification sets `qualified` and opens one attribution-snapshotted opportunity in the default pipeline’s `Qualified` stage; booking moves that opportunity to `Visit/Demo Scheduled`.
- **Booked means terminal for acquisition nurture:** successful booking cancels scheduled acquisition-funnel executions before another delayed SMS can run. Appointment reminders remain separate transactional lifecycle messages.
- **Provider failure is visible:** the CRM appointment remains authoritative if Google is unavailable, but video booking records `sync_status=failed/not_connected` and must not tell the customer a Meet link exists. A successful Google sync persists the Meet URL and includes it in customer/rep confirmations and CRM appointment details.

## Existing Paths to Reuse

- `backend/app/api/v1/lead_form.py` already rate-limits, origin-checks, honeypot-checks, phone-deduplicates, captures attribution, persists explicit SMS consent, tags the contact, emits `lead_created` only for a new contact, and notifies workspace users.
- `backend/app/services/automations/` plus `backend/app/workers/automation_worker.py` already provide event-triggered workflows, waits, branches using shared contact filters, outbound compliance, idempotent SMS, and resumable executions.
- `backend/app/services/ai/website_lead_qualification.py`, `text_response_generator.py`, and `text_tool_executor.py` already gate booking tools behind evidence-based qualification for website leads.
- `backend/app/services/calendar/booking.py` and `backend/app/services/appointments/booking_finalizer.py` already validate local availability, prevent duplicate live bookings, persist appointments, and fan out lifecycle notifications.
- `backend/app/services/google_calendar.py` already requests Google Meet with `conferenceData`, returns `meet_link`, and can create the event on the assigned rep’s calendar.
- `backend/app/services/opportunities/lead_opportunity.py` already creates a deduped open opportunity with first/latest-touch attribution, behind the workspace auto-pipeline switch.
- `scripts/ops/setup_lead_automation.py` already creates an idempotent source-scoped `lead_created` workflow and is the right operational harness for the canonical Maxteriors form funnel.

## Backend Changes

### 1. First outreach as a real CRM transition

Update `backend/app/workers/automation_worker.py` so `_action_send_sms()` returns its `OutboundDeliveryResult` to `_run_actions()`. After a provider-accepted `lead_created` SMS:

- set the contact to `contacted` only when it was `new`;
- leave `qualified`, `converted`, and `lost` untouched;
- stamp no state when delivery was blocked, skipped, or failed;
- ensure the Telnyx-created conversation is assigned to `config.agent_id` and has `ai_enabled=true`, matching the existing lead-source auto-text behavior.

Add a typed `agent_id` option to the `send_sms` action config in `backend/app/schemas/automation.py`; pass it through the existing JSON action configuration without a migration.

### 2. Durable qualification transition

Extract a small idempotent CRM transition service, e.g. `backend/app/services/leads/funnel_transitions.py`, for state changes shared by AI and booking paths:

- `mark_contact_contacted(...)`;
- `mark_contact_qualified(...)` and call `open_lead_opportunity(..., source="website_lead_qualification")`;
- `mark_contact_booked(...)`, setting `last_appointment_status="scheduled"`, opening the opportunity if needed, then moving the contact’s open opportunity to the target scheduled stage through `OpportunityService.move_stage()` so stage activity and automation events remain canonical.

Call the qualification helper from `TextToolExecutor._execute_mark_lead_qualified()` after score/evidence validation. Keep the current qualification payload and redacted logging. Repeat tool calls must not duplicate opportunities or stage activity.

### 3. Canonical appointment-booked event and terminal cleanup

Add `lead_qualified` and `appointment_booked` to:

- `backend/app/services/automations/events.py` trigger constants;
- `backend/app/schemas/automation.py` trigger literals;
- `backend/app/workers/automation_worker.py` event matching/dispatch where special matching is needed;
- frontend trigger labels in `frontend/src/components/automations/automations-page.tsx`.

Emit `lead_qualified` from the qualification transition and `appointment_booked` from the successful appointment finalization transaction. The booked event payload includes `appointment_id`, `service_type`, `scheduled_at`, `bookable_staff_id`, and sync state available at commit time.

Add a funnel identifier to automation metadata/config and cancel only scheduled/running executions for that same acquisition funnel/contact when booking succeeds. Also add a resume guard in `_resume_execution()` that completes a parked acquisition execution without sending if the contact now has a live scheduled appointment. Do not globally cancel job, invoice, reminder, or other unrelated automations.

### 4. Phone vs video booking contract

Extend the text booking tool in `backend/app/services/ai/voice_tools.py` with a required `call_type` enum (`phone_call`, `video_call`) for the website-lead booking path. Thread it through:

- `backend/app/services/ai/base_tool_executor.py`;
- `backend/app/services/ai/text_tool_executor.py`;
- `backend/app/services/calendar/booking.py` as the appointment `service_type`.

Update `build_qualification_instructions()` so AI asks which format the lead wants before booking and never invents a Meet link.

In `backend/app/services/appointments/booking_finalizer.py`:

- request `conference=True` only for `video_call`;
- persist the returned `GoogleEvent.meet_link` in a new nullable `appointments.meeting_url` field;
- set phone-call invite location/copy to the lead’s phone number;
- generate email/ICS/rep copy after calendar sync so a successful video call includes the actual Meet URL;
- keep the CRM booking if Google fails, expose the sync failure, and send copy that promises a follow-up rather than a nonexistent link.

Add the model/schema migration under `backend/alembic/versions/`, expose `meeting_url` in `backend/app/schemas/appointment.py`, regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, and extend `frontend/src/types/appointment.ts`.

### 5. Funnel provisioning and readiness

Refactor `scripts/ops/setup_lead_automation.py` from “tag + one SMS” into an idempotent source-scoped acquisition workflow:

1. apply the source tags;
2. send the consent-gated personalized first SMS with the chosen AI `agent_id`;
3. wait a short, configured interval;
4. branch out when `last_appointment_status=scheduled`, opted out, lost, or `no-automation` applies;
5. send a second concise booking-focused follow-up;
6. wait and repeat for a bounded sequence, checking terminal state before each send.

The script must keep dry-run/production confirmation, update in place, and validate prerequisites before applying:

- target lead source exists and is enabled;
- lead source action is `collect` (or the script changes it deliberately to avoid double send);
- agent has website-lead qualification and booking tools enabled;
- qualification questions/minimum score/booking label are configured;
- `book_appointment` action policy is `auto`;
- selected agent resolves to active bookable staff linked to the intended operator;
- that user has a connected Google Calendar;
- workspace auto-pipeline is enabled and contains `Qualified` and `Visit/Demo Scheduled` stages;
- the public form integration sends explicit SMS consent.

Update `frontend/src/components/settings/lead-sources-settings-tab.tsx` readiness copy/logic to say **call-booking ready**, not “Zoom ready,” and report the actual blockers: AI qualification, auto-approved booking, bookable rep, and Google Calendar for video.

## Public Form and Compliance Controls

Update `docs/wordpress-quote-form.html` so the checked checkbox maps to `sms_consent: true`; the current snippet records consent only in free-form notes, which does not activate the server-enforced consent field. Keep the box optional and unchecked by default, with message frequency, rates, STOP/HELP, privacy-policy, and terms links visible beside it.

Do not weaken `require_consent`, global opt-out, quiet-hours, rate limits, origin allowlists, honeypot, or `no-automation` suppression. Update `COMPLIANCE.md` with this funnel’s evidence and residual operational prerequisites. This is engineering guidance, not legal advice.

## Operator Visibility

Update `frontend/src/components/calendar/appointment-details-dialog.tsx` and `frontend/src/components/contacts/contact-sidebar/contact-appointments.tsx` to show:

- Phone call vs video call;
- **Join Google Meet** only when `meeting_url` exists;
- calendar sync failure/not-connected state with an operator action to connect/retry rather than silently claiming success.

Use existing badges/buttons/layout; this is a narrow extension, not a redesign.

## Risks and Safeguards

- **Duplicate outreach:** prevent by making the source action `collect`, keeping `lead_created` new-contact-only, and retaining outbound idempotency keys.
- **Unconsented texting:** require explicit `sms_consent=true`; every funnel SMS uses `require_consent=true`; blocked sends do not advance status.
- **Stale nurture after booking:** check terminal state both immediately before each outbound action and when resuming waits; cancel only the named acquisition funnel.
- **False calendar promise:** persist/show Meet only from Google’s returned `hangoutLink`; expose sync failures and never fabricate a URL.
- **Wrong operator calendar:** readiness validates agent → bookable staff → user → Google connection; booking preserves assigned staff.
- **Duplicate deals/bookings:** retain open-opportunity dedupe and the partial unique live-contact-slot appointment index; transition helpers are idempotent.
- **User-work collision:** implement against the current branch after the active Google Calendar/self-contained scheduler changes are stable; do not restore deleted Cal.com files.

## Verification

### Targeted automated checks

- `backend/tests/api/test_lead_form_tagging_e2e.py`: new vs returning lead, consent persistence, one `lead_created` event, no eager opportunity before qualification.
- `backend/tests/workers/test_automation_event_triggers.py` and `test_automation_resume.py`: provider-accepted first contact, blocked-send behavior, agent conversation handoff, terminal branch, and booked resume cancellation.
- `backend/tests/services/ai/test_text_tool_executor.py` and `test_website_lead_qualification.py`: evidence gate, one qualified transition/opportunity, phone/video selection, booking-policy readiness, and no fabricated link.
- `backend/tests/services/appointments/test_booking_finalizer.py` plus Google Calendar tests: scheduled contact state, booked event, Meet persistence, phone-call no-conference path, provider failure copy, dedupe, and cancellation of stale funnel runs.
- `backend/tests/scripts/test_setup_lead_automation_config.py`: idempotent workflow graph, source `collect`, consent on every SMS, bounded waits/branches, and prerequisite failures.
- Frontend component tests for readiness blockers and appointment Meet/sync rendering.

### Runtime proof

1. Run targeted backend/frontend tests, then `make ci.backend`, `make ci.frontend`, `make ci.codegen`, and `make ci.migrations` because this changes models, migration, API schemas, workers, and UI.
2. Start the local stack; submit `docs/wordpress-quote-form.html`’s representative payload through `.ezcoder/eyes/http.sh` with consent on and off. Confirm contact, attribution, event, and 2xx response shape.
3. Inspect worker logs with `.ezcoder/eyes/logs.sh` to prove exactly one first SMS, no send without consent, AI conversation ownership, and no delayed send after booking.
4. Exercise AI qualification through a representative SMS conversation, verify questions/evidence before booking, then book one phone call and one video call. Confirm CRM appointment, opportunity stage, contact status, Google event/Meet URL when a local test Google connection is available, and explicit sync failure otherwise.
5. Clear/read the test inbox with `.ezcoder/eyes/mail.sh` and verify confirmation recipient, call type, time, phone/Meet details, and no duplicate confirmation.

## Steps

1. Add idempotent lead-funnel transition helpers for contacted, qualified/opportunity-opened, and booked/stage-moved states, with focused backend tests.
2. Make automation SMS return delivery outcomes, assign the configured AI agent/conversation, and advance only provider-accepted new leads to `contacted`.
3. Emit and support `lead_qualified` and `appointment_booked` automation events across backend schemas, worker matching, and frontend trigger labels.
4. Wire AI qualification to the qualified CRM transition and deduped opportunity creation.
5. Add `phone_call`/`video_call` to the AI booking contract and persist the selected type through local appointment creation.
6. Add `appointments.meeting_url`, capture Google Meet only for video calls, correct confirmation/ICS copy, regenerate API artifacts, and render call details/sync state in the CRM.
7. Stop only the canonical acquisition funnel’s active or parked executions after booking, and add the pre-send/resume terminal guards.
8. Refactor `scripts/ops/setup_lead_automation.py` into the bounded consent-aware AI booking workflow with prerequisite validation and update-in-place behavior.
9. Fix `docs/wordpress-quote-form.html` to submit structured SMS consent and update lead-source readiness copy/tests plus `COMPLIANCE.md`.
10. Run targeted tests, codegen/migration/full checks, then prove form → outreach → AI qualification → phone/video booking → stopped nurture with the local HTTP/log/mail probes.