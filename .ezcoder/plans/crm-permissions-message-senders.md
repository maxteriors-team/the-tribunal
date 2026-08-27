# CRM Permission Audit and Message Sender Attribution

## Objective

Audit the CRM’s workspace-role enforcement and close confirmed authorization gaps, then persist and display the actual human sender for every newly sent CRM message. Automated, AI, external-provider, and unrecoverable historical messages must be labeled honestly rather than shown as the current viewer (“You”).

The existing uncommitted edits in `backend/app/services/email.py` and `backend/tests/services/test_email.py` are unrelated user work and will not be changed.

## Confirmed findings

All findings below are **CODE** findings: confirmed by tracing current source, not by exercising production.

1. **High — admins can grant admin access despite the owner-only policy.** `backend/app/api/v1/workspaces.py::update_member_role` blocks editing an existing admin but allows an admin to promote a non-admin to `admin`; `backend/app/api/v1/invitations.py::create_invitation` also allows an admin to invite another admin. `backend/app/services/workspaces/bulk_members.py` already documents and enforces the intended rule: only an owner may grant admin. The two frontend role pickers expose the same invalid option.
2. **High — campaign sender numbers are not consistently tenant-bound.** `backend/app/api/v1/campaigns.py::_validate_campaign_sender` looks up globally unique numbers without `workspace_id`; voice and drip campaign creation do not validate number ownership at all. A workspace operator who supplies another customer’s known business number can make campaign state reference that number and potentially consume or impersonate the other workspace’s telephony resource.
3. **High — drip enrollment accepts cross-workspace contacts and agents.** `backend/app/api/v1/drip_campaigns.py::enroll_contact` queries only `Contact.id`; campaign creation accepts `agent_id` without checking its workspace. Standard and voice campaign enrollment already include the missing tenant predicate.
4. **Medium — CRM media routes bypass the CRM capability matrix.** `backend/app/api/v1/contact_attachments.py` and `backend/app/api/v1/integrations/companycam.py::get_contact_photos` require workspace membership but not `crm:read`/`crm:write`. A field technician intentionally denied the contact book can call these APIs directly and read customer media within the same workspace; attachment mutations are likewise not capability-gated.
5. **Integrity gap — outbound messages lose human authorship.** `backend/app/models/conversation.py::Message` has AI/agent metadata but no human sender. Authenticated manual-send routes in `backend/app/api/v1/contacts.py` and `backend/app/api/v1/conversations.py` receive `current_user` but drop it before `TelnyxSMSService.send_message`; the CRM-assistant `send_sms` tool also has a user ID but does not persist it. `frontend/src/components/conversation/outbound-message-item.tsx` therefore labels every non-AI outbound message as the current viewer with a generic “You” avatar.
6. **External attribution gap — Quo provides an outbound `userId`, but sync discards it.** Current Quo message resources expose `userId`, and the verified `GET /v1/users/{userId}` endpoint returns first name, last name, and email. `backend/app/services/quo/sync.py` currently stores none of those fields.

## Existing controls retained

- `backend/app/core/permissions.py` fails unknown roles down to the field tier and has an exhaustive eight-role capability test in `backend/tests/core/test_permissions.py`.
- Conversation reads and sends already use `CanReadCRM` and `CanSendComms`, and conversation/contact services scope records by workspace.
- Standard and voice campaign contact enrollment already scopes contact IDs to the campaign workspace.
- The bulk membership path already prevents admins from granting or editing admin roles.
- Telephony, Quo, contact, and message writes use SQLAlchemy expressions rather than interpolated SQL.

## Authorization changes

### Role assignment policy

Add one shared `can_assign_workspace_role(actor_role, target_role)` policy in `backend/app/core/roles.py`:

- owners may assign every `AssignableRole`, including `admin`;
- admins may assign every non-admin role;
- other roles may assign none (the `members:manage` dependency remains the first gate).

Use this policy in direct role updates, invitations, and bulk updates. On invitation acceptance, re-check that an admin invitation’s inviter is still an owner; this closes pending invitations created through the old gap and fails closed after an ownership change. Return 403 without writing when the policy fails.

Mirror the policy in `frontend/src/lib/workspace-roles.ts`, and use it in `frontend/src/components/workspaces/edit-member-dialog.tsx` and `frontend/src/components/workspaces/invite-member-dialog.tsx` so admins are not offered an action the API rejects. The backend remains authoritative.

