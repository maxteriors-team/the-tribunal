# Quo single-inbox sending

## Goal

Make the CRM the only staff messaging interface for Quo-backed conversations. Quo remains the transport and webhook source, but staff compose, send, read, and track delivery in the CRM. Exactly one Quo phone number is active per workspace at a time, so messages from the user’s three Quo lines never mix.

## Settled product behavior

- Connecting Quo requires choosing one phone number returned by Quo; an API key alone is not enough.
- A workspace has exactly one active Quo number. The composer has no sender dropdown for Quo threads and always sends from that selected number.
- Switching the selected number changes future sync and sending. Existing history is retained, never deleted, and becomes visible again when that line is selected.
- A Quo contact timeline is scoped to the selected line’s conversation, so old lines are not mixed into the active view.
- Quo-backed threads use the normal CRM composer for manual text replies.
- Quo is provider metadata, not a second inbox: remove reply links and the read-only bridge.
- Keep a quiet `via Quo` indicator and the active phone number; do not add new product-brand copy because a rename is planned.
- Quo-backed automation, AI replies, follow-ups, outbound calls, and MMS remain disabled in this pass.
- Preserve the unrelated uncommitted receipt-email changes in `backend/app/services/email.py` and `backend/tests/services/test_email.py`.

## One-number integration boundary

Update the Quo integration lifecycle in `backend/app/api/v1/integrations/credentials.py`, `backend/app/services/quo/client.py`, and `frontend/src/components/settings/integration-config-dialog.tsx`:

- Testing either a candidate or stored key returns safe phone-number choices (`id`, normalized number, and provider label when available).
- The dialog requires one choice before save and shows the selected number after connection.
- The backend re-fetches the Quo phone-number list and derives the stored normalized number from the selected ID; it never trusts a client-supplied sender number.
- Encrypted integration credentials store `phone_number_id` and `phone_number` beside the API key and webhook metadata.
- Selection-only updates merge with the stored encrypted key; staff never need the existing key returned to the browser.
- Existing Quo integrations without a selection fail closed for syncing and sending until an administrator chooses a number.

Keep Quo’s wildcard webhook if resource-scoped subscriptions are not documented, but filter every message/call event locally by the selected `phoneNumberId`. Events lacking that ID or belonging to either unselected line are acknowledged and ignored with metadata-only logs. Standalone contact events are not imported globally; selected-line message/call processing resolves its own contact. Historical backfill validates and requests only the selected phone-number ID.

Add a small authenticated, non-secret active-line status response for CRM readers. `ConversationFeed` uses it to select the matching conversation and passes that conversation ID to an optional contact-timeline filter. Switching lines therefore swaps the active view without deleting old history. Outbound sending additionally compares the conversation’s server-owned workspace phone with the integration’s selected normalized phone and fails closed on mismatch.

## Outbound request lifecycle

Add `backend/app/services/quo/outbound.py` as a dedicated Quo sender rather than inheriting the current Telnyx commit path. It uses the existing redacting provider HTTP client with this fixed contract:

- `POST https://api.openphone.com/v1/messages`
- `Authorization: <workspace Quo API key>`
- JSON body `{content, from, to: [recipient]}`
- text only; media is rejected rather than dropped
- one network attempt only; Quo’s documented endpoint does not guarantee idempotency, so transport errors, 5xx responses, and rate limits are never automatically retried

Extend the existing message-create request with a client request UUID. The frontend generates it once per composer submission. A new `quo_send_attempts` table claims `(workspace_id, client_request_id)` before network I/O, preventing concurrent browser/API retries from issuing a second provider request.

Attempt states are `sending`, `accepted`, `failed`, and `unknown`:

- A documented 4xx rejection is `failed`; no timeline `Message` is created.
- A transport timeout/disconnect or 5xx response is `unknown`, not `failed`; no timeline `Message` is created because provider acceptance is unknowable.
- Replaying an `accepted` request returns its canonical message without another provider call.
- Replaying a `sending` or `unknown` request returns a clear “status unknown; wait for the timeline before retrying” response and never calls Quo again.
- A successful provider response atomically links the attempt to the canonical reconciled message.
- If an unknown attempt was actually accepted, the provider webhook creates the one canonical timeline row. The attempt remains an operational audit record because Quo supplies no documented client correlation value; it is never rendered as a second message.

The attempt table stores identifiers, state, timestamps, and sanitized error class only—not API keys, phone plaintext, or message body. Add model and migration coverage with explicit foreign keys and unique constraints.

## Atomic provider reconciliation

Add `backend/app/services/quo/reconciliation.py` as the only write path for Quo text-message resources. Outbound acceptance, signed webhooks, webhook retries, and historical backfills all pass a normalized `QuoMessageSnapshot` to `reconcile_quo_message()`. Remove the current check-then-insert/update logic from `QuoSyncService._sync_message()`.

The reconciliation statement is one PostgreSQL `INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING` keyed by `(source_provider, provider_message_id)` with `source_provider="quo"`:

- Generate the candidate message UUID before the statement; comparing the returned UUID with the candidate reports whether this transaction inserted the row without a preceding race-prone SELECT.
- Preserve immutable identity (`workspace`, conversation, direction, sender, recipient). A conflicting provider ID pointing at another workspace/conversation/direction returns no row and fails closed instead of merging tenants.
- Merge nullable body/provider metadata with `COALESCE`; never erase richer webhook/backfill data with a sparse send response.
- Merge lifecycle status monotonically (`queued < sent < failed < delivered`, with proof of delivery winning) and retain the greatest known lifecycle timestamps, so a late queued response cannot downgrade a delivered webhook.
- Apply new-message side effects only when the returned UUID equals the candidate UUID. Duplicate webhook/backfill/send contenders update lifecycle fields but cannot increment unread counts or create notifications twice.
- Update conversation preview/last-message timestamps with monotonic SQL or a row lock so an older backfill cannot replace newer activity.

Add a non-destructive migration that creates a Quo-only partial unique index on `(source_provider, provider_message_id)` where `source_provider='quo'` and the provider ID is non-null. Keep the existing stronger global provider-ID constraint for legacy providers. Build/drop the new index concurrently so production message writes are not blocked. The upsert explicitly targets the partial composite index.

The send-response transaction and webhook transaction may run in either order: both execute the same upsert, PostgreSQL serializes the conflict, both receive the same canonical UUID, and exactly one durable timeline row remains. There is no catch-and-log integrity-conflict fallback.

## Conversation send and consent

Update `ConversationService.send_message()` in `backend/app/services/conversations/conversation_service.py`:

- retain the authenticated workspace-scoped conversation lookup
- choose Quo only from `conversation.source_provider`, never request data
- resolve the active integration in that same workspace and require both selected phone ID and exact selected sender number
- reject a known contact opt-out or matching `GlobalOptOut` before creating an attempt
- allow unknown consent only when that exact conversation already contains inbound SMS; starting outbound still requires recorded SMS consent
- route Quo through the dedicated attempt/reconciliation service and close its client in `finally`
- map definitive provider rejection and ambiguous status to distinct, sanitized API errors so the UI never reports success incorrectly

The existing signed webhook remains authoritative for sent/delivered/failed lifecycle updates and STOP remains routed through the shared opt-out manager.

## Frontend

Update `frontend/src/components/conversation/conversation-feed.tsx`, `message-composer.tsx`, and the relevant API/query-key helpers:

- load the safe active Quo line and select only its matching conversation for the contact
- request the contact timeline with that conversation ID for Quo, preventing the other two lines’ history from mixing into the active view
- send through `conversationsApi.sendMessage` with one stable `client_request_id` per submission
- use the conversation’s fixed sender; hide sender selection and image attachment controls
- on an ambiguous response, retain the draft and show “Delivery status unknown—wait for the message to appear before retrying” rather than “failed”
- preserve keyboard sending, mutation locking, timeline polling, and accessible labels

