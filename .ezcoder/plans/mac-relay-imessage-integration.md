# Mac Relay iMessage Integration Plan

## Goal

Add a self-hosted Mac relay path so outbound text can go through Apple Messages on a Mac for iMessage blue-bubble delivery when the sender identity is an iMessage-enabled Apple account/phone alias, while preserving Telnyx SMS as the fallback/default path.

This will not depend on a third-party messaging provider. The implementation will use our backend plus a small Mac-hosted relay daemon that shells out to the open-source `imsg` CLI.

## Kencode and web research findings

- `openclaw/imsg` is the best phase-one surface: it reads `~/Library/Messages/chat.db`, streams inbound rows with `imsg watch --json`, and sends through Messages.app with `imsg send --to "+14155551212" --text "Hello" --service imessage|sms|auto`. It requires macOS, Messages.app signed in, Full Disk Access for reads, and Automation permission for sends.
- `kacy/chatbubbles` validates the production shape we want: a Mac daemon backed by `imsg`, token auth, server/chats/history/event endpoints, `POST /v1/messages`, webhook delivery, and Tailscale exposure instead of public internet exposure.
- `BlueBubblesApp/bluebubbles-server` validates the older mature pattern: a Mac server reads chat.db, uses AppleScript or optional private API helper, exposes send-message/start-chat/socket/webhook surfaces, and forwards iMessages to remote clients.
- `BlueBubblesApp/bluebubbles-helper` and `photon-hq/advanced-imessage-kit` show private-IMCore richer features such as replies, effects, edit/unsend, typing indicators, and group management. We should not start with private API injection because it adds SIP/library-validation risk; keep phase one to public Messages automation through `imsg`.
- `carterlasalle/mac_messages_mcp` confirms a simpler Python bridge can send through Messages.app and check local iMessage availability, but MCP is not the right production transport for our backend.

## Telnyx number answer

Our Telnyx numbers cannot be used as arbitrary blue-bubble iMessage senders just because we own them in Telnyx. iMessage sender identity must be an Apple-registered iMessage address on the Mac’s signed-in Apple account, normally an Apple ID email or a phone number activated by an iPhone/SIM/eSIM and verified by Apple. Telnyx SMS DIDs remain green-bubble SMS through Telnyx. The only practical way for a Telnyx-owned number to become a blue iMessage sender is to port that number to a cellular carrier/iPhone line or otherwise activate it on an Apple-supported iPhone identity; after that it is no longer just a Telnyx SMS sender in our current Telnyx messaging profile.

Implication: the Mac relay needs its own sender identities. We can keep Telnyx numbers for SMS fallback, voice, compliance pools, and contacts that are not reachable on iMessage.

## Current code touchpoints

- `backend/app/services/telephony/telnyx.py:117` contains `TelnyxSMSService.send_message()`, which normalizes numbers, creates/reuses `Conversation`, creates/reuses a `Message`, shortens links, calls `_post_message()`, marks status, updates conversation preview, commits, and returns the row.
- `backend/app/services/telephony/telnyx.py:270` contains `process_inbound_message()`, which dedupes provider IDs, creates/reuses conversations, creates inbound `Message`, updates unread counters, commits, and returns the row.
- `backend/app/services/telephony/telnyx.py:464` contains `_get_or_create_conversation()`, currently hardcoded to create conversations with `channel="sms"`.
- `backend/app/models/conversation.py:63` defines `MessageChannel` with only `sms`, `voice`, and `voicemail`. We need `imessage` for proper channel attribution.
- `backend/app/models/conversation.py:79` stores `Conversation.channel` as plain string and `backend/app/models/conversation.py:209` stores per-message channel using `MessageChannel` with a non-native SQLAlchemy enum and no DB check constraint.
- `backend/app/models/phone_number.py:47` models sender identities as Telnyx phone numbers only. We need provider/capability fields so Mac identities do not masquerade as Telnyx DIDs.
- `backend/app/workers/campaign_worker.py:102`, `backend/app/workers/automation_worker.py`, `backend/app/workers/followup_worker.py`, `backend/app/workers/message_test_worker.py`, and `backend/app/workers/never_booked_worker.py` construct `TelnyxSMSService` directly. These should use a provider factory/protocol so campaign logic does not care whether the text sender is Telnyx or Mac relay.
- `backend/app/api/webhooks/telnyx_message_handlers.py:22` handles inbound SMS and then triggers shared side effects: approval commands, operator assistant commands, AI debounce, drip pause, campaign reply classification, and push notifications. Mac relay inbound needs the same side effects without duplicating business logic.
- `backend/app/main.py:489` includes the Telnyx webhook router. We need a Mac relay webhook router alongside it.
- `backend/app/core/config.py:43` has Telnyx settings. We need Mac relay URL/token/webhook settings and a text-provider selector.

## Proposed architecture

