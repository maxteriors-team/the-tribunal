# AI-first inbound calling pilot runbook

This runbook covers the dedicated-number pilot where Telnyx answers an inbound call, plays a fixed AI/transcription disclosure, then streams audio to OpenAI Realtime. It does **not** add browser ringing, a softphone ring group, or raw call recording.

This is engineering guidance, not a legal certification. Counsel must approve the disclosure and jurisdiction-specific consent process before a live pilot.

## Safety model

AI inbound answering stays off unless all gates pass:

- The phone number has `inbound_ai_enabled=true` through the authenticated settings flow.
- The workspace UUID is in `INBOUND_VOICE_PILOT_WORKSPACE_IDS`.
- The phone and selected agent belong to the same workspace.
- The number is active, voice-enabled, and linked to a Telnyx provider number.
- The agent is active, voice-capable, and uses OpenAI Realtime.
- Workspace OpenAI credentials resolve successfully.
- Telnyx API key, public key, connection ID, and public HTTPS API URL are configured.
- Emergency fallback and human-transfer destinations are valid E.164 numbers.
- Redis-backed caller, workspace, daily-spend, and two-call concurrency controls are available.

A failed gate never starts OpenAI streaming. The call transfers to the configured emergency fallback. If transfer cannot start, the caller hears a short unavailable notice and the call ends. A caller-specific hourly limit hears a generic busy notice instead of consuming fallback capacity.

## Required environment

Set these on the backend service:

```text
INBOUND_VOICE_PILOT_WORKSPACE_IDS=["<workspace-uuid>"]
TELNYX_API_KEY=<secret>
TELNYX_PUBLIC_KEY=<webhook-signing-public-key>
TELNYX_CONNECTION_ID=<voice-api-application-id>
API_BASE_URL=https://<public-backend-origin>
```

Optional pilot controls retain safe defaults:

```text
INBOUND_VOICE_CALLER_HOUR_LIMIT=6
INBOUND_VOICE_WORKSPACE_HOUR_LIMIT=60
INBOUND_VOICE_WORKSPACE_DAY_LIMIT=100
INBOUND_VOICE_WORKSPACE_MAX_CONCURRENT=2
INBOUND_VOICE_ESTIMATED_COST_PER_MINUTE_USD=0.12
```

The cost value is a blended operational estimate, not billing truth. Update it when provider pricing or the model changes.

## Telnyx setup

Use one dedicated pilot number. Do not repoint an existing customer number for the first test.

1. Create or select one Voice API application.
2. Set its primary webhook URL to the production Telnyx voice webhook endpoint.
3. Configure the provider failover URL before live traffic.
4. Assign only the dedicated pilot number to that application.
5. Keep provider-side recording disabled.
6. Confirm the number's provider ID and Voice API connection ID match the readiness screen.
7. Keep the existing SMS application/routing intact unless the pilot number also needs SMS.

Provider changes and database activation are separate. The settings flow configures the number with the Voice API application first, then enables the database kill switch. A provider failure leaves the kill switch off.

## Workspace setup

1. Connect or verify the workspace OpenAI integration.
2. Create an active OpenAI voice agent with a configured voice.
3. Configure the agent's human-transfer destination in E.164 format.
4. Choose a separate emergency fallback destination in E.164 format.
5. Add the workspace UUID to the pilot allowlist.
6. Open **Phone Numbers > AI calls** for the dedicated number.
7. Review every readiness result and the disclosure copy.
8. Check the explicit acknowledgement and enable AI answering.

The API does not return decrypted fallback or transfer destinations. The UI only reports whether each destination is configured; entering a blank value preserves an existing encrypted destination.

## Fixed disclosure and recording policy

Before caller audio can reach OpenAI, Telnyx speaks:

> You are speaking with {business name}'s AI assistant. This call will be transcribed to help with your request. By continuing, you agree to that processing.

The message row records disclosure status, version, and completion time. OpenAI streaming starts only after the signed `call.speak.ended` webhook carries the message-bound disclosure marker.

The pilot never invokes Telnyx raw recording, even when an agent's legacy `record_call` flag is enabled. If an unexpected provider recording arrives, the handler ignores its URL for disclosed pilot calls. Transcripts and disclosure audit fields follow the existing conversation/message retention and deletion lifecycle. Confirm that lifecycle with counsel before launch; do not claim that transcription and recording have identical consent rules.

## Local and staged verification

Run the repository checks first:

```bash
make ci.all
```

Then test the dedicated number in this order:

1. **Disabled:** Call while AI answering is off; confirm no OpenAI session starts.
2. **Happy path:** Hear the full disclosure once, speak after it ends, and confirm a two-way conversation.
3. **Human transfer:** Ask for a person; confirm warm transfer reaches only the configured destination.
4. **OpenAI unavailable:** Temporarily use a test workspace with invalid credentials; confirm emergency transfer, not AI.
5. **Telnyx stream failure:** Use a staging failure injection; confirm emergency transfer or the unavailable notice.
6. **Redis unavailable:** Stop staging Redis; confirm AI never starts.
7. **Caller limit:** Exceed six attempts from a test number; confirm the generic busy notice.
8. **Workspace limit:** Use staging overrides; confirm emergency fallback.
9. **Concurrency:** Hold two calls, place a third, and confirm the third does not start AI.
10. **Duplicate webhook:** Replay the signed staging disclosure completion; confirm disclosure and stream are not duplicated.
11. **No recording:** Confirm no recording command appears and no recording URL is stored.
12. **Tenant isolation:** Route a test call with a foreign agent ID; confirm readiness blocks without naming the foreign workspace or agent.

Do not perform failure injection against the live customer number.

## Observability

Watch bounded logs and Prometheus metrics. Never add caller numbers, fallback numbers, transcript content, or provider response bodies to logs or metric labels.

Key metrics:

- `inbound_voice_disclosure_total{workspace_id,outcome}`
- `inbound_voice_fallback_total{outcome}`
- `inbound_voice_active_calls{workspace_id}`
- `inbound_voice_duration_seconds{workspace_id}`
- `inbound_voice_estimated_cost_usd{workspace_id}`
- Existing voice completion and Telnyx webhook counters

Alert during the pilot on:

- any disclosure failure;
- any fallback failure or unavailable notice;
- active calls stuck above zero beyond the call-duration cap;
- repeated workspace protection blocks;
- a material increase in estimated per-call cost;
- provider signature failures or webhook retries.

## Launch gates

Do not send real callers to the pilot until all are true:

- Counsel approved disclosure and consent handling for the intended jurisdictions.
- Product approved transcript retention and deletion behavior.
- Telnyx failover routing is configured and tested.
- Provider-side recording is disabled.
- Workspace OpenAI credentials and billing are active.
- Emergency fallback and human transfer both reach staffed destinations.
- Focused, migration, full CI, and staging call tests pass.
- An operator is watching logs, metrics, and provider spend during the first calls.

## Rollback

The fastest rollback is the database kill switch:

1. Open the pilot number's **AI calls** settings.
2. Select **Disable AI answering**.
3. Confirm readiness reports `enabled=false`.
4. Remove the workspace from `INBOUND_VOICE_PILOT_WORKSPACE_IDS` for defense in depth.
5. Repoint or unassign the pilot Telnyx number if calls must stop entirely.

Disabling commits before optional configuration validation, so a bad agent or destination edit cannot keep AI answering active. Do not delete conversations or rewrite prior messages during rollback; disclosure audit history remains attached to the original calls.
