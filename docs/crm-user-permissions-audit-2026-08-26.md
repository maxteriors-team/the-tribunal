# CRM workspace permissions and message sender audit — 2026-08-26

## Scope and claim limits

This review checked workspace-role assignment, CRM contact media, standard/voice/drip campaign resource ownership, campaign runtime sender selection, native CRM SMS authorship, and Quo outbound-message authorship. Findings are labelled **CODE** when traced from source and **RUNTIME** when exercised locally.

This report does **not** claim the CRM is secure. Production rows were not inspected, and the unchecked surfaces are listed below.

## Fixed findings

### High — admins could grant admin access

**CODE source → sink:** an authenticated admin could submit `role=admin` to `update_member_role` or `create_invitation`; both handlers passed the general `members:manage` gate and wrote an admin membership or invitation. The bulk path already documented the intended owner-only policy.

**Fix:** `backend/app/core/roles.py` now owns one fail-closed `can_assign_workspace_role` policy. Owners may assign every assignable role; admins may assign only non-admin roles; every other or unknown actor role may assign none. Direct updates, invitations, invitation acceptance, and bulk membership changes use that policy. Pending admin invitations are rejected when their inviter is no longer an owner.

**Frontend mirror:** role pickers use the same policy to stop offering admin grants to admins. The API remains authoritative.

**RUNTIME:** focused policy, direct-update, invitation, acceptance, and bulk tests pass locally.

### High — campaign sender numbers could cross workspace boundaries

**CODE source → sink:** campaign request data reached global `PhoneNumber.phone_number` lookups, while voice and drip creation lacked equivalent ownership checks. A known number from another tenant could be persisted into campaign state and later selected for provider traffic.

**Fix:** one resolver now requires the number to belong to the campaign workspace, be active, and provide the requested text or voice capability. Standard campaigns validate text senders on create, update, and start. Voice campaigns validate voice senders on create and start. Drip campaigns validate text senders on create and start.

**Runtime containment:** number-pool selection joins phone numbers and filters by `campaign.workspace_id`. Voice and drip runners re-check senders before provider calls; invalid running campaigns are paused and logged without sending. Drip conversation-number continuity accepts only an active workspace-owned text number.

**RUNTIME:** focused standard, voice, drip, number-pool, and worker tests pass locally, including assertions that provider calls are not reached.

### High — drip contacts and agents could cross workspace boundaries

**CODE source → sink:** drip creation accepted an `agent_id` without workspace validation, and enrollment selected `Contact.id` without `Contact.workspace_id`; both values could reach campaign enrollment and automated SMS processing.

**Fix:** supplied drip agents must be active, belong to the campaign workspace, and support text or both channels. Enrollment now selects contacts through the campaign workspace predicate and treats foreign contacts as not found.

**RUNTIME:** focused foreign-agent and foreign-contact tests pass locally.

### Medium — standard campaign updates could attach a foreign agent

**CODE source → sink:** creation scoped `agent_id`, but draft/paused campaign updates wrote a supplied UUID directly. Start did not re-check it; the SMS worker assigned it to conversations, and inbound AI previously loaded conversations and agents by ID without workspace predicates. A known foreign agent UUID could therefore expose its prompt and knowledge preamble after a controlled recipient replied.

**Fix:** standard campaign create, update, and start now require an active, workspace-owned text agent. The SMS worker pauses a corrupted campaign before sending or assigning the agent. Inbound AI independently scopes both conversation and agent lookups to the supplied workspace and requires an active text agent.

**RUNTIME:** cross-workspace update/start, worker fail-closed, and inbound query-scope tests pass locally. This candidate was found during the final defensive review and independently confirmed before fixing.

### Medium — CRM media routes bypassed CRM capabilities

**CODE source → sink:** workspace membership alone reached attachment list/download/upload/delete and CompanyCam contact-photo reads. A field technician intentionally denied the contact book could call these routes directly.

**Fix:** attachment reads and CompanyCam photo reads require `crm:read`; attachment mutations require `crm:write`. Existing workspace predicates, private-storage controls, file validation, and attachment ownership checks remain in place.

**RUNTIME:** field-technician denial tests cover all five route classes and pass locally.

### Integrity — native outbound messages lost human authorship

**CODE source → sink:** authenticated contact, conversation, and manual-follow-up routes received `current_user`, but service calls discarded it before `Message` persistence. The CRM-assistant SMS tool similarly had a context user ID but did not validate membership or persist attribution.

**Fix:** new outbound message writes accept `sender_user_id` and a send-time `sender_display_name` snapshot. Contact, conversation, manual-follow-up, and CRM-assistant paths propagate the authenticated workspace member. Idempotent retries may fill missing fields but never overwrite populated attribution. Non-human sends persist `AI Agent` or `Automation`.