### Campaign resources

Extend `backend/app/services/telephony/phone_number_resolver.py` with a workspace-scoped active-number resolver that can require SMS/iMessage or voice capability. Reuse it from standard, voice, and drip campaign create/start validation rather than repeating global number lookups.

- Standard campaigns must validate the sender against their workspace on create, update, and start.
- Voice campaigns must validate a voice-capable sender on create and start.
- Drip campaigns must validate an SMS/iMessage sender and a workspace-owned active text agent on create and start.
- Drip enrollment must query `Contact.id` together with `Contact.workspace_id` and return 404 for a foreign contact.
- `backend/app/services/rate_limiting/number_pool.py` must join/filter phone numbers by `campaign.workspace_id`, so legacy or manually-corrupted pool links cannot send cross-tenant.
- `backend/app/workers/voice_campaign_worker.py` and `backend/app/services/reactivation/drip_runner.py` must re-check sender ownership before provider calls; invalid running campaigns are paused and logged without sending.

### CRM media

Add `CanReadCRM` to attachment list/download and CompanyCam contact-photo reads. Add `CanWriteCRM` to attachment upload/delete. Keep the existing workspace ownership predicates, file-size/type checks, path containment, and storage controls unchanged.

## Sender attribution design

### Durable data model

Create `backend/alembic/versions/20260826_message_sender_attribution.py`, based on the current `20260826_quo_voice` head, with three nullable, additive `messages` columns:

- `sender_user_id BIGINT` — CRM user foreign key to `users.id`, `ON DELETE SET NULL`;
- `sender_display_name VARCHAR(255)` — immutable send-time snapshot (`full_name`, falling back to email);
- `provider_sender_user_id VARCHAR(255)` — provider-side identity such as Quo’s `US…` ID.

No existing row is rewritten or guessed. Nullable additions preserve message history and avoid a table-wide data backfill. Downgrade removes only these new fields; production should prefer a forward repair because downgrading after new sends would discard newly recorded attribution.

Update `backend/app/models/conversation.py::Message` and its user relationship. No index is added because sender is not a query predicate; message timeline queries continue using their existing contact/conversation indexes.

### Native/manual sends

Extend `TextMessageService.send_message` and `TelnyxSMSService.send_message` with optional sender user ID and display name. Persist both atomically with the `Message`; an idempotent retry may fill missing attribution but must never overwrite a populated sender.

Propagate the authenticated user through:

- `backend/app/api/v1/contacts.py` → `backend/app/services/contacts/contact_service.py`;
- `backend/app/api/v1/conversations.py` → `backend/app/services/conversations/conversation_service.py`, including manually triggered follow-ups;
- `backend/app/services/ai/crm_assistant/_campaign_tools.py`, resolving the tool context’s user through a workspace membership before attribution.

New non-human sends use explicit labels (`AI Agent` or `Automation`) at persistence time. Missing metadata on an old outbound row is shown as `Unknown sender (historical)`, never as the current viewer.

### Quo/external sends

Add `QuoClient.get_user(user_id)` using the current documented `/v1/users/{userId}` endpoint. In `backend/app/services/quo/sync.py`, capture outbound `userId`, resolve and cache each distinct Quo user for the sync run, and snapshot full name (email fallback). A provider lookup failure must not lose the message: store the provider user ID as an honest fallback and retry enrichment when a later event or historical backfill revisits the row.

The existing bounded, dry-run-first `scripts/ops/backfill_quo.py` already replays message resources through `QuoSyncService`; rerunning the approved historical windows after backup will enrich existing Quo outbound messages idempotently. Native historical human senders cannot be reconstructed from current data and will retain the explicit historical fallback.

### API and frontend

Expose `sender_user_id` and `sender_display_name` from `backend/app/schemas/conversation.py::MessageResponse` and `backend/app/schemas/contact.py::TimelineItem`. Populate timeline values in `backend/app/services/contacts/contact_repository.py`.

Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, then update `frontend/src/types/conversation.ts` and `frontend/src/types/contact.ts`.

Render the sender name above every outbound bubble in `frontend/src/components/conversation/outbound-message-item.tsx`; derive the avatar initial and accessible label from that name. Keep inbound layout and existing delivery/AI/tool controls unchanged.

