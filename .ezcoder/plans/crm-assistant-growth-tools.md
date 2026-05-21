# CRM Assistant Growth Tools — Backend Contracts

## Purpose

Define backend tool contracts for the CRM assistant acting as an outbound growth operator. These tools let the assistant plan, draft, monitor, and route outbound growth work while preserving deterministic backend execution, auditability, and human-in-the-loop approval for risky actions.

This repo uses the `.ezcoder` framework/toolchain. Keep related plans, commands, skills, and agent metadata under `.ezcoder/`; do not recreate `.claude/commands`, `.gg/commands`, or `.gg/plans`.

## KenCode MCP references

Required research flow was used: `exploreCodeSamples` first, then literal `searchCode` verification.

- `exploreCodeSamples("OpenAI function/tool schemas and approval-gated agent tools with confirmation requirements")` found no directly reusable CRM-specific samples, so the follow-up used literal anchors.
- `searchCode("FunctionTool")` found `xvolcano02/UCAS`, `verl/tools/schemas.py`, with typed OpenAI-compatible models such as `OpenAIFunctionToolSchema`, `OpenAIFunctionSchema`, and `OpenAIFunctionToolCall`. Useful pattern: store tool specs as typed schema objects with `type`, `function`, `name`, `description`, `parameters`, and decoded `arguments`.
- `searchCode("parameters: {")` found `Claw-Company/clawcompany`, `packages/tools/src/index.ts`, defining `BUILTIN_TOOLS` as OpenAI-style function tools with narrow `action` enums and JSON-schema `required` fields. Useful pattern: prefer small bounded actions or explicit enums over broad free-form tools.
- `searchCode("needsApproval")` found `alex000kim/claude-code`, `src/utils/permissions/permissions.ts`, where permission decisions distinguish commands that require approval and generate explicit human-readable approval reasons. Useful pattern: approval metadata should be first-class and explain why the action is gated.
- `searchCode("parameters: {")` found `n8n-io/n8n`, MCP tool files that include tool metadata, typed input schemas, telemetry payloads, and operation-specific handler functions. Useful pattern: every tool execution should log `tool_name`, parameters summary, user/workspace, outcome, and errors.

Local contracts should continue the existing backend style in `backend/app/services/ai/crm_assistant/_tools.py`: OpenAI `type: "function"` dictionaries, short imperative descriptions, JSON-schema parameters, and central execution via a tool executor.

## Contract design principles

1. **Read tools execute immediately.** Listing, resolving, summarizing, classifying, and previewing are safe read/analysis actions unless they trigger outbound side effects.
2. **Draft tools may create durable drafts without sending.** Offer, agent, segment, and campaign draft tools can create or update non-public/non-running objects when `approval_mode` allows it.
3. **Outbound or irreversible actions require backend approval gates.** Campaign start, bulk enrollment, outbound SMS/call activation, AI auto-reply enablement, contact assignment changes at scale, opportunity creation from AI inference, and human handoff notifications must be routed through `ApprovalGateService.check_and_execute_or_queue()` unless a workspace policy explicitly auto-approves.
4. **Prompt confirmation is not safety.** Tool descriptions may tell the model when to confirm, but the executor must enforce confirmation/approval using `confirmation` arguments, `approval_mode`, and pending actions.
5. **Tools return typed envelopes.** All tools return a shared envelope so the assistant UI can render results, pending approvals, errors, previews, and audit references consistently.
6. **No hidden workspace/user scope in arguments.** `workspace_id`, `user_id`, `crm_assistant_agent_id`, auth, and DB session are injected by the executor, not accepted from the model.
7. **Stable IDs and idempotency.** Mutating tools accept optional `idempotency_key`. The executor also derives a stable key from `(workspace_id, user_id, conversation_id, tool_call_id, action_type, target IDs)` when absent.
8. **Least-power tool names.** Prefer `growth_start_campaign` over a generic `campaign_action` when the approval policy, audit log, and return shape differ.

## Shared schemas

