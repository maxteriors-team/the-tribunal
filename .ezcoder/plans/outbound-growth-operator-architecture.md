# Outbound Growth Operator Architecture

## Purpose

Design an AI-driven outbound growth operator that can plan, launch, monitor, and optimize CRM outbound motions across contacts, segments, offers, campaigns, drips, agents, opportunities, and pending human approvals.

The target is not a separate CRM. It should be an orchestration layer on top of the existing Tribunal primitives:

- contacts, conversations, calls, appointments
- text/voice agents and their tools
- offers and lead magnets
- dynamic segments
- SMS campaigns, voice campaigns, drip campaigns
- opportunities and pipelines
- pending actions / human-in-the-loop approval gates
- background workers and rate-limit/safety services

This repo uses the `.ezcoder` framework/toolchain. Keep all future planning/commands under `.ezcoder/`; do not recreate `.gg/commands` or `.claude/commands`.

## Research references from KenCode MCP

I used `exploreCodeSamples` first for “AI CRM copilot outbound orchestration with approval-gated tool use and campaign automation”; it did not find concrete CRM-specific samples, so I verified adjacent, working orchestration patterns with literal `searchCode` anchors:

1. **Approval/interrupt boundary pattern**
   - `akamai/patchdiff-ai`, `src/patchdiff_ai/graphs/interrupts.py`
   - Relevant pattern: graph nodes do not call `input()` directly; they yield typed interrupt payloads via `interrupt(request)`, the orchestrator surfaces them to a human interactor, then resumes with `Command(resume=Response(...))`.
   - Application here: the growth operator should not directly perform risky outbound mutations in the model loop. It should emit typed action proposals, persist them, and let the existing `PendingAction` + review UI/worker resume execution.

2. **Orchestrator resume loop**
   - `akamai/patchdiff-ai`, `src/patchdiff_ai/runtime/orchestrator.py`
   - Relevant pattern: the runtime watches for interrupt objects, dispatches them to the right human handler, and feeds the answer back through `Command(resume=...)`.
   - Application here: approved pending actions should resume a durable growth-run step, not just fire an isolated side effect. The operator needs a run/step table or equivalent durable state so an approval can continue `plan → draft → approve → execute → observe`.

3. **Tool registry / function dispatch pattern**
   - `NousResearch/hermes-agent`, `agent/transports/hermes_tools_mcp_server.py`
   - Relevant pattern: JSON-schema tool specs are converted into callable dispatch closures that route to a central `handle_function_call`.
   - Application here: keep CRM tools as explicit schemas with a central executor, but add typed categories and approval metadata instead of scattering outbound business rules in prompts.

4. **Composed tool toolkit pattern**
   - `langflow-ai/langflow`, `src/lfx/src/lfx/components/exa/exa_search.py`
   - Relevant pattern: a component builds a toolkit of narrow tools (`search`, `get_contents`, `find_similar`) over a client rather than one broad opaque tool.
   - Application here: define narrow CRM tools (`resolve_segment`, `draft_campaign`, `estimate_audience`, `queue_campaign_launch`, `pause_campaign`, `create_opportunity`) so approvals and audit logs are intelligible.

5. **Agent executor with explicit tool list**
   - `yarenty/kowalski`, `benchmark/scenario2_single_tool_use/run_langchain.py`
   - Relevant pattern: an agent executor receives a bounded set of tools and a prompt, then invokes the tool loop.
   - Application here: the current CRM assistant already follows this bounded tool-loop approach; the growth operator should extend it with stateful run orchestration, not replace it with an unbounded autonomous process.

## Current local capabilities

### CRM assistant

Files inspected:

- `backend/app/api/v1/crm_assistant.py`
- `backend/app/schemas/crm_assistant.py`
- `backend/app/models/assistant_conversation.py`
- `backend/app/services/ai/crm_assistant/_processor.py`
- `backend/app/services/ai/crm_assistant/_tools.py`
- `backend/app/services/ai/crm_assistant/_tool_executor.py`
- `backend/app/services/ai/crm_assistant/_summarizer.py`
- `frontend/src/app/assistant/page.tsx`
- `frontend/src/components/assistant/assistant-chat.tsx`
- `frontend/src/lib/api/assistant.ts`

What exists:

- In-app operator chat at `/assistant`.
- Persistent `AssistantConversation` and `AssistantMessage` history.
- OpenAI Chat Completions tool loop with:
  - max tool-turn cap (`MAX_TOOL_TURNS = 5`)
  - sequential tool execution against one async SQLAlchemy session
  - prompt-cache key per `(workspace_id, user_id)`
  - history repair for orphaned tool-call/tool-result pairs
  - history summarization when over token budget
- Current tools:
  - `search_contacts`
  - `create_contact`
  - `list_campaigns`
  - `list_agents`
  - `send_sms`
  - `get_conversation`
  - `list_recent_conversations`
  - `list_appointments`
  - `get_dashboard_stats`
  - `list_opportunities`

Important limitation:

- The assistant prompt says to confirm before sending SMS, but `_tool_executor._send_sms()` directly sends SMS and does not route through `ApprovalGateService` or `PendingAction`. This is prompt-level safety, not system-level safety.
- The assistant has read/list capabilities for campaigns, agents, opportunities, and appointments, but does not create/update/launch campaigns, resolve segments, generate offers, enroll drips, create opportunities, or inspect pending actions.
- The assistant response UI hides tool messages and only renders chat bubbles; it does not expose proposed plans, draft campaign artifacts, approval state, or run progress.

### Campaigns

Files inspected:

- `backend/app/models/campaign.py`
- `backend/app/api/v1/campaigns.py`
- `backend/app/api/v1/voice_campaigns.py` by discovery
- `backend/app/schemas/campaign.py` by discovery
- `backend/app/workers/base_campaign_worker.py` by discovery
- `backend/app/workers/campaign_worker.py`
- `backend/app/workers/voice_campaign_worker.py` by discovery
- `frontend/src/app/campaigns/page.tsx`
- `frontend/src/app/campaigns/new/page.tsx`
- `frontend/src/app/campaigns/sms/new/page.tsx` by discovery
- `frontend/src/app/campaigns/voice/new/page.tsx` by discovery
- `frontend/src/components/campaigns/*` by discovery
- `frontend/src/lib/api/campaigns.ts`, `sms-campaigns.ts`, `voice-campaigns.ts` by discovery

What exists:

- Campaign model supports SMS and `voice_sms_fallback` types.
- Status lifecycle: `draft`, `scheduled`, `running`, `paused`, `completed`, `canceled`.
- Contact enrollment via `CampaignContact` with statuses including `pending`, `sent`, `delivered`, `replied`, `qualified`, `opted_out`, `failed`, `completed`, and voice-specific states.
- Campaign metadata includes:
  - linked `agent_id`, `voice_agent_id`, SMS fallback agent
  - linked `offer_id`
  - sending windows/days/timezone
  - message/call rate limits
  - follow-up settings
  - voice fallback settings
  - denormalized stats
  - guarantee tracking
- `CampaignWorker` handles SMS campaigns with:
  - sending-window checks inherited from base worker
  - campaign-level Redis rate limit
  - number pool rotation
  - global opt-out checks
  - stable idempotency key for each initial send
  - Telnyx SMS dispatch
  - conversation assignment to campaign agent
  - follow-up scheduling
  - structured logging and retry behavior
- Campaign API supports listing, creating, reading, updating draft/paused campaigns, starting, pausing, resuming, canceling, and adding contacts.

Important limitation:

- Campaign launch is an immediate API mutation. There is no explicit pre-launch approval gate for “send to N contacts,” no generated campaign preview object, and no dry-run estimation endpoint.
- The current assistant can list campaigns but cannot draft, enroll contacts, start/pause, or analyze campaign performance through tools.

### Drip campaigns / reactivation

Files inspected:

- `backend/app/models/drip_campaign.py`
- `backend/app/api/v1/drip_campaigns.py`
- `backend/app/services/reactivation/drip_runner.py`
- `backend/app/services/reactivation/drip_bootstrap.py` by discovery
- `backend/app/workers/drip_campaign_worker.py`

What exists:

- `DripCampaign` defines multi-step SMS sequences in JSONB.
- `DripEnrollment` tracks per-contact progress.
- Lifecycle statuses:
  - campaign: `draft`, `active`, `paused`, `completed`
  - enrollment: `active`, `paused`, `responded`, `completed`, `cancelled`