## Tests and proof

### Regression tests written before fixes

- Extend `backend/tests/core/test_permissions.py` and add focused API tests for owner/admin role assignment and pending admin invitations.
- Extend `backend/tests/api/test_rbac.py` with field-technician denials for attachment and CompanyCam photo routes.
- Extend `backend/tests/api/test_campaigns_validation.py` and `backend/tests/api/test_voice_campaigns_workspace_isolation.py`; add `backend/tests/api/test_drip_campaigns_workspace_isolation.py` for foreign numbers, agents, and contacts.
- Add worker/service tests proving invalid tenant-bound sender resources never reach Telnyx/voice provider calls.
- Extend Telnyx, contact service, conversation service, CRM-assistant, timeline, and Quo sync tests to prove exact sender persistence, idempotent retry behavior, provider fallback, and serialization.
- Extend `frontend/src/components/conversation/outbound-message-item.test.tsx` and add `frontend/src/lib/workspace-roles.test.ts` for exact names, historical fallback, and owner/admin picker policy.

### Verification commands

1. Run the focused red tests before implementation, then rerun them green.
2. Run `make codegen` and verify both generated artifacts are present and stable.
3. Run `make ci.migrations` to exercise upgrade → model check → downgrade → upgrade against local PostgreSQL.
4. Run `make ci.backend` and `make ci.frontend`; do not claim `make ci.codegen` passes while intended generated artifacts remain uncommitted, because that target compares them with `HEAD`.
5. Start/use the local backend and inspect `/openapi.json` plus representative unauthorized media and campaign requests with `.ezcoder/eyes/http.sh`; verify sender fields and 401/403 behavior from the saved redacted responses.

## Audit boundaries and risks

- Checked: workspace-role capability mapping; member/invitation mutation; contact/conversation/message routes; standard, voice, and drip campaign ownership; contact attachments; CompanyCam contact photos; Quo message attribution; associated frontend guards.
- Not checked: auth token/session implementation, public/webhook signatures beyond Quo sender parsing, billing, secrets/history, dependency supply chain, deployment configuration, or every non-CRM domain router.
- Production rows were not inspected. Existing active campaigns with invalid cross-workspace references are only a possibility until production data is queried; runtime revalidation prevents them from sending after this change.
- Exact native sender identity before this migration is unrecoverable because no user identifier was stored. The plan preserves that uncertainty rather than fabricating attribution.
- Quo user enrichment adds one provider read per distinct sender per sync run; the per-run cache bounds repeated calls, and failures degrade to the provider user ID without dropping messages.

## Deliverable

Add `docs/crm-user-permissions-audit-2026-08-26.md` recording the confirmed source→sink paths, severities, fixes, tests run (`CODE`/`RUNTIME` labels), dropped candidates, residual historical attribution limit, and explicitly unchecked surfaces. It must not claim the CRM is “secure” or that production data was verified.

## Steps

1. Add failing authorization tests for admin role grants, CRM media gates, campaign resource ownership, drip contact/agent isolation, and worker fail-closed behavior.
2. Implement the shared backend role-assignment policy across direct updates, invitations, acceptance, and bulk membership changes.
3. Implement workspace-scoped phone/agent/contact validation across standard, voice, and drip campaign APIs, number pools, and workers.
4. Add CRM read/write capability dependencies to contact attachment and CompanyCam photo routes.
5. Add and map the reversible, nullable message-sender attribution migration without rewriting historical rows.
6. Add failing sender-attribution tests for native manual sends, idempotent retries, CRM-assistant sends, timelines, Quo sync, and historical fallbacks.
7. Persist authenticated sender snapshots through contact, conversation, follow-up, CRM-assistant, and Telnyx message paths.
8. Capture, cache, and safely expose Quo sender identities while preserving messages when user enrichment fails.
9. Extend backend schemas/timeline serialization and regenerate the OpenAPI and frontend API contracts.
10. Render exact outbound sender names and restrict frontend role pickers to roles the current actor may grant.
11. Write the scoped audit report with fixed findings, evidence labels, residual risks, and unchecked surfaces.
12. Run focused tests, migration reversibility, backend/frontend CI checks, code generation, and local HTTP probes; fix every relevant failure before reporting results.