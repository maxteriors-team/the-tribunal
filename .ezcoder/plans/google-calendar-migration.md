# Migrate scheduling from Cal.com → Google Calendar

## TL;DR
Replace Cal.com with Google Calendar as the booking backend, **behind the existing
`BookingService` seam**, so AI voice/SMS agents keep auto‑booking from live
availability. This is a multi‑phase migration touching ~60 files. The safe path is a
**provider abstraction** (ship Google alongside Cal.com, migrate, then delete Cal.com)
— not a hard rip‑and‑replace against live prod data.

## ⚠️ Decision needed before coding
1. **Keep AI auto‑booking?** Assumed **YES** (it's the product's core). The plan builds a
   Google availability engine to preserve it. If agents should only *read/create* events
   and humans do the booking, the scope shrinks a lot — say so and I'll re‑cut.
2. **Per‑workspace Google accounts?** Cal.com today uses a **single global API key**
   (`settings.calcom_api_key`). Google Calendar uses **OAuth2 per workspace** (each
   workspace connects its own Google account). This plan assumes per‑workspace OAuth
   (correct multi‑tenant model). Confirm.

## �zBlocking prerequisites (you must provide — external, I can't create these)
- **Google Cloud project** with **Google Calendar API** enabled.
- **OAuth 2.0 Client** (Web application): client ID + client secret, and an authorized
  redirect URI (e.g. `https://<backend>/api/v1/integrations/google-calendar/callback`
  and a localhost variant for dev).
- **OAuth consent screen** configured (scopes below; add test users until verified).
- Decision on scope: recommend `https://www.googleapis.com/auth/calendar.events`
  (create/read/update our own events + free/busy) — least privilege that still books.
- These become new secrets: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
  `GOOGLE_OAUTH_REDIRECT_URI`.

## Why this is non‑trivial (the core gap)
Cal.com is a **scheduling engine**; Google Calendar is **events + free/busy**. Google
gives us none of the following natively — we build them:

| Cal.com provides today | Google equivalent |
|---|---|
| `get_availability()` → bookable slots (working hours, duration, buffers) | ❌ only `freebusy.query` (raw busy blocks) → we build the slot engine |
| `create_booking()` → event + confirmation + Meet link | `events.insert` (+ `conferenceData` for Meet); double‑book guard is on us |
| Signed webhooks: BOOKING_CREATED/RESCHEDULED/CANCELLED/MEETING_ENDED | `events.watch` push channels (expire ≤7d, need renewal worker) + sync tokens; **no MEETING_ENDED** |
| `MEETING_ENDED` → drives NO_SHOW / COMPLETED | ❌ none → time‑based status worker |
| Hosted reschedule page (`generate_booking_url`) | ❌ none → our own reschedule link/flow |
| One API key | OAuth2 + refresh tokens per workspace |

## Current integration seams (verified in‑repo)
- **`app/services/calendar/booking.py`** — `BookingService` (channel‑agnostic dataclasses:
  `AvailableSlot`, `AvailabilityResult`, `BookingResult`; methods `check_availability`,
  `book_appointment`, `close`). **This is the clean seam.**
- **`app/services/calendar/calcom.py`** — `CalComService` HTTP client:
  `get_availability`, `create_booking`, `get_booking`, `cancel_booking`,
  `generate_booking_url`, `_request_with_retry`.
- **`app/services/ai/base_tool_executor.py`** — only builder of `BookingService`
  (`_create_booking_service`, `_resolve_event_type_id`, `_validate_calcom_config`).
  Voice + text executors inherit this.
- **`app/services/calendar/staff_assignment.py`** — round‑robin / skill routing keyed on
  `bookable_staff.calcom_event_type_id`.
- **`app/api/webhooks/calcom*.py`** (`calcom.py`, `calcom_handlers.py`, `calcom_events.py`,
  `calcom_parser.py`) — inbound state machine driving `AppointmentStatus`.
- **Workers**: `reminder_worker.py`, `never_booked_worker.py`,
  `noshow_reengagement_worker.py` build reschedule/booking links via
  `generate_booking_url`; `__init__.py` declares a `calcom` capability dependency.
- **Data model**: `appointment.calcom_booking_uid/id/event_type_id`,
  `agent.calcom_event_type_id`, `bookable_staff.calcom_event_type_id`.
  `AppointmentStatus = {scheduled, completed, cancelled, no_show}`.
