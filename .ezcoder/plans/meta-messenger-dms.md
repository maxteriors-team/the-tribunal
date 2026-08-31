# Meta Messenger + Instagram DMs as a CRM channel

## Goal

Inbound Facebook Messenger and Instagram Direct messages land in the existing
conversation inbox, are answerable from the app, and attribute to `facebook_ads`
so they feed the same Lead Source ROI card as Instant Form leads.

## What exists today

- `backend/app/api/webhooks/meta.py` — verified Meta webhook, but it only routes
  `field == "leadgen"`. Signature check (`_verify_signature`), body cap
  (`_bounded_body`), and the `hub.challenge` handshake are already correct and
  reusable as-is for a `messages` field.
- `backend/app/services/lead_sources/meta_lead_ads_service.py` — Graph client
  (`MetaLeadAdsClient`) with URL validation, timeouts, PII-safe errors. Page
  token already stored encrypted per workspace in `WorkspaceIntegration`.
- `backend/app/api/webhooks/mac_relay_handlers.py` — the closest precedent: a
  non-Telnyx transport feeding the shared inbound pipeline.
- `backend/app/services/telephony/inbound_text.py` — shared ingestion
  (`process_inbound_text_event`, `persist_inbound_text_message`) that drives AI
  reply scheduling, campaign sync, engagement scoring, push, and auto-opening an
  opportunity.
- `backend/app/services/telephony/text_provider.py` — `TextMessageProvider`
  protocol + `provider_for_conversation()`, the seam a Messenger sender plugs into.

## The blocker: the data model is phone-keyed, DMs have no phone

Verified in the models:

- `backend/app/models/contact.py:75-76` — `phone_number` and `phone_hash` are
  both `nullable=False`.
- `backend/app/models/conversation.py:163-168` — `workspace_phone`,
  `workspace_phone_hash`, `contact_phone`, `contact_phone_hash` all
  `nullable=False`, with `uq_conversation_phones` unique across
  `(workspace_id, workspace_phone_hash, contact_phone_hash)`.
- `_get_or_create_text_conversation()` keys threads purely on those two hashes.

A Messenger sender is a **Page-Scoped ID (PSID)** plus a display name. No phone,
ever, unless the person types one. So there is no way to persist a DM thread
without changing this keying.

One thing already works in our favour: `Conversation.contact_id` is **nullable**
(`conversation.py:148`), so contact-less threads are an existing, supported state.

### Options

| | Approach | Cost | Risk |
|---|---|---|---|
| **A (recommended)** | Add `messenger_psid`/`_hash` to `conversations`; make the phone columns nullable; swap `uq_conversation_phones` for two partial unique indexes | 1 migration on `conversations`, no change to `contacts` | Medium — migration on a live table, but `contacts` (the encrypted PII table) is untouched |
| B | Store `messenger:<psid>` in the existing phone columns | No migration | Poisons `phone_lookup_variants`, and a campaign or AI could try to text a non-number. Real correctness hazard |
| C | No thread until the person shares a phone | Trivial | Throws away the conversation — defeats the feature |

**Recommendation: A.** It confines the change to `conversations`, leaves the
encrypted `contacts` table alone, and reuses the already-supported
`contact_id IS NULL` state. A DM thread links to a contact only once a phone or
email surfaces in the conversation.

## The policy constraint that shapes the product

Meta's standard messaging window is 24 hours from the user's last message; after
that a send fails with error code 10 unless it carries an approved tag. The
7-day human-agent tag explicitly does **not** cover bot-generated replies — so
**AI follow-up on Messenger is hard-capped at 24h**, unlike SMS. Instagram also
rate-limits automated DMs to ~200/hour.

Practical consequence: the Messenger agent's job is to get a phone number inside
the window and continue on SMS. This should be an explicit behaviour, not an
accident — otherwise silent code-10 failures look like the AI ghosting leads.

## Scope

**In:** inbound Messenger + IG DM ingestion, inbox display, manual operator
reply, AI reply inside the 24h window, window-expiry handling, `facebook_ads`
attribution, per-workspace Page routing.

**Out (later):** DM campaigns/blasts, message tags, sponsored messages,
comment-to-DM automation, WhatsApp.

## Risks

- **Migration on a live table.** `conversations` is hot, so it gets touched
  **exactly once**: every schema change lands in a single migration (step 1 →
  step 2), never a follow-up ALTER. All local work runs against Docker Postgres;
  the prod backup gates the **deploy** (final step), not the build. Making the
  phone columns nullable *before* anything writes NULL keeps a rollback a no-op
  for existing rows.
- **Cross-tenant routing.** Same class of bug as mac-relay H-4: the webhook's
  Page ID must select *within* one workspace's integration, never widen. Reuse
  the existing "one Page per workspace" guard in
  `_ensure_meta_page_is_available`.
- **Echo loops.** Meta emits `message_echo` for our own sends; ignoring them is
  mandatory or the AI replies to itself.
- **AI cost.** Every DM currently schedules an AI response. Gate Messenger
  threads behind the same agent config as SMS.

## Prerequisites

