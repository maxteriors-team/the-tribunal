# Weekly/Daily AI Outbound Improvement Suggestions Plan

## Goal

Add a backend-only automated suggestion system that runs daily/weekly, analyzes outbound campaign and prompt performance, identifies the best-performing segment/angle/message/responder agent, recommends follow-up campaigns, and queues those recommendations as `PendingAction` rows for human approval. The implementation should reuse existing campaign reports, prompt stats, improvement suggestion concepts, and pending-action approval workflow without adding frontend scope.

## Existing Systems to Reuse

- `backend/app/models/campaign_report.py` already stores AI post-mortem fields: `recommendations`, `segment_analysis`, `timing_analysis`, `prompt_performance`, and `generated_suggestion_ids`.
- `backend/app/services/ai/campaign_report_service.py` already gathers campaign metrics and performs LLM analysis for completed campaigns.
- `backend/app/models/prompt_version_stats.py` and `backend/app/workers/prompt_stats_worker.py` already aggregate daily prompt metrics.
- `backend/app/models/improvement_suggestion.py` and `backend/app/services/ai/prompt_improvement_service.py` already represent prompt-level improvement suggestions.
- `backend/app/models/pending_action.py` and `backend/app/services/approval/approval_gate_service.py` are the canonical HITL approval queue.
- `backend/app/workers/__init__.py` is the worker registry entry point.

## Design

Create a new service `backend/app/services/ai/outbound_improvement_suggestion_service.py` with dataclasses for evidence and generated suggestions. It will query completed campaign reports and recent campaigns over a configurable period (`daily` = previous day, `weekly` = previous seven days), compute best performers deterministically where possible, use report recommendations as structured evidence, and call OpenAI only for synthesizing campaign recommendations from those existing findings. The service will produce `PendingAction` rows with a new action type such as `outbound_improvement.follow_up_campaign` and `require_approval_without_agent=True` when no responder agent is tied to the recommendation.

The pending action payload should be reviewable and executable-safe. Initial implementation should create approval suggestions, not auto-create campaigns. Payload fields should include `period`, `source_campaign_ids`, `source_report_ids`, `best_segment`, `best_angle`, `best_message`, `best_responder_agent`, `recommended_campaign`, `evidence`, and `confidence`. Context should include `source: "outbound_improvement_suggestions"`, `period`, and source IDs for deduplication/auditing.

Deduplication should prevent duplicate pending recommendations per workspace/period/source report set while earlier pending/approved/executed rows still exist. Use a deterministic `dedupe_key` stored inside `PendingAction.context`, since the pending actions table currently has no dedicated idempotency column.

A new worker `backend/app/workers/outbound_improvement_suggestion_worker.py` should run daily. It should invoke daily generation every cycle and weekly generation only on a stable weekday (Monday UTC) or through an injectable date for tests. It should subclass `RetryableWorker` and `BaseWorker`, mirror retry settings from `PromptImprovementWorker`, and be registered in `backend/app/workers/__init__.py` after prompt/report-related workers and before approval worker so approval notifications can process the created pending actions.

Approval execution should be conservative. `ApprovalGateService._dispatch_action()` can support the new action type by marking it as accepted/no-op with the recommendation payload, or leave it unsupported if product intent is approval-as-acknowledgement. Prefer adding an explicit `_execute_outbound_follow_up_campaign_suggestion()` handler that returns `{"status": "acknowledged", "recommendation": ...}` so approved actions do not become failed.

Extend `CampaignReport.generated_suggestion_ids` usage by updating reports whose evidence generated pending actions. No schema change is required for campaign reports. A migration is likely unnecessary unless we decide to add columns; avoid schema changes by using `PendingAction.context` for dedupe metadata.

## Tests

Add focused backend tests, mainly unit-style with mocked async DB/OpenAI where possible:

- `backend/tests/services/ai/test_outbound_improvement_suggestion_service.py` for pure helpers: rate calculations, best campaign/segment/timing/prompt extraction, LLM JSON parsing fallback, pending-action payload shape, and dedupe query behavior.
- `backend/tests/workers/test_outbound_improvement_suggestion_worker_retryable.py` mirroring `test_prompt_improvement_worker_retryable.py` for inheritance, retry config, and DLQ routing.
- `backend/tests/services/approval/test_outbound_improvement_pending_action_execution.py` for the new approval dispatch handler, if added.

## Risks

- Existing campaign reports may contain loose `dict[str, Any]` shapes, so parsing must be defensive and tolerate missing fields.
- There is no current segment ID on campaign contacts in the inspected model, so “best-performing segment” should be inferred from `CampaignReport.segment_analysis` rather than inventing a new join.
- There is no current “angle” column, so “best angle” should be inferred from report recommendations/what_worked/key_findings and campaign `initial_message`/fallback template evidence.
- Pending actions can be approved repeatedly if dedupe is weak; use a stable dedupe key in `context` and query existing pending/approved/executed rows before creating.
- LLM calls in a daily worker can create cost/noise; cap suggestions per workspace/period and skip periods below minimum evidence thresholds.

## Verification Criteria

- Backend lint: `cd backend && uv run ruff check app`.
- Backend type check: `cd backend && uv run mypy app`.
- Relevant tests: run new/changed pytest files under `backend/tests/services/ai`, `backend/tests/services/approval`, and `backend/tests/workers`.
- If backend API routes are not changed, no `http.sh` probe is required. If `ApprovalGateService` execution behavior changes, no route is modified but tests should prove approved action execution no longer returns unsupported type.

## Steps

1. Create `backend/app/services/ai/outbound_improvement_suggestion_service.py` with typed dataclasses, period window helpers, campaign/report evidence queries, defensive report-field parsers, best performer extraction helpers, LLM synthesis, pending-action dedupe, pending-action creation, and report `generated_suggestion_ids` updates.
2. Add `backend/app/workers/outbound_improvement_suggestion_worker.py` that runs daily, generates daily suggestions every cycle, generates weekly suggestions on Monday UTC, uses retry handling per workspace/period, commits on success, and logs counts/failures with structured fields.
3. Register the new worker in `backend/app/workers/__init__.py` by importing its registry and adding it to `ALL_REGISTRIES` before `approval_registry`.
4. Update `backend/app/services/approval/approval_gate_service.py` to dispatch `outbound_improvement.follow_up_campaign` approvals to an explicit acknowledgement handler so approved recommendation actions execute cleanly instead of failing as unsupported.
5. Add tests in `backend/tests/services/ai/test_outbound_improvement_suggestion_service.py` covering deterministic best performer extraction, payload/context shape, dedupe skip behavior, and report suggestion ID updates using lightweight mocks or async-session fixtures matching existing test patterns.
6. Add `backend/tests/workers/test_outbound_improvement_suggestion_worker_retryable.py` covering `RetryableWorker`/`BaseWorker` inheritance, component/retry config, and failed workspace processing DLQ routing.
7. Add `backend/tests/services/approval/test_outbound_improvement_pending_action_execution.py` covering approved `outbound_improvement.follow_up_campaign` execution returns an acknowledged status and preserves recommendation payload metadata.
8. Run the relevant pytest files, fix failures, then run `cd backend && uv run ruff check app` and `cd backend && uv run mypy app` and fix all reported issues.