### OpenAI tool schema shape

Each tool is exposed to OpenAI as:

```python
{
    "type": "function",
    "function": {
        "name": "growth_tool_name",
        "description": "Short imperative description with confirmation hint.",
        "parameters": {
            "type": "object",
            "properties": {...},
            "required": [...],
            "additionalProperties": False,
        },
    },
}
```

### Tool return envelope

Every executor handler returns this shape:

```json
{
  "ok": true,
  "tool_name": "growth_tool_name",
  "status": "completed | preview | draft_created | pending_approval | blocked | failed | noop",
  "summary": "Human-readable one sentence result.",
  "data": {},
  "approval": null,
  "warnings": [],
  "audit": {
    "workspace_id": "uuid",
    "user_id": 123,
    "tool_call_id": "call_...",
    "idempotency_key": "stable-key",
    "created_ids": [],
    "updated_ids": []
  }
}
```

When an action is queued:

```json
{
  "ok": true,
  "tool_name": "growth_start_campaign",
  "status": "pending_approval",
  "summary": "Queued approval to start campaign 'May Reactivation' for 842 contacts.",
  "data": {"campaign_id": "uuid", "audience_count": 842},
  "approval": {
    "required": true,
    "pending_action_id": "uuid",
    "action_type": "growth_start_campaign",
    "reason": "Bulk outbound SMS to 842 contacts requires approval.",
    "review_url": "/pending-actions/<uuid>",
    "expires_at": "2026-05-19T18:45:00Z"
  },
  "warnings": [],
  "audit": {...}
}
```

When blocked or invalid:

```json
{
  "ok": false,
  "tool_name": "growth_start_campaign",
  "status": "blocked",
  "summary": "Campaign cannot start because no sending phone number is available.",
  "data": {},
  "approval": null,
  "warnings": [],
  "error": {
    "code": "missing_sender_number",
    "message": "No active workspace phone number can send SMS.",
    "details": {"campaign_id": "uuid"},
    "retryable": false
  },
  "audit": {...}
}
```

### Shared argument fragments

Use these consistently across mutating tools.

```json
{
  "approval_mode": {
    "type": "string",
    "enum": ["auto", "require", "preview_only"],
    "description": "auto applies workspace policy; require always queues approval; preview_only never mutates."
  },
  "confirmation": {
    "type": "object",
    "properties": {
      "confirmed_by_user": {"type": "boolean"},
      "confirmation_text": {"type": "string"}
    },
    "required": ["confirmed_by_user"]
  },
  "idempotency_key": {"type": "string"},
  "reason": {"type": "string", "description": "Why the operator asked for this action."}
}
```

`confirmed_by_user=true` means the operator explicitly said to do it in the current assistant turn. It does **not** bypass policy. It only gives the executor enough context to avoid asking a second natural-language confirmation before queuing/executing.

## Confirmation and approval policy matrix

| Action category | Tool examples | Natural-language confirmation | Backend approval gate | Default policy |
|---|---|---:|---:|---|
| Read/summary/classification | list offers, resolve segment, performance summary, classify replies | No | No | Execute |
| Draft only | create offer draft, create campaign draft, create agent draft | If user intent is ambiguous | Optional for public/active assets | Execute draft |
| Single-record internal mutation | assign one contact, create one opportunity from explicit user instruction | Yes | Policy-dependent | Ask if inferred by AI |
| Bulk internal mutation | assign segment, bulk AI toggle, bulk opportunity creation | Yes | Yes | Queue |
| Outbound communication activation | start/resume campaign, enable AI auto-reply for contacts, human handoff SMS/push | Yes | Yes | Queue |
| Pause/disable safety action | pause campaign, disable AI for contact/segment | Confirmation if broad | Usually auto; approval optional | Execute fast |
| Public-facing content publish | publish offer/landing page, make campaign active | Yes | Yes | Queue |

## Tool contracts

### 1. `growth_list_offers`

List offers available for outbound motions.

**Arguments**