Update `chat-header.tsx` with a small `via Quo · <selected number>` badge. Remove provider exit paths from `message-item-shell.tsx`, delete `quo-bridge-banner.tsx`, and delete the unused Quo-link helper/tests. Update AI/follow-up explanatory copy to neutral, rename-safe “manual messaging only” language.

## API, migration, and documentation artifacts

This revision changes schemas and storage. Generate and commit:

- one Alembic migration for `quo_send_attempts` and the concurrent Quo composite unique index
- model/schema changes for the attempt lifecycle, active-line status, timeline conversation filter, and client request UUID
- `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` through the repository codegen workflow
- `docs/quo-integration-runbook.md` with one-number selection/switching, text-only sending, unknown-status behavior, and duplicate guarantees
- the focused Quo addendum in `COMPLIANCE.md`, labelled as engineering controls rather than legal certification

No existing message or conversation rows are deleted or rewritten. The migration touches neither contacts nor leads; production backup is therefore not required by the repository release rule, but migration up/down/up verification remains required.

## Verification

- Provider contract tests: exact host/path/header/body, selected sender, text-only rejection, sanitized errors, and exactly one network attempt after transport/5xx/429 outcomes.
- Integration selection tests: three returned Quo numbers require exactly one valid selection; unselected webhook events and backfill resources create zero contacts/conversations/messages; switching changes the accepted line without deleting prior history.
- Tenant tests: another workspace’s integration, number ID, conversation, or send attempt cannot be read or used.
- Consent tests: STOP/global opt-out blocks before attempt/network I/O; unknown consent without inbound history blocks; inbound history or explicit opt-in permits the direct reply.
- Atomic race test: start independent database sessions for outbound acceptance, webhook delivery, and backfill against the same provider ID behind a barrier; commit them concurrently; assert one `Message`, one canonical UUID, monotonic delivered status, one set of side effects, and one linked accepted attempt.
- Reverse-order race test: commit webhook before the provider-response transaction and assert the response links to that existing row without an integrity error.
- Ambiguous transport test: assert one `unknown` attempt, zero definitive failed/timeline messages, no automatic provider retry, stable replay behavior, and later webhook creation of exactly one timeline row.
- Frontend tests: number selection is mandatory; only the selected line renders; composer uses a fixed sender/request UUID; MMS and Quo exit links are absent; ambiguous status retains the draft; manual-only restrictions remain.
- Run targeted backend tests, frontend Vitest suites, backend lint/type checks, frontend lint/type checks, OpenAPI codegen drift checks, and `make ci.migrations`.
- Do not send a live production SMS during implementation. Record that carrier delivery and real-recipient consent were not runtime-verified.

## Steps

1. Add the non-destructive attempt-table and Quo composite-index migration plus matching models.
2. Add typed one-number credential validation, active-line status, local webhook filtering, and selected-line backfill behavior.
3. Implement the durable Quo send-attempt claim and one-attempt provider client.
4. Implement the atomic Quo message reconciliation upsert and route outbound responses, webhooks, and backfills through it.
5. Add workspace, sender-line, opt-out, consent, definitive-failure, and unknown-status enforcement to conversation sending.
6. Add backend contract, tenant, selection, migration, ambiguity, reverse-order, and concurrent three-writer reconciliation tests.
7. Regenerate OpenAPI artifacts for the request, status, and timeline contract changes.
8. Add required one-number selection and switching behavior to the integration dialog.
9. Replace the read-only bridge with the fixed-sender CRM composer, selected-line timeline, and truthful unknown-status handling.
10. Remove Quo exit links/read-only branding and add neutral active-line/manual-only indicators.
11. Update frontend tests, the Quo runbook, and the focused compliance register addendum.
12. Run targeted checks, migration up/down/up verification, codegen drift checks, and relevant backend/frontend CI commands.
13. Review the final diff to confirm exactly-one-row race evidence, untouched receipt-email work, no secrets, and no unrelated changes.