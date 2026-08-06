# Outbound calls: choose AI agent or the human user

## Goal

From the dashboard, start an outbound call to a contact and pick who talks:

- **AI mode** — a voice agent handles the call (mostly exists today).
- **User mode** — the call rings *the operator's own phone* first, then dials the contact and bridges the two legs. New.

## What already exists (verified in this checkout)

- `POST /api/v1/workspaces/{workspace_id}/calls` → `initiate_call` in `backend/app/api/v1/calls.py:29`. Takes `CallCreate` (`to_number`, `from_phone_number`, `contact_phone`, `agent_id`).
- `TelnyxVoiceService.initiate_call` (`backend/app/services/telephony/telnyx_voice.py:195`) creates the `Message` row (`channel="voice"`, `is_ai = agent_id is not None`) and dials via Telnyx Call Control, with idempotency via `client_state`.
- `handle_call_answered` (`backend/app/api/webhooks/telnyx_call_handlers.py:233`) starts the AI audio stream **only** when `direction == "outbound" and agent_id` is set.
- Full two-leg orchestration primitives already exist for AI→human warm transfer: `dial_transfer_leg` (`telnyx_voice.py:819`), `speak_text` (`:883`), `bridge_calls` (`:944`), `transfer_call` (`:750`), plus Redis pending-state helpers in `backend/app/services/telephony/call_transfer.py` (`store_/peek_/pop_pending_transfer`, `make_transfer_leg_client_state`).
- Frontend callers: `useContactSidebarData.callContact()` (`frontend/src/components/contacts/contact-sidebar/use-contact-sidebar-data.ts:126`) and the agents test-call dialog (`frontend/src/components/agents/agents-list.tsx:176`).

## Live bug this work fixes

`callContact()` sends **no `agent_id`**. So today the contact-detail / contact-rail "Call" button dials the customer, the customer answers, and `handle_call_answered` starts no stream and no bridge — **dead air**, then the customer hangs up. The only working path is the agents-list test dialog, which always passes an agent. Requiring a resolvable participant (agent or user leg) at request time closes this.

## Design: dial-the-rep-first bridging

User mode originates **two** legs we control end to end, so both `call_control_id`s are known to us:

1. Pre-create the `Message` (`direction="outbound"`, `is_ai=False`, `status="queued"`) on the contact's conversation.
2. Dial **leg A → the rep's phone** from the workspace number. Stash Redis pending state keyed by leg A's ccid.
3. On `call.answered` for leg A: dial **leg B → the contact**, set `Message.provider_message_id = legB_ccid`, stash pending state keyed by leg B's ccid.
4. On `call.answered` for leg B: `bridge_calls(legB, legA)`, mark the `Message` answered, start recording if the workspace enables it.
5. Either leg hanging up early tears down its peer.

Anchoring the `Message` on the **contact leg** keeps `hangup_call`, duration, recording, transcript, and call-history semantics byte-identical to AI calls — no changes needed in `handle_call_hangup`'s main path or `list_calls`.

**Rejected: in-browser WebRTC softphone.** Needs the Telnyx WebRTC SDK, per-user SIP credentials, mic permissions, and a new token-mint endpoint. Bridging works with the primitives already in the repo and reaches the rep on any phone, including mobile. Worth revisiting later as a second `mode`.

## Risks and controls

- **Toll fraud (the important one).** If `user_phone_number` is a free-form E.164 from the client, any `CanSendComms` member can bill the workspace for calls to premium-rate/international numbers. Control: resolve the rep number against an allowlist — the caller's own `User.phone_number`, the workspace `settings["transfer_destination_number"]`, or a workspace-owned voice number. Reject anything else with 400.
- **Doubled telephony spend.** Every user-mode call is two billable legs. Cap leg timeouts (rep 25s, contact 30s) and always tear down the orphan leg.
- **Redis best-effort.** The existing pending-transfer helpers swallow Redis errors. If pending state is lost, the answered leg must hang up rather than sit on a live parked leg burning minutes.
- **Multi-instance.** Webhooks may land on any backend replica; keep all cross-leg state in Redis (as `call_transfer.py` already does), never in process memory.

## Verification

