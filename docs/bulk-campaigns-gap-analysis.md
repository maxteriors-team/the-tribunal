# Bulk Email + Bulk SMS Campaigns — Gap Analysis

**Date:** 2026-09-11 · **Status:** audit only, no code changed · **Scope:** consent tracking, opt-out/unsubscribe, rate limits, audience segmentation by tag + pipeline stage (GoHighLevel parity).

---

## 1. Verdict

The SMS side is close to production-grade bulk sending. The email side has the *shape* of campaigns but is missing most of the compliance and throughput machinery that SMS already has, and **three defects in the email path are live-compliance issues today**, independent of any new feature work.

| Capability | SMS | Email |
|---|---|---|
| Campaign model + per-recipient rows | ✅ | ✅ (shares `CampaignContact`) |
| Send worker with batching | ✅ `campaign_worker.py` | ✅ `email_campaign_worker.py` |
| Pre-send compliance gate | ✅ 6 gates | ❌ **none** |
| Consent status on contact | ✅ `sms_consent_status` + source/timestamp/notes | ⚠️ `email_opted_out_at` only (no opt-in record) |
| Opt-out capture | ✅ STOP keywords + AI intent classifier | ✅ unsubscribe link (2 token schemes) |
| Suppression enforced at send | ✅ every send | ❌ **enrollment only** |
| Quiet hours / time-of-day | ✅ tz-aware, DST-safe | ❌ none |
| Rate limiting | ✅ per-second/hour/day/campaign, Redis token bucket | ❌ none beyond a fixed tick size |
| Sender reputation / warmup | ✅ number pool, auto-quarantine | ❌ none |
| Bounce/complaint → suppression | ✅ reputation tracker | ❌ **counters only** |
| List-Unsubscribe (RFC 8058) | n/a | ⚠️ automation mail yes, **campaign mail no** |

---

## 2. What exists today

### SMS (strong)

- **Compliance gate** — `backend/app/services/compliance/outbound_compliance.py`. `OutboundComplianceService.evaluate()` runs six gates before every campaign send: global opt-out, SMS consent status, quiet hours (tz-aware via `ZoneInfo`, wraparound windows supported), per-campaign cap, per-contact cap, duplicate-initial-send guard. Blocked sends write `suppressed_reason` + `last_compliance_result` onto the `CampaignContact` row, so suppression is auditable per recipient.
- **Consent record** — `Contact.sms_consent_status` / `_source` / `_collected_at` / `_notes`.
- **Opt-out** — keyword pre-filter plus an LLM intent check (`app/services/ai/opt_out_detector.py`) so "I think you should quit" isn't treated as STOP. Persists to Redis set + contact status, workspace-scoped.
- **Rate limits** — `app/services/rate_limiting/`: Lua token bucket per number per second, hourly/daily per number, daily + per-minute per campaign, number pool round-robin with health checks, warming stages, and auto-quarantine on bounce/complaint thresholds.
- **Idempotency** — `derive_outbound_key("campaign_sms_initial", campaign_contact.id)`.

### Email (thin)

- `CampaignType.EMAIL` exists; `email_campaign_worker.py` claims 50 pending rows per 30s tick with `FOR UPDATE SKIP LOCKED`, renders placeholders, calls `send_campaign_email()`.
- Two independent unsubscribe token schemes (HMAC-signed): per-enrollment (`campaigns/email_unsubscribe.py`) and per-contact (`email_opt_out.py`), with public landing routes in `app/api/v1/email_unsubscribe.py`.
- `render_email()` enforces that `EmailCategory.MARKETING` mail carries an unsubscribe URL or rendering fails — a genuinely good guardrail.
- Resend webhook records `sent/delivered/bounced/opened/clicked/complained/unsubscribed` into `EmailEvent` and bumps campaign counters.

### Segmentation

- Canonical engine: `app/services/contacts/contact_filters.py` (~15 fields: status, source, lead_score, engagement_score, is_qualified, enrichment_status, sms_consent_status, created_at, last_engaged_at, tags, noshow_count, last_appointment_status, BANT signals).
- Saved segments with JSONB rule definitions, `POST /v1/segments/preview` live count, and a real rule-builder UI (`components/filters/contact-filter-builder.tsx`).
- Campaign audience enrollment correctly **reuses** `apply_contact_filters()` — no duplicate filter logic. Capped at `MAX_CAMPAIGN_AUDIENCE_SIZE = 5_000`.

---

## 3. Compliance defects (fix before any bulk email volume)

These are current-code issues, verified by reading the source — not future feature gaps.