**Nothing blocks local implementation.** Steps 1–16 run entirely against local
Docker Postgres (`make dev.db`) and cannot reach production.

Two credentials are needed only at the **release** step, from the user:

- **Prod `DATABASE_URL`** (public `*.proxy.rlwy.net` connection string) — for the
  pre-deploy backup in step 17. Not in this checkout.
- **Meta app credentials** — verified absent from Railway: zero `META_*`
  variables in production. Needs `META_LEAD_ADS_APP_SECRET` +
  `META_LEAD_ADS_VERIFY_TOKEN` (same pair the ROI work needs), plus
  `pages_messaging` on the Page token and Meta App Review approval for that
  permission before real users can message in.

## Verification

- Unit tests beside `backend/tests/` for webhook parsing, echo suppression,
  cross-Page rejection, and window-expiry.
- `.ezcoder/eyes/http.sh` POST of a signed sample payload to
  `/webhooks/meta/messages`, then `.ezcoder/eyes/logs.sh` for tracebacks.
- `make ci.all` green; `make ci.migrations` for the up→down→up check.

## Steps

1. Make every `Conversation` schema change in one pass in `backend/app/models/conversation.py`, so step 2 emits exactly **one** migration against the live `conversations` table:
   - add `messenger_psid` (`EncryptedString`) and `messenger_psid_hash` (`LookupHash`), plus a `_sync_messenger_lookup_hash` listener mirroring the existing phone-hash listener;
   - add `messenger_window_expires_at` (`DateTime(timezone=True)`, nullable) so the 24h send window is queryable rather than recomputed per send;
   - make `workspace_phone`, `workspace_phone_hash`, `contact_phone`, `contact_phone_hash` nullable;
   - replace `uq_conversation_phones` with a partial unique index on the phone hashes (`WHERE contact_phone_hash IS NOT NULL`) and add a partial unique index on `(workspace_id, messenger_psid_hash)`.
2. Generate one migration for all of step 1 (`make migrate.new m="messenger dm channel"`), read it before running it, apply to **local** Docker Postgres with `make migrate`, and verify down→up reversibility. Widening columns to nullable and swapping in partial indexes leaves existing rows untouched, so a rollback is a no-op for current data.
3. Add `MESSENGER` and `INSTAGRAM` to `MessageChannel` in `backend/app/models/conversation.py`. No DDL and no migration: both `Conversation.channel` (`String(20)`) and `Message.channel` (`SAEnum(..., native_enum=False, length=20)`) are VARCHAR-backed, so new members need no type change — keep the values under 20 characters.
4. Extend `backend/app/api/webhooks/meta.py` with a `_message_events()` parser for `field == "messages"`, reusing the existing signature and body-size guards; drop `message_echo` and delivery/read receipts.
5. Add `backend/app/services/lead_sources/meta_messenger_service.py`: resolve Page ID → workspace integration (rejecting cross-workspace Pages), fetch sender profile name via Graph, and persist the inbound message.
6. Add a `_get_or_create_messenger_conversation()` path in `backend/app/services/telephony/inbound_text.py` keyed on `messenger_psid_hash`, leaving `contact_id` NULL until a phone or email appears.
7. Set `messenger_window_expires_at` to inbound timestamp + 24h on every inbound user message, and clear it on echo.
8. Add `MessengerMessageService` implementing `TextMessageProvider` in `backend/app/services/telephony/`, sending via Graph `/me/messages`; refuse to send when the window has expired and surface a typed error rather than a silent failure.
9. Route Messenger threads in `provider_for_conversation()` in `backend/app/services/telephony/text_provider.py`.
10. Attribute new Messenger threads to `LeadSourceType.FACEBOOK_ADS` via the existing `apply_web_attribution` path so they reach the ROI card.
11. Teach the AI text agent to prioritise capturing a phone number inside the 24h window, and to stop scheduling replies once the window closes.
12. Add `"messenger"` and `"instagram"` to `MessageChannel` in `frontend/src/types/conversation.ts` and render channel badges plus a "reply window closed" state in the conversation feed.
13. Run `make codegen`, commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together.
14. Add backend tests for signature rejection, echo suppression, cross-Page rejection, duplicate delivery, and expired-window sends.
15. Verify locally with `.ezcoder/eyes/http.sh` against `/webhooks/meta/messages` and check `.ezcoder/eyes/logs.sh` for tracebacks.
16. Run `make ci.all` and `make ci.migrations` until both exit 0.
17. **Release gate — hard stop, needs the prod `DATABASE_URL` from the user.** Before the migration ships to production, run `make db.backup.prod DATABASE_URL='<public *.proxy.rlwy.net url>'` and confirm the dump decrypts to `PGDMP` (`openssl enc -d ... | head -c 5`). `make db.backup.prod` hard-fails without `DATABASE_URL` and that credential is not in this checkout — if it is not supplied, **stop and ask**; do not deploy a `conversations` migration with no backup. Then follow the repo release process (PR → merge → `make deploy.backend` from merged `main` → `/version` check), and keep the dump until the release is proven.
