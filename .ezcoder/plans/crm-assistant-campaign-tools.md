# CRM Assistant Campaign Lifecycle Tools Plan

## Context

The CRM assistant currently defines `start_campaign` in `backend/app/services/ai/crm_assistant/_tools.py` and implements it directly in `CRMToolExecutor._start_campaign()` in `backend/app/services/ai/crm_assistant/_tool_executor.py` (lines 438-464). Campaign API lifecycle logic already exists in `backend/app/api/v1/campaigns.py`:

- `start_campaign()` lines 149-184: draft/paused/scheduled -> `CampaignStatus.RUNNING`, requires contacts, sets `started_at`, guarantee pending.
- `pause_campaign()` lines 187-207: running -> `CampaignStatus.PAUSED`.
- `resume_campaign()` lines 210-230: paused -> `CampaignStatus.RUNNING`.
- `get_analytics()` lines 335-369: summarizes campaign totals and rates.

Workers only process `CampaignStatus.RUNNING` campaigns (`backend/app/workers/base_campaign_worker.py` lines 71-83). Existing worker-compatible statuses are the `CampaignStatus` enum in `backend/app/models/campaign.py` lines 44-52: `draft`, `scheduled`, `running`, `paused`, `completed`, `canceled`.

Approval gating exists in `CRMToolExecutor.execute()` but `_APPROVAL_GATED_TOOLS` only includes `start_campaign` for lifecycle actions. Queued assistant actions are stored as `crm_assistant.<function_name>` in `_queue_pending_action()` lines 55-61, but `ApprovalGateService._dispatch_action()` only supports `book_appointment` and `send_sms`, so approved queued CRM assistant actions currently cannot execute.

KenCode MCP examples for `start_campaign` are mostly simple lifecycle delegations (e.g. Celery task loads campaign then calls `campaign.start()`), supporting the approach of extracting and reusing one canonical service method rather than duplicating endpoint/tool behavior.

## Design

Create a shared backend service module for campaign lifecycle actions so API routes, CRM assistant tools, and approval-worker execution use the same state transitions and contact-count validation.

Proposed file: `backend/app/services/campaigns/campaign_lifecycle.py`

Functions:

- `get_campaign_for_workspace(db, campaign_id, workspace_id) -> Campaign | None`
- `start_campaign(db, campaign, contact_count: int | None = None) -> CampaignLifecycleResult`
- `pause_campaign(campaign) -> CampaignLifecycleResult`
- `resume_campaign(campaign) -> CampaignLifecycleResult`
- `summarize_campaign(campaign) -> dict[str, Any]`
- `count_campaign_contacts(db, campaign_id) -> int`

Use a small frozen dataclass `CampaignLifecycleResult` with `status: CampaignStatus`, `message: str`, `contact_count: int | None = None`. Raise domain-specific `CampaignLifecycleError(message: str)` for invalid transitions and no-contact starts/resumes. The API can translate that to `HTTPException(400)`, while tools return structured `success=False`.

`start_campaign` and `resume_campaign` must set `CampaignStatus.RUNNING` exactly, not `active`, preserving worker compatibility. `pause_campaign` must set `CampaignStatus.PAUSED`. `start_campaign` should preserve the current behavior: allow `draft`, `paused`, `scheduled`; set `started_at=datetime.now(UTC)`; set `guarantee_status="pending"` when `guarantee_target > 0`. `resume_campaign` should require paused and require at least one campaign contact because it is send-capable.

## File Changes

- `backend/app/services/campaigns/campaign_lifecycle.py`
  - Add shared state-machine and summary helpers.
  - Keep DB flush/commit out of the service helpers except contact-count queries so API/tool callers own transaction boundaries.

- `backend/app/api/v1/campaigns.py`
  - Import shared lifecycle helpers.
  - Replace duplicated start/pause/resume transition logic with the helper functions, keeping endpoint response shapes compatible (`{"status": "running", "message": ...}` etc.).
  - Keep API commits in the route functions.
  - Optionally use `summarize_campaign()` in `get_analytics()` only if it preserves the existing `CampaignAnalytics` response model exactly.

- `backend/app/services/ai/crm_assistant/_tools.py`
  - Add `pause_campaign`, `resume_campaign`, and `summarize_campaign` tool definitions.
  - Update `start_campaign` description to emphasize explicit confirmation because it can send messages/calls.
  - Add `confirmed` to `resume_campaign` and mark it required by safety policy in the description. `pause_campaign` and `summarize_campaign` do not require confirmation.