```json
{
  "status": {"type": "string", "enum": ["draft", "active", "archived", "any"]},
  "query": {"type": "string"},
  "include_metrics": {"type": "boolean"},
  "limit": {"type": "integer", "minimum": 1, "maximum": 50}
}
```

**Returns**

`data.offers[]`: `id`, `name`, `status`, `public_slug`, `summary`, `value_stack`, `discount`, `urgency`, `lead_magnet_count`, optional `metrics`.

**Confirmation/approval**: none.

**Errors**: `invalid_filter`, `workspace_not_found`.

### 2. `growth_draft_offer`

Generate or update a draft offer for a target audience and outbound campaign.

**Arguments**

```json
{
  "mode": {"type": "string", "enum": ["generate", "revise", "clone"]},
  "offer_id": {"type": "string", "description": "Required for revise/clone."},
  "name": {"type": "string"},
  "audience_description": {"type": "string"},
  "pain_points": {"type": "array", "items": {"type": "string"}},
  "desired_outcome": {"type": "string"},
  "constraints": {"type": "array", "items": {"type": "string"}},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data.offer`: `id`, `name`, `status: draft`, `positioning`, `headline`, `value_stack`, `guarantee`, `urgency`, `recommended_channels`, `preview_url` when available.

**Confirmation/approval**: draft creation can execute when intent is clear. Publishing or attaching to a running campaign is not part of this tool and must be approved through campaign tools.

**Errors**: `missing_offer_id`, `offer_not_found`, `generation_failed`, `invalid_offer_payload`, `duplicate_idempotency_key`.

### 3. `growth_list_agents`

List text/voice agents that can support outbound campaigns or handoffs.

**Arguments**

```json
{
  "channel_mode": {"type": "string", "enum": ["text", "voice", "both", "any"]},
  "status": {"type": "string", "enum": ["active", "inactive", "any"]},
  "include_capabilities": {"type": "boolean"},
  "limit": {"type": "integer", "minimum": 1, "maximum": 50}
}
```

**Returns**

`data.agents[]`: `id`, `name`, `channel_mode`, `is_active`, `enabled_tools`, `calcom_configured`, `voice_provider`, `recent_assignment_count`, `capabilities`.

**Confirmation/approval**: none.

**Errors**: `invalid_filter`.

### 4. `growth_draft_agent`

Create or revise a non-active agent draft for an outbound motion.

**Arguments**

```json
{
  "mode": {"type": "string", "enum": ["create", "revise", "clone"]},
  "agent_id": {"type": "string", "description": "Required for revise/clone."},
  "name": {"type": "string"},
  "channel_mode": {"type": "string", "enum": ["text", "voice", "both"]},
  "goal": {"type": "string"},
  "tone": {"type": "string"},
  "system_prompt": {"type": "string"},
  "enabled_tools": {"type": "array", "items": {"type": "string"}},
  "handoff_rules": {"type": "array", "items": {"type": "string"}},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data.agent`: `id`, `name`, `status`, `channel_mode`, `prompt_excerpt`, `enabled_tools`, `handoff_rules`, `needs_review`.

**Confirmation/approval**: creating inactive drafts may execute. Activating the agent or enabling it for existing conversations must use `growth_toggle_ai` or campaign start tools.

**Errors**: `agent_not_found`, `invalid_tool_selection`, `unsafe_prompt`, `generation_failed`.

### 5. `growth_resolve_segment`

Resolve an existing segment or ad-hoc filter definition into an auditable audience preview.

**Arguments**

```json
{
  "segment_id": {"type": "string"},
  "filters": {"type": "array", "items": {"type": "object"}, "description": "FilterDefinition list compatible with contact_filters.py."},
  "exclude_contact_ids": {"type": "array", "items": {"type": "integer"}},
  "exclude_recently_contacted_days": {"type": "integer", "minimum": 0, "maximum": 365},
  "exclude_opted_out": {"type": "boolean"},
  "sample_size": {"type": "integer", "minimum": 0, "maximum": 25},
  "include_risk_breakdown": {"type": "boolean"}
}
```

