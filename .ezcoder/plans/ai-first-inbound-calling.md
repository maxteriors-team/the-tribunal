# AI-First Inbound Calling

Snapshot: 2026-08-29 · Target: current `origin/main` · Planning only

## Goal

Let an external caller dial a dedicated Tribunal-managed Telnyx number, hear a deterministic AI/transcription notice before any audio reaches OpenAI, speak naturally with the assigned AI agent, and request a warm transfer to a human. Launch first as an allowlisted pilot; do not replace the business's primary number until independent failover and legal/retention decisions are complete.

## Success criteria

- A workspace manager can configure one phone number with an active voice-capable agent, an emergency fallback number, and AI-first inbound calling.
- Activation fails closed unless the phone number and agent belong to the same workspace, Telnyx production routing is configured, usable workspace OpenAI credentials exist, and the pilot workspace is allowlisted.
- An inbound call follows this observable order: persist call → reserve spend budget → answer → play fixed disclosure with Telnyx TTS → start media streaming → converse with OpenAI.
- The first pilot does not start Telnyx raw-audio recording, even when the agent's existing `enable_recording` flag is true.
- Replayed or out-of-order Telnyx webhooks cannot repeat the disclosure, open duplicate streams, duplicate messages, or double-transfer.
- Saying or selecting human handoff uses the existing warm-transfer path; preflight, Redis, or OpenAI setup failures cold-transfer to the configured fallback when possible.
- Cross-workspace, inactive, or text-only agents cannot be assigned or resolved for inbound voice.
- Caller/workspace spend limits and existing concurrency/duration caps bound anonymous inbound OpenAI usage.
- The settings page clearly says the AI answers immediately; it does not imply that a browser or employee phone rings first.
- A live external-phone pilot proves two-way audio, disclosure ordering, CRM persistence, transfer, fallback, hangup, and provider status before wider exposure.

## Confirmed current state

### Repository

- `backend/app/api/webhooks/telnyx_call_handlers.py::auto_answer_call_if_agent_assigned` already resolves a number/agent, starts Telnyx media streaming, answers, and starts recording when `Agent.enable_recording` is true.
- `handle_call_answered` and `handle_call_speak_ended` already receive the lifecycle events needed to place a deterministic pre-stream disclosure.
- `backend/app/websockets/voice_bridge.py` already bridges Telnyx media to OpenAI Realtime and invokes the existing voice tools.
- `backend/app/services/telephony/telnyx_voice.py` already exposes `speak_text`, `start_audio_streaming`, `start_recording`, and `transfer_call`.
- `backend/app/services/ai/warm_transfer.py` already supports human handoff through `Agent.transfer_destination_number`.
- `backend/app/services/telephony/voice_agent_resolver.py` does not enforce that a resolved assigned agent belongs to the phone number's workspace.
- `backend/app/api/v1/phone_numbers.py::update_phone_number` accepts `assigned_agent_id` without workspace/voice-capability validation.
- Number purchase/sync persists Telnyx numbers, but inbound Voice API activation is not an explicit, validated product workflow.
- The browser softphone connects only while starting a browser call. There is no persistent inbound WebRTC registration, ring group, background ringing, or closed-tab answer path.
- The existing voice WebSocket has global/per-workspace concurrency and duration caps; Redis admission currently fails open, so it is not sufficient as an anonymous spend control.
- `COMPLIANCE.md` already records `AI-001` for missing source-enforced AI disclosure and `COST-001` for unentitled platform-paid Telnyx/OpenAI work.

### Production provider snapshot

Read-only Telnyx checks found:

- One active Telnyx number exists, is assigned to the sole active Call Control Application, and has a messaging profile.
- The Call Control Application posts to `https://the-tribunal-api-production.up.railway.app/webhooks/telnyx/voice` and webhook verification material is configured.
- The application is still named `Tribunal Voice (ngrok dev)` and has no failover URL.
- Railway's resolved `TELNYX_CONNECTION_ID` is blank even though the provider application exists; activation/provisioning cannot rely on that setting yet.
- No global OpenAI key/token is configured. This is acceptable only when the target workspace has a usable active OpenAI integration; that database fact was not verified.
- Retained Railway logs contained no observed inbound-call attempt or successful auto-answer, so the path has no live proof.

## Recommended product boundary

### Included

- Dedicated pilot number only.
- AI answers immediately after a deterministic Telnyx-spoken disclosure.
- Existing AI booking/CRM tools and warm transfer.
- Emergency cold transfer when the backend is reachable but AI prerequisites fail.
- Workspace-scoped setup UI, provider reconciliation, spend limits, audit fields, metrics, tests, runbook, and staged rollout.