- `backend/app/services/ai/crm_assistant/_tool_executor.py`
  - Add `resume_campaign` to `_APPROVAL_GATED_TOOLS`; leave `pause_campaign` and `summarize_campaign` ungated.
  - Add handlers in `execute()` for `pause_campaign`, `resume_campaign`, `summarize_campaign`.
  - Update `_describe_pending_action()` for `resume_campaign`.
  - Replace `_start_campaign()` internals with shared lifecycle helper calls.
  - Implement `_pause_campaign()` using shared lifecycle helper.
  - Implement `_resume_campaign()` using shared lifecycle helper and contact-count validation.
  - Implement `_summarize_campaign()` using shared summary helper and contact status counts.
  - Return summary data including id, name, status, type, total_contacts, messages/calls stats, replies, qualifications, opt-outs, appointments, guarantee status, started/completed timestamps, and calculated reply/delivery/qualification rates.

- `backend/app/services/approval/approval_gate_service.py`
  - Add dispatch support for `crm_assistant.start_campaign` and `crm_assistant.resume_campaign` so actions queued by CRMToolExecutor can execute after approval.
  - Implement `_execute_crm_assistant_campaign_lifecycle()` that reads `campaign_id`, scopes by `action.workspace_id`, calls shared lifecycle helpers, commits through the existing approval-worker transaction path, and returns a structured result.
  - Do not add pause here because pause is not approval-gated.

- Tests
  - Update `backend/tests/services/ai/crm_assistant/test_tool_executor.py` parity expectations to include all current tool names or derive them from the executor dispatch table if a helper is exposed.
  - Add tests that:
    - `start_campaign` without `confirmed` returns `pending_approval=True` and does not change status.
    - `resume_campaign` without `confirmed` returns `pending_approval=True`.
    - `pause_campaign` does not require approval and changes running -> paused.
    - `resume_campaign` with `confirmed=True` changes paused -> running.
    - `summarize_campaign` returns calculated rates and status counts.
    - invalid lifecycle transitions return structured errors.
  - Add focused tests for the new lifecycle service if model-based executor tests become too mock-heavy.
  - Add approval dispatch tests for approved `crm_assistant.start_campaign` / `crm_assistant.resume_campaign` if existing approval tests are practical; otherwise test the private dispatch handler with mocked DB/action.

## Risks

- Existing test `test_tool_spec_handler_parity` is stale: it does not include already-defined tools such as `send_initial_message`, offers, and agent mutations. Updating it may uncover intended drift. Prefer deriving dispatch names from a class-level handler map to avoid future false failures.
- `ApprovalGateService` currently uses stdlib logging and supports different payload shapes for `send_sms`; assistant pending actions store `campaign_id`, so lifecycle dispatch must not assume Telnyx payload fields.
- SQLAlchemy enum comparisons are mixed in the repo (`Campaign.status == "running"` and `Campaign.status == CampaignStatus.RUNNING`). New code should use `CampaignStatus` enum values to preserve worker compatibility.
- `resume_campaign` is send-capable because workers immediately process `running` campaigns; it must be approval-gated exactly like `start_campaign`.

## Verification Criteria

- `pause_campaign`, `resume_campaign`, and `summarize_campaign` appear in `get_crm_tools()` and dispatch successfully from `CRMToolExecutor.execute()`.
- Unconfirmed `start_campaign` and `resume_campaign` queue pending actions instead of changing campaign status.
- Confirmed `start_campaign`/`resume_campaign` set `CampaignStatus.RUNNING`; `pause_campaign` sets `CampaignStatus.PAUSED`.
- API routes and assistant tools share the same transition validation and worker-compatible statuses.
- Approved pending actions of type `crm_assistant.start_campaign` and `crm_assistant.resume_campaign` execute through approval worker dispatch.
- Run: `cd backend && uv run ruff check app && uv run mypy app`.

## Steps

1. Add `backend/app/services/campaigns/campaign_lifecycle.py` with shared campaign lookup, contact counting, start/pause/resume transition helpers, summary helper, result dataclass, and lifecycle exception.
2. Refactor `backend/app/api/v1/campaigns.py` start/pause/resume endpoints to call the shared lifecycle helpers and translate lifecycle errors into 400 responses while preserving response shapes.
3. Extend `backend/app/services/ai/crm_assistant/_tools.py` with `pause_campaign`, `resume_campaign`, and `summarize_campaign` tool specs, making only start/resume confirmation-gated.
4. Extend `backend/app/services/ai/crm_assistant/_tool_executor.py` with pause/resume/summarize handlers, gate `resume_campaign`, reuse the lifecycle helpers for all state transitions, and update pending-action descriptions.
5. Extend `backend/app/services/approval/approval_gate_service.py` to dispatch approved `crm_assistant.start_campaign` and `crm_assistant.resume_campaign` actions through the shared lifecycle helpers.
6. Add or update backend tests for CRM tool specs, approval gating, lifecycle transitions, campaign summary output, invalid transitions, and approved pending-action dispatch.
7. Run focused pytest tests for the modified campaign assistant/approval/lifecycle areas and fix failures.
8. Run `cd backend && uv run ruff check app && uv run mypy app` and fix all reported issues.