Exactly one of `segment_id` or `filters` is required.

**Returns**

`data`: `audience_ref`, `segment_id`, `count`, `sample_contacts[]`, `exclusions`, `risk_breakdown`, `filter_summary`, `resolved_at`.

`audience_ref` should be a short-lived durable reference used by campaign draft/start tools instead of passing large contact ID arrays through the model.

**Confirmation/approval**: none for preview. Persisting a new segment is a separate tool.

**Errors**: `segment_not_found`, `invalid_filters`, `audience_empty`, `filter_engine_failed`.

### 6. `growth_save_segment`

Create or update a reusable dynamic segment from validated filters.

**Arguments**

```json
{
  "mode": {"type": "string", "enum": ["create", "update"]},
  "segment_id": {"type": "string"},
  "name": {"type": "string"},
  "description": {"type": "string"},
  "filters": {"type": "array", "items": {"type": "object"}},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data.segment`: `id`, `name`, `description`, `filter_summary`, `cached_count`, `created_or_updated`.

**Confirmation/approval**: confirmation required for updates to an existing segment. Approval required if segment is attached to active automations/campaigns.

**Errors**: `segment_not_found`, `invalid_filters`, `segment_in_use`, `name_conflict`.

### 7. `growth_draft_campaign`

Create or revise an SMS/voice campaign draft with offer, audience, agent, copy, and sending constraints.

**Arguments**

```json
{
  "mode": {"type": "string", "enum": ["create", "revise", "clone"]},
  "campaign_id": {"type": "string", "description": "Required for revise/clone."},
  "campaign_type": {"type": "string", "enum": ["sms", "voice_sms_fallback"]},
  "name": {"type": "string"},
  "goal": {"type": "string"},
  "offer_id": {"type": "string"},
  "agent_id": {"type": "string"},
  "voice_agent_id": {"type": "string"},
  "audience_ref": {"type": "string"},
  "segment_id": {"type": "string"},
  "message_variants": {"type": "array", "items": {"type": "string"}},
  "follow_up_plan": {"type": "array", "items": {"type": "object"}},
  "sending_window": {"type": "object"},
  "rate_limits": {"type": "object"},
  "compliance_notes": {"type": "array", "items": {"type": "string"}},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data.campaign`: `id`, `name`, `status: draft`, `campaign_type`, `offer_id`, `agent_id`, `audience_count`, `message_previews[]`, `follow_up_plan`, `sending_window`, `rate_limits`, `estimated_daily_volume`, `risk_flags[]`, `approval_brief`.

**Confirmation/approval**: draft creation can execute when intent is clear. If the draft enrolls a resolved audience immediately, route through approval when audience size or policy requires it. `preview_only` returns the full draft payload without writing.

**Errors**: `campaign_not_found`, `offer_not_found`, `agent_not_found`, `audience_not_found`, `audience_empty`, `invalid_sending_window`, `unsafe_message_copy`, `draft_validation_failed`.

### 8. `growth_start_campaign`

Start or resume a draft/paused campaign after generating an approval brief.

**Arguments**

```json
{
  "campaign_id": {"type": "string"},
  "start_mode": {"type": "string", "enum": ["start_now", "schedule", "resume"]},
  "scheduled_at": {"type": "string", "description": "ISO datetime for schedule mode."},
  "max_initial_sends": {"type": "integer", "minimum": 1},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data`: `campaign_id`, `status`, `audience_count`, `estimated_first_day_sends`, `sending_window`, `approval_brief`, `started_at` or `scheduled_at`.

**Confirmation/approval**: explicit confirmation required. Backend approval required by default for any outbound campaign start/resume. If policy returns `auto`, execute; if `pending`, return `pending_action_id`; if `preview_only`, do not start.

**Errors**: `campaign_not_found`, `campaign_not_startable`, `missing_audience`, `missing_agent`, `missing_sender_number`, `outside_sending_window`, `approval_required`, `policy_blocked`, `campaign_already_running`.

