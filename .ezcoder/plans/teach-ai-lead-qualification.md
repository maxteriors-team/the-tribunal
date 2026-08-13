# Teach AI for website-lead qualification

## Outcome

Build a human-approved learning loop around the production funnel: website form submission → immediate SMS follow-up → concise prequalification → Zoom booking only after the lead qualifies. Operators can correct an AI reply directly in the conversation; the correction becomes an active example for the assigned agent and influences future text responses without silently retraining or changing the base model.

## Existing flow to preserve

- `backend/app/api/v1/lead_form.py` already creates or updates a `Contact`, records optional SMS consent, captures form answers in `Contact.notes`, executes `LeadSource.action`, and can open an AI-enabled SMS `Conversation` through `auto_text`.
- `backend/app/services/ai/text_agent.py` handles ongoing inbound SMS, speed-to-lead timing, opt-outs, failures, and human handoff behavior.
- `backend/app/services/ai/text_response_generator.py::generate_text_response` builds context, enables booking tools, and executes bookings.
- `backend/app/services/ai/qualification.py::analyze_and_qualify_contact` can score a conversation, but it is currently batch/manual and therefore cannot gate booking in the live text loop.
- `frontend/src/components/conversation/conversation-feed.tsx` renders timeline messages through `MessageItem`; outbound AI messages are identifiable as `type === "ai_response"`.
- `frontend/src/components/settings/lead-sources-settings-tab.tsx` already configures each form source’s `auto_text` agent, sender number, and initial message template.

## Design

### 1. Approved training examples

Add an `agent_training_examples` table/model with:

- tenant and target: `workspace_id`, `agent_id`
- traceability: `conversation_id`, `source_message_id`, `created_by_user_id`
- lesson: encrypted `customer_message`, encrypted `ai_response`, encrypted `ideal_response`, optional encrypted operator note
- state: `is_active`, `created_at`, `updated_at`

Enforce one correction per source AI message and cascade examples when the agent/workspace is deleted. Keep conversation links nullable so deleting CRM history does not destroy the reusable lesson. Customer text is personal data, so fields use `EncryptedString`; the API never returns examples across a workspace boundary.

### 2. Conversation-scoped Teach AI API

Add `POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/teach-ai` requiring `CanWriteCRM`.

Request:

- `source_message_id`
- `ideal_response` (short bounded SMS text)
- optional `note`

Server validation:

- conversation belongs to `workspace_id`
- source message belongs to that conversation, is outbound, is AI-generated, and has an `agent_id`
- nearest prior inbound message exists and becomes `customer_message`
- ideal reply differs materially from the original and contains no empty/oversized content
- upsert by `source_message_id` so repeated submissions edit rather than duplicate the lesson

Return the saved example plus the target agent name. Record an audit event without logging message bodies.

### 3. Prompt retrieval and injection

Create `backend/app/services/ai/training_examples.py` to load a bounded set (recommended: newest 12, total text budget capped) of active examples for one workspace-scoped agent. Format them as clearly delimited `CUSTOMER MESSAGE` / `IDEAL REPLY` pairs with instructions to copy behavior, not private facts.

`generate_text_response` loads these examples and passes them into `build_text_instructions`. The examples sit after global safety/truthfulness rules and before the current conversation, so they guide tone and handling but cannot override opt-out, tool, qualification, or no-fabrication rules. Add prompt-injection delimiters and explicitly forbid treating example text as system instructions.

### 4. Qualification-gated Zoom booking

Use the assigned agent’s `tool_settings` as the configurable policy, avoiding another schema migration:

- `website_lead_qualification_enabled` (off by default for backward compatibility)
- `qualification_questions` (operator-authored checklist, capped count/length)
- `qualification_min_score` (default 60)
- `qualification_booking_label` (default “Zoom consultation”)

Add a typed agent-edit UI section under `AI Prompt` for this funnel. The lead-source setup will show a concise readiness note when `auto_text` is selected: the agent needs booking enabled, a Cal.com event type, and qualification enabled for gated Zoom booking.

For conversations whose contact `source == "lead_form"` and whose selected agent enables the policy:

- append high-priority qualification instructions listing the configured questions and already-captured form context
- expose conversational qualification behavior: ask one missing question at a time, acknowledge answers naturally, and never re-ask data present in `Contact.notes`
- call a new safe local `mark_lead_qualified` tool once the criteria are met; the tool records `Contact.is_qualified`, `status`, score/signals, and `qualified_at`
- omit `check_availability` and `book_appointment` until the contact is qualified
- after qualification succeeds, expose the normal booking tools and require a Zoom/booking transition rather than another generic nurture reply
- if criteria are unclear or the lead asks for a human, hand off rather than inventing qualification