- **Config**: global `settings.calcom_api_key`, `settings.calcom_webhook_secret`.
- **Credentials**: per‑workspace `WorkspaceIntegration` (encrypted via
  `app/core/encryption.encrypt_json`) already exists — reuse it for Google OAuth tokens.

## Design: provider abstraction (recommended)
Introduce a `CalendarProvider` protocol so booking code is provider‑agnostic and we can
run Google + Cal.com side‑by‑side during migration, then delete Cal.com.

- `app/services/calendar/provider.py` — `CalendarProvider` Protocol:
  `get_availability(...) -> list[slot]`, `create_booking(...) -> {external_event_id,...}`,
  `cancel_booking(...)`, `reschedule_booking(...)`, `reschedule_link(...)`.
- `CalComService` is adapted to implement it (thin wrapper, keeps current behavior).
- New `app/services/calendar/google/` package implements it via Google Calendar API.
- `BookingService` takes a `CalendarProvider` instead of hard‑wiring `CalComService`.
- A factory `get_calendar_provider(workspace, agent/staff)` picks Google when the workspace
  has a connected Google account, else falls back to Cal.com (until Cal.com is removed).

### Availability engine (the real build)
`app/services/calendar/google/availability.py`:
- Inputs: workspace/staff **working hours** + **timezone** + **slot duration** + **buffers**
  + Google **free/busy** for the connected calendar(s).
- Output: same `AvailableSlot` shape `BookingService` already returns → zero change upstream.
- Needs a **working‑hours/config model** (Cal.com stored this server‑side; we must store it).
  Add per‑agent or per‑`bookable_staff` schedule config (JSON: weekly hours, slot length,
  buffer, min‑notice, max‑horizon). This replaces "event type" semantics.

### Booking / cancel / reschedule
`app/services/calendar/google/client.py` (OAuth + API calls):
- `events.insert` (with `conferenceData` for a Meet link, `attendees`, timezone).
- `events.patch/update` for reschedule; `events.delete` (or status=cancelled) for cancel.
- Store returned `event.id` in a new provider‑neutral `external_event_id` column.

### Status sync (replaces signed webhooks)
- **Inbound changes** (user edits/cancels in Google): `events.watch` push channels →
  `POST /api/webhooks/google-calendar`, then `events.list(syncToken)` to diff. Channels
  expire (≤7d) → a **renewal worker** re‑registers them. MVP fallback: a **polling worker**
  every N minutes using sync tokens (simpler; no public webhook needed for dev).
- **No‑show/completed** (was MEETING_ENDED): new **time‑based worker** that, after
  `scheduled_at + duration + grace`, marks `COMPLETED` (or `NO_SHOW` if a human/agent
  flagged non‑attendance). Drives `noshow_reengagement_worker` as before.

## Data model changes (additive, safe for prod)
Do **not** rename Cal.com columns (prod `appointments` data). Add provider‑neutral columns
and backfill:
- `appointment.calendar_provider` (str, default `calcom`), `appointment.external_event_id`
  (str, index), keep `calcom_*` until Cal.com removal.
- New `calendar_connection` table (or reuse `WorkspaceIntegration`) for Google OAuth:
  encrypted `access_token`/`refresh_token`, `token_expiry`, `google_calendar_id`, `scopes`,
  `watch_channel_id`/`resource_id`/`expiration`, `sync_token`.
- New schedule config for agents/staff (weekly hours JSON) — new columns or a
  `bookable_schedule` table.
- Alembic migration under `backend/alembic/versions/`; test up→down→up locally
  (`make ci.migrations`); **back up prod** before applying (`make db.backup.prod`).

## Rollout strategy
1. Ship Google provider **behind the abstraction**, disabled unless a workspace connects.
2. Pilot one workspace end‑to‑end (connect → AI checks availability → books → shows in
   Google → reschedule/cancel sync → reminders/no‑show work).
3. Migrate remaining workspaces; monitor.
4. **Remove Cal.com** (delete `calcom*.py`, webhook routes, config keys, columns) in a
   final cleanup PR once no workspace uses it.