- `.ezcoder/eyes/http.sh http://localhost:8000/api/v1/workspaces/<ws>/calls POST @payload.json -H "Authorization: Bearer ..."` for each mode + the rejection cases.
- Replay `backend/tests/fixtures/webhooks/telnyx/call_answered.json` (rewritten ccids) against `/webhooks/telnyx/voice` via `.ezcoder/eyes/http.sh`, then `.ezcoder/eyes/logs.sh --service backend --grep "user_call|ERROR|Traceback"`.
- `make ci.codegen`, `make ci.backend`, `make ci.frontend`.

## Steps

1. Add `backend/app/services/telephony/user_call.py` modeled on `call_transfer.py`: `PendingUserCall` dataclass (`rep_call_control_id`, `contact_call_control_id`, `message_id`, `workspace_id`, `user_id`, `contact_number`, `from_number`, `stage`, `created_at`), Redis `store_/peek_/pop_pending_user_call` under prefix `voice:usercall:pending:` with a 600s TTL, and `make_user_call_leg_client_state`.
2. Add `resolve_rep_callback_number(db, user, workspace, requested)` to `user_call.py`: returns the allowlisted rep number (caller's `User.phone_number` → workspace `settings["transfer_destination_number"]` → workspace voice-enabled number) and raises a domain error for anything off-allowlist.
3. Add `start_user_call(...)` to `user_call.py`: create the `Message` (`is_ai=False`, `status="queued"`) via the existing conversation resolution used by `TelnyxVoiceService._get_or_create_conversation`, dial leg A with `dial_transfer_leg` (`timeout_secs=25`, user-call `client_state`), store pending state keyed by leg A's ccid, and return the `Message`.
4. Extend `CallCreate` in `backend/app/schemas/call.py` with `mode: Literal["ai", "user"] = "ai"` and `user_phone_number: str | None = None`; document that `agent_id` applies only to `mode="ai"`.
5. Update `initiate_call` in `backend/app/api/v1/calls.py`: for `mode="user"` call `start_user_call` and 400 on an off-allowlist number; for `mode="ai"` resolve the agent (explicit `agent_id` → conversation `assigned_agent_id` → workspace default voice agent) and 400 when none resolves, so the dead-air path is impossible.
6. Add `_handle_user_call_leg_answered(call_control_id, log)` to `backend/app/api/webhooks/telnyx_call_handlers.py` and call it in `handle_call_answered` right after `_handle_transfer_leg_answered`: on the rep leg dial the contact leg and repoint `Message.provider_message_id`; on the contact leg `bridge_calls` into the rep leg, set `MessageStatus.ANSWERED`, and start recording when enabled. Return `True` to short-circuit AI streaming.
7. Extend `handle_call_hangup` in the same file to tear down the peer leg for user calls: rep leg hangs up before bridge → hang up the contact leg and mark the `Message` `no_answer`/`failed`; contact leg hangs up → hang up the rep leg; clear Redis state in both directions.
8. Add `backend/tests/api/test_calls_initiate_modes.py` covering: `mode="ai"` without any resolvable agent → 400; `mode="user"` with an off-allowlist `user_phone_number` → 400; `mode="user"` happy path creates an `is_ai=False` message and dials the rep first.
9. Extend `backend/tests/api/test_webhooks_telnyx_call_handlers.py` with user-call webhook cases: rep answered → contact dialed, contact answered → `bridge_calls` invoked, rep hangup pre-bridge → contact leg hung up.
10. Add `mode` and `user_phone_number` to `InitiateCallRequest` in `frontend/src/lib/api/calls.ts`.
11. Add `frontend/src/components/calls/outbound-call-dialog.tsx`: a from-number select plus an AI-agent / My-phone mode toggle, showing an agent picker in AI mode and the resolved callback number (editable, defaulting to the user's profile phone) in user mode, following the dialog patterns in `frontend/src/components/agents/agents-list.tsx`.
12. Wire the dialog into `frontend/src/components/contacts/contact-sidebar/use-contact-sidebar-data.ts`, `contact-sidebar.tsx`, and `contact-detail/contact-detail-page.tsx` so the Call button opens the mode picker instead of firing an agent-less call.
13. Run `make ci.codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together with the schema change.
14. Verify locally with `.ezcoder/eyes/http.sh` against `/calls` for both modes and the two rejection cases, replay the `call_answered` fixture against the Telnyx voice webhook for each leg, and check `.ezcoder/eyes/logs.sh --service backend --grep "user_call|ERROR|Traceback"`.
15. Run `make ci.backend` and `make ci.frontend` and fix any failures.
