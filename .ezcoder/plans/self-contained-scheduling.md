# Self-Contained Scheduling — Remove External Calendar Sync

## Goal
Make the CRM the **single source of truth** for appointments. Scheduling reads/writes
only the local `appointments` table. Remove all integration with personal/external
calendars (Cal.com **and** the in-progress Google Calendar work): no outbound sync, no
inbound webhooks, no OAuth, no per-agent event-type binding, no sync status in the UI.

AI voice/SMS booking and the CRM calendar keep working — availability is computed
locally from each agent/workspace `schedule_config` minus existing CRM appointments.

## Current state (what "external calendar sync" is today)

Two integrations are entangled:

- **Cal.com** (committed baseline): global API key, `BookingService` → `CalComCalendarProvider`,
  inbound webhooks (`/webhooks/calcom`) that create/reschedule/cancel appointments,
  manual-create `_try_calcom_sync`, `/appointments/{id}/sync` retry endpoint, agent
  `calcom_event_type_id`, `bookable_staff.calcom_event_type_id`, appointment `calcom_*`
  columns + `sync_status`.
- **Google Calendar** (ALL UNTRACKED / uncommitted): `services/calendar/google/*`,
  `factory.py`, `provider.py`, `models/calendar_connection.py`,
  `api/v1/integrations/google_calendar.py`, `api/webhooks/google_calendar.py`, three
  `google_*` workers, migration `c1cb7455d5cc_add_google_calendar_provider_.py`, frontend
  `google-calendar-card.tsx` + `schedule-config-section.tsx`. It also **modified** many
  committed files (agent/appointment/bookable_staff models, booking/calcom/staff_assignment
  services, base_tool_executor, router, main, workers registry).

Key reusable asset: `services/calendar/google/availability.py::compute_available_slots`
is already a **provider-neutral local slot engine** (weekly hours + busy intervals →
`{date,time,iso}` slots). We keep this logic (relocated) and feed it CRM appointments as
the busy set — that is the whole self-contained availability engine.

## Design: `LocalCalendarProvider`

New `services/calendar/local.py` implementing the existing `CalendarProvider` protocol:
- `get_availability(start,end,tz)`: load the workspace's `scheduled` appointments in range
  as busy intervals, call `compute_available_slots(schedule, ..., busy_intervals=...)`.
- `create_booking(...)`: **no external call**. Return a `ProviderBooking(provider="local",
  external_event_id=<uuid>)`. The appointment row is persisted by the existing
  `post_booking_success` hooks (voice/text executors) exactly as today.
- `cancel_booking` / `reschedule_booking`: local no-ops returning success (DB row is the
  record; status changes happen through `AppointmentService`).
- `reschedule_link(...)`: return `""` → reminders fall back to "reply to reschedule".
- `close()`: no-op.

`get_calendar_provider(...)` becomes: always return `LocalCalendarProvider` bound to the
resolved `schedule_config`. `BookingService` keeps its shape; the provider it wraps changes.

## Decisions required before implementation (BLOCKING)