### 9. `growth_pause_campaign`

Pause a running or scheduled campaign. This is a safety action and should be fast.

**Arguments**

```json
{
  "campaign_id": {"type": "string"},
  "pause_reason": {"type": "string"},
  "scope": {"type": "string", "enum": ["campaign", "campaign_and_followups"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data`: `campaign_id`, `previous_status`, `status: paused`, `paused_at`, `pending_sends_canceled`, `followups_paused`.

**Confirmation/approval**: confirmation recommended but not required when the user says stop/pause urgently. Approval should not block safety pauses unless workspace policy explicitly requires it.

**Errors**: `campaign_not_found`, `campaign_not_running`, `pause_failed`.

### 10. `growth_assign_owner`

Assign a human owner to contacts and/or conversations for follow-up accountability.

**Arguments**

```json
{
  "target_type": {"type": "string", "enum": ["contact", "conversation", "segment", "audience_ref"]},
  "contact_ids": {"type": "array", "items": {"type": "integer"}},
  "conversation_ids": {"type": "array", "items": {"type": "string"}},
  "segment_id": {"type": "string"},
  "audience_ref": {"type": "string"},
  "assigned_to_user_id": {"type": "integer"},
  "assignment_reason": {"type": "string"},
  "notify_assignee": {"type": "boolean"},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data`: `assigned_to_user_id`, `updated_contacts_count`, `updated_conversations_count`, `skipped[]`, `notification_status`.

**Confirmation/approval**: single contact/conversation can execute with clear user instruction. Segment/audience bulk assignment requires approval or `preview_only`. Notifications to humans use the same approval policy as handoff notifications when sent externally.

**Errors**: `assignee_not_found`, `target_not_found`, `audience_not_found`, `bulk_assignment_requires_approval`, `notification_failed`.

### 11. `growth_toggle_ai`

Enable or disable AI handling for contacts, conversations, agents, campaigns, segments, or audiences.

**Arguments**

```json
{
  "target_type": {"type": "string", "enum": ["contact", "conversation", "agent", "campaign", "segment", "audience_ref"]},
  "target_ids": {"type": "array", "items": {"type": "string"}},
  "segment_id": {"type": "string"},
  "audience_ref": {"type": "string"},
  "enabled": {"type": "boolean"},
  "agent_id": {"type": "string", "description": "Agent to assign when enabling AI for contacts/conversations."},
  "toggle_reason": {"type": "string"},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data`: `enabled`, `target_type`, `updated_count`, `agent_id`, `skipped[]`, `previous_state_summary`.

**Confirmation/approval**: disabling AI is a safety action and should execute quickly. Enabling AI for one explicit contact/conversation can execute by policy. Enabling AI for a campaign, segment, or audience requires approval because it authorizes autonomous replies at scale.

**Errors**: `target_not_found`, `agent_not_found`, `agent_inactive`, `bulk_ai_enable_requires_approval`, `policy_blocked`, `toggle_failed`.

### 12. `growth_get_performance_summary`

Summarize campaign, offer, segment, agent, or workspace performance for the growth operator.

**Arguments**

```json
{
  "scope": {"type": "string", "enum": ["workspace", "campaign", "offer", "segment", "agent"]},
  "scope_id": {"type": "string"},
  "time_range": {"type": "string", "enum": ["today", "7d", "30d", "90d", "custom"]},
  "start_date": {"type": "string"},
  "end_date": {"type": "string"},
  "include_recommendations": {"type": "boolean"},
  "include_conversation_samples": {"type": "boolean"}
}
```

**Returns**

`data`: `metrics` (`sent`, `delivered`, `replies`, `positive_replies`, `appointments`, `opportunities`, `opt_outs`, `failures`, `conversion_rates`), `trend`, `top_segments`, `agent_performance`, `offer_performance`, `recommendations[]`, `sample_conversations[]`.

**Confirmation/approval**: none.

**Errors**: `scope_not_found`, `invalid_time_range`, `metrics_unavailable`.