### Excluded

- Inbound browser softphone, staff ring groups, native/background ringing, or closed-tab answering.
- Porting or replacing the existing primary business number during the pilot.
- Raw Telnyx audio recording during the first launch.
- Outbound campaign or autodialer changes.
- Self-service enablement for every tenant.
- Independent cross-provider/platform disaster failover in the first pilot. The existing business number remains the outage fallback until that separate control exists.

## Proposed design

### Data model and audit trail

Add an additive reversible migration with:

- `PhoneNumber.inbound_ai_enabled`: non-null boolean, default `false`; this is the explicit kill switch. Agent assignment alone must never make a number live.
- `PhoneNumber.inbound_fallback_number`: nullable `EncryptedString`; used for infrastructure/preflight cold transfer and never logged in plaintext.
- `Message.voice_disclosure_status`: nullable bounded string (`pending`, `speaking`, `completed`, `failed`).
- `Message.voice_disclosure_version`: nullable bounded string, initially `ai-transcription-v1`.
- `Message.voice_disclosed_at`: nullable timezone-aware timestamp.

Add the encrypted fallback column to `scripts/ops/reencrypt_with_old_key.py` rotation targets. The migration is metadata-only for existing rows except for the boolean default; no contact/lead/invoice values are rewritten. Back up production before applying because phone/message rows contain customer communications and downgrading after calls would discard disclosure evidence.

Do not add a raw-recording toggle yet. The inbound handler must ignore the agent-level recording flag. A later, separately reviewed change may enable recording only after the operating jurisdictions, exact notice/consent mechanism, retention, and deletion path are approved.

### Workspace-safe activation

Add a small `backend/app/services/telephony/inbound_call_readiness.py` service as the single activation/runtime chokepoint. It must:

- Scope `PhoneNumber` and `Agent` by the same `workspace_id` in SQL.
- Require an active agent with `channel_mode` of `voice` or `both`.
- Validate normal handoff and emergency fallback destinations as E.164.
- Check `OpenAICredentialResolver.is_openai_configured(workspace_id)` without exposing credentials.
- Require `TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY`/verification configuration, `API_BASE_URL`, and `TELNYX_CONNECTION_ID`.
- Require the workspace UUID in a new default-empty `INBOUND_VOICE_PILOT_WORKSPACE_IDS` setting.
- Return allowlisted reason codes, never foreign resource details or secret/provider responses.

Add workspace-managed endpoints under `backend/app/api/v1/phone_numbers.py`:

- `GET /{phone_number_id}/inbound-readiness` returns bounded readiness checks and current safe configuration.
- `PUT /{phone_number_id}/inbound-config` sets agent/fallback and activates or deactivates AI-first routing.

When activation is requested, validate everything first, then patch the Telnyx number to the configured Call Control Application, then commit `inbound_ai_enabled=true`. If the provider succeeds but the database commit fails, the default-false database state still prevents AI pickup. Deactivation changes the database kill switch first and leaves provider delivery attached so the handler can apply fallback behavior.

Also harden the existing generic update route and `voice_agent_resolver.py` so a poisoned cross-tenant `assigned_agent_id` fails closed at runtime, not only in the setup UI.

### Inbound lifecycle

Refactor `auto_answer_call_if_agent_assigned` into an explicit inbound router:

1. Resolve the phone row by normalized destination and workspace.
2. Persist the inbound call/message idempotently and send the existing informational push.
3. If AI inbound is disabled, cold-transfer to the encrypted fallback or play a brief unavailable message and hang up.
4. Run readiness and spend checks before opening any OpenAI session.
5. On a ready call, mark disclosure `pending` and answer without starting media or recording.
6. On inbound `call.answered`, atomically transition `pending → speaking` and call `TelnyxVoiceService.speak_text` with fixed, versioned copy.
7. On the matching `call.speak.ended`, preserve warm-transfer precedence, atomically transition `speaking → completed`, set `voice_disclosed_at`, and start media streaming exactly once.
8. Never call `start_recording` on the inbound pilot path.

Recommended fixed copy for counsel/product review:

> Thanks for calling [business name]. I'm an AI assistant. This call will be transcribed to help with your request. By continuing, you agree to that processing. You can ask for a person at any time.

The business name is server-derived and escaped; operators cannot remove or weaken the identity/transcription sentences. Default to notice plus continued use. Switch to an affirmative Telnyx Gather/DTMF gate only if counsel says the caller's jurisdictions require it. This plan is engineering guidance, not legal advice.