**Durability:** migration `20260826_msg_sender` adds three nullable columns without rewriting historical rows: `sender_user_id` with `ON DELETE SET NULL`, `sender_display_name`, and `provider_sender_user_id`. No sender index was added because timeline queries do not filter on sender. The migration follows the actual current local head (`20260826_sms_drafts`) so unrelated pending migrations remain one linear chain.

**RUNTIME:** Telnyx persistence/idempotency, contact service, conversation/manual-follow-up, and CRM-assistant membership tests pass locally.

### Integrity — Quo outbound `userId` was discarded

**CODE source → sink:** outbound Quo message resources contain `userId`; sync persisted message content and provider IDs but not the sending user. The current Quo documentation was checked for `GET /v1/users/{userId}` and its `firstName`, `lastName`, and `email` response fields.

**Fix:** `QuoClient.get_user` validates provider identity and uses the path-versioned endpoint. Sync resolves each distinct outbound sender once per service run, snapshots full name with email fallback, and stores the provider user ID. Provider lookup failures preserve the message and use the provider ID as an honest display fallback. A later sync may replace only that fallback; a real snapshot is not overwritten.

**Retirement note (2026-09-02):** the former provider backfill command was removed during code severance. This review did not execute a production backfill.

## Sender API and UI behavior

`MessageResponse` and contact `TimelineItem` expose nullable `sender_user_id` and `sender_display_name`. Timeline serialization copies both fields from `Message`; generated OpenAPI and frontend contracts include them.

Every outbound bubble displays its stored sender name and derives its avatar initial and accessible label from that value. A row with no attribution displays `Unknown sender (historical)` and never claims the current viewer sent it. Inbound layout, delivery state, Quo controls, AI badges, and tool controls remain unchanged.

## Dropped candidates and retained controls

- **Dropped — unknown-role escalation:** `backend/app/core/permissions.py` fails unknown roles to the field tier, and the exhaustive eight-role capability matrix remains covered.
- **Dropped — standard conversation/contact API tenant leak:** reviewed API reads/sends and repository queries combine CRM capabilities with workspace predicates. The separate inbound-AI lookup gap found during final review is fixed above.
- **Dropped — standard/voice contact enrollment leak:** those enrollment queries already include the campaign workspace.
- **Dropped — bulk admin grant:** the existing bulk implementation already blocked admins from granting or editing admins; it now delegates the shared policy to prevent drift.
- **Dropped — SQL injection in reviewed writes:** reviewed telephony, Quo, contact, and message paths use SQLAlchemy expressions rather than interpolated SQL.

These dropped candidates are not statements about unreviewed neighbouring modules.

## Residual limits and operational risk

- Native human sender identity before this migration is unrecoverable from current data. Historical rows remain explicitly unknown rather than guessed.
- Quo historical attribution is incomplete until approved windows are backed up and replayed. Lookup failures intentionally retain provider-ID fallbacks for later retry.
- Existing production campaigns with foreign or inactive resource references are possible because production rows were not queried. Runtime validation prevents those campaigns from sending after deployment.
- Downgrading after attributed messages are written discards the three new fields. Production should prefer a forward repair.
- Quo enrichment adds one provider read per distinct outbound sender per sync run; the per-run cache bounds repeats.

## Unchecked surfaces

This review did not check auth token/session implementation, public or webhook signatures beyond Quo sender parsing, billing, secrets or git history, dependency supply chain, deployment configuration, every non-CRM router, or production database contents.

## Verification record

### RUNTIME — passing

- Focused backend regression suite: **201 passed** across role policy, CRM media, standard/voice/drip isolation, worker fail-closed behavior, inbound-AI scoping, native attribution, serialization, timeline, and Quo client tests.
- Quo sender-enrichment and historical-backfill integration selection: **4 passed** against local PostgreSQL.
- `make ci.backend`: environment drift, evals, lint, formatting, mypy, **4,907 tests**, and **60.72%** coverage passed; 21 tests skipped and 789 integration/eval cases were deselected by repository policy.
- Independent backend suite excluding every test/check file edited in this work: **4,758 passed, 21 skipped, 787 deselected**. This protects against self-validating test edits.
- `make ci.migrations`: upgrade → model check → downgrade → upgrade passed; the attendance integration gate also passed **6/6**.
- `make ci.frontend`: lint, type-check, **1,563 tests across 188 files**, and the production Next.js build passed.
- `make ci.codegen`: export and TypeScript generation passed against the intended generated artifacts. They were staged only for the HEAD-based drift comparison, then immediately returned to their original unstaged state; no commit was created.
- Local API-only backend: `/openapi.json` returned 200 with both sender fields; unauthenticated attachment and campaign requests returned 401 without data.
- UI inspection: `.ezcoder/eyes/out/sender-attribution-ui.png` shows human, AI, automation, and historical labels with derived initials.

No recognized verification gate remains blocked.
