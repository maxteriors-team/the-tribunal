# Guarded AI Sales Booking

## Objective

Make SMS/voice AI collect a preferred slot, restate the exact date/time/timezone, require the customer's explicit confirmation, then direct-book through the existing CRM-to-Google Calendar flow.

## Existing behavior to preserve

- `backend/app/services/ai/base_tool_executor.py` already filters offered slots through `google_calendar.filter_available_slots()` and rechecks the chosen slot with `is_time_available()` immediately before booking.
- `backend/app/services/calendar/booking.py` already generates and validates slots against `workspace.settings["business_hours"]`; these CRM hours are the enforceable sales-call windows because Google does not expose Appointment Schedule rules through the Calendar API.
- `backend/app/services/appointments/booking_finalizer.py` already creates the Google event, attendee invitation, and Google Meet conference after a successful booking.

## Changes

- Tighten text and voice booking instructions so selecting a proposed time starts a confirmation turn; booking occurs only after the AI restates the full date, time, timezone, duration, and invite email and receives an explicit affirmative reply.
- Add a required `customer_confirmed` boolean to booking tool schemas and reject booking execution unless it is true, providing a deterministic guard in addition to prompt instructions.
- Keep Google conflict checks fail-closed and add regression coverage proving booking cannot bypass confirmation or a newly occupied Google slot.

## Files

- `backend/app/services/ai/text_prompt_builder.py`
- `backend/app/services/ai/prompt_builder.py`
- `backend/app/services/ai/voice_prompt_builder.py`
- `backend/app/services/ai/voice_tools.py`
- `backend/app/services/ai/text_tool_executor.py`
- `backend/app/services/ai/tool_executor.py`
- `backend/app/services/ai/base_tool_executor.py`
- Relevant tests under `backend/tests/services/ai/` and `backend/tests/services/calendar/`

## Risks

- Prompt-only confirmation can be bypassed by a mistaken model tool call, so execution must also reject a missing/false confirmation flag.
- Google Appointment Schedule rules are not available through the Calendar API; this change preserves existing CRM business hours and does not guess or mutate workspace-wide production settings.

## Verification

- Targeted pytest coverage passes for prompt text, tool schemas, booking executor confirmation rejection, Google busy-slot rejection, and existing booking success.
- Backend lint/type checks pass for touched modules.
- A representative local booking tool call without confirmation returns no appointment; a confirmed free slot creates one event/invitation through the existing finalizer path.

## Steps

1. Add the explicit customer-confirmation contract to text, generic, and voice booking prompts.
2. Add `customer_confirmed` to every booking tool schema and pass it through SMS and voice executors.
3. Reject unconfirmed booking calls in `BaseToolExecutor` before staff assignment, persistence, or Google writes.
4. Add regression tests for confirmation gating, exact confirmation wording, Google conflict rechecks, and successful confirmed booking.
5. Run targeted backend tests and lint/type checks, then fix any failures.