### 13. `growth_classify_replies`

Classify replies for intent, sentiment, lead quality, and recommended next action.

**Arguments**

```json
{
  "scope": {"type": "string", "enum": ["conversation", "campaign", "contact", "segment", "unread"]},
  "scope_id": {"type": "string"},
  "limit": {"type": "integer", "minimum": 1, "maximum": 200},
  "labels": {"type": "array", "items": {"type": "string"}, "description": "Optional allowed labels."},
  "include_next_actions": {"type": "boolean"},
  "persist_classification": {"type": "boolean"},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]}
}
```

**Returns**

`data.classifications[]`: `conversation_id`, `contact_id`, `latest_message_id`, `classification`, `sentiment`, `confidence`, `evidence`, `recommended_action`, `should_handoff`, `should_create_opportunity`.

**Confirmation/approval**: read-only classification needs no approval. Persisting labels/classification can execute if policy allows because it is internal metadata; bulk persistence can queue approval if labels trigger downstream automations.

**Errors**: `scope_not_found`, `classification_failed`, `label_not_allowed`, `too_many_messages`, `persist_failed`.

### 14. `growth_create_opportunity`

Create one or more opportunities from explicit operator instruction or classified replies.

**Arguments**

```json
{
  "mode": {"type": "string", "enum": ["single", "batch_from_classifications"]},
  "contact_id": {"type": "integer"},
  "conversation_id": {"type": "string"},
  "classification_refs": {"type": "array", "items": {"type": "string"}},
  "pipeline_id": {"type": "string"},
  "stage_id": {"type": "string"},
  "title": {"type": "string"},
  "estimated_value": {"type": "number"},
  "probability": {"type": "number", "minimum": 0, "maximum": 100},
  "source": {"type": "string", "enum": ["assistant", "campaign", "reply_classification", "manual"]},
  "notes": {"type": "string"},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data`: `created_opportunities[]`, `skipped[]`, `pipeline_id`, `stage_id`, `source_attribution`.

**Confirmation/approval**: explicit single-opportunity creation can execute by policy. AI-inferred or batch creation from classifications requires approval unless workspace policy auto-approves below a configured count/confidence threshold.

**Errors**: `contact_not_found`, `conversation_not_found`, `pipeline_not_found`, `stage_not_found`, `duplicate_opportunity`, `classification_ref_not_found`, `batch_requires_approval`.

### 15. `growth_handoff_to_human`

Create a human handoff for hot, risky, confused, or compliance-sensitive conversations.

**Arguments**

```json
{
  "conversation_id": {"type": "string"},
  "contact_id": {"type": "integer"},
  "assigned_to_user_id": {"type": "integer"},
  "handoff_reason": {"type": "string"},
  "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
  "disable_ai_until_resolved": {"type": "boolean"},
  "notify_channels": {"type": "array", "items": {"type": "string", "enum": ["in_app", "sms", "push", "email"]}},
  "suggested_response": {"type": "string"},
  "due_at": {"type": "string"},
  "approval_mode": {"type": "string", "enum": ["auto", "require", "preview_only"]},
  "confirmation": {"type": "object", "properties": {"confirmed_by_user": {"type": "boolean"}, "confirmation_text": {"type": "string"}}, "required": ["confirmed_by_user"]},
  "idempotency_key": {"type": "string"}
}
```

**Returns**

`data`: `handoff_id`, `conversation_id`, `contact_id`, `assigned_to_user_id`, `ai_disabled`, `notification_results`, `suggested_response`, `status`.

**Confirmation/approval**: creating an in-app handoff and disabling AI for one conversation should execute quickly. Sending SMS/push/email notifications to humans can auto-execute for urgent handoffs if workspace notification settings allow it; otherwise queue approval. This tool never sends a message to the contact.

**Errors**: `conversation_not_found`, `contact_not_found`, `assignee_not_found`, `handoff_already_open`, `notification_failed`, `ai_toggle_failed`.

## Error code taxonomy