**D1 — Email suppression is checked at enrollment, never at send.**
`_is_channel_eligible()` (`audience_service.py:236-242`) checks `contact.email_opted_out_at is None` when contacts are enrolled. The worker then sends every `PENDING` row with no further check. A contact who unsubscribes *after* enrollment — or who unsubscribed via a different campaign or a workflow email — still receives the queued mail. `email_suppressed()` exists in `email_opt_out.py` but **no caller in the campaign path invokes it**. CAN-SPAM requires honouring opt-outs within 10 business days; this can violate it within minutes.
**FIXED** — `email_campaign_worker.py` now re-checks `email_opted_out_at` on the eager-loaded contact before every send and marks the row `OPTED_OUT` + `suppressed_reason="email_opted_out"`, mirroring `apply_suppression()`. Read off the loaded relationship rather than calling `email_suppressed()` so 50 sends stay one query. Terminal status matters: skipping without it would re-claim the row every tick forever.

**D2 — Campaign email omits the List-Unsubscribe headers.**
`list_unsubscribe_headers()` is passed in `send_automation_email()` (`email.py:424`) and the template sender (`:1479`), but `send_campaign_email()` (`:502-530`) builds `params` with only `_campaign_html()` — a visible footer link, no headers. Gmail and Yahoo require one-click List-Unsubscribe for bulk senders above 5k/day; without it, bulk volume goes to spam.
**FIXED** — `send_campaign_email()` now sets `params["headers"] = list_unsubscribe_headers(...)` when an unsubscribe URL is present, matching `send_automation_email()`.

**D3 — Hard bounces and spam complaints don't suppress anyone.**
`dispatch_resend_event()` records the `EmailEvent` and increments `emails_bounced`, then stops. The address stays enrolled and eligible forever. Repeat-sending to hard bounces is the fastest route to a burned sending domain, and complaint rate is the metric mailbox providers actually police.
**FIXED** — new `_apply_suppression()` in `services/webhooks/resend.py` calls `record_email_opt_out()` on hard bounce (`data.bounce.type == "Permanent"`, per the `email_bounced.json` contract fixture), spam complaint, and provider-side unsubscribe. `Transient`/`Undetermined` deliberately do **not** suppress — opting someone out over a temporarily full mailbox loses a real customer, so the ambiguous cases fail toward delivery.

**D4 — `has_none` tag filter validates inconsistently.**
Implemented in `contact_filters.py:206`, exposed in the filter-builder UI, but absent from `contact_filter_validation.py:23` (`{"has_any","has_all"}`). Segment preview/create/refresh skip validation and accept it; campaign enrollment calls `validate_contact_filter_rules()` and rejects it. An operator can build and save a segment that then fails when used in a campaign.
*Fix:* add `has_none` to the validation frozenset. **Not fixed** — it lives in `contact_filters.py`/`contact_filter_validation.py`, the shared segmentation primitive, so it should land with the stage-filter work rather than as a drive-by edit while other agents are active.