## Interim (do NOT block on this migration)
The Cal.com timestamp fix already committed/pushed (`438ea77`) still needs the backend
deployed (`railway up --service the-tribunal-api`) so **current** bookings work while the
Google migration (weeks) proceeds. Migration does not fix today's outage.

## Risks / watch‑list
- OAuth token refresh + revocation handling (per workspace); encrypt at rest (reuse
  `encrypt_json`). Never log tokens.
- Double‑booking races (Google has no atomic "book if free") → re‑check free/busy
  immediately before `events.insert`, accept small race, reconcile via sync.
- Timezone correctness across availability, insert, reminders (repo is UTC‑aware; keep it).
- Watch‑channel expiry/renewal reliability; provide polling fallback.
- Codegen: if any public API/schema changes (new connect/callback endpoints), run
  `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
- Frontend: onboarding/integration UI must add a "Connect Google Calendar" OAuth flow and
  schedule config editor (separate frontend workstream).

## Verification per phase
- Unit tests for availability engine (working hours + free/busy → slots), Google client
  (mock transport), status worker, OAuth token refresh.
- `.ezcoder/eyes/http.sh` against new endpoints (connect/callback/webhook) + `/readyz`.
- `make ci.backend` (ruff/mypy/pytest) green; `make ci.migrations` for the migration.
- Manual pilot booking flow through a real AI agent.

## Steps
1. Confirm the two decisions (keep AI auto‑booking = yes; per‑workspace OAuth = yes) and
   collect Google OAuth prerequisites (client id/secret, redirect URI, enabled Calendar API,
   consent screen). Add `GOOGLE_OAUTH_*` to `app/core/config.py` + env templates + `ci.env` drift.
2. Add a `CalendarProvider` Protocol in `app/services/calendar/provider.py` defining
   availability/book/cancel/reschedule/reschedule_link; refactor `CalComService` to implement it
   and make `BookingService` depend on the protocol (no behavior change, keep tests green).
3. Add a `get_calendar_provider(...)` factory that returns Cal.com today; wire
   `base_tool_executor._create_booking_service` and the 3 workers through it (still Cal.com).
4. Write the additive Alembic migration: `appointment.calendar_provider` + `external_event_id`;
   new `calendar_connection` (Google OAuth tokens, calendar id, watch/sync fields) and a
   per‑agent/staff weekly‑schedule config; run `make ci.migrations` locally.
5. Implement Google OAuth: `app/api/v1/integrations/google_calendar.py` connect + callback
   endpoints, token storage encrypted via `encrypt_json`, and a token‑refresh helper.
6. Implement `app/services/calendar/google/client.py` (events.insert with Meet, patch, delete,
   freebusy.query) using the stored per‑workspace credentials.
7. Implement `app/services/calendar/google/availability.py` slot engine (weekly hours + timezone
   + duration + buffers + free/busy → `AvailableSlot`), with unit tests.
8. Add `GoogleCalendarProvider` implementing `CalendarProvider` over the client + availability
   engine; make the factory choose Google when the workspace has a live connection.
9. Replace status sync: add `POST /api/webhooks/google-calendar` + `events.watch` registration,
   an `events.list(syncToken)` differ mapping changes to `AppointmentStatus`, and a
   watch‑channel renewal worker (with a polling fallback worker for dev).
10. Add the time‑based no‑show/completed worker to replace `MEETING_ENDED`; keep
    `noshow_reengagement_worker` behavior intact.
11. Replace `generate_booking_url` usages in `reminder_worker`, `never_booked_worker`,
    `noshow_reengagement_worker` with provider‑neutral reschedule links (Google path = our own
    reschedule flow/link).
12. Update `staff_assignment.py` and schedule resolution to use the new schedule config instead of
    `calcom_event_type_id` (keep Cal.com path working during transition).
13. Frontend: add "Connect Google Calendar" OAuth UI + schedule‑config editor in onboarding/
    integrations; run `make codegen` and commit both generated artifacts.
14. Pilot one workspace end‑to‑end; verify availability→book→sync→reminders→no‑show with
    `.ezcoder/eyes` probes and a real AI agent booking.
15. Cleanup PR: remove `calcom*.py`, Cal.com webhook routes/signature verifier, `calcom_*`
    config keys, and (after backfill) the `calcom_*` columns; update docs/CLAUDE.md and env
    templates; final `make ci.all`.