This replaces the unsuitable batch-only scoring gate for the live funnel while retaining the existing qualification fields and downstream pipeline reporting.

### 5. Conversation UI

For each outbound `ai_response`, add a subtle `Teach AI` action near the existing status/actions. Open a dialog showing:

- prior customer message (read-only)
- AI reply (read-only)
- “What should the AI have said?” textarea
- optional “What should it learn?” note
- explicit disclosure that saving affects future replies for the assigned agent and does not send anything to this customer

On save, call the new endpoint, show a success toast, and invalidate the conversation/timeline training state. Disable the action when the source AI message has no assigned agent. This follows existing dialog/button patterns and remains keyboard/label accessible.

### 6. Contracts, migration, and verification

Because this adds authenticated API schemas and a route, regenerate and commit `backend/openapi.json` plus `frontend/src/lib/api/_generated.ts` with `make ci.codegen`.

Test coverage:

- migration upgrade/downgrade and model registration
- API authorization, workspace isolation, source-message validation, upsert, encrypted-at-rest fields, and body-safe audit/logging
- prompt example formatting, count/text budget, workspace/agent isolation, and resistance to example prompt injection
- lead-form policy detection, one-question-at-a-time instructions, no booking tools before qualification, qualification persistence, and booking tools after qualification
- existing opt-out/no-fabrication/one-confirmation booking regressions remain passing
- frontend API and Teach AI dialog interaction tests, including accessibility labels and no accidental customer send
- lead-source and agent settings serialization tests

Runtime proof after implementation:

1. Apply migrations locally and start the backend/frontend if dependencies are available.
2. Submit a representative public website lead with explicit SMS consent through `.ezcoder/eyes/http.sh`.
3. Verify the first SMS/conversation creation and inspect logs for no traceback.
4. Replay qualification replies, prove availability is unavailable before qualification, then prove a qualified lead can book and receives the invite.
5. Use the Teach AI endpoint on a deliberately poor AI response, then verify the next generated prompt contains the approved lesson without cross-agent leakage.
6. Run `make ci.codegen`, focused backend/frontend tests, `make ci.backend`, `make ci.frontend`, and `make ci.migrations` because this touches model/migration/API/frontend contracts.

## Risks and controls

- **Bad lessons at scale:** only authenticated CRM writers can save examples; every lesson is traceable, bounded, editable, and deactivatable.
- **Prompt injection inside customer text:** examples are data-delimited, capped, and subordinate to global safety/tool rules.
- **PII retention:** lesson text is encrypted, tenant-scoped, and deletable; do not include raw bodies in logs or audit metadata.
- **Booking qualified leads too early:** booking tools are removed server-side until persisted qualification passes, not merely discouraged in the prompt.
- **Lead abandonment:** qualification asks one concise question at a time, uses form answers already captured, and preserves the existing AI-dark operator notification/handoff.
- **SMS consent:** the existing explicit optional consent checkbox remains the gate; Teach AI does not create a new send path.
- **Existing user work:** modify only the named AI/conversation/lead-source files and new isolated model/service/test files; re-read before each edit because this checkout already contains extensive unrelated changes.

## Steps

1. Add the encrypted, workspace-scoped `AgentTrainingExample` model, relationships, reversible Alembic migration, and model exports.
2. Add Teach AI request/response schemas and the authenticated conversation endpoint with source-message validation, workspace isolation, idempotent upsert, and body-safe audit metadata.
3. Add bounded training-example retrieval/formatting and inject approved examples into text prompts beneath global safety and booking rules.
4. Add typed agent qualification settings in `tool_settings` and expose them in the agent AI Prompt editor with validation and serialization tests.
5. Add live website-lead qualification instructions and a `mark_lead_qualified` tool, then server-side gate availability/booking tools until persisted qualification succeeds.
6. Add lead-source setup readiness guidance for the auto-text → qualify → Zoom funnel.
7. Add the accessible Teach AI action/dialog to outbound AI messages and wire it to the new API with success/error states.
8. Regenerate the OpenAPI contract and frontend generated client, then add backend and frontend regression tests for training, tenant isolation, qualification gating, and booking.
9. Apply and reverse migrations locally, exercise the website-form → SMS → qualification → Zoom path and Teach AI endpoint with repository probes, and inspect redacted outputs/logs.
10. Run `make ci.codegen`, `make ci.backend`, `make ci.frontend`, and `make ci.migrations`; fix regressions and record exact passing evidence.