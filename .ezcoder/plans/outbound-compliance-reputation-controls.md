# Outbound Compliance and Reputation Controls Plan

## Scope

Strengthen backend outbound controls for SMS/campaign/AI-initiated actions by extending existing rate limiting, opt-out, phone-number reputation, campaign worker, and pending-action systems. Changes are backend-only unless schema exposure requires follow-up UI wiring later.

## Current Code Map

- `backend/app/workers/campaign_worker.py:117-123` checks campaign per-minute rate only once before fetching a batch, then `backend/app/workers/campaign_worker.py:155-272` sends each initial SMS.
- `backend/app/workers/campaign_worker.py:307-313` repeats the campaign per-minute check for follow-ups, then `backend/app/workers/campaign_worker.py:353-448` sends follow-ups.
- `backend/app/services/rate_limiting/number_pool.py:36-168` selects a phone number and consumes per-second, hourly, and daily Redis counters before a message is actually sent. This is a bug-prone pattern because counters are consumed during selection and cannot be reverted when later compliance checks or Telnyx send fail.
- `backend/app/services/rate_limiting/rate_limiter.py:40-59` has the atomic Redis increment-with-limit Lua script, and `backend/app/services/rate_limiting/rate_limiter.py:178-222` already implements daily limits. Add campaign daily send caps here using the same pattern instead of introducing a parallel limiter.
- `backend/app/services/rate_limiting/opt_out_manager.py:41-63` checks only exact `GlobalOptOut.phone_number` values; `backend/app/services/rate_limiting/opt_out_manager.py:65-122` records keyword/campaign/message source but not opt-out source type/channel/context.
- `backend/app/models/opt_out.py:17-63` stores global opt-outs with keyword, source campaign, and source message but lacks source type/channel/actor/context fields.
- `backend/app/models/campaign.py:151-154` has `messages_per_minute` and `max_messages_per_contact`, but no campaign-wide total send cap. `backend/app/models/campaign.py:143-149` has sending windows, but no dedicated quiet-hour fields or enforcement reason.
- `backend/app/api/v1/campaigns.py:256-305` suppresses duplicates only within the same campaign through the DB unique constraint and application-side existing IDs; it does not return duplicate/opt-out/no-consent preview details.
- `backend/app/schemas/campaign.py:117-136` has minimal add/contact response schemas; previews need richer consent/source/compliance fields.
- `backend/app/models/contact.py:122-131` has lead source and source campaign, but no explicit SMS consent/status/source/timestamp fields.
- `backend/app/services/ai/crm_assistant/_tool_executor.py:32-40` approval-gates outbound AI tools, and `backend/app/services/ai/crm_assistant/_tool_executor.py:56-89` queues pending actions. It does not persist a durable audit row for AI outbound proposals/executions.
- `backend/app/models/pending_action.py:49-78` has payload/context/status/execution tracking that can be reused for audit context, but immutable audit logs should be separate from mutable pending-action status.
- `backend/app/services/approval/approval_gate_service.py:25-167` creates pending actions; `backend/app/services/approval/approval_gate_service.py:209-240` records execution results. Hook audit creation/update here for all AI-initiated outbound action proposals and outcomes.
- Existing tests to extend: `backend/tests/api/test_campaigns_validation.py`, `backend/tests/schemas/test_campaign_schemas.py`, `backend/tests/workers/test_campaign_worker_retryable.py`, and add service-level tests under `backend/tests/services/rate_limiting/` or `backend/tests/services/compliance/` if no closer sibling exists.

## Research Notes

KenCode MCP was used as requested. `exploreCodeSamples` for SMS compliance/rate-limit enforcement returned weak generic compliance results, then literal `searchCode` probes for `opt_out`, `daily_limit`, `quiet_hours`, and `do_not_contact` mostly found unrelated public code. I will therefore rely on this repo’s stronger existing implementations: Redis atomic increment in `RateLimiter`, opt-out manager, number reputation tracker, campaign worker idempotency keys, and pending action approval gate.

## Design

### Data Model and Migration

Create a new Alembic migration under `backend/alembic/versions/` depending on the current head after checking `uv run alembic heads` during implementation. The migration should add:

- Contact consent fields to `contacts`: `sms_consent_status` string with default `unknown`, `sms_consent_source` string nullable, `sms_consent_collected_at` timezone datetime nullable, `sms_consent_notes` text nullable. Add an index on `(workspace_id, sms_consent_status)` if Alembic supports it cleanly in this schema.
- Campaign caps/quiet-hour fields to `campaigns`: `max_messages_per_campaign` integer nullable, `quiet_hours_start` time nullable, `quiet_hours_end` time nullable, `quiet_hours_timezone` string nullable. Null cap means no explicit campaign-wide cap beyond existing per-minute/per-contact controls; null quiet hours means use existing sending-hours only.
- Opt-out source tracking to `global_opt_outs`: `source_type` string nullable, `source_channel` string nullable, `source_actor_type` string nullable, `source_actor_id` string nullable, `source_context` JSONB nullable.
- Compliance/audit state to `campaign_contacts`: `suppressed_reason` string nullable, `suppressed_at` timezone datetime nullable, `compliance_checked_at` timezone datetime nullable, `last_compliance_result` JSONB nullable.
- Immutable audit table `outbound_action_audit_logs` with UUID id, workspace_id FK, agent_id nullable FK, pending_action_id nullable FK, action_type, action_payload JSONB, compliance_result JSONB nullable, decision/status string, reason nullable text, source string, actor_user_id nullable integer FK, contact_id nullable bigint FK, campaign_id nullable UUID FK, message_id nullable UUID FK, created_at. Add indexes on workspace/created_at, pending_action_id, campaign_id, contact_id.

Update `backend/app/models/contact.py`, `backend/app/models/campaign.py`, `backend/app/models/opt_out.py`, `backend/app/models/pending_action.py` only if relationships are needed, and add a new `backend/app/models/outbound_action_audit_log.py`. Export the new model in `backend/app/models/__init__.py`.

### Compliance Service

Add `backend/app/services/compliance/outbound_compliance.py` with small dataclasses/Pydantic-style internal value objects:

- `OutboundComplianceRequest` containing workspace, campaign, campaign_contact, contact, channel, action_type, now.
- `OutboundComplianceResult` containing `allowed`, `reason`, `details`, and optional `next_allowed_at`.
- `OutboundComplianceService` methods for evaluating do-not-contact, consent, duplicate suppression, quiet hours, max campaign cap, and per-contact cap.

Rules:

- Do-not-contact: use `OptOutManager.check_opt_out` and set `CampaignContactStatus.OPTED_OUT` plus opted-out timestamps when true.
- Consent: block outbound SMS when `Contact.sms_consent_status` is not `opted_in` unless the campaign/action explicitly represents an already-approved manual/HITL action. For campaign workers, require opted-in.
- Duplicate suppression: before sending an initial campaign message, query for another `CampaignContact` in the same workspace/contact with outbound status or prior `conversation_id`/`first_sent_at` for the same campaign/channel, and also treat the unique `(campaign_id, contact_id)` as a preview duplicate. For follow-ups, rely on existing `messages_sent`, `last_reply_at`, and status but centralize the check in the service.
- Quiet hours: add helper that handles windows that cross midnight; if `quiet_hours_start <= quiet_hours_end`, block between them, otherwise block when current local time is after start or before end. Use `campaign.quiet_hours_timezone or campaign.timezone or "UTC"`.
- Campaign send cap: block if `campaign.max_messages_per_campaign` is not null and `campaign.messages_sent >= cap`; enforce again immediately before each send in the worker.
- Side effects: a helper `apply_suppression` should set `suppressed_reason`, `suppressed_at`, `compliance_checked_at`, `last_compliance_result`, contact status as appropriate, and increment `campaign.messages_failed` only for true send failures, not compliance suppressions.

### Rate Limiting and Number Budgets

Refactor `backend/app/services/rate_limiting/number_pool.py` to avoid consuming Redis counters during candidate selection unless a send will be attempted. Add a two-phase API:

- `peek_next_available_number(campaign, db)` checks health, warming, and current count capacity without incrementing.
- `reserve_number_for_send(phone, db)` consumes per-second/hourly/daily counters immediately before Telnyx send.