If TTS/disclosure fails, do not stream audio. Transfer to fallback; if that fails, play an unavailable message and hang up. If OpenAI setup fails after disclosure, `voice_bridge.py` must invoke the same bounded fallback helper before closing the Telnyx leg.

### Spend and abuse controls

Reuse the atomic Redis Lua pattern from `backend/app/services/rate_limiting/softphone_limiter.py` in a dedicated inbound limiter. Key callers by the existing HMAC phone hash, never plaintext. Configure conservative pilot limits:

- caller: 6 AI starts/hour;
- workspace: 60 AI starts/hour and 100/day;
- existing global/per-workspace active-session and maximum-duration caps remain in force.

A caller-specific limit ends with a generic busy message instead of ringing the human fallback. A workspace-budget or Redis-availability failure does not open an OpenAI stream; it cold-transfers to the human fallback and emits a high-signal metric/log. Add a `simplification:` comment stating that the allowlisted pilot plus start-count budgets must be replaced by paid entitlement and metered minutes before multi-tenant release.

### Operator UI

Extend the existing phone-number settings surface, matching neighboring dialogs and controls:

- Add an `Inbound calling` action in `phone-numbers-views.tsx`/`phone-numbers-table.tsx`.
- Fetch only active voice-capable workspace agents.
- Configure assigned AI agent, normal human-transfer number, and encrypted emergency fallback number.
- Show fixed disclosure preview and an explicit `Raw recording is off` status.
- Show readiness checks with direct links to OpenAI integration or agent configuration where applicable.
- Activation copy must say: `The AI answers immediately. Your Tribunal browser will not ring.`
- Require an explicit activation confirmation; deactivation remains immediate and reversible.

Use existing React Query keys/options and generated OpenAPI types. Do not add a dependency or build an inbound softphone.

### Observability and operations

Add structured, PII-free events and counters for:

- inbound route selected (`ai`, `fallback`, `unavailable`);
- disclosure started/completed/failed;
- readiness failure reason;
- spend-limit reason;
- AI startup fallback;
- transfer success/failure.

Fix the incoming push deep link from nonexistent `/call/{id}` to the existing calls surface. Keep call IDs pseudonymous/bounded and never log caller, fallback, transcript, prompt, or provider credentials.

Add `docs/operations/inbound-calling.md` with provider setup, activation, emergency deactivation, fallback behavior, metrics/log queries, cost limits, live test script, rollback, and the known lack of independent failover. Update `COMPLIANCE.md` with a focused inbound-voice addendum: `AI-001` becomes fixed only for this inbound path; raw recording remains disabled; retention/privacy/vendor and jurisdiction-specific consent remain open decisions.

## Verification

### Automated

- Extend `backend/tests/test_phone_numbers.py` for readiness/configuration, E.164 validation, role checks, provider failure ordering, activation/deactivation, and cross-workspace agent rejection.
- Extend `backend/tests/test_telnyx_default_agent.py` for runtime same-workspace, active, voice-capable resolution.
- Extend `backend/tests/test_webhooks_telnyx_call_handlers.py` for exact answer→disclose→stream ordering, no raw recording, duplicate/out-of-order events, disabled AI, missing agent/OpenAI, TTS failure, and fallback behavior.
- Extend `backend/tests/test_voice_bridge.py` for OpenAI-startup fallback without leaking provider errors.
- Add focused inbound limiter tests for caller/workspace limits and Redis fail-closed behavior.
- Add frontend tests beside the phone-number settings components for readiness states, activation warning, agent filtering, and recording/browser-ringing copy.
- Regenerate and commit `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` together.
- Run targeted Ruff, mypy, pytest, and frontend Vitest checks, then `make ci.all` including migration reversibility and codegen drift.

### Local runtime

- Start the local backend with test provider transports and hit readiness/configuration endpoints using `.ezcoder/eyes/http.sh` for authorized 2xx, foreign-resource 404, malformed fallback 422, and missing-prerequisite fail-closed responses.
- Replay representative signed Telnyx fixtures for initiated, answered, speak-ended, duplicate, and failure events; inspect redacted logs for ordering and absence of traceback/PII.
- Verify migration upgrade→schema check→downgrade→upgrade against a PostgreSQL 17 + pgvector database.

### Production pilot

External prerequisites before billed/live proof:

- User supplies the pilot workspace, human-transfer number, emergency fallback number, and a caller phone they control.
- Workspace OpenAI integration is connected and usable.
- Counsel/product approves the exact disclosure and decides transcript retention/deletion for real customer calls.
- Railway `TELNYX_CONNECTION_ID` is set to the existing application ID; the Telnyx application is renamed for production.

