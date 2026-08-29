# CRM Assistant Resource Creation and RBAC

## Objective

Make the CRM Assistant useful for end-to-end CRM setup and daily operation without becoming a privilege-escalation or cross-tenant side door. The assistant will be able to build inactive automations, create saved audiences, enroll those audiences into draft campaigns, create/update owned pipeline opportunities, and connect existing workspace resources. External credentials and provider integrations remain admin-managed; the assistant may guide setup but will not read, write, or expose secrets.

## Current-state findings

- `backend/app/services/ai/crm_assistant/_tools.py` and `_automation_tools.py` already expose campaign and automation CRUD, but the automation JSON schema does not cover every declared action (`branch`, aliases), exposes trigger values the worker cannot execute (`generic_event`, `schedule`), and does not validate referenced workspace resources before persistence.
- Automation creation currently defaults active, so an approved create can immediately execute outbound steps. Creation and editing should produce an inactive draft; `enable_automation` should remain the separate approval-gated activation boundary.
- Campaign CRUD can connect agents/offers, but there is no assistant tool for campaign enrollment. `OutboundGrowthWorkflowService` currently enrolls only the three preview contacts, silently leaving the rest of a selected segment out.
- Saved segments are the existing reusable audience primitive (`Segment` + `apply_contact_filters`), but the assistant cannot list, preview, create, or update them. Existing filters silently ignore unsupported fields, which is unsafe for model-authored targeting because a bad filter can broaden an audience.
- Opportunity tools are read-only. `list_opportunities` also omits the sales-owner restriction used by the HTTP API.
- Appointment assistant reads query the whole workspace and omit `appointment_owner_scope`, unlike the calendar HTTP API.
- Tool schemas are filtered by role and execution checks capabilities, but approved actions trust the requester's queued role snapshot. Membership removal or downgrade after queueing does not currently revoke execution.
- Existing uncommitted formatting-only changes in five CRM Assistant test files are user-owned and must be preserved.

## Product behavior

### Segments and campaign audiences

Add strict tools:

- `list_tags`: return workspace tag IDs/names needed by saved filters.
- `list_segments`: list reusable workspace audiences.
- `preview_segment`: return current count and a bounded contact sample.
- `create_segment`: create a dynamic segment from validated rules.
- `update_segment`: edit an existing segment and recompute its count.
- `enroll_campaign_audience`: add either one validated segment or explicit workspace contact IDs to a draft campaign.

`enroll_campaign_audience` will require exactly one source, reject cross-workspace IDs, reject non-draft campaigns, deduplicate existing enrollments, skip channel-ineligible contacts with an explicit count, and fail before writing if a segment exceeds a documented bounded batch ceiling. The growth-workflow planner will use the same service and enroll the complete eligible audience rather than its three-row preview.

### Automations/workflows

- Define an assistant-supported trigger set from triggers the runtime actually evaluates; do not expose unsupported `generic_event` or `schedule` values through the model tool schema.
- Expose canonical worker actions only, not legacy aliases, and add a valid `branch` schema with step IDs, contact-filter conditions, and `then_goto`/`else_goto` targets.
- Validate action type/config pairs server-side after tool invocation, not only in OpenAI JSON schema.
- Validate unique step IDs, existing branch targets, acyclic control flow, positive bounded waits, and supported contact-filter rules.
- Resolve referenced agent, campaign, drip campaign, pipeline stage, and pipeline IDs inside the current workspace before saving; return non-disclosing not-found errors for foreign IDs.
- Create automations inactive and remove `is_active` from create/update tool arguments. Reject content edits on active automations until they are disabled. Keep `enable_automation` approval-gated and `disable_automation` immediate.

### Pipeline operations

Extend `OpportunityAssistantTools` with `get_opportunity`, `create_opportunity`, and `update_opportunity`, delegating to `OpportunityService`. Apply `pipeline_owner_scope` to list/get/update and force sales-tier creates to self-assignment, matching `backend/app/api/v1/opportunities.py`. Do not add destructive opportunity deletion.

## RBAC enforcement

- Add explicit capability entries for every new tool; the parity test must fail closed when a declared tool lacks a policy.
- Segment reads use `crm:read`; segment writes use `crm:write`; campaign enrollment uses `outreach:write`; opportunity writes use `pipeline:write_own` with object-level owner scoping.
- Apply `appointment_owner_scope` to assistant appointment list/get reads so sales and lower tiers see only their login-backed calendar assignment.
- At approved-action execution, load the initiator's current `WorkspaceMembership` for the action workspace. Missing membership, unknown role, or lost capability denies execution even if the queued role snapshot was privileged. The snapshot remains audit context only.
- Continue workspace predicates at every lookup and return the same not-found response for absent and foreign-tenant IDs.

