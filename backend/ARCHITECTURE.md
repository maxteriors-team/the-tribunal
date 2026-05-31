# Backend Architecture

The AI CRM backend is a FastAPI service that orchestrates AI voice agents, SMS
campaigns, and Cal.com appointment booking on top of PostgreSQL and Redis. It
is multi-tenant by `workspace_id`, async end-to-end (SQLAlchemy 2 async +
asyncio workers), and integrates with Telnyx (telephony), OpenAI/xAI Grok
Realtime (voice AI), ElevenLabs (TTS), Cal.com (scheduling), and Resend
(email).

This document is grounded in the code in `backend/app/`. When the code and
this doc disagree, the code wins — please update the doc.

---

## 1. High-Level System Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │                  CLIENTS                    │
                    │  Next.js dashboard · embedded widget · CLI  │
                    └────────────────────┬────────────────────────┘
                                         │ HTTPS / WSS
                                         ▼
   ┌──────────────────────────────────────────────────────────────────────┐
   │                       FastAPI app (app/main.py)                      │
   │                                                                      │
   │  Middleware: SecurityHeaders · CORS · global exception handlers      │
   │  ────────────────────────────────────────────────────────────────    │
   │  /api/v1/*       43 resource routers   (app/api/v1/router.py)        │
   │  /webhooks/*     Telnyx · Cal.com · Resend                           │
   │  /voice-bridge   WebSocket μ-law ⇄ PCM16 (app/websockets/)           │
   │  /static/*       Lead-magnet assets                                  │
   │  /r/{slug}       Public short-link redirects                         │
   └────────┬──────────────┬──────────────┬──────────────┬────────────────┘
            │              │              │              │
            ▼              ▼              ▼              ▼
   ┌────────────────┐ ┌──────────┐ ┌────────────┐ ┌─────────────────┐
   │  Services      │ │ Workers  │ │ WebSockets │ │ External APIs   │
   │  app/services/ │ │ 17 types │ │ voice      │ │ OpenAI, Telnyx, │
   │  24 domains    │ │ polling  │ │ bridge     │ │ Cal.com, 11Labs │
   └────────┬───────┘ └─────┬────┘ └─────┬──────┘ │ Resend, FUB     │
            │               │            │        └────────┬────────┘
            └───────────────┴────────────┴─────────────────┘
                            │                    │
                            ▼                    ▼
                  ┌──────────────────┐  ┌─────────────────┐
                  │  PostgreSQL 17   │  │    Redis 7      │
                  │  async SQLA 2    │  │  rate limits,   │
                  │  Alembic migr.   │  │  number pool,   │
                  └──────────────────┘  │  opt-outs       │
                                        └─────────────────┘
```

The HTTP app, workers, and the voice WebSocket can run in the **same process**
for the default local/single-replica topology — workers are started/stopped by
`lifespan` in `app/main.py` via
`app/workers/__init__.py::start_all_workers()` when `RUN_BACKGROUND_WORKERS` is
`true`. Set `RUN_BACKGROUND_WORKERS=false` for API-only mode and run
`uv run backend-workers` from `backend/` as a separate single-replica worker
process.

---

## 2. Request Flows

### 2.1 Inbound Voice Call → AI Agent

```
PSTN caller
   │
   ▼
Telnyx ──HTTP POST──▶ /webhooks/telnyx/voice          (app/api/webhooks/telnyx.py)
                          │
                          │  call.initiated · call.answered · call.hangup
                          │  call.machine.detection.ended
                          ▼
                     telnyx_call_handlers
                          │  - resolve workspace + agent by called number
                          │  - create Message (channel=voice) row
                          │  - tell Telnyx to start media streaming
                          ▼
Telnyx Media WS ─────▶ /voice-bridge  (app/websockets/voice_bridge.py)
                          │
                          │  μ-law 8 kHz  ⇄  PCM16 24 kHz (3× resample)
                          │  app/services/audio/
                          ▼
                     voice_session_factory.create_voice_session()
                          │
                          ├── VoiceAgentSession        (OpenAI Realtime)
                          ├── GrokVoiceAgentSession    (xAI Grok)
                          └── ElevenLabsVoiceAgentSession (TTS-driven)
                          │
                          │  Tool calls (function calling)
                          ▼
                     tool_executor.create_tool_callback
                          │  - check_availability  ──▶ Cal.com
                          │  - book_appointment    ──▶ Cal.com
                          │  - send_dtmf, transfer_call ──▶ Telnyx
                          │  - lookup contact, save notes ──▶ DB
                          ▼
                     IVRGate decides if we’re in a phone tree, switches
                     to DTMF mode (app/services/ai/ivr/) when needed.

On hangup: handle_call_hangup persists the transcript via
save_call_transcript and enqueues transcript_analysis_worker.
```

Key files:
- `app/api/webhooks/telnyx.py`, `telnyx_call_handlers.py`, `telnyx_parser.py`
- `app/websockets/voice_bridge.py`
- `app/services/ai/voice_session_factory.py`, `voice_agent.py`,
  `elevenlabs_voice_agent.py`, `grok/session.py`
- `app/services/ai/tool_executor.py`, `voice_tools.py`
- `app/services/audio/` (PCM/μ-law conversion)
- `app/services/ai/ivr/` (DTMF / phone-tree gate)

### 2.2 SMS Campaign → Contact

```
User creates Campaign         POST /api/v1/workspaces/{ws}/campaigns
   │                          (app/api/v1/campaigns.py)
   ▼
Campaign row (status=running) in PostgreSQL
   │
   ▼
CampaignWorker (poll = settings.campaign_poll_interval)
   app/workers/campaign_worker.py
   │
   │  1. Find running campaigns within sending hours.
   │  2. Per campaign:
   │       - check rate limit via RateLimiter (Redis)
   │       - pick a sending number via NumberPoolManager (Redis)
   │       - load up to MAX_MESSAGES_PER_TICK pending CampaignContacts
   │       - filter against GlobalOptOut + OptOutManager (Redis)
   │  3. Resolve template, render variables, attach short links
   │       (app/services/messaging/link_shortener.py).
   │  4. TelnyxSMSService.send_message() → Telnyx REST API.
   │  5. Persist Message + update CampaignContact.status = sent.
   ▼
Telnyx delivery webhook (message.sent / message.finalized)
   │
   ▼
telnyx_message_handlers.handle_delivery_status
   - updates Message.status (delivered / failed)
   - feeds ReputationTracker (Redis) and PhoneNumberDailyStats

Contact replies → message.received
   │
   ▼
handle_inbound_message
   - upserts Conversation + Message
   - hands off to ai.text_agent + text_response_generator for AI reply
     (gated by ApprovalGateService when the agent requires HITL)
```

Worker is **idempotent on `provider_message_id`** — Telnyx retries on
non-2xx, so handlers re-raise as HTTP 500 to trigger retry rather than
silently swallowing errors (see comment in `app/api/webhooks/telnyx.py`).

Key files:
- `app/api/v1/campaigns.py`, `voice_campaigns.py`, `drip_campaigns.py`
- `app/workers/campaign_worker.py`, `voice_campaign_worker.py`,
  `drip_campaign_worker.py`, `base_campaign_worker.py`
- `app/services/telephony/telnyx.py` (SMS), `telnyx_voice.py` (calls)
- `app/services/rate_limiting/` (rate_limiter, number_pool, opt_out_manager,
  reputation_tracker, warming_scheduler)
- `app/services/ai/text_agent.py`, `text_response_generator.py`,
  `text_tool_executor.py`
- `app/services/approval/` (HITL gate + delivery)

### 2.3 Cal.com Webhook → Appointment

The `Opportunity` model is user-driven CRUD (`app/api/v1/opportunities.py`).
The closest webhook-to-record flow is the **Cal.com booking** path, which
produces an `Appointment` row tied to a `Contact` (and downstream may feed an
opportunity via the dashboard).

```
Cal.com event ──HTTP POST──▶ /webhooks/calcom/booking
                                  (app/api/webhooks/calcom.py)
                                       │
                                       │  verify_calcom_webhook (HMAC)
                                       ▼
                                  _EVENT_DISPATCH
                                       │
                ┌──────────────────────┼──────────────────────┐
                ▼                      ▼                      ▼
   handle_booking_created    handle_booking_rescheduled    handle_meeting_ended
   handle_booking_cancelled                                (no-show / completed)
                │
                │  app/api/webhooks/calcom_handlers.py
                ▼
   1. find_contact_by_attendee     (email/phone match in workspace)
   2. resolve_campaign_id          (was this driven by a campaign?)
   3. INSERT Appointment row       (status, scheduled_at, duration, uid)
   4. apply_contact_tag            ("booked", "no-show", …)
   5. send_lifecycle_sms           confirmation / reminder / follow-up
   6. send_appointment_booked_notification  (Resend email)
   7. push_notification_service.notify()    (device tokens)
   8. increment_completed_and_check_guarantee  (campaign guarantee tracker)

   Downstream workers pick up state changes:
   - reminder_worker          → 24h / 1h reminders
   - never_booked_worker      → re-engage contacts who didn’t book
   - noshow_reengagement_worker → after MEETING_ENDED with no-show
```

Key files:
- `app/api/webhooks/calcom.py`, `calcom_handlers.py`, `calcom_parser.py`,
  `calcom_events.py`
- `app/core/webhook_security.py` (HMAC verification)
- `app/services/calendar/calcom.py`, `booking.py`, `reminder_service.py`
- `app/services/campaigns/guarantee_tracker.py`

---

## 3. Data Model Overview

All tables are scoped by `workspace_id` (cascade delete). Models live in
`app/models/` — one model per file, re-exported from `app/models/__init__.py`.

```
Workspace ─┬─ WorkspaceMembership ── User
           ├─ WorkspaceIntegration       (encrypted credentials per provider)
           ├─ WorkspaceInvitation
           │
           ├─ Contact ─┬─ ContactTag ── Tag
           │           ├─ Conversation ── Message
           │           │                    └─ CallOutcome, CallFeedback,
           │           │                       BanditDecision, EmailEvent
           │           ├─ Appointment    (Cal.com booking)
           │           ├─ CampaignContact (status per campaign enrollment)
           │           ├─ DripEnrollment
           │           ├─ Opportunity (M2M via opportunity_contacts)
           │           ├─ TestContact   (message A/B tests)
           │           └─ PendingAction (HITL approval gate)
           │
           ├─ Agent ─┬─ PromptVersion ── PromptVersionStats
           │         ├─ HumanProfile      (persona attached to agent)
           │         └─ KnowledgeDocument
           │
           ├─ Campaign ─┬─ CampaignContact
           │            ├─ CampaignNumberPool
           │            └─ CampaignReport
           │
           ├─ DripCampaign ── DripEnrollment
           ├─ MessageTest ─┬─ TestVariant
           │               └─ TestContact
           │
           ├─ Pipeline ─┬─ PipelineStage
           │            └─ Opportunity ─┬─ OpportunityLineItem
           │                            └─ OpportunityActivity
           │
           ├─ PhoneNumber ── PhoneNumberDailyStats
           ├─ Offer ── OfferLeadMagnet ── LeadMagnet
           ├─ Automation ── AutomationExecution
           ├─ Segment, LeadSource, MessageTemplate
           ├─ ShortLink ── LinkClick
           ├─ HumanNudge, ImprovementSuggestion
           └─ AssistantConversation ── AssistantMessage  (in-app CRM assistant)

Cross-cutting (not workspace-scoped):
   GlobalOptOut, AuthRateLimit, RefreshToken, DemoRequest, DeviceToken
```

Identity / IDs:
- Most rows use `UUID` primary keys.
- `Contact.id` and `Message.id` use `BigInteger` for compactness and
  pagination by ID.
- Tenant-sensitive provider credentials inside `WorkspaceIntegration` are
  Fernet-encrypted with `ENCRYPTION_KEY` (see `app/core/encryption.py`).

Filtering and pagination:
- `app/services/contacts/contact_filters.py` is the canonical filter engine
  (`apply_contact_filters`, `FilterDefinition`). Opportunities and segments
  use the same pattern.
- `app/db/pagination.py` provides the shared `paginate()` helper for all
  list endpoints.

---

## 4. Workers / Background Jobs

All workers extend `BaseWorker` (`app/workers/base.py`) — an async polling
loop with `_on_start` / `_process_items` / `_on_stop` hooks and a singleton
`WorkerRegistry`. They are started together in `app/workers/__init__.py`
during FastAPI `lifespan` startup.

| Worker | Poll | Responsibility |
|---|---|---|
| `campaign_worker` | `campaign_poll_interval` | Send SMS campaign messages |
| `voice_campaign_worker` | 10 s | Initiate outbound voice calls (Telnyx) |
| `drip_campaign_worker` | — | Advance contacts through drip sequences |
| `followup_worker` | — | Send agent-decided follow-ups after silence |
| `reminder_worker` | — | Appointment reminders (24 h / 1 h / custom) |
| `message_test_worker` | — | Run multi-variant SMS A/B tests |
| `reputation_worker` | — | Roll up per-number reputation stats |
| `enrichment_worker` | — | Enrich Contact metadata from external sources |
| `prompt_stats_worker` | — | Aggregate PromptVersionStats |
| `prompt_improvement_worker` | — | Generate suggested prompt edits |
| `experiment_evaluation_worker` | — | Score multi-armed bandit experiments |
| `automation_worker` | — | Execute Automation rules (`AutomationExecution`) |
| `noshow_reengagement_worker` | — | Re-engage no-show contacts |
| `never_booked_worker` | — | Re-engage contacts who never booked |
| `nudge_worker` | — | Deliver `HumanNudge`s to the operator |
| `approval_worker` | 30 s | HITL: notify, execute, expire `PendingAction` |
| `transcript_analysis_worker` | — | Post-call transcript analysis + outcomes |
| `auth_rate_limit_cleanup_worker` | 1 h | Prune `auth_rate_limits` rows older than 24 h |

Shared infrastructure:
- `base_campaign_worker.py` — common loop for SMS and voice campaign workers
  (sending-hours, rate-limit checks, contact selection).
- `retryable.py` — decorator for transient-error retries.
- Idempotency keys live in domain code (e.g. `provider_message_id` for
  Telnyx, `booking_uid` for Cal.com).

Because workers and the API share a process, **horizontal scaling must
account for singleton-worker assumptions**. To run more than one app
replica, the worker registry needs leader election or workers need to be
split out — neither is in place today.

---

## 5. External Service Boundaries

| Service | Wrapper | Direction | Entry points |
|---|---|---|---|
| **Telnyx** (SMS) | `services/telephony/telnyx.py::TelnyxSMSService` | out · in webhook | `workers/campaign_worker.py`, `webhooks/telnyx_message_handlers.py` |
| **Telnyx** (Voice) | `services/telephony/telnyx_voice.py::TelnyxVoiceService` | out · in webhook · in WS | `workers/voice_campaign_worker.py`, `webhooks/telnyx_call_handlers.py`, `websockets/voice_bridge.py` |
| **OpenAI Realtime** | `services/ai/voice_agent.py::VoiceAgentSession` | bidirectional WS | `websockets/voice_bridge.py` via `voice_session_factory.py` |
| **xAI Grok Realtime** | `services/ai/grok/session.py::GrokVoiceAgentSession` | bidirectional WS | same factory as above |
| **ElevenLabs** | `services/ai/elevenlabs_tts.py`, `elevenlabs_voice_agent.py` | out | voice bridge (TTS), text agent (preview) |
| **Cal.com** | `services/calendar/calcom.py`, `booking.py` | out REST · in webhook | tool calls in `ai/tool_executor.py`, `webhooks/calcom.py` |
| **Resend** (email) | `services/email.py` | out | `webhooks/calcom_handlers.py`, nudges, lead-form, invitations |
| **Follow Up Boss** | `services/followupboss/`, `api/v1/integrations/followupboss.py` | out · sync | realtor onboarding flow |
| **Stripe** (billing) | `api/v1/billing.py` | out · in webhook | subscription / metered usage |
| **Redis** | `db/redis.py` | in-process | rate limits, number pool, opt-outs, reputation, warming |
| **PostgreSQL** | `db/session.py::AsyncSessionLocal` | in-process async | everywhere |

Boundary rules in use:
- **Webhook verification.** Telnyx (`telnyx_parser.verify_and_parse`),
  Cal.com (`core/webhook_security.verify_calcom_webhook`), and Resend each
  verify signatures before dispatch. The `skip_webhook_verification` flag
  is allowed only in `debug` mode; `main.py::_validate_startup_config`
  refuses to boot with default `SECRET_KEY` / `ENCRYPTION_KEY` in
  production.
- **Credential storage.** Per-tenant API keys live encrypted in
  `WorkspaceIntegration.credentials` (Fernet via `core/encryption.py`).
- **Idempotency at the edge.** Inbound webhooks key on
  `provider_message_id` / `booking_uid` so Telnyx and Cal.com retries are
  safe; voice handlers short-circuit on terminal hangup statuses.
- **Background dispatch.** Lifecycle SMS / push from webhook handlers is
  fired through `app/utils/background_tasks.spawn_background_task` so the
  webhook 200 is not blocked by downstream I/O.

---

## Conventions & Where Things Go

- **API routes** → `app/api/v1/<resource>.py`, registered in
  `app/api/v1/router.py`. Webhook routes live in `app/api/webhooks/`.
- **Models** → `app/models/<resource>.py`, one model per file, all listed
  in `app/models/__init__.py`.
- **Schemas** (Pydantic v2) → `app/schemas/`, mirrors model layout.
- **Services** → `app/services/<domain>/`, 24 domain folders. Reuse
  `contact_filters.py`-style filter engines for list endpoints.
- **Workers** → `app/workers/<name>_worker.py`, registered in
  `app/workers/__init__.py::ALL_REGISTRIES`.
- **Migrations** → `backend/alembic/versions/`. Run with
  `uv run alembic upgrade head`.
- **Config** → `app/core/config.py` (`settings`). Never read env vars
  outside of this module.
- **Logging** → `structlog`, always `logger.bind(context=...)` then
  `log.info("event_name", key=value)`. Never `print` or `f"…{x}"` into a
  log message.

When extending the backend, prefer the canonical primitives called out in
`CLAUDE.md` (`contact_filters`, `query-keys`/`query-options` on the
frontend, `PageLoadingState` etc.) and mirror the structure of the
nearest existing module rather than introducing a new pattern.