Release from a clean current-main checkout through the protected PR process. Back up production before the additive phone/message migration. Deploy backend before activating the number; frontend may auto-deploy afterward.

Run five controlled calls from an external phone:

1. normal conversation and hangup;
2. interruption/barge-in after disclosure;
3. requested warm transfer to the human destination;
4. deliberately unavailable OpenAI integration producing cold fallback;
5. duplicate/replayed webhook delivery producing no duplicate stream/message/transfer.

For each, verify Telnyx event status, `/version`, `/readyz`, message/conversation ownership, disclosure audit fields, transcript, no recording URL, transfer result, redacted Railway logs, and cost/limit counters. Keep the number unadvertised for 48 hours while monitoring. Do not port or replace the primary business number until an independently hosted Telnyx failover handler and an approved retention/privacy policy exist.

## Rollback and risks

- Immediate operational rollback is `inbound_ai_enabled=false`; inbound calls then use fallback without changing provider ownership.
- Code rollback uses the prior Railway deployment. Do not downgrade the migration after real calls without exporting disclosure audit fields or restoring the pre-release encrypted backup.
- Provider configuration is an external side effect; activation must never release a purchased number on failure.
- Telnyx webhooks are retried and may arrive out of order, so all lifecycle transitions need row locks/idempotent guards.
- A Railway outage still defeats the primary webhook during the pilot; the dedicated number and existing business line contain that risk.
- OpenAI/Telnyx process voice data. OpenAI states API data is not used for training by default, but provider retention and the app's stored transcript remain privacy/contract facts to document and periodically re-verify.

References:

- Telnyx Voice API webhook delivery, retries, signatures, and failover: https://developers.telnyx.com/docs/voice/programmable-voice/receiving-webhooks.md
- Telnyx browser calling requires an active WebRTC client: https://developers.telnyx.com/docs/voice/webrtc/make-a-call-to-a-web-browser.md
- OpenAI API data controls and retention: https://platform.openai.com/docs/guides/your-data
- State recording rules vary; obtain operating-jurisdiction advice: https://www.rcfp.org/reporters-recording-guide/

## Steps

1. Create an isolated feature branch from current `origin/main`, confirm the working tree contains no unrelated changes, and record the exact production configuration snapshot without exposing secrets or phone numbers.
2. Add the additive `PhoneNumber` inbound kill-switch/encrypted fallback fields and `Message` disclosure-audit fields, register the encrypted field for key rotation, and write a reversible Alembic migration.
3. Add strict inbound configuration/readiness schemas, E.164 validation, default-empty pilot-workspace allowlisting, and bounded reason codes.
4. Implement the workspace-scoped inbound readiness service using active voice-agent, OpenAI credential, Telnyx configuration, fallback, and pilot-entitlement checks.
5. Add phone-number readiness/configuration endpoints that validate first, configure the Telnyx Voice Application, commit activation last, and harden existing assignment updates against cross-tenant/inactive/text-only agents.
6. Harden `voice_agent_resolver.py` so every inbound assigned-agent resolution enforces the phone number's workspace and voice capability at the data layer.
7. Add the fail-closed anonymous inbound spend limiter with HMAC caller keys, workspace budgets, bounded configuration, metrics, and the documented pilot ceiling.
8. Refactor inbound Telnyx handling to answer without streaming, play one versioned deterministic disclosure, start streaming once after `call.speak.ended`, and never start raw recording.
9. Add shared cold-fallback behavior for disabled/unready/over-budget/TTS/OpenAI-startup failures, preserving existing warm-transfer behavior and idempotent webhook ordering.
10. Add PII-free inbound routing/disclosure/fallback metrics and logs, and correct the incoming-call push deep link to the existing calls screen.
11. Add the phone-number inbound-calling dialog, readiness display, agent/fallback configuration, fixed disclosure preview, no-recording status, and explicit AI-immediate-answer activation copy.
12. Add backend and frontend regression coverage for authorization, readiness, provider ordering, disclosure ordering, replay safety, spend limits, fallbacks, UI states, and absence of inbound recording.
13. Regenerate OpenAPI/client artifacts, update the operations runbook and focused compliance register, then run targeted checks and full `make ci.all` including migration reversibility.
14. Open and merge a focused protected PR without staging unrelated work, then back up production and deploy the merged current-main backend before frontend activation.
15. Set the production Call Control Application ID, connect the workspace OpenAI integration, configure the approved pilot agent/transfer/fallback, and activate only the dedicated pilot number.
16. Execute the five-call external pilot, inspect provider/API/log/cost evidence, keep the number unadvertised for 48 hours, and block primary-number cutover until independent failover plus approved retention/privacy terms exist.