Alternatively, if keeping the existing API is lower risk, add `consume_rate_limit: bool = True` and call it with `False` before compliance checks; then reserve after compliance passes. Keep existing public behavior for unrelated callers.

Add `RateLimiter.check_and_increment_campaign_daily(campaign_id, daily_limit)` and `get_campaign_daily_count(campaign_id)` in `backend/app/services/rate_limiting/rate_limiter.py` using the existing `INCREMENT_WITH_LIMIT_SCRIPT` and UTC midnight expiry. Use this for `max_messages_per_campaign` so multiple worker instances cannot exceed the cap.

### Campaign Worker Integration

In `backend/app/workers/campaign_worker.py`:

- Instantiate `OutboundComplianceService` in `__init__`.
- In `_process_initial_messages`, evaluate compliance after loading each contact and before selecting/reserving a number. Store compliance result on `CampaignContact`.
- Re-check campaign daily cap atomically via `RateLimiter.check_and_increment_campaign_daily` immediately before send when `max_messages_per_campaign` is configured.
- Select/reserve the phone number after compliance passes. If reservation fails, leave the contact pending and break so the worker retries later.
- After successful send, keep existing idempotency, reputation increment, conversation assignment, and campaign stats behavior.
- In `_process_follow_ups`, run the same centralized compliance checks with action type `campaign_follow_up_sms`; block quiet hours, opt-out, per-contact caps, and campaign cap.
- Log structured compliance suppressions with campaign_id, campaign_contact_id, contact_id, reason, and action_type.

### API Preview and Schemas

Extend `backend/app/schemas/campaign.py`:

- `CampaignCreate`, `CampaignUpdate`, `CampaignResponse`, and duplicate campaign response with `max_messages_per_campaign`, `quiet_hours_start`, `quiet_hours_end`, and `quiet_hours_timezone`.
- `CampaignContactPreviewRequest` with `contact_ids`.
- `CampaignContactPreviewItem` with contact_id, phone_number, source, source_campaign_id, sms_consent_status, sms_consent_source, sms_consent_collected_at, duplicate_in_campaign, globally_opted_out, allowed, suppression_reasons.
- `CampaignContactPreviewResponse` with items and aggregate counts.
- `CampaignContactAdd` can optionally include `skip_suppressed: bool = True` only if existing frontend can tolerate it; otherwise add a separate preview endpoint and keep add behavior backward-compatible.

Add `POST /api/v1/campaigns/{campaign_id}/contacts/preview` in `backend/app/api/v1/campaigns.py` that verifies workspace ownership, loads contacts, computes duplicates and global opt-out status, includes consent/source fields, and returns a non-mutating preview.

Update `add_contacts` to suppress invalid duplicates more transparently by returning counts for `added`, `duplicates`, `not_found`, `opted_out`, `no_consent` if changing response shape is acceptable. If response compatibility is risky, keep the old response and add a new `add_contacts_detailed` endpoint; given existing response model is `dict[str, int]`, additional keys should be safe.

### Opt-Out Source Tracking

Update `OptOutManager.add_opt_out` signature in `backend/app/services/rate_limiting/opt_out_manager.py` with optional `source_type`, `source_channel`, `source_actor_type`, `source_actor_id`, and `source_context`, and persist them. Existing callers continue working because defaults are null.

Update `backend/app/services/campaigns/reply_handler.py` where `_record_opt_out` creates `GlobalOptOut` directly or via manager to populate source fields as inbound SMS/AI classifier/campaign reply. If it currently bypasses `OptOutManager`, route through manager unless that causes transaction commits at the wrong time; in that case create the model directly with the same source fields and no separate commit.

### AI Outbound Audit Logs

Add `backend/app/services/compliance/outbound_audit_logger.py` to create immutable audit rows.

Hook it into:

- `backend/app/services/ai/crm_assistant/_tool_executor.py:56-89` when queuing outbound pending actions (`send_sms`, `send_initial_message`, `start_campaign`, `resume_campaign`) with decision `pending_approval`.
- `backend/app/services/ai/crm_assistant/_tool_executor.py:140-146` when explicitly confirmed outbound actions execute without queueing, with decision `confirmed_execution_requested` before execution and `executed`/`failed` afterward where practical.
- `backend/app/services/approval/approval_gate_service.py:169-207` to audit approved/rejected decisions for outbound action types.
- `backend/app/services/approval/approval_gate_service.py:209-240` to update or append execution outcome audits for approved actions.