## Files

### Backend implementation

- `backend/app/services/ai/crm_assistant/_tools.py`: strict schemas for segments, audiences, opportunities, and runtime-valid automation branches/actions/triggers.
- `backend/app/services/ai/crm_assistant/_segment_tools.py` (new): workspace-scoped tag/segment list, preview, create, and update handlers.
- `backend/app/services/ai/crm_assistant/_campaign_tools.py`: register campaign-audience enrollment.
- `backend/app/services/ai/crm_assistant/_automation_tools.py`: draft-only lifecycle, server-side workflow validation, and workspace resource checks.
- `backend/app/services/ai/crm_assistant/_opportunity_tools.py`: scoped get/create/update operations.
- `backend/app/services/ai/crm_assistant/_appointment_tools.py`: calendar owner predicates for restricted roles.
- `backend/app/services/ai/crm_assistant/_tool_executor.py`: register segment handlers.
- `backend/app/services/ai/crm_assistant/_tool_metadata.py`: capabilities, risk policies, and current-membership reauthorization for approved actions.
- `backend/app/services/contacts/contact_filter_validation.py` (new): fail-closed field/operator/value validation shared by segment, audience, and branch inputs.
- `backend/app/services/campaigns/audience_service.py` (new): idempotent, workspace-scoped audience resolution/enrollment shared by assistant and composite workflows.
- `backend/app/services/outbound/growth_workflow.py`: replace preview-only enrollment with the shared full-audience service.

No database migration or OpenAPI/client code generation is expected because all persisted models and public HTTP contracts already exist.

### Tests

- Extend `backend/tests/test_crm_assistant_tool_schemas.py` to prove every assistant automation enum has a matching closed config variant and unsupported runtime values are hidden.
- Extend `backend/tests/test_crm_assistant_automation_tools.py` for inactive drafts, malformed branches, active-edit refusal, and foreign-resource rejection.
- Add `backend/tests/test_crm_assistant_segments_and_audience.py` for filter fail-closed behavior, tenant isolation, deduplication, campaign state checks, and full segment enrollment.
- Extend `backend/tests/test_outbound_growth_operator_happy_path.py` with more than three contacts and assert all eligible matches are enrolled.
- Extend opportunity/appointment assistant tests for sales-owner scoping and manager-wide visibility.
- Extend assistant authorization tests for every new tool, direct unauthorized execution, and role downgrade/removal between queue and approval.

## Risks and controls

- **Outbound blast radius:** campaign starts and automation activation remain separate approval-gated tools; draft creation/enrollment sends nothing.
- **Prompt-injected targeting:** model output is validated against allowlisted filter fields/operators and workspace-owned IDs; unsupported rules fail instead of becoming an unfiltered query.
- **Large audiences:** resolve and count before writing, enforce a documented batch ceiling, and return narrowing guidance without partial enrollment.
- **Tenant leakage:** every ID lookup includes `workspace_id`; owner-scoped resources additionally include the current user where required.
- **Legacy automations:** public schema constants and stored rows remain backward compatible; only the assistant's model-facing creation contract is narrowed.

## Verification

- Run targeted tests for tool schemas, automation handlers, segments/audiences, growth workflow, tool execution, opportunities, appointments, and RBAC.
- Run backend formatting/lint/type checks on touched modules.
- Run `make ci.backend` as the final regression gate.
- Confirm no OpenAPI diff and no migration head change.
- Report runtime-tested claims separately from source-reviewed claims; external OpenAI/provider behavior is not exercised by unit tests.

## Steps

1. Add fail-closed contact-filter validation for model-authored segment and branch rules.
2. Add the shared campaign audience enrollment service with workspace, state, deduplication, eligibility, and size controls.
3. Add strict segment/tag tool definitions and workspace-scoped segment handlers.
4. Add campaign audience enrollment to the CRM Assistant and wire its capability/risk metadata.
5. Replace outbound growth workflow preview-only enrollment with full shared audience enrollment.
6. Narrow automation tool enums to executable runtime values and add closed branch/control-flow schemas.
7. Enforce inactive automation drafts, active-edit refusal, branch validation, and workspace-owned action references.
8. Add scoped opportunity get/create/update tools using the existing opportunity service.
9. Apply appointment owner visibility to assistant calendar reads.
10. Reauthorize approved actions against the initiator's current workspace membership and capability.
11. Add schema, resource lifecycle, tenant-isolation, owner-scope, approval-revocation, and full-audience regression tests.
12. Run targeted tests, touched-file lint/type checks, and the complete backend CI gate.
