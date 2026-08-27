# Quo single-inbox operations runbook

Quo is the transport and webhook source; the CRM is the only staff messaging interface. Each CRM workspace has exactly one active Quo phone number. Treat a Quo API key like an administrator password: never place it in source, logs, tickets, shell history, or prompts.

## Connect one phone number

1. In Quo, create a dedicated API key for the intended environment.
2. In the CRM, open **Settings → Integrations → Quo**, enter the key, and select **Test Connection**.
3. Choose exactly one phone number from the provider-returned list. A key without a selection cannot be saved.
4. Save and confirm the integration displays **Connected** and the selected normalized number.
5. Confirm Quo shows the CRM webhook as enabled for the intended backend URL.

The server re-fetches Quo's phone-number list and derives the stored number from the selected provider ID. It never trusts a browser-supplied sender number. The API key, selected line, and webhook metadata are encrypted at rest; authenticated CRM readers receive only the active line's non-secret ID and number.

Existing integrations created before line selection fail closed: synchronization and sending stay disabled until an administrator selects a provider-validated number.

## Work from the CRM inbox

- Open the contact in the CRM. The header shows `via Quo · <active number>`.
- The timeline displays only that contact's conversation on the active Quo line.
- Send manual text replies with the normal CRM composer. The selected line is fixed; there is no sender menu.
- Quo conversations do not support attachments, MMS, outbound calls, AI replies, automations, or generated follow-ups in this release.
- Do not open Quo to reply. Provider exit links and the former read-only bridge are intentionally absent.

Before sending, the server rechecks the workspace, conversation provider, selected line ID and number, contact opt-out state, and SMS consent. A direct reply is allowed when the exact conversation already has inbound SMS; starting outreach still requires recorded SMS consent. A `STOP` received through Quo uses the shared CRM opt-out path.

## Switch the active line

1. Open the connected Quo integration and select **Change phone number**.
2. Test the connection if entering a replacement key; otherwise choose from the provider-validated lines using the stored encrypted key.
3. Save one line and confirm the integration card shows the new number.
4. Open a known contact and confirm the header and timeline use the newly selected line.

Switching changes future synchronization, backfill, and sending. It does not delete or rewrite messages, conversations, contacts, or leads. History from the previous line remains stored and becomes visible again if that line is selected later.

Quo may keep one wildcard webhook. The CRM acknowledges but ignores message or call events that lack `phoneNumberId` or belong to another line. Standalone contact events never import contacts globally; accepted selected-line message and call events resolve their own contact.

## Handle uncertain sends safely

Every composer submission carries one stable client request UUID. The CRM claims that UUID before contacting Quo and makes exactly one provider request.

If the CRM says **“Delivery status unknown—wait for the message to appear before retrying”**:

1. Do not resend, refresh into a new draft, or copy the text into another submission.
2. Leave the draft intact and wait for the timeline to poll or receive the Quo webhook.
3. Check provider/webhook health if no message appears after the normal delivery window.
4. Escalate with workspace ID, conversation ID, request UUID, time, and sanitized error class only—never message text, phone numbers, or credentials.

A timeout, disconnect, rate limit, or Quo 5xx can leave provider acceptance unknowable. The attempt remains `unknown`; replaying the same UUID does not call Quo again. A later signed webhook may create the canonical timeline message. Only a documented provider rejection is definitive failure.

## Duplicate and ordering guarantees

- Concurrent browser or API retries with one request UUID issue at most one Quo request.
- Provider acceptance, signed webhooks, webhook retries, and historical backfill use the same provider-message reconciliation path.
- A Quo provider message ID maps to one canonical timeline row.
- Late or sparse events cannot erase richer content or downgrade a delivered status.
- Duplicate contenders do not repeat unread-count, notification, or conversation-preview side effects.
- Older backfill activity cannot replace a newer conversation preview.

Do not manually delete send-attempt or message rows to resolve an incident. Preserve them for reconciliation and audit.

## Rotate a key

1. Create a new dedicated Quo key while the old key remains active.
2. Replace the key in the CRM, run **Test Connection**, select the intended line again, and save.
3. Confirm the replacement webhook is enabled and selected-line events reach the CRM.
4. Remove any orphaned old webhook, then revoke the old key.

If replacement validation fails, leave the old key active. Never compare or log plaintext keys.

## Backfill safely

Use [`docs/quo-historical-backfill.md`](./quo-historical-backfill.md) with one explicit CRM workspace and a half-open UTC window no longer than 31 days.

1. Confirm the stored selected phone ID still exists in Quo and matches its stored normalized number.
2. Run without `--apply`; dry-run is the default and rolls back all writes.
3. Review aggregate counts only. Stop on provider, tenant, line, or resource validation errors.
4. Follow the historical-backfill runbook's backup requirement, then repeat the identical command with `--apply`.
5. Re-running the same bounded window is safe because reconciliation is idempotent.

Backfill requests and accepted resources are constrained to the selected line. Unselected-line resources and standalone contacts create no CRM rows.

## Disconnect and monitor

Disconnecting removes the encrypted integration credential and attempts best-effort webhook cleanup. It never deletes existing CRM history. Manually remove an orphaned Quo webhook before revoking its dedicated key.

Investigate:

- webhook signature or credential-validation failures;
- selected-line events missing from the CRM beyond the normal retry window;
- repeated ignored events caused by a stale selected phone ID;
- any SMS after a known opt-out;
- `unknown` attempts without a later canonical message.

Operational logs may contain bounded IDs, event type, state, and sanitized error class. They must not contain API keys, webhook secrets, phone numbers, message bodies, transcripts, or full provider responses.

## Verification boundary

Automated contract, tenant, consent, ambiguity, duplicate, and PostgreSQL reconciliation tests exercise these engineering controls. They do not prove carrier delivery, inbox placement, recipient identity, or lawful consent for a real recipient. No live production SMS, customer call, recording playback, transcript review, or production backfill was performed during implementation.