Do not mutate audit rows except possibly to attach message_id if it is only known after execution; safer approach is append-only rows for proposal, approval/rejection, execution.

### Tests

Add/extend backend tests:

- Migration smoke: rely on local Alembic upgrade, no dedicated migration unit unless project has one.
- `backend/tests/services/compliance/test_outbound_compliance.py` for opt-out block, no-consent block, quiet-hour block including midnight wrap, campaign cap block, per-contact cap block, and duplicate suppression.
- `backend/tests/services/rate_limiting/test_rate_limiter_campaign_daily.py` with Redis mocked/faked following existing rate limiter test style if present.
- `backend/tests/api/test_campaigns_validation.py` or new `backend/tests/api/test_campaign_contacts_preview.py` for preview response fields and add_contacts duplicate/opt-out/no-consent counts.
- `backend/tests/workers/test_campaign_worker_retryable.py` or new worker tests to assert suppressed contacts are not sent, opted-out contacts are marked opted_out, campaign caps stop additional sends, and phone number daily counters are not consumed when compliance blocks before send.
- `backend/tests/services/approval/test_outbound_audit_logs.py` or closest existing approval tests for pending/approved/rejected/executed audit creation.

## Risks

- The existing `NumberPoolManager.get_next_available_number` consumes Redis limits before send. Refactoring this incorrectly could under-throttle or over-throttle sends. Tests must pin that blocked compliance checks do not consume number budgets and successful sends do.
- Requiring `sms_consent_status == opted_in` for campaigns can suppress existing contacts until imports/backfills set consent. The migration should default to `unknown`; the preview will make this visible. If product expects legacy contacts to remain sendable, adjust the service to allow `unknown` only for non-AI/manual approved actions.
- Changing `add_contacts` response shape could affect frontend callers. Because it already returns an untyped dict, extra keys are probably safe, but preview endpoint is the main compatibility path.
- `OptOutManager.add_opt_out` currently commits internally. Avoid using it inside larger transactional reply handling if that commit would split transaction boundaries unexpectedly.
- Audit logs may capture payload PII. Store only necessary payload fields or redact phone/body if existing compliance/security conventions require it.

## Verification Criteria

- Run local migration from `backend`: `uv run alembic upgrade head` if a migration is added.
- Run targeted pytest files added/changed from `backend`.
- Run required backend checks: `uv run ruff check app` and `uv run mypy app`.
- After route/schema changes, if backend server is running, use `.gg/eyes/http.sh` against `/api/v1/campaigns/{campaign_id}/contacts/preview` with an authenticated test token if available; otherwise document that runtime probe could not be executed due to auth/server state.

## Steps

1. Check Alembic heads and nearest test patterns, then create the migration for contact consent, campaign caps/quiet hours, opt-out source tracking, campaign contact suppression metadata, and outbound audit logs.
2. Update SQLAlchemy models and schema exports for the new columns/table while keeping defaults backward-compatible.
3. Add `OutboundComplianceService` with quiet-hour, opt-out, consent, duplicate, per-contact, and campaign-cap evaluation plus suppression side-effect helpers.
4. Extend `RateLimiter` and `NumberPoolManager` for atomic campaign daily caps and non-consuming number selection followed by explicit reservation.
5. Integrate centralized compliance checks into initial SMS and follow-up paths in `CampaignWorker` without changing existing successful-send accounting/idempotency behavior.
6. Extend campaign schemas and add the contact preview endpoint with consent/source/duplicate/opt-out fields, then enhance add-contacts counts for duplicates and suppressions.
7. Extend opt-out source tracking through `OptOutManager` and campaign reply opt-out recording.
8. Add append-only outbound audit logging and hook it into CRM assistant pending-action creation, confirmed outbound execution, approval decisions, and approved-action execution outcomes.
9. Add targeted service, API, worker, and approval/audit tests covering the new compliance blocks and budget behavior.
10. Run `cd backend && uv run alembic upgrade head` if migration was added, targeted pytest files, `uv run ruff check app`, and `uv run mypy app`; fix all failures before marking the task done.