**D5 — One-click unsubscribe endpoints were GET-only.** *(found while fixing D2)*
`list_unsubscribe_headers()` advertises `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, and its own docstring says the endpoint must treat POST as a real opt-out — but both routes in `api/v1/email_unsubscribe.py` were `@public_router.get`. Gmail POSTs, gets **405**, and the opt-out is lost while the mailbox provider still shows the customer "unsubscribed". Both ends report success; the person keeps getting mail. This was already live for automation mail, and shipping D2 would have extended it to campaign mail.
**FIXED** — both routes are now `api_route(methods=["GET", "POST"])`. Public OpenAPI changed, so `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` were regenerated via `make codegen`.

**D6 — No consent proof for either channel.**
`sms_consent_notes` is free text; email has no opt-in record at all. TCPA disputes are defended with proof of consent — form URL, timestamp, IP, and what the checkbox said. There is no structured record, and status is overwritten in place with no history.

---

## 4. Feature gaps for GoHighLevel parity

### Email (largest gap)
1. No pre-send compliance gate — email needs the equivalent of `OutboundComplianceService.evaluate()`; today it has zero gates.
2. No quiet hours / scheduled send / timezone awareness.
3. No rate limiting, warmup, or per-workspace daily cap. Throughput is a hardcoded ~100/min per campaign (50 per 30s tick, `MAX_CONCURRENCY = 1`) — a 100k send takes ~16h.
4. Resend's batch API is unused; every message is a separate `send_async()` call.
5. **Per-workspace sending domain does not exist** — all tenants share the global `resend_from_email`/`resend_from_name`. This is the same envelope-scoping gap CLAUDE.md already flags as the pre-SaaS blocker, and it is also a deliverability problem: one tenant's complaint rate would poison every tenant's reputation.
6. No soft/hard bounce classification for email (SMS has `bounce_classifier.py`).
7. No A/B variants, no click attribution back to the campaign contact.

### SMS
1. No scheduled send — the worker polls on a fixed interval; there's no "start Thursday 9am".
2. Consent history is overwritten, not versioned.
3. Transactional/AI-reply sends bypass `OutboundComplianceService` entirely (protected only by per-conversation `ai_enabled`). Worth closing.
4. No carrier-level STOP reconciliation (Telnyx-managed opt-outs).

### Segmentation
1. **Pipeline stage is not filterable.** `stage_id` lives on `Opportunity`, and `contact_filters.py` has no `stage`/`pipeline` field. This is explicitly in scope for the request and is the single biggest segmentation gap — GHL treats "contacts in stage X" as a first-class audience filter.
2. No nested boolean groups — `logic` is top-level only, so `(A OR B) AND (C OR D)` is inexpressible.
3. Segments are **static snapshots**; `is_dynamic=True` is a flag with no scheduled re-evaluation. A "smart list" that doesn't re-evaluate isn't smart.
4. No audience preview in the campaign wizard (the segments page has one — reuse it).
5. No email-consent filter (`email_opted_out_at` isn't in the filter schema), no activity-recency filter ("not contacted in 30 days"), no opportunity value/close-date filters, no custom fields.

---

## 5. Suggested sequencing

**Phase 0 — compliance repair. DONE except D4.** D1, D2, D3 and D5 are fixed and tested (see §7). D4 is deliberately deferred into Phase 3 because it touches the shared segmentation primitive.

**Phase 1 — email parity with SMS.** Extend `OutboundComplianceService` to accept `channel="email"` rather than writing a second gate engine; add quiet hours + scheduled send; bounce/complaint suppression list; per-workspace sending domain (pairs with the `_from_address()` workspace threading already identified in CLAUDE.md).

**Phase 2 — throughput.** Resend batch API, per-workspace daily caps, warmup ramp, reputation tracking for email domains mirroring `reputation_tracker.py`.

**Phase 3 — segmentation.** Stage filter via `Contact → Opportunity → PipelineStage` subquery in `contact_filters.py` (extend the existing `_resolve_contact_extra` resolver — same pattern tags use); nested rule groups; dynamic segment re-evaluation at send time; audience preview in the campaign wizard.

---

## 6. Notes for parallel work

The remaining work clusters into files that barely overlap, so it can be parallelised safely:

- `contact_filter_validation.py` / `contact_filters.py` (D4, stage filter) — segmentation.
- `outbound_compliance.py` (email channel support) — compliance engine.
- `rate_limiting/` (email caps, warmup) — throughput.

The one genuine collision risk is **`contact_filters.py`**, which CLAUDE.md designates as the shared filtering primitive — anything touching segmentation should land as a single change rather than several concurrent ones. The second is the per-workspace sender identity, which overlaps the deferred SaaS envelope work; don't start it without confirming that decision is being reopened.

---

## 7. Changes landed with this audit

Phase 0 fixes only — no feature work, no refactors, no shared segmentation code touched.

| File | Change |
|---|---|
| `backend/app/workers/email_campaign_worker.py` | D1 — send-time opt-out re-check, terminal `OPTED_OUT` status |
| `backend/app/services/email.py` | D2 — `List-Unsubscribe` headers on campaign mail |
| `backend/app/services/webhooks/resend.py` | D3 — hard bounce / complaint / provider-unsubscribe suppression |
| `backend/app/api/v1/email_unsubscribe.py` | D5 — both unsubscribe routes accept POST |
| `backend/openapi.json`, `frontend/src/lib/api/_generated.ts` | regenerated (`make codegen`) for the new POST operations |

Tests added (24, all passing):

- `tests/workers/test_email_campaign_worker.py` — opted-out contact is suppressed, not sent. Mutation-checked: reverting the guard turns this test red.
- `tests/services/test_email.py` — one-click headers present with an unsubscribe URL, absent without one.
- `tests/services/test_webhooks_resend_suppression.py` — hard bounce / complaint / unsubscribe suppress; `Transient` and `Undetermined` do not; malformed and missing `bounce` blocks don't crash; unlinked contact logs rather than throws.
- `tests/api/test_email_unsubscribe_one_click.py` — GET and POST both return 200 on both routes; DELETE still 405.

Verification: full backend suite `5629 passed, 21 skipped`; `ruff check app tests` clean; `mypy app` clean across 869 files; `npm run lint` and `npm run build` clean.

### Caught by `npm run build`, worth remembering

D5 was first implemented as `api_route(methods=["GET", "POST"])`. FastAPI derives an operation id from `list(route.methods)[0]`, so one multi-method route emits the **same** `operationId` under both verbs — a duplicate identifier that fails the frontend TypeScript build (`TS2300`). And because `route.methods` is a `set`, which verb wins varies per interpreter run, so `openapi.json` stops being reproducible. Mid-audit I saw that hash flapping and wrongly blamed a concurrent agent; it was this bug. **Use one decorator per verb**, and treat unstable codegen output as a bug in the route definition rather than environmental noise. Three consecutive `make codegen` runs now produce byte-identical artifacts.