- `DripCampaignWorker` runs every 15 minutes and delegates to `process_active_drip_campaigns()`.
- `drip_runner`:
  - processes due enrollments using row locks with `skip_locked`
  - checks sending windows
  - checks global opt-out
  - renders templates
  - resolves a from-number with conversation continuity
  - sends SMS via Telnyx using stable idempotency keys per `(enrollment, step)`
  - assigns an agent to conversations so replies move to AI handling
  - pauses drip cadence when inbound reply arrives

Important limitation:

- Drips are cadence executors, not strategy planners. There is no AI tool to propose sequence steps, preview audience impact, enroll a segment, or manage safety approvals around bulk enrollment.

### Agents and text/voice automation

Files inspected/discovered:

- `backend/app/models/agent.py`
- `backend/app/api/v1/agents.py`
- `backend/app/services/agents/agent_service.py`
- `backend/app/services/ai/text_agent.py`
- `backend/app/services/ai/text_tool_executor.py`
- `backend/app/services/ai/tool_executor.py`
- `backend/app/services/ai/voice_agent.py`
- `backend/app/services/ai/voice_agent_base.py`
- `backend/app/services/ai/voice_tools.py`
- `backend/app/services/telephony/voice_agent_resolver.py`
- `frontend/src/app/agents/page.tsx`
- `frontend/src/app/agents/create/page.tsx` by discovery
- `frontend/src/app/agents/[id]/page.tsx` by discovery
- `frontend/src/components/agents/*` by discovery

What exists:

- Agents support voice/text/both channel modes.
- Voice provider configuration supports OpenAI/ElevenLabs.
- Agents have:
  - system prompt, temperature, max tokens
  - enabled tools and tool settings
  - Cal.com event type ID
  - IVR navigation settings
  - recording settings
  - reminder/no-show/post-meeting/value-reinforcement/never-booked follow-up settings
  - embed settings
  - auto-suggestion/evaluation/improvement fields
- Text/voice agent services already execute inbound conversation behavior and appointment tooling.

Important limitation:

- The growth operator needs to select or provision the right agent for an outbound motion, but the CRM assistant currently only lists agents.
- Agent tool policies exist conceptually via `enabled_tools` and `HumanProfile`, but outbound growth actions need a stronger policy layer tied to action category, audience size, channel, spend/rate limits, and compliance risk.

### Segments

Files inspected:

- `backend/app/api/v1/segments.py`
- `backend/app/models/segment.py` by discovery
- `backend/app/schemas/segment.py` by discovery
- `backend/app/services/segments/segment_service.py`
- `backend/app/services/segments/segment_repository.py` by discovery
- `backend/app/services/contacts/contact_filters.py` by project guidance
- `frontend/src/lib/api/segments.ts` by discovery

What exists:

- Segment API supports list, create, get, update, delete, resolve contacts, and refresh cached counts.
- `SegmentService` delegates contact resolution to repository functions.
- Project guidance identifies `backend/app/services/contacts/contact_filters.py` as the gold-standard filter engine using `apply_contact_filters()` and `FilterDefinition`.

Important limitation:

- No frontend segment page was found under `frontend/src/app`.
- CRM assistant has no segment tools.
- Campaign contact enrollment currently takes explicit contact IDs, so an operator needs a safe bridge: `segment_id -> resolved contact IDs -> preview -> approval -> enrollment`.

### Offers and lead magnets

Files inspected:

- `backend/app/api/v1/offers.py`
- `backend/app/models/offer.py` by discovery
- `backend/app/models/offer_lead_magnet.py` by discovery
- `backend/app/schemas/offer.py` by discovery
- `backend/app/services/ai/offer_generator.py` by discovery
- `frontend/src/app/offers/page.tsx`
- `frontend/src/app/offers/new/page.tsx` by discovery
- `frontend/src/app/offers/[id]/page.tsx` by discovery
- `frontend/src/lib/api/offers.ts` by discovery

What exists:

- Offer API supports AI generation, CRUD, attaching lead magnets, public offer pages, and opt-in flows.
- Offer model supports value stacking, discounts, guarantees, urgency/scarcity, public slug, opt-in requirements, and associated lead magnets.
- Campaigns can link to `offer_id`.

Important limitation:

- Assistant does not expose offer-generation or offer-selection tools.
- Growth operator needs to connect offer strategy to segment/campaign/drip selection: “which offer for which audience and why,” with a previewable artifact before launch.

### Opportunities and pipeline

Files inspected:

- `backend/app/api/v1/opportunities.py`
- `backend/app/models/opportunity.py` by discovery
- `backend/app/schemas/opportunity.py` by discovery
- `backend/app/services/opportunities/opportunity_service.py` by discovery
- `backend/app/services/opportunities/opportunity_filters.py` by discovery
- `frontend/src/app/opportunities/page.tsx`
- `frontend/src/app/opportunities/opportunities-client.tsx` by discovery
- `frontend/src/lib/api/opportunities.ts` by discovery

What exists:

- Pipeline, stage, opportunity, and line-item APIs exist.
- Opportunity listing supports filters by pipeline, stage, owner, status, source, value range, probability range, created date range, pagination, and search.
- Assistant can list recent opportunities.

Important limitation:

- Assistant cannot create/update opportunities, advance stages, or attribute campaign/drip results to pipeline outcomes.
- Growth operator needs feedback loops from campaign conversations/appointments into opportunities.

### Pending actions / HITL approval

Files inspected:

- `backend/app/models/pending_action.py`
- `backend/app/api/v1/pending_actions.py`
- `backend/app/schemas/pending_action.py` by discovery
- `backend/app/services/approval/approval_gate_service.py`
- `backend/app/services/approval/approval_delivery_service.py` by discovery
- `backend/app/workers/approval_worker.py`
- `frontend/src/app/pending-actions/page.tsx`
- `frontend/src/components/pending-actions/pending-actions-page.tsx`
- `frontend/src/lib/api/pending-actions.ts` by discovery

What exists:

- `PendingAction` stores AI-proposed actions awaiting review.
- Fields include workspace, agent, action type, payload, description, context, status, urgency, reviewer, execution result, expiration, and notification state.
- Statuses include `pending`, `approved`, `rejected`, `expired`, `executed`, `failed`.
- `HumanProfile` controls action policies per agent:
  - `auto`
  - `ask`
  - `never`
  - default policy
  - auto-approve timeout
  - auto-reject timeout
- `ApprovalGateService.check_and_execute_or_queue()` decides auto/block/pending.
- `ApprovalWorker` sends notifications, executes approved actions, auto-approves after timeout, and expires pending actions.
- Current dispatch handlers support only:
  - `book_appointment`
  - `send_sms`
- Frontend `/pending-actions` lists, filters, approves, and rejects actions.

Important limitation:

- Pending actions are action-level, not plan/run-level.
- There are no handlers for campaign/drip/segment/offer/opportunity actions.
- Approval UI shows cards but not a full growth plan diff, audience preview, estimated volume, compliance risks, or rollback/pause controls.
- Existing assistant `send_sms` bypasses this service.

### Workers and background automation

Files discovered:

- `backend/app/workers/approval_worker.py`
- `backend/app/workers/automation_worker.py`
- `backend/app/workers/base.py`
- `backend/app/workers/base_campaign_worker.py`
- `backend/app/workers/campaign_worker.py`
- `backend/app/workers/drip_campaign_worker.py`
- `backend/app/workers/voice_campaign_worker.py`
- `backend/app/workers/enrichment_worker.py`
- `backend/app/workers/followup_worker.py`
- `backend/app/workers/never_booked_worker.py`
- `backend/app/workers/noshow_reengagement_worker.py`
- `backend/app/workers/nudge_worker.py`
- `backend/app/workers/reminder_worker.py`
- `backend/app/workers/reputation_worker.py`
- `backend/app/workers/retryable.py`
- plus prompt/message/test/evaluation workers

What exists:

- A worker registry/base abstraction exists.
- Campaign and drip workers already handle durable scheduled outbound execution.
- Approval worker already bridges human approval to execution.
- Rate-limit, number-pool, opt-out, reputation, and idempotency services exist and are used by outbound workers.

Important limitation:

- There is no “growth operator run worker” that owns multi-step orchestration state.
- Existing workers execute specific outbound mechanisms; none choose the next growth action from goals, data, and performance.

## Proposed architecture

### Core concept: Growth Operator Run

Add a durable orchestration layer that represents an operator-directed growth goal and its planned/executed steps.

Suggested backend package:

```text
backend/app/models/growth_operator_run.py
backend/app/schemas/growth_operator.py
backend/app/api/v1/growth_operator.py
backend/app/services/growth_operator/
  planner.py
  tool_registry.py
  tool_executor.py
  approval.py
  run_service.py
  performance_analyzer.py
backend/app/workers/growth_operator_worker.py
```