Add a provider-neutral text messaging layer with two concrete providers:

- Telnyx provider: current implementation and behavior remain the default.
- Mac relay provider: calls our self-hosted Mac HTTP daemon, which invokes `imsg send` and streams `imsg watch --json` inbound events back to the backend.

The backend should expose a stable interface all workers call: `send_message(...) -> Message` plus `close() -> None`. The Mac relay sender should reuse the existing idempotency and message persistence contract so campaigns remain crash-safe. Provider IDs from the Mac relay should be prefixed, for example `mac-relay:<guid-or-client-id>`, to avoid collisions with Telnyx IDs under the existing unique constraint on `messages.provider_message_id`.

## Backend implementation design

Create `backend/app/services/telephony/text_provider.py`:

- Define a `TextMessageProvider` protocol matching the existing `TelnyxSMSService.send_message()` and `close()` signatures.
- Add `get_text_message_provider()` that returns `MacRelayMessageService` only when settings select Mac relay and the Mac relay URL/token are present; otherwise return `TelnyxSMSService`.
- Add an optional `preferred_provider` argument so later flows can explicitly force Telnyx fallback.

Create `backend/app/services/telephony/mac_relay.py`:

- Implement `MacRelayMessageService` using `httpx.AsyncClient` against `settings.mac_relay_base_url`.
- Keep the same public `send_message()` signature as `TelnyxSMSService`.
- Extract shared message persistence from `TelnyxSMSService` into helper methods or add small configurable attributes to `TelnyxSMSService` so the Mac service can reuse `_get_or_create_conversation()` and the idempotent row creation logic without copying 150 lines.
- Send relay payload `{to, from, text, service, client_message_id}` to `POST /v1/messages`.
- Use `service="imessage"` by default for blue-bubble intent. Allow `auto` only if we intentionally want green SMS fallback through the iPhone/Mac.
- Mark local message `sent` when the relay accepts and Messages.app handoff succeeds. Do not claim delivered/read because public Messages automation does not expose reliable delivery receipts.
- On relay 4xx/5xx/network failure, set `MessageStatus.FAILED` and store `error_message`, matching Telnyx semantics.

Refactor `backend/app/services/telephony/telnyx.py` carefully:

- Add `MessageChannel.IMESSAGE = "imessage"` in `backend/app/models/conversation.py` first.
- Add constructor attributes such as `message_channel`, `conversation_channel`, `service_name`, and `provider_payload_type`, defaulting to current SMS/Telnyx behavior.
- Replace hardcoded `channel="sms"` for created `Message` rows and new `Conversation` rows with these attributes.
- Set `conversation.last_message_direction = "outbound"` in outbound send if it is currently missing; inbound already updates preview/unread but should also set `last_message_direction = "inbound"` if not already handled elsewhere.
- Keep Telnyx `_post_message()` and all tests passing.

Create `backend/app/api/webhooks/mac_relay.py` and `backend/app/api/webhooks/mac_relay_handlers.py`:

- Accept `POST /webhooks/mac-relay/messages` from the Mac daemon.
- Authenticate with a shared bearer token or HMAC header from settings. Start with bearer token because the Mac daemon is ours and can live behind Tailscale; keep HMAC as a follow-up if needed.
- Parse payload fields from our daemon: `event_id`, `message_id` or `guid`, `from`, `to`, `text`, `created_at`, `is_from_me`, `service`, and optional `chat_guid`.
- Ignore outbound echo events (`is_from_me=true`) initially or use them only to reconcile provider IDs. Inbound echo handling is risky because backend already writes outbound messages on send.
- For inbound messages, look up workspace by `PhoneNumber.phone_number == to_number`, then call a provider-neutral inbound helper modeled after `TelnyxSMSService.process_inbound_message()` with `channel=MessageChannel.IMESSAGE` and provider ID prefix `mac-relay:<guid>`.
- Reuse the same downstream side effects from Telnyx inbound: approval commands, operator assistant command routing, AI response scheduling, drip pause, campaign reply handling, and push notifications. Prefer extracting that common logic into `backend/app/services/telephony/inbound_text.py` so both Telnyx and Mac relay call it.

Update models and migrations:

- `backend/app/models/conversation.py`: add `MessageChannel.IMESSAGE = "imessage"`.
- `backend/app/models/phone_number.py`: add `provider` with default `telnyx`, `imessage_enabled` default `false`, `mac_relay_sender_id` nullable string, `mac_relay_service` default `imessage`, and maybe `sms_enabled` can remain true for Telnyx fallback.
- New Alembic migration after `20260519_outbound_compliance_controls` adding phone number fields and indexes. No enum DB migration is needed for `messages.channel` because the project uses non-native enum without constraints, but existing code must include the new enum value.
- Update `backend/app/models/__init__.py` only if adding new model classes; likely not needed.

Update worker senders:

- Replace direct `TelnyxSMSService(settings.telnyx_api_key)` construction with `get_text_message_provider()` in campaign, automation, followup, message test, and never-booked workers.
- Preserve Telnyx behavior when settings are default or Mac relay is not configured.
- Make number pool selection prefer `PhoneNumber.imessage_enabled` identities when Mac relay is selected, but keep current active/SMS-enabled logic as fallback. If this is too large for phase one, use provider factory only and document that the selected `from_phone.phone_number` must match an iMessage alias on the relay Mac.

Create a self-hosted Mac relay daemon script:

- Add `scripts/mac_imessage_relay.py` as a Python 3.12+ FastAPI app or standard-library HTTP server. Prefer FastAPI only if already available in backend dependencies when running on the Mac; otherwise avoid adding a new dependency by using Python stdlib plus subprocess.
- Endpoints: `GET /healthz`, `POST /v1/messages`, and optional `POST /v1/webhooks/test`.
- `POST /v1/messages` validates bearer token, validates E.164-ish recipient, runs `imsg send --to <to> --text <text> --service <service> --json`, captures stdout/stderr/exit code, and returns `{id, status, raw}`.
- Include a watch mode command or companion function that runs `imsg watch --json`, parses one JSON object per line, and POSTs inbound events to `settings.mac_relay_backend_webhook_url` with bearer token.
- Document running it behind Tailscale or localhost tunnel; do not expose it directly to the public internet.

## Risks and mitigations

- Apple can change Messages.app automation behavior. Mitigation: keep Telnyx fallback and make Mac relay a configurable provider.
- Public `imsg send` handoff is not delivery/read receipt. Mitigation: only mark `sent`, not `delivered`.
- Outbound echo from `imsg watch` can double-ingest messages. Mitigation: ignore `is_from_me=true` events at first.
- Mac sleep or Messages logout stops relay. Mitigation: health endpoint plus backend logging; future worker can monitor relay health.
- Telnyx number mismatch can confuse conversations. Mitigation: create explicit Mac relay sender identities in `phone_numbers` and do not assume existing Telnyx DIDs can send blue bubbles.
- High-volume iMessage campaigns may trigger Apple account anti-abuse systems. Mitigation: reuse existing compliance, approval, quiet-hour, number pool, warming, and rate-limit gates; keep daily caps conservative.

## Verification criteria

- Unit tests prove provider factory defaults to Telnyx and selects Mac relay only when configured.
- Unit tests prove Mac relay sender sends the expected `POST /v1/messages` payload and stores local messages as `channel=imessage` with provider IDs prefixed by `mac-relay:`.
- Unit tests prove Mac relay inbound webhook dedupes by provider ID, ignores outbound echo, and reuses shared inbound side effects.
- Existing Telnyx idempotency tests continue passing.
- `cd backend && uv run ruff check app && uv run mypy app` pass after backend edits.
- If a backend server is running, hit `POST /webhooks/mac-relay/messages` via `.gg/eyes/http.sh` with an authenticated sample payload and confirm non-500 response shape.
- On a Mac with `imsg` installed, run `python scripts/mac_imessage_relay.py serve`, then send a test through `POST /v1/messages` to a consenting internal test number and confirm it appears in Messages as iMessage when the recipient is reachable.

## Steps

1. Add `MessageChannel.IMESSAGE` and Mac relay sender fields to `PhoneNumber`, plus an Alembic migration with safe defaults and indexes.
2. Refactor `TelnyxSMSService` so message/conversation channel and provider logging are configurable without changing default Telnyx behavior.
3. Add `MacRelayMessageService` that uses the shared persistence path and calls the Mac relay HTTP API with idempotency-safe `client_message_id` values.
4. Add `TextMessageProvider` and `get_text_message_provider()` factory, defaulting to Telnyx and selecting Mac relay only when configured.
5. Replace direct `TelnyxSMSService` construction in text-sending workers with the provider factory while preserving all current arguments and close semantics.
6. Extract shared inbound text side effects from the Telnyx webhook path into a reusable helper.
7. Add authenticated Mac relay webhook routes that process inbound relay events as `imessage`, ignore outbound echoes, and reuse the shared inbound helper.
8. Register the Mac relay webhook router in `backend/app/main.py` and add Mac relay settings in `backend/app/core/config.py`.
9. Add `scripts/mac_imessage_relay.py` with authenticated `GET /healthz`, `POST /v1/messages`, and watch/webhook forwarding around `imsg`.
10. Add backend unit tests for provider selection, Mac relay send persistence/payload mapping, inbound webhook auth/dedupe/echo behavior, and Telnyx regression coverage.
11. Run `cd backend && uv run ruff check app && uv run mypy app`, fix all issues, then run focused pytest files for telephony/webhooks if available.
12. If runtime services are available, verify the new webhook with `.gg/eyes/http.sh` and document local Mac relay smoke-test commands.