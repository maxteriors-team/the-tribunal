# Current AI Google Meet flow — read-only investigation

## Objective

Document how the existing AI decides whether an appointment is a Google Meet, how it chooses the host, how Google creates and returns the Meet link, and how that link reaches the attendee. This plan is **read-only**: no Send Meet feature, UI/API work, migration, consent-policy change, worktree, or production change is in scope.

## Verified flow

### 1. The text AI requires an explicit call format

`backend/app/services/ai/voice_tools.py::get_text_booking_tools` defines `book_appointment.call_type` as a required enum with exactly `phone_call` and `video_call`. Its tool description tells the model to ask the attendee explicitly and not infer the format.

`backend/app/services/ai/website_lead_qualification.py::text_qualification_instructions` reinforces the same rule for website leads: ask whether they prefer phone or video, then pass that answer as `call_type`. The AI does not derive Google Meet from date, service name, email domain, or another heuristic; the decisive value is `call_type="video_call"`.

`backend/app/services/ai/text_tool_executor.py::TextToolExecutor._execute_book_appointment` stores that value as `_pending_call_type`, and `TextToolExecutor._finalize_booking_with_context` forwards it to the shared booking finalizer as `service_type`.

Existing guards:

- `backend/tests/services/ai/test_website_lead_qualification.py::test_text_booking_requires_explicit_call_type` verifies the required enum.
- `backend/tests/services/ai/test_text_tool_executor.py` verifies `video_call` is forwarded to `finalize_booking`.

### 2. The selected AI agent determines the host

`backend/app/services/ai/base_tool_executor.py::BaseToolExecutor._resolve_assigned_staff` delegates to `backend/app/services/calendar/staff_assignment.py::resolve_staff_for_booking`. That function loads active, login-backed `BookableStaff` rows from the selected AI agent’s pool plus workspace-wide Team rows and applies the agent’s assignment strategy: single/default, round robin, or skill based.

The availability check then calls `backend/app/services/google_calendar.py::is_time_available` for the chosen staff user. A connected per-user Google Calendar is required; there is no workspace-wide Google Meet account and Cal.com is not used in this flow.

Verified limitation: `resolve_staff_for_booking` filters for `BookableStaff.user_id`, but not for an existing `GoogleCalendarConnection`. The later availability check catches a missing connection, so a disconnected rep can be selected before the flow reports that no connected calendar is available.

### 3. The CRM appointment is committed before Google is called

`backend/app/services/appointments/booking_finalizer.py::finalize_booking` opens the shared booking transaction. Its internal finalization path creates an `Appointment` with the chosen `service_type`, assigned staff, and `sync_status="pending"`, applies the live contact/slot uniqueness guard, commits the CRM row, and then launches `deliver_booking_notifications` with `spawn_background_task`.

That ordering makes the CRM appointment durable before any external side effect. It also means the AI receives the appointment result before the Google Meet request has completed.

### 4. Google Calendar creates the Meet link

`backend/app/services/appointments/booking_finalizer.py::deliver_booking_notifications` loads the committed appointment and calls `_sync_google_calendar`. `_sync_google_calendar` calls `backend/app/services/google_calendar.py::create_event` with:

- `conference=appointment.service_type == "video_call"`;
- the assigned staff user ID and selected calendar;
- the attendee email/name;
- a deterministic event ID (`tribunalappointment{appointment.id}`);
- the appointment time, duration, workspace timezone, summary, and description.

When `conference=True`, `create_event` sends Google Calendar `conferenceData.createRequest` with `conferenceSolutionKey.type="hangoutsMeet"`, `conferenceDataVersion=1`, and `sendUpdates="all"`. It reads the returned `hangoutLink` (or Meet entry point), and `_sync_google_calendar` persists it to `Appointment.meeting_url` together with the Google event ID/URL and `sync_status="synced"`.

Existing guards in `backend/tests/services/appointments/test_booking_finalizer.py` verify video-call Meet persistence, no-link behavior, and provider-failure state.

### 5. How the attendee receives the link

After calendar sync, the same notification flow uses the resulting `meeting_url` in three places:

1. Google Calendar receives the attendee email and `sendUpdates="all"`, so Google sends the calendar invitation.
2. `backend/app/services/email.py::send_appointment_confirmation_to_attendee` sends a separate confirmation email with an ICS attachment and a “Join Google Meet” hyperlink when the URL exists.
3. `backend/app/services/appointments/lifecycle_sms.py::build_confirmation_body` includes the Meet URL in lifecycle SMS when `send_customer_sms=True`.

Important channel distinction: `TextToolExecutor._finalize_booking_with_context` passes `send_customer_sms=False` because the live AI text reply is treated as the confirmation. Since Google sync happens afterward in the background, that immediate AI reply normally cannot contain the newly created Meet URL. The attendee still receives it through Google’s invite and the separate confirmation email. Other booking paths that request lifecycle SMS can receive the URL by SMS after sync.

### 6. Automated reminders and failure behavior

`backend/app/workers/reminder_worker.py::AppointmentReminderWorker` uses the appointment’s AI agent reminder configuration. `backend/app/models/agent.py` defaults to 1,440, 120, and 30 minutes before the appointment, with SMS as the default channel.

Verified limitation: the current reminder renderer formats business name, attendee name, and appointment time, but does not inject `Appointment.meeting_url`; attendees must return to the original Google invite/email for the link.

If no staff/login is assigned, `_sync_google_calendar` records `sync_status="not_connected"`. If Google rejects the request, it records `sync_status="failed"` and `sync_error`. The committed CRM appointment remains in place, and confirmation copy falls back to saying the team will follow up with the video link rather than inventing one.

## Boundaries

- Cal.com booking/webhooks are separate integrations and do not create this Google Meet.
- The standard manual appointment-create route writes a CRM row but does not run this AI booking finalizer.
- `backend/app/services/ai/voice_tools.py::get_booking_tools` (the standard voice tool set) does not currently expose the text tool’s required `call_type`; this investigation does not change voice behavior.
- No code, schema, configuration, consent policy, UI, or deployment will be modified as part of this investigation.

## Deliverable

Return a concise, source-linked explanation of the six stages above, clearly separating verified behavior from the three observed limitations: disconnected staff can be selected before connection validation, live text confirmations generally lack the newly generated link, and automated reminders omit the link.

## Steps

1. Re-read the exact tool schemas and prompt instructions that establish `call_type` as the decision input, recording the file/function references and text-versus-voice distinction.
2. Trace staff assignment and Google availability checks from `BaseToolExecutor` through `resolve_staff_for_booking` and `is_time_available`, documenting how the host/calendar is chosen and where connection validation occurs.
3. Trace `finalize_booking`, `deliver_booking_notifications`, `_sync_google_calendar`, and `google_calendar.create_event`, documenting transaction order, Google conference parameters, persisted fields, and provider-failure states.
4. Trace attendee email/SMS and reminder rendering, documenting which channels receive `meeting_url` and which do not.
5. Run the existing focused AI-tool and booking-finalizer tests named above as non-mutating verification, then provide the read-only findings without proposing or implementing product changes.