Suggested frontend package:

```text
frontend/src/app/growth-operator/page.tsx
frontend/src/components/growth-operator/
frontend/src/lib/api/growth-operator.ts
```

Alternative: integrate into `/assistant` first and add `/growth-operator` later. The lower-risk path is to add backend run models and expose run cards inside the assistant before a dedicated page.

### Data model

#### `GrowthOperatorRun`

Represents one user goal, e.g. “reactivate no-shows from the last 90 days with the spring inspection offer.”

Fields:

- `id`
- `workspace_id`
- `created_by_id`
- `status`: `drafting`, `awaiting_approval`, `approved`, `running`, `paused`, `completed`, `failed`, `canceled`
- `goal`: raw user goal
- `strategy_summary`: concise plan
- `risk_level`: `low`, `medium`, `high`
- `channel_mix`: `sms`, `voice`, `email` when added, `drip`, `manual`
- `target_segment_id` nullable
- `offer_id` nullable
- `agent_id` nullable
- `campaign_id` nullable
- `drip_campaign_id` nullable
- `opportunity_pipeline_id` nullable
- `audience_snapshot`: count, sample contacts, exclusions, opt-out count, missing-phone count
- `approval_action_id` nullable
- `metrics_snapshot`: sent, replies, appointments, opportunities, opt-outs, failures
- timestamps

#### `GrowthOperatorStep`

Represents durable sub-steps that can be resumed after approval.

Fields:

- `id`
- `run_id`
- `step_type`: `resolve_audience`, `draft_offer`, `draft_campaign`, `draft_drip`, `request_approval`, `launch_campaign`, `monitor`, `pause`, `optimize`, `create_opportunities`
- `status`: `pending`, `running`, `waiting_for_approval`, `completed`, `failed`, `skipped`
- `input_payload`
- `output_payload`
- `pending_action_id` nullable
- `error`
- timestamps

#### `GrowthOperatorArtifact`

Stores previewable generated assets:

- segment definition
- message variants
- campaign settings
- drip steps
- offer copy
- approval brief
- post-run analysis

This avoids burying generated state only in assistant chat messages.

### Tool categories

Use a registry similar to the current CRM assistant, but with explicit metadata:

```python
@dataclass(frozen=True, slots=True)
class GrowthToolSpec:
    name: str
    category: Literal["read", "draft", "propose", "execute"]
    risk: Literal["low", "medium", "high"]
    approval_action_type: str | None
    schema: dict[str, Any]
```

#### Read tools

Safe, auto-executable:

- `search_contacts`
- `get_contact_profile`
- `list_segments`
- `resolve_segment_preview`
- `list_offers`
- `get_offer`
- `list_agents`
- `list_campaigns`
- `get_campaign_stats`
- `list_drip_campaigns`
- `list_opportunities`
- `get_dashboard_stats`
- `get_recent_conversations`
- `get_pending_actions`

#### Draft tools

Create draft artifacts only; no external sends:

- `draft_segment_definition`
- `draft_offer_copy`
- `draft_sms_campaign`
- `draft_voice_campaign`
- `draft_drip_sequence`
- `draft_opportunity_followup_plan`
- `simulate_campaign_audience`
- `estimate_send_volume`

#### Propose tools

Create `PendingAction` records and set run step to `waiting_for_approval`:

- `propose_create_segment`
- `propose_create_campaign`
- `propose_enroll_segment_in_campaign`
- `propose_launch_campaign`
- `propose_create_drip_campaign`
- `propose_enroll_segment_in_drip`
- `propose_pause_campaign`
- `propose_send_bulk_sms`
- `propose_create_opportunities`
- `propose_agent_policy_change`

#### Execute tools

Only called by `ApprovalWorker` or `GrowthOperatorWorker` after approval:

- `execute_create_segment`
- `execute_create_campaign`
- `execute_enroll_campaign_contacts`
- `execute_start_campaign`
- `execute_create_drip_campaign`
- `execute_enroll_drip_contacts`
- `execute_pause_campaign`
- `execute_create_opportunities`

## Data flow

### 1. User starts from assistant or growth page

User says:

> Find stalled leads from the last 60 days and start a reactivation campaign for our spring offer.

Frontend sends to either:

- existing `POST /api/v1/workspaces/{workspace_id}/assistant/chat`, or
- new `POST /api/v1/workspaces/{workspace_id}/growth-operator/runs`.

Recommended implementation path: start with a new growth endpoint and let assistant call it later. This keeps run state explicit and avoids overloading chat history.

### 2. Planner builds a draft run

Planner reads:

- contacts through filter engine / segment repository
- segment definitions
- offers
- agents
- campaign/drip history
- conversations and outcomes
- pending action state
- opportunity pipeline state

Planner writes:

- `GrowthOperatorRun(status="drafting")`
- draft artifacts
- audience preview
- safety/risk analysis

No outbound side effects occur during planning.

### 3. System generates approval brief

Approval brief includes:

- goal
- selected segment / filter definition
- estimated audience count
- excluded contacts and reasons
- channel and cadence
- message previews
- linked offer
- selected agent
- send windows/rate limits
- opt-out handling
- expected worker path
- rollback/pause plan
- risk level and policy reason

### 4. Approval gate queues action

For risky steps, call `ApprovalGateService.check_and_execute_or_queue()` with a new action type such as:

- `launch_campaign`
- `create_campaign`
- `enroll_campaign_contacts`
- `create_drip_campaign`
- `enroll_drip_contacts`
- `pause_campaign`
- `create_opportunity_batch`

The payload should include `run_id` and `step_id` so approval can resume the run.

### 5. Human reviews

Current `/pending-actions` can approve/reject, but should be extended to render growth-specific approval briefs.

Minimum first version:

- include run summary in `PendingAction.description`
- include full brief in `PendingAction.context` or `action_payload`
- card links to `/growth-operator/runs/{id}` or assistant thread

### 6. Worker resumes execution

`ApprovalWorker` currently executes approved actions directly. There are two viable designs:

#### Option A: Extend `ApprovalGateService._dispatch_action()`

Add handlers for growth actions. Each handler calls `GrowthOperatorRunService.resume_from_approval(action)`.

Pros:

- Minimal new worker behavior.
- Uses existing approved-action polling.

Cons:

- Approval worker starts owning orchestration logic.

#### Option B: Approval worker only marks approved; growth worker resumes

`ApprovalWorker` continues changing status. `GrowthOperatorWorker` polls steps where `pending_action_id` is approved and resumes.

Pros:

- Cleaner orchestration ownership.
- Easier to add retries and run-level observability.

Cons:

- Requires new worker and polling path.

Recommended: Option B for durability and separation. Add a small `ApprovalGateService` dispatch fallback only for legacy action types.

### 7. Existing outbound workers execute sends

The growth operator should create/start campaigns and drips, then let existing specialized workers send messages/calls:

- `CampaignWorker` for SMS campaigns
- `VoiceCampaignWorker` for voice/SMS fallback campaigns
- `DripCampaignWorker` for drip steps
- existing text/voice agents for replies
- `ApprovalWorker` for one-off approved SMS/appointment actions

This preserves current rate limits, opt-out checks, idempotency, number pools, sending windows, and worker retry behavior.

### 8. Monitor and optimize

Growth operator periodically reads:

- campaign stats
- drip enrollment stats
- replies and appointments
- opt-outs/failures
- opportunities created/won/lost
- pending action backlog

It can propose:

- pause campaign
- adjust follow-up message
- create opportunity records
- enroll responders into a different drip
- generate a campaign report
- create a nudge for a human

Optimization actions that mutate outbound behavior must go back through approval unless policy allows auto.

## Safety gates

### System-level approval, not prompt-only confirmation

Required changes:

- Route assistant `send_sms` through `ApprovalGateService` for agents/operators with `ask` policies, or create a separate `send_sms_now` only for trusted/manual mode.
- Add approval action handlers for campaign and drip mutations.
- Treat bulk outbound, campaign launch, and drip enrollment as high-risk by default.

### Risk tiers

Suggested defaults:

| Action | Default policy | Risk |
|---|---:|---:|
| Read/list/search | auto | low |
| Draft artifact | auto | low |
| Create draft segment/campaign/drip | ask | medium |
| Send one SMS | ask | medium |
| Enroll contacts | ask | high |
| Start campaign/drip | ask | high |
| Pause campaign | auto or ask | medium |
| Create opportunities | ask | medium |
| Delete/cancel destructive records | never or ask | high |

### Audience and compliance checks

Before approval, compute and display:

- total contacts selected
- contacts missing phone/email
- global opt-outs excluded
- contacts already active in another campaign/drip
- contacts with recent inbound conversation
- contacts with appointments already booked
- quiet-hours/sending-window validation
- phone-number pool capacity
- per-minute and daily send estimates
- duplicate-send/idempotency plan

### HumanProfile extension

Current `HumanProfile.action_policies` can remain the source of truth, but add documented action types and optional constraints:

```json
{
  "launch_campaign": "ask",
  "enroll_campaign_contacts": "ask",
  "send_sms": "ask",
  "pause_campaign": "auto",
  "create_opportunity_batch": "ask"
}
```

Future constraints:

```json
{
  "max_auto_audience_size": 25,
  "max_daily_messages": 200,
  "allowed_channels": ["sms", "voice"],
  "quiet_hours_policy": "block",
  "require_offer_for_bulk_outbound": true
}
```

### Idempotency

Preserve existing outbound idempotency patterns:

- campaign initial SMS: `derive_idempotency_key("campaign_sms_initial", campaign_contact.id)`
- drip step: `derive_idempotency_key("drip_step", enrollment.id, enrollment.current_step)`
- approved SMS: `derive_idempotency_key("approval_send_sms", action.id)`

Add growth-run keys for creating entities:

- `growth_create_campaign:{run_id}:{step_id}`
- `growth_enroll_campaign:{campaign_id}:{segment_snapshot_hash}`
- `growth_create_drip:{run_id}:{step_id}`

### Rollback and stop controls

Each approval brief should include what can be undone:

- draft campaign/drip can be deleted before launch
- running campaign can be paused
- pending contacts can be removed only before send
- sent SMS/calls cannot be recalled
- created opportunities can be marked/corrected, but deletion should remain manual/destructive

## Missing tools and APIs

### Backend assistant/growth tools

Add these before full autonomy:

1. `list_segments`
2. `resolve_segment_preview`
3. `create_segment_draft` or `propose_create_segment`
4. `list_offers`
5. `generate_offer_draft`
6. `list_drip_campaigns`
7. `draft_drip_campaign`
8. `propose_create_drip_campaign`
9. `propose_enroll_drip_contacts`
10. `draft_sms_campaign`
11. `propose_create_campaign`
12. `propose_enroll_campaign_contacts`
13. `propose_launch_campaign`
14. `pause_campaign`
15. `get_campaign_performance`
16. `create_opportunity_draft`
17. `propose_create_opportunity_batch`
18. `list_pending_actions`
19. `get_pending_action_status`

### Approval dispatch handlers

Extend `ApprovalGateService._dispatch_action()` or route through `GrowthOperatorWorker` for:

- `create_segment`
- `create_campaign`
- `enroll_campaign_contacts`
- `launch_campaign`
- `create_drip_campaign`
- `enroll_drip_contacts`
- `pause_campaign`
- `create_opportunity_batch`

### Frontend views

Minimum:

- extend assistant UI to show action proposal cards and links to pending approvals
- extend pending action cards for growth actions with structured fields
- add a growth run detail page showing:
  - plan
  - audience preview
  - message/cadence preview
  - approval status
  - execution timeline
  - metrics

Nice-to-have:

- dedicated `/growth-operator` page
- segment builder UI if no segment page exists
- campaign/drip plan diff viewer
- “pause all run activity” button

## Implementation phases

### Phase 1 — Make current assistant safe for outbound actions

Backend:

- Update `backend/app/services/ai/crm_assistant/_tool_executor.py` so `send_sms` goes through `ApprovalGateService` or a clearly named safe proposal path.
- Add tool result responses that distinguish `sent`, `queued_for_approval`, and `blocked_by_policy`.
- Add tests for assistant SMS behavior under `auto`, `ask`, and `never` policies.

Frontend:

- Render `actions_taken` or approval-queued summaries in `AssistantChat` so users can see when an action is pending.

Verification:

- Backend: `cd backend && uv run ruff check app && uv run mypy app`
- Hit assistant/pending-action endpoints with `.gg/eyes/http.sh` if server is running.

### Phase 2 — Add growth-run durable model and read-only planner

Backend:

- Add `GrowthOperatorRun`, `GrowthOperatorStep`, and optional `GrowthOperatorArtifact` models/migration.
- Add schemas and `GET/POST /api/v1/workspaces/{workspace_id}/growth-operator/runs`.
- Implement read-only planner service that can:
  - parse a goal
  - choose existing segment/offer/agent candidates
  - produce an audience preview
  - produce a draft outbound plan
- Do not execute mutations yet.

Frontend:

- Add a simple growth run list/detail view or embed run cards in assistant.

Verification:

- Backend lint/typecheck.
- Run migration locally.
- Hit new endpoints with `http.sh`.

### Phase 3 — Add draft/proposal tools

Backend:

- Add `GrowthToolSpec` registry and executor.
- Add tools for segment preview, offer listing, campaign drafting, drip drafting, and proposal creation.
- Create `PendingAction` rows for proposed high-risk mutations with `run_id` and `step_id` in context.
- Keep all mutation execution behind approval.

Frontend:

- Show proposal cards with audience count, selected offer/agent, messages, and risk warnings.
- Link proposals to pending actions.

Verification:

- Unit tests for tool registry and proposal payloads.
- Endpoint tests for creating proposal runs.

### Phase 4 — Approval resume and execution

Backend:

- Add `GrowthOperatorWorker`.
- Worker polls steps waiting on approved pending actions.
- Implement execution handlers:
  - create campaign
  - enroll contacts from a segment snapshot
  - start campaign
  - create drip
  - enroll drip contacts
  - pause campaign
  - create opportunity batch
- Reuse existing Campaign/Drip APIs/services where possible.
- Preserve current campaign/drip workers as send executors.

Frontend:

- Growth run timeline updates as steps complete.
- Pending action detail can show execution result and linked run.

Verification:

- Backend lint/typecheck.
- Worker logs via `.gg/eyes/logs.sh --service backend --grep "growth_operator"` if runtime is available.
- Hit dependent endpoints with `http.sh`.

### Phase 5 — Monitoring and optimization loop

Backend:

- Add performance analyzer that reads campaign/drip/opportunity stats.
- Generate post-launch summaries and recommended next actions.
- Queue optimization actions through approval:
  - pause underperforming campaign
  - alter follow-up copy
  - enroll responders in a new drip
  - create opportunities for qualified replies

Frontend:

- Run metrics panel.
- Recommendations panel with approve/reject actions.

Verification:

- Tests for recommendation thresholds.
- Runtime check against a seeded/dev campaign.

### Phase 6 — Policy, capacity, and compliance hardening

Backend:

- Extend `HumanProfile` policy documentation and seed defaults.
- Add audience-size/channel/rate constraints.
- Add dry-run capacity check for phone number pool, daily rate limits, quiet hours, opt-outs, and recent-contact exclusions.
- Add audit events for all growth-run decisions and approvals.

Frontend:

- Policy settings UI under agent/human profile settings.
- Approval UI displays exact policy rule that caused `auto`, `ask`, or `never`.

Verification:

- Policy unit tests.
- Approval-worker integration tests.

## Recommended first slice

Build the smallest useful, safe flow:

1. User asks assistant/growth endpoint to create a reactivation campaign.
2. System resolves an existing segment or previews a filter-defined audience.
3. System drafts SMS campaign copy using an existing offer and agent.
4. System creates a `PendingAction(action_type="launch_campaign")` containing the full preview.
5. Human approves in `/pending-actions`.
6. Growth worker creates a draft campaign, enrolls contacts, and starts it.
7. Existing `CampaignWorker` sends messages under existing rate limits and opt-out checks.
8. Growth run detail shows launch status and campaign stats.

This slice proves the durable loop: `goal → plan → approval → execution → worker sends → metrics`, while preserving current safety boundaries.

## Open decisions

1. Should growth runs live as a dedicated page (`/growth-operator`) or inside the existing assistant first?
2. Should approval execution be dispatched by `ApprovalWorker` or resumed by a new `GrowthOperatorWorker`? Recommended: new worker.
3. Should assistant and growth operator share one tool registry, or should growth tools remain separate and be callable by assistant? Recommended: separate registry with assistant wrapper tools.
4. What default policy should apply to one-off assistant SMS? Recommended: route through `HumanProfile`, default `ask`.
5. Should segment snapshots be materialized at approval time or execution time? Recommended: materialize at approval preview and store a snapshot hash/count; revalidate at execution and block if drift exceeds a configured threshold.