Use stable machine-readable codes. The assistant can paraphrase `message`, but downstream UI should key on `code`.

| Code | Meaning | Retryable |
|---|---|---:|
| `validation_error` | Arguments failed schema or cross-field validation | No |
| `workspace_not_found` | Executor context workspace missing/inaccessible | No |
| `permission_denied` | Current user lacks workspace/action permission | No |
| `policy_blocked` | HumanProfile/workspace policy blocks action | No |
| `approval_required` | Tool was called with insufficient confirmation or preview mode | No |
| `pending_action_exists` | Same idempotency key/action is already queued | No |
| `target_not_found` | Referenced CRM object does not exist in workspace | No |
| `conflict` | State changed, e.g. campaign already running/paused | Sometimes |
| `rate_limited` | Backend or provider rate limit hit | Yes |
| `provider_error` | OpenAI/Telnyx/Cal.com/SendGrid external failure | Yes |
| `execution_failed` | Unexpected executor/service failure | Yes |
| `serialization_error` | Tool result cannot be encoded safely | No |

## Approval payload requirements

For every gated action, `PendingAction.action_payload` should include:

```json
{
  "tool_name": "growth_start_campaign",
  "idempotency_key": "stable-key",
  "run_id": "uuid-or-null",
  "step_id": "uuid-or-null",
  "target": {"type": "campaign", "id": "uuid", "name": "May Reactivation"},
  "requested_by_user_id": 123,
  "arguments": {},
  "preview": {},
  "risk": {
    "audience_count": 842,
    "channel": "sms",
    "estimated_first_day_sends": 200,
    "compliance_flags": [],
    "rollback": "pause_campaign"
  }
}
```

`PendingAction.description` should be short and reviewable in SMS/push: `Start SMS campaign "May Reactivation" for 842 contacts.`

`PendingAction.context` should contain the full approval brief: audience summary, sample contacts, message previews, offer summary, sending window, agent summary, expected metrics, risk flags, and rollback/pause instructions.

## Executor requirements

- Register these tools in a separate growth tool module, e.g. `backend/app/services/ai/crm_assistant/_growth_tools.py`, and merge them into `get_crm_tools()` only for assistant agents with growth-operator capability enabled.
- Execute via central dispatch in `_tool_executor.py` or a dedicated `GrowthToolExecutor` called from it.
- Inject `workspace_id`, `user_id`, `crm_assistant_agent_id`, DB session, and tool call metadata at execution time.
- Validate arguments with Pydantic models before calling domain services.
- Use existing services directly instead of HTTP calls from inside the backend.
- Use `backend/app/services/contacts/contact_filters.py` and `apply_contact_filters()` for segment/audience resolution.
- Use `ApprovalGateService.check_and_execute_or_queue()` for gated actions and preserve `action_type` values matching tool names unless a legacy action type already exists.
- Log structured execution boundaries: `workspace_id`, `user_id`, `tool_name`, `action_type`, target IDs/counts, approval decision, elapsed time, and error code.
- Do not expose raw provider errors, secrets, phone-number pools, or full prompts in tool results.

## Proposed action types

Use these action types for policy and pending actions:

- `growth_draft_offer`
- `growth_save_segment`
- `growth_draft_campaign`
- `growth_start_campaign`
- `growth_pause_campaign`
- `growth_assign_owner`
- `growth_toggle_ai`
- `growth_persist_reply_classification`
- `growth_create_opportunity`
- `growth_handoff_to_human`

## Minimal implementation order

1. Add typed argument/result models and `_growth_tools.py` schemas.
2. Add executor plumbing with read-only tools first: offers, agents, segment resolve, performance summary, reply classification preview.
3. Add draft tools: offer draft, agent draft, campaign draft, save segment.
4. Add approval-gated tools: campaign start/pause, assignment, AI toggle, opportunity creation, human handoff.
5. Extend pending-action rendering to show growth approval briefs.
6. Add tests for schema validation, approval decisions, idempotency, and representative success/error envelopes.