1. **Uncommitted Google Calendar work** — this refactor deletes it. It is untracked work
   (possibly another dev's in-flight branch). Per "preserve user work", I will not delete
   it without explicit OK. Options: (a) delete the Google files as part of this refactor;
   (b) `git stash -u` / branch it first, then delete on main. **Need confirmation.**
2. **Existing working-tree pile** — mockups, wizard labels, and the calendar month view are
   uncommitted alongside the Google work. Recommend committing/among-separating those FIRST
   so this refactor lands as a reviewable diff, not on top of 40 mixed files.
3. **DB columns** — keep the `calcom_*` / `sync_status` / `external_event_id` /
   `calendar_provider` columns in place for now (stop using them; default new rows to
   `calendar_provider="local"`). Dropping columns is a **separate, later** migration that
   needs a prod backup (`make db.backup.prod`). This de-risks the production `appointments`
   table. **Confirm: defer column drops (recommended) vs drop now.**

## Risks
- Production booking path: AI agents book live. The Local provider must produce correct
  slots or agents can't book. Mitigate with unit tests on `LocalCalendarProvider` +
  existing `compute_available_slots` tests, and manual `.ezcoder/eyes/http.sh` checks on
  check-availability/book flows.
- Removing `/webhooks/calcom` means any still-configured Cal.com account stops flowing in.
  Intended, but confirm no live Cal.com automation depends on it before deploy.
- Schema/OpenAPI changes require `make codegen` and committing both artifacts.
- `calcom_booking_uid` has a UNIQUE index; leaving the column is fine (stays null for new
  local rows).

## Verification
- `make ci.backend` (ruff/mypy/pytest), `make ci.frontend`, `make ci.codegen`.
- New tests: `LocalCalendarProvider` availability (busy = CRM appointments), booking returns
  local ids; `get_calendar_provider` returns local. Update/remove Cal.com + Google tests.
- Runtime: start backend, hit check-availability + book via a text agent path or the
  `/appointments` create API with `.ezcoder/eyes/http.sh`; confirm 2xx and a row with
  `calendar_provider="local"`, no sync fields set. Screenshot `/calendar` still renders.

## Out of scope
- Dropping DB columns (deferred to a follow-up migration + prod backup).
- Any hosted self-service reschedule page (reminders use "reply to reschedule").

## Steps
1. Get confirmation on the three BLOCKING decisions (Google-work deletion method, commit
   existing pile first, defer column drops) before editing.
2. Add `backend/app/services/calendar/local.py` with `LocalCalendarProvider` implementing the
   `CalendarProvider` protocol, backed by a relocated copy of `compute_available_slots` and a
   query of in-range `scheduled` CRM appointments as busy intervals.
3. Move the slot engine out of `services/calendar/google/availability.py` into a
   provider-neutral module (e.g. `services/calendar/availability.py`); keep `ScheduleConfig` +
   `resolve_schedule_config` + `compute_available_slots`.
4. Rewrite `services/calendar/factory.py` so `get_calendar_provider(...)` always returns a
   `LocalCalendarProvider` (drop Google/Cal.com selection); make `reschedule_link_for_agent`
   return `""`.
5. Simplify `services/calendar/booking.py` to wrap the injected provider only (drop the
   Cal.com default-construction branch and Cal.com-specific docstrings).
6. Update `services/ai/base_tool_executor.py` `_create_booking_service` to build the local
   provider via the factory (drop `event_type_id`/`calcom_api_key` plumbing and the
   `_workspace_has_google` branching in availability/book paths).
7. Update `services/appointments/appointment_service.py`: remove `_try_calcom_sync` and the
   `sync_to_calcom` method; `create_appointment` persists with `calendar_provider="local"`
   and no sync fields.
8. Remove the `/appointments/{id}/sync` route from `api/v1/appointments.py` (and its schema
   usage); keep list/create/update/delete/stats/send-reminder.
9. Remove Cal.com inbound webhooks: delete `api/webhooks/calcom*.py`, drop the
   `calcom_webhook_router` include + `/webhooks/calcom` registration and the
   `calcom_api_key` startup warning in `app/main.py`.
10. Remove the Google Calendar backend surface: delete `services/calendar/google/`,
    `models/calendar_connection.py`, `api/v1/integrations/google_calendar.py`,
    `api/webhooks/google_calendar.py`, and the three `google_*` workers; drop their
    registrations in `workers/__init__.py`, `api/v1/router.py`, and any `main.py`/config
    wiring (per the confirmed deletion method in Step 1). **Keep** `services/calendar/provider.py`
    (the `CalendarProvider` protocol + `ProviderSlot`/`ProviderBooking`) — `LocalCalendarProvider`
    implements it; also delete `services/calendar/calcom.py` since the Cal.com provider is gone.
11. Strip external-calendar config: remove `calcom_api_key`/`calcom_webhook_secret` and the
    Google OAuth/worker settings from `core/config.py`, the `calcom` circuit breaker, Cal.com
    webhook metrics/security helpers, and the `.env.example` entries.
12. Update models: default `Appointment.calendar_provider` to `"local"`; stop populating
    `calcom_*`/`sync_*`; remove Cal.com/Google references from `agent.py` and
    `bookable_staff.py` docstrings and any now-unused fields kept only for sync. (No column
    drops — deferred.)
13. Update the reminder/nudge workers to drop the `reschedule_link_for_agent` calls (link is
    always `""` now) so `{reschedule_link}` renders empty and the fallback copy is used.
14. Frontend: delete the `SyncButton` + sync-status badges from
    `components/calendar/appointment-actions.tsx` and `appointment-details-dialog.tsx`, remove
    "pending sync" chips in `calendar-page.tsx`, drop the `syncAppointment` client in
    `lib/api/appointments.ts`, and remove `sync_status`/`calcom_*` from `types/appointment.ts`.
15. Frontend settings: remove the Cal.com integration card + the "Cal.com Settings" link on
    `/calendar`, delete `google-calendar-card.tsx`, and remove/relabel the
    "(Google Calendar)" scheduling copy in `schedule-config-section.tsx` to generic
    "Booking schedule".
16. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
17. Update tests: delete Cal.com webhook/handler + Google calendar suites, add
    `LocalCalendarProvider` unit tests (availability from CRM busy set; booking returns local
    ids; factory returns local), and fix any appointment/booking tests that asserted sync.
18. Run `make ci.backend`, `make ci.frontend`, `make ci.codegen`; then runtime-verify with
    `.ezcoder/eyes/http.sh` (check-availability + create appointment → `calendar_provider="local"`,
    no sync fields) and a `/calendar` screenshot.
