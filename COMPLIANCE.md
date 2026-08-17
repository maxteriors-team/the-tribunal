# Compliance Register

Snapshot: 13 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Commit reviewed: working tree based on `5a2efb34` (uncommitted manual-deposit work after the merged aerial-plan fix).

Scope of this pass: landscape-lighting proposal deposit truth, authenticated cash/check/other deposit recording, custom monetary line items, customer acceptance receipts, accepted-quote conversion, crew assignment notifications, and authenticated installation-plan delivery. This is a focused feature review, not a certification or a full-product legal/security audit.

## Assumed exposure profile

- **Reach — Confirmed:** deployed CRM with authenticated staff UI plus public customer proposal/payment pages.
- **Jurisdictions — Assumed:** internet-reachable worldwide; United States plus EU/UK exposure may apply.
- **Personal data — Confirmed:** customer identity, address, property imagery, field notes, staff identity, and notification addresses.
- **Money — Confirmed:** consumer card deposits use hosted Stripe Checkout; authenticated operators may now attest that cash, check, or another offline deposit was received. Tribunal records method/user/time but does not receive card data or move the offline funds.
- **Messaging — Confirmed:** transactional assignment email/push notifications.
- **Minors — Assumed unlikely but not technically age-gated:** this B2B home-services workflow is not designed for children.
- **Entity — Confirmed from repository context:** operated as a deployed commercial CRM; exact legal entity details were not reviewed.

## Focused coverage ledger

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| 1 | Secrets in client/repo | pass | CODE: no new secret, token, `.env`, or client provider credential; generated runtime artifacts stayed under gitignored `.ezcoder/eyes/out`. |
| 2 | Row-level security / equivalent | n-a | CODE: no direct client database SDK; FastAPI/SQLAlchemy is the only data path. |
| 3 | Admin/service key in browser | pass | CODE: Stripe/payment and notification providers remain backend-only. |
| 4 | Object authorization at server/data layer | pass | RUNTIME: assigned installer received selected plan; unassigned installer and cross-workspace requests returned 404. |
| 4a | Access-granting defaults | pass | CODE: linkage is nullable; no role or entitlement default was added. |
| 4b | Tenant isolation from authenticated membership | pass | RUNTIME: workspace mismatch returned 404; service queries include workspace and assignment predicates. |
| 5 | Mass assignment | pass | CODE: Pydantic request schemas and explicit service field mapping constrain conversion/project updates. |
| 6 | String-built queries | pass | CODE: SQLAlchemy expression APIs only. |
| 7 | Unauthenticated internal endpoint | pass | RUNTIME: installation-plan and manual-deposit requests without authentication returned 401; neither has a public token route. |
| 8 | Public writable/listable storage | n-a | CODE: this feature adds no bucket/static object; plan imagery remains in the private project record. |
| 9 | Expensive/abusable endpoint rate limit | pass | CODE: plan read is a bounded database projection; checkout remains in the existing rate-limited/provider flow. |
| 10 | Password hashing | n-a | No authentication implementation changed. |
| 11 | Session cookie/token storage | n-a | No session implementation changed. |
| 12 | JWT verification | n-a | No token verification implementation changed. |
| 13 | Credentialed wildcard CORS | n-a | No CORS implementation changed. |
| 14 | Card data reaches Tribunal | pass | CODE: customer payment remains hosted Stripe Checkout; only payment/session identifiers and reconciled timestamps are used. |
| 14b | Cleartext financial/identity identifiers | pass | CODE: no bank, tax, government-ID, PAN, or CVV field added. |
| 15 | PII/plan bytes in logs | pass | CODE/RUNTIME: notification and conversion logs carry IDs/counts only; no diagram bytes or public/payment token in captured output. |
| 16 | Transport security / mixed content | pass | CODE: authenticated API response only; no new remote asset or public static URL. Production HTTPS remains an environment control. |
| 17 | SSRF | n-a | No server-side user URL fetch added. |
| 18 | Backup/restore | n-a | Existing project backup controls apply; no storage system changed. |
| U1 | Privacy notice / deletion / vendor list | n-a | Existing product-wide obligation; this pass adds stable links but no new data class or processor. |
| U2 | Third-party scripts consent | n-a | No tracking script added. |
| U3 | Account security baseline | pass | Focused authorization tests and runtime probes passed; product-wide auth was not re-audited. |
| U4 | Public-page accessibility | n-a | No new public page; existing hosted proposal/payment surfaces were reused. |
| U5 | Email duties | pass | CODE/tests: assignment copy and the new customer acceptance receipt are transactional, recipient-scoped, HTML-escaped, and use deterministic provider idempotency keys; repeated acceptance does not resend. |
| U6 | Contact form privacy | n-a | No contact form added. |
| U7 | Error/log handling | pass | CODE: delivery errors produce counts/status without payload bytes or provider secrets. |
| U8 | Personal-liability/entity review | n-a | Exact contracting entity was outside this focused implementation. |
| A1 | Image alternatives | pass | CODE: selected canvas has an accessible label; fixture/field text remains readable beside it. |
| A2 | Form labels | pass | CODE/tests: schedule, crew, and confirmation controls have labels. |
| A3 | Keyboard operability | pass | CODE: native buttons, checkbox, inputs, select, tabs, and links. |
| A4 | Colour contrast | n-a | Existing design-system tokens were reused; literal contrast values were not introduced or re-audited. |
| A5 | Focus visibility | pass | CODE: existing Button/Input/Tabs primitives retain design-system focus treatment. |
| A6 | Media controls/captions | n-a | No audio/video media. |
| A7 | Page language | n-a | Components mount inside the existing app document; root language was not changed. |
| C1-US | Consumer contract duties | fail | CODE/DEDUCED: this pathway now applies a configured deposit to a public proposal; server-derived pricing and hosted Stripe Checkout were verified, but the actual cancellation, refund, tax, and contract disclosures were not reviewed. |
| C1-EU/UK | Consumer pre-contract/withdrawal duties | fail | CODE/DEDUCED: the public proposal may request a deposit; jurisdiction-specific pre-contract information, withdrawal rights, and any service-start waiver need legal review where offered. |
| M1 | Minors | n-a | Staff-only B2B operations feature; no child-directed intake or profiling added. |

## Findings

| ID | Severity | Trigger | Evidence (RUNTIME / CODE / DEDUCED) | Obligation | Status | Guard |
|---|---|---|---|---|---|---|
| LL-001 | BLOCKER | Customer property imagery becomes available to field staff | RUNTIME: assigned technician received only `install-front`; unassigned and cross-workspace reads returned 404 | Enforce workspace and direct/crew assignment authorization; avoid public/static delivery | Fixed | Backend service/API tests plus runtime 200/404 probes |
| LL-002 | BLOCKER | Consumer deposit state affects invoice credit and pre-booking confirmation | RUNTIME: paid 25% deposit credited exactly `$250.00`; authenticated cash recording returned method/user/time; unauthenticated recording returned 401 | Preserve an immutable first-paid transition: provider-confirm card payments; require billing-write authorization and operator attestation for offline payments; record method/user/time; close any open checkout first | Fixed | Quote/deposit integration tests, atomic conditional update, generated API contract, and runtime 200/401 probes |
| LL-003 | HIGH | Transactional assignment email/push exposes private-work availability | RUNTIME: captured email had one installer recipient and availability copy; no image, token, provider payment ID, or procurement note | Scope recipients, honor preferences, deduplicate, and keep imagery behind authenticated access | Fixed | Notification unit tests, Redis dedupe, delivery counts, Mailpit artifact |
| LL-004 | HIGH | Failed delivery must remain retryable and truthful | RUNTIME: initial probe found a failed send retained its dedupe claim and a retry falsely said sent | Release dedupe claims after total failure; report delivery separately from committed job | Fixed | Post-fix exact retry remained `failed`; targeted tests and final backend CI |
| LL-005 | LAWYER | US consumers may pay a landscape-lighting deposit through the public proposal | CODE/DEDUCED: hosted checkout and server-derived totals are present, but the customer-facing cancellation, refund, tax, and contract terms were outside this review | Confirm the actual proposal terms match each US jurisdiction served | Open | Legal review of the deployed proposal and refund/cancellation policy |
| LL-006 | LAWYER | EU/UK consumers may pay a landscape-lighting deposit if the service is offered there | CODE/DEDUCED: no geographic block was established and jurisdiction-specific pre-contract/withdrawal wording was not reviewed | Confirm required pre-contract information, withdrawal handling, and any early-service waiver before offering there | Open if EU/UK consumers are served | Legal review plus a jurisdictional launch checklist |
| LL-007 | HIGH | A customer needs durable proof after accepting a proposal | CODE/tests: acceptance previously changed status without sending the customer a receipt; the new transactional email records proposal number, accepted UTC timestamp, accepted total, deposit state, and a stable proposal link | Send one itemized, escaped, idempotent receipt only on the first acceptance | Fixed | Email-renderer test plus public-approval duplicate-send guard |

## Implemented in this pass

- Stable quote/job/project links and database uniqueness prevent duplicate converted jobs.
- Public proposal schemas omit project IDs, plans, staff assignments, procurement, and job/payment handoff details.
- Installation imagery is authenticated and assignment-scoped with 404 non-disclosure.
- Card truth remains Stripe-derived; cash/check/other can be marked paid only by an authenticated billing-write operator after an explicit received-money confirmation. The API records method/user/time, atomically preserves the first paid transition, and closes any open card checkout before accepting an offline record.
- Notifications target active direct/crew installers, honor existing master/preferences, use deterministic dedupe, report partial/failure separately, and omit imagery/tokens.
- Internal payment receipts identify the client using CRM name, email, phone, and quote number; payment credentials and provider identifiers remain excluded, and all customer-supplied values are HTML-escaped.
- Customer proposal-acceptance receipts are transactional, itemize the accepted total and deposit state, retain a proposal link, and use deterministic idempotency; they do not contain marketing or unsubscribe theater.
- Read-only installer actions support print/download while preserving the editable project as the single design source.

## Open — needs a decision from you

None for this approved implementation.

## Needs a lawyer

- **Before launch,** confirm the deployed public proposal’s cancellation, refund, tax, and contract disclosures for every US jurisdiction served; if EU/UK customers can buy, also confirm pre-contract information, withdrawal handling, and any early-service waiver.
- Confirm the privacy notice, retention schedule, vendor disclosures, and exact contracting entity for the jurisdictions actually served. No legal facts or documents were invented in this engineering pass.

## Re-verify before relying (date-sensitive)

- PCI DSS hosted-checkout eligibility and payment-page script obligations with Stripe for the actual deployed checkout mode.
- US/EU/UK consumer contract, withdrawal, transactional-email, privacy, and accessibility requirements before launch in each served jurisdiction.
- Notification provider and Stripe data-processing/retention terms.
- Local Mailpit exercised the exact assignment email renderer/idempotency-key path and proved one recipient plus no imagery/token leakage; it does not prove Resend delivery or inbox placement.


## Addendum — Manual quote deposits

Snapshot: 13 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

- **RUNTIME:** an authenticated owner recorded a `$125.00` cash deposit and received `deposit_paid=true`, `deposit_payment_method=cash`, a recorder ID, and a server timestamp; the same route without credentials returned 401.
- **Tenant and role control — Fixed:** the route requires `billing:write`; the service selects and locks the quote by both workspace and quote ID, and integration coverage rejects a different workspace.
- **Double-payment control — Fixed:** an existing Stripe Checkout Session is reconciled and expired before cash/check/other is accepted; a card payment that completed first wins and remains labelled `card`.
- **Audit/data minimization — Fixed:** the database retains method, operator, and time but no check number, bank account, card number, CVV, or offline-payment note.
- **Money movement — Not triggered by this change:** Tribunal records an operator's statement that funds were received outside the product; it does not custody, transmit, or settle those funds.
- **Residual operational risk:** an authorized operator can record money they did not actually receive. The UI warning, irreversible confirmation, role gate, and recorder attribution reduce this risk; workspace owners still need a reconciliation policy and should correct mistakes through an audited adjustment rather than direct database edits.


## Addendum — Teach AI and website-lead qualification

Snapshot: 12 August 2026 · NOT LEGAL ADVICE

- **Personal data — Confirmed:** approved lessons retain encrypted customer SMS, AI replies, ideal replies, and optional operator notes.
- **Tenant isolation — Fixed:** CRM-write authorization protects lesson creation; conversation, source message, agent, retrieval, and timeline agent metadata are workspace-scoped or server-derived.
- **Prompt injection — Fixed:** active examples are capped at 12/6,000 prompt characters, JSON-quoted, marked untrusted, and cannot override truthfulness, opt-out, qualification, booking, or tool rules.
- **Automated sales qualification — Fixed in code:** off by default, reuses captured form answers, asks one missing question at a time, requires evidence/score, preserves human handoff, and removes booking/availability tools until qualification persists.
- **Messaging — Unchanged:** Teach AI has no send path; existing consent and opt-out controls remain the only customer-message gates.
- **Key rotation — Fixed:** all four new `EncryptedString` columns are registered in `scripts/ops/reencrypt_with_old_key.py`, with a regression guard.
- **LAWYER before relying broadly:** define lesson retention and deletion propagation, disclose AI/personal-data reuse, and confirm lawful basis/data-subject rights where EU/UK leads are served.

## Addendum — Unified jobs and appointments calendar

Snapshot: 13 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Commits reviewed: `02b4fb77`, `1ecd31f7`, and `1148fe66`.

Scope: the authenticated calendar, appointment/job visibility and mutations, bookable-staff login linkage, manual appointment reminder SMS, and dependency versions rebuilt for this release. This focused release gate does not replace the product-wide findings above.

### Assumed exposure profile

- **Reach — Confirmed:** deployed, authenticated CRM staff surface; no new public route.
- **Personal data — Confirmed:** customer names, addresses, appointments, jobs, and staff assignments appear on the calendar.
- **Tenant model — Confirmed:** every calendar request is workspace-scoped from authenticated membership.
- **Messaging — Confirmed:** the existing manual appointment reminder can create customer-visible SMS and provider spend.
- **Jurisdictions — Assumed:** worldwide reach remains possible, but this staff-only feature adds no consumer contract, tracking, or public intake surface.
- **Minors — Not applicable to this feature:** business staff accounts operate the calendar; it does not collect child-directed data.

### Focused coverage ledger

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| 1 | Secrets in client/repo | pass | RUNTIME: Gitleaks scanned the release commits with the repository config and found no leaks; `.env*`, backups, worktrees, virtual environments, and dependencies are ignored. |
| 2 | Row-level security / equivalent | n-a | CODE: the browser has no direct database SDK; FastAPI and SQLAlchemy are the only calendar data path. |
| 3 | Admin/service key in browser | pass | CODE: no provider credential or privileged key was added to frontend code or generated client types. |
| 4 | Object authorization at server/data layer | pass | RUNTIME: route and PostgreSQL integration tests prove field users can read/mutate only their assigned appointments/jobs; another worker's object returns 404 while dispatch remains workspace-wide. |
| 4a | Access-granting defaults | pass | CODE: `BookableStaff.user_id` is nullable and grants nothing by default; linking it requires `members:manage`. |
| 4b | Tenant isolation from authenticated membership | pass | RUNTIME: API tests derive workspace membership server-side; service predicates include both `workspace_id` and assignment/bookable-staff linkage. |
| 5 | Mass assignment | pass | CODE: Pydantic request schemas and explicit service updates constrain appointment, job, and staff fields. |
| 6 | String-built queries | pass | CODE: changed data access uses SQLAlchemy expressions and bound predicates only. |
| 7 | Unauthenticated internal endpoint | pass | CODE/tests: calendar, staff-link, mutation, and reminder routes require authenticated workspace membership. |
| 8 | Public writable/listable storage | n-a | No storage surface or upload was added. |
| 9 | Expensive/abusable endpoint rate limit | pass | RUNTIME: manual reminder SMS is capped per user and workspace with hourly/daily Redis windows, returns 429 with `Retry-After`, and fails closed with 503 if metering is unavailable. |
| 10 | Password hashing | n-a | Authentication storage did not change. |
| 11 | Session cookie/token storage | n-a | Session handling did not change. |
| 12 | JWT verification | n-a | Token verification did not change. |
| 13 | Credentialed wildcard CORS | n-a | CORS configuration did not change. |
| 14 | Card data reaches Tribunal | n-a | No payment flow changed. |
| 14b | Cleartext financial/identity identifiers | pass | No bank, tax, government-ID, card, or payout field was added. |
| 15 | PII in logs/error trackers | pass | CODE: changed logs contain workspace, appointment, user, counts, and status only—not customer bodies, phone numbers, tokens, or message text. |
| 16 | Transport security / mixed content | pass | RUNTIME: production API and frontend baselines served over HTTPS; no new remote asset or insecure URL was added. |
| 17 | SSRF | n-a | No server-side user-supplied URL fetch was added. |
| 18 | Backup/restore | pass | RUNTIME: a mode-600 AES-256-CBC production backup was created before release and decrypted to the `PGDMP` archive signature; existing restore tooling remains unchanged. |
| U1 | Privacy notice, deletion, retention, vendor list | n-a | No new data class or processor; existing CRM records are projected into a new authenticated view. Product-wide retention/deletion duties remain above. |
| U2 | Third-party scripts consent | n-a | No analytics, pixel, session replay, or third-party browser script was added. |
| U3 | Account security baseline | pass | Calendar access reuses authenticated membership and capability checks; auth implementation was not changed or re-audited here. |
| U4 | Public-page accessibility | n-a | No public page was added; authenticated calendar accessibility is checked separately below. |
| U5 | Email/SMS duties | pass | CODE: reminder SMS reuses existing appointment reminder consent/opt-out handling; this pass adds spend/abuse limits and does not add marketing messaging. |
| U6 | Contact-form privacy | n-a | No contact form or public intake was added. |
| U7 | Error/log handling | pass | CODE/tests: unauthorized objects are non-disclosing 404s; limiter failures return generic 429/503 responses without internal details. |
| U8 | Personal-liability/entity review | n-a | No new customer-facing promise or contracting surface. |
| A1 | Image alternatives | n-a | The calendar adds no image content; decorative icons are hidden and entry species is present in accessible names. |
| A2 | Form labels | pass | CODE: status/view groups have accessible group names, location filtering uses the existing labeled primitive, and the mine-only switch has a linked label. |
| A3 | Keyboard operability | pass | CODE/tests: entries, overflow controls, filters, navigation, and queue rows use native buttons with keyboard activation. |
| A4 | Colour contrast | pass | CODE: no literal color values were introduced; design-system tokens are reused, and job/appointment species differ structurally by icon/accent rail rather than color alone. |
| A5 | Focus visibility | pass | CODE: every added interactive control has the existing `focus-visible` ring treatment. |
| A6 | Media controls/captions | n-a | No audio or video element. |
| A7 | Page language | pass | CODE: the calendar inherits the app document's `lang="en"`. |
| C1-US | Consumer contract duties | n-a | Staff-only scheduling surface; no purchase or consumer agreement changed. |
| C1-EU/UK | Consumer pre-contract/withdrawal duties | n-a | Staff-only scheduling surface; no purchase or consumer agreement changed. |
| M1 | Minors | n-a | Authenticated business-operator workflow, not a child-directed consumer feature. |

### Findings

| ID | Severity | Trigger | Evidence (RUNTIME / CODE / DEDUCED) | Obligation | Status | Guard |
|---|---|---|---|---|---|---|
| CAL-001 | BLOCKER | A field worker could directly invoke appointment update/delete/reminder routes outside the new read scope | RUNTIME: API and database integration tests now return 404 outside the worker's assigned calendar and preserve dispatch-wide access | Enforce object authorization on reads and every mutation at the service query | Fixed | `test_calendar_scope_api.py` and `test_calendar_visibility.py` |
| CAL-002 | BLOCKER | Manual reminder SMS creates provider spend and customer-visible messaging without a request cap | RUNTIME: limiter tests exercise per-user/workspace windows, 429 exhaustion, and fail-closed 503 behavior | Meter expensive messaging at the server boundary | Fixed | `test_appointment_reminder_limiter.py` plus route assertion |
| CAL-003 | HIGH | The release rebuild originally resolved known-vulnerable Next.js, Axios, and transitive packages | RUNTIME/CODE: Next.js and Axios were upgraded to patched releases; full `npm audit` now reports zero vulnerabilities | Do not deploy a fresh client/server bundle with known exploitable dependencies | Fixed | Committed lockfile, `npm ci`, `npm audit`, typecheck, tests, and production build |
| CAL-004 | BLOCKER | Linking a bookable staff record to a login determines whose customer calendar becomes visible | RUNTIME/CODE: only `members:manage` may set or change `user_id`; workspace and uniqueness constraints are tested | Treat identity linkage as team administration, not ordinary agent configuration | Fixed | `test_bookable_staff_link_api.py` and service tests |

### Implemented and proved in this pass

- Field-role list, deep-link, update, delete, and reminder access now share one assignment predicate and return non-disclosing 404s outside scope.
- Dispatcher/manager calendar access remains workspace-wide; job dispatch controls stay hidden from field roles.
- Manual reminder SMS is capped at 25 per user/hour, 100 per workspace/hour, and 500 per workspace/day.
- Jobs and appointments remain distinguishable without relying on color; native controls and visible focus treatment cover keyboard use.
- Next.js `16.3.0`, Axios `1.19.0`, and audited transitive versions are lockfile-pinned; `npm audit` reports zero known vulnerabilities.

### Open — needs a decision from you

None for this calendar release.

### Re-verify before relying

- This was source and automated runtime verification, not a legal certification or a manual assistive-technology audit.
- Re-run dependency audit and authenticated calendar smoke checks for future releases; external advisories and provider behavior change.

## Addendum — Google availability with Zoom booking links

Snapshot: 12 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Scope: server-side Zoom meeting creation for video bookings assigned to the one configured Google-connected host, customer confirmation links, and Zoom lifecycle synchronization on reschedule/cancellation.

- **Personal data — Minimized:** Zoom receives the configured host email, appointment start/duration/timezone, a generic workspace consultation topic, and the internal appointment ID. The API request omits lead name, email, phone, address, notes, and CRM conversation content.
- **New processor — Confirmed:** Zoom processes meeting metadata and, when a lead joins, Zoom may process participant account/device/network and meeting-use data under the workspace's Zoom agreement and settings.
- **Tenant/identity boundary — Fixed:** Zoom activates only when `ZOOM_HOST_EMAIL` exactly matches the assigned representative's connected Google account; other users and workspaces keep Google Meet fallback.
- **Secrets — Fixed:** account ID, client ID, client secret, and short-lived access token remain backend-only. Partial configuration fails startup, provider errors/logs omit secrets, and the host-only `start_url` is never stored or returned.
- **Meeting safety — Fixed:** every booking receives a unique meeting with waiting room enabled, join-before-host disabled, authentication not required for the customer, and automatic recording disabled. A passcode that is not embedded in the join URL fails closed to Google Meet.
- **Lifecycle truth — Fixed:** provider resources are best-effort mirrors of the CRM appointment; rescheduling updates Zoom and Google, cancellation deletes both, and provider failure never rolls back the local customer booking.
- **Customer messaging — Existing transactional path:** the Zoom link is included only in appointment confirmation/lifecycle copy and the calendar invite for that booking; this change adds no marketing send path.
- **Data retention/deletion — Provider-dependent:** CRM cancellation deletes the Zoom meeting, but Zoom account audit/retention records remain governed by Zoom settings and contract.

### Focused findings

| ID | Severity | Trigger | Guard | Status |
|---|---|---|---|---|
| ZM-001 | BLOCKER | A global Zoom credential could create meetings for another tenant | Host email must exactly match the assigned user's Google Calendar connection | Fixed in code/tests |
| ZM-002 | HIGH | Reusable room links can leak between leads | Create a unique meeting per booking; validate `https` and `*.zoom.us`; never store `start_url` | Fixed in code/tests |
| ZM-003 | HIGH | A separate passcode would not reach the lead | Accept embedded-passcode URLs only when Zoom returns a passcode; otherwise fall back to Meet | Fixed in code/tests |
| ZM-004 | HIGH | Cancellation/reschedule could leave stale live meetings | Parse only validated numeric Zoom IDs and update/delete alongside Google events | Fixed in code/tests |
| ZM-005 | LAWYER | Leads are directed to a new video processor | Confirm the deployed privacy notice/vendor disclosure, Zoom DPA/retention settings, and jurisdictional lawful basis | Open before broader rollout |

### Re-verify before broader rollout

- Confirm the customer-facing privacy notice and vendor/subprocessor disclosure cover Zoom participant and meeting metadata; review the applicable Zoom DPA and account retention controls.
- Confirm the host's Zoom plan limits, caption/accessibility settings, meeting-region settings, and required Marketplace scopes for the actual account.
- This focused engineering review is not legal certification and does not assess Zoom's service or contract.


## Addendum — Customer quote-link recovery

Snapshot: 16 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Commit reviewed: working tree based on `5a8b41dc`.

Scope: transactional proposal delivery by email/SMS, recovery of still-active quotes whose prior messages used unreachable branded domains, and the explicit quote re-send path. This is a focused incident review, not a full-product legal/security audit.

### Focused findings

| ID | Severity | Trigger | Evidence | Control | Status / guard |
|---|---|---|---|---|---|
| QTL-001 | HIGH | Previously sent proposal URLs used `app.maxteriorslighting.com` or `go.maxteriorslighting.com`, which no longer resolve after the DNS move | RUNTIME: both hosts failed DNS; the Vercel proposal page and public proposal API returned 200 for an affected active quote | Production `FRONTEND_URL` and `PUBLIC_BASE_URL` use reachable provider origins; only still-active proposals were re-sent | Fixed operationally; public page/API and replacement short links were exercised |
| QTL-002 | HIGH | The explicit **Re-send email** action reused a revision-scoped Resend idempotency key, so Resend returned the original message instead of creating a replacement | CODE/RUNTIME: repeated historical sends returned the same provider ID; the regression test now requires distinct keys for deliberate deliveries | Give each explicit delivery attempt a fresh provider key while leaving the `mark_sent` courtesy email revision-idempotent | Fixed in code; `test_explicit_quote_resend_uses_a_fresh_provider_key` |
| QTL-003 | MEDIUM | HTML-only button styling can be removed by inbox clients, leaving the proposal URL hard to find | CODE: quote emails previously sent only HTML with the URL inside a styled button | Include a visible copy/paste URL in HTML and a plain-text MIME alternative containing the same server-generated proposal URL | Fixed in code; `test_quote_email_renders_visible_and_plain_text_proposal_links` |
| QTL-004 | HIGH | Recovery messages could become unsolicited outreach if sent to new recipients or over new channels | RUNTIME/CODE: remediation used each quote's existing recipient and only channels previously accepted for that quote; both SMS recipients passed the existing opt-out gate | Keep recovery transactional, preserve recipient/channel, and enforce SMS opt-out before provider send | Fixed for this incident; shared `send_client_link_sms` opt-out guard remains in force |

### Implemented and proved in this pass

- The reachable proposal origin is `the-tribunal-two.vercel.app`; the public proposal page and API returned 200 for an affected active quote.
- Four active proposal emails (`QUO-000015`, `QUO-000016`, `QUO-000021`, and `QUO-000023`) were accepted by Resend with fresh links. Acceptance proves provider intake, not inbox placement.
- Replacement texts for `QUO-000016` and `QUO-000021` passed opt-out checks, were reported delivered by Telnyx, and their tracked links resolved through the Railway origin to the Vercel proposal page with HTTP 200.
- Approved/declined quotes and inactive historical delivery channels were not re-sent.

### Residual risk / re-verify

- Old messages that embed the unreachable branded domains remain broken until those DNS records are restored; active customers now have replacement messages, but provider-origin URLs are the temporary continuity path.
- Resend's production API key is send-only, so delivery/inbox placement could not be queried after provider acceptance. Customer opens and Resend webhook events remain the runtime confirmation.
- This focused engineering review is not legal advice and does not reassess the wider product's messaging consent or retention program.

## Addendum — Chatbot appointment booking and reminder delivery

Snapshot: 16 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Commit reviewed: deployed backend `e229d64584be7cfae81613d1f19ef630a9e1eb81`.

Scope: production chatbot appointment finalization, Google Calendar creation, booking notifications, automatic/manual appointment reminders, Telnyx/Resend delivery reconciliation, and the minimum messaging/privacy controls attached to those paths. This is a focused workflow audit, not a product-wide certification.

### Assumed exposure profile

- **Reach — Confirmed:** deployed public chatbot/SMS surfaces plus authenticated operator UI.
- **Jurisdictions — Assumed:** reachable worldwide; US and EU/UK duties may apply unless access is technically limited.
- **Personal data — Confirmed:** customer name, phone, email, conversation, appointment time/location, and calendar attendee data.
- **Third parties — Confirmed:** OpenAI, Google Calendar, Telnyx, and Resend process workflow data.
- **Messaging — Confirmed:** transactional calendar invitation, email, and automated SMS reminders; production reminders are configured SMS-only.
- **AI — Confirmed:** the appointment is booked through an AI text-agent tool.
- **Minors — Assumed possible, no technical age gate:** the home-services product is not directed to children, but its public surface is reachable without age verification.
- **Entity — Assumed commercial operator:** exact legal entity and contracting disclosures were not re-reviewed.

### Focused coverage ledger

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| 1 | Committed secrets and ignore gaps | pass | CODE: `.env*`, credential files, dumps, logs, probe output, and backups are ignored; only example env files are tracked. A dedicated secret-scanner binary was unavailable in this checkout, so this is not a fresh history scan. |
| 2 | Row-level security / equivalent | n-a | CODE: browsers do not access the database directly; FastAPI/SQLAlchemy is the only data path. |
| 3 | Admin/service key in browser | pass | CODE: Google, Telnyx, Resend, database, and encryption credentials remain backend-only. |
| 4 | Object authorization at server/data layer | pass | CODE: booking operates on the already workspace-scoped contact/agent; calendar ownership resolves through the assigned login-linked staff record. Existing calendar scope controls are recorded under CAL-001/CAL-004. |
| 4a | Access-granting defaults | pass | CODE: a missing login-linked staff/calendar produces `not_connected`; it does not grant another user's calendar. |
| 4b | Multi-tenant isolation | pass | CODE: booking staff resolution is constrained by the agent workspace; reminder queries load each appointment's own workspace/contact. No cross-tenant production data was returned by the aggregate audit. |
| 5 | Mass assignment | pass | CODE: tool arguments are explicitly validated/mapped; provider event IDs and sync state are server-written. |
| 6 | String-built queries | pass | CODE: SQLAlchemy expressions are used; the fixed `_mark_offset_sent` column comes from a server-owned channel map. |
| 7 | Unauthenticated internal endpoint | n-a | Booking finalization is an internal agent tool; the scoped audit added no new route. Existing public chat/webhook boundary controls were not re-audited. |
| 8 | Public writable/listable storage | n-a | No file or bucket storage in this workflow. |
| 9 | Expensive/abusable provider call | pass | CODE: duplicate booking has a database uniqueness guard and manual reminders retain the existing route limiter. Public chatbot rate limits were not re-audited. |
| 10 | Password hashing | n-a | No password path in scope. |
| 11 | Session cookie/token storage | pass | CODE: Google OAuth refresh/access tokens use encrypted backend storage; no browser provider token. |
| 12 | JWT verification | n-a | No JWT path changed or reviewed. |
| 13 | Credentialed wildcard CORS | n-a | No CORS change; product-wide policy not re-reviewed. |
| 14 | Payment data | n-a | Appointment booking/reminders do not collect card data. |
| 14b | Cleartext high-value identifiers | pass | CODE: Google tokens and customer contact fields use existing encrypted storage; provider IDs are not credentials. |
| 15 | Personal data in logs | fail | CODE/RUNTIME: reminder/booking/email logs bind full phone, from-number, and recipient email fields. See LOG-001. |
| 16 | Transport security | pass | RUNTIME: production API and Google/Telnyx/Resend calls use HTTPS. |
| 17 | SSRF | n-a | No user-supplied server fetch URL; provider endpoints are fixed. |
| 18 | Backup/restore | pass | Existing encrypted backup workflow applies. Any proposed appointment backfill must use the production backup/migration release procedure. |
| U1 | Privacy notice, deletion, vendor list | fail | DEDUCED: Google/Telnyx/Resend/OpenAI process appointment data; this pass did not verify that the current privacy notice names purposes, processors, retention, and deletion propagation. See PRIV-001. |
| U2 | Third-party scripts consent | n-a | No browser tracking script reviewed or added. |
| U3 | Account security baseline | n-a | Broad authentication/session security is outside this focused workflow audit. |
| U4 | Public-page accessibility | n-a | The audit exercised backend/provider behavior and did not alter or manually audit the public chatbot UI. Accessibility conclusions must not be inferred from this pass. |
| U5 | Email/SMS duties | fail | RUNTIME/CODE: automatic SMS sends consumed reminders with failed/missing delivery; all inspected contacts recorded consent as `unknown`; the worker checks opt-out but not consent or quiet hours. See REM-001, REM-002, OBS-001, and MSG-001. |
| U6 | Contact-form privacy | n-a | The booking data-entry disclosure shown before the conversation was outside runtime scope; no new form was added. |
| U7 | Error handling / logging | fail | CODE/RUNTIME: calendar side effects are non-durable background tasks; reminder provider failures are swallowed and marked sent; no reminder failures reached the dead-letter table. See BOOK-001 and REM-001. |
| U8 | Personal-liability/entity review | n-a | Exact operating entity was not established. |
| A1 | Image alternatives | n-a | No image UI reviewed or changed. |
| A2 | Form labels | n-a | No form UI reviewed or changed. |
| A3 | Keyboard operability | n-a | No UI interaction audit was performed. |
| A4 | Colour contrast | n-a | No literal UI colors were reviewed. |
| A5 | Focus visibility | n-a | No UI interaction audit was performed. |
| A6 | Media controls/captions | n-a | No audio/video surface was in the tested text-booking flow. |
| A7 | Page language | n-a | No document shell was reviewed or changed. |
| C1-US | Consumer contract duties | n-a | This scoped booking flow does not take payment or form the service contract by itself. |
| C1-EU/UK | Consumer pre-contract/withdrawal duties | n-a | Same scope reason; existing proposal/payment duties remain tracked elsewhere. |
| P1-US | Platform/user-content duties | n-a | Customers do not publish hosted content to other users through this workflow. |
| P1-EU/UK | Platform/user-content duties | n-a | Same scope reason. |
| M1 | Minors | fail | DEDUCED: the public chatbot has no technical age gate. The service is not child-directed, but terms alone would not prevent use. See MIN-001. |
| AI1 | Bot identity and AI disclosure | fail | DEDUCED: no source-enforced first-turn AI disclosure was found in the scoped text-agent path; a database prompt may contain one, but the behavior is not guarded. See AI-001. |

### Findings

| ID | Severity | Trigger | Evidence (RUNTIME / CODE / DEDUCED) | Obligation | Status | Guard |
|---|---|---|---|---|---|---|
| BOOK-001 | HIGH | Local booking commits before Google/email/SMS work starts in an in-memory task | CODE + RUNTIME: the one live post-connection event exists, but no durable outbox, restart replay, shutdown drain, or pending/failed sync worker exists | Make promised calendar/notification side effects durable and observable | Open | Add transaction-outbox tests including process death and transient Google failure |
| REM-001 | HIGH | Failed automatic/manual SMS can be recorded and reported as sent | RUNTIME: only 7 of 11 automatic markers correlate to delivered reminder copy; 3 correlate to failed messages and 1 to no message. CODE: callers do not inspect returned `Message.status` | Do not represent a failed provider request as delivery; retry/dead-letter it | Open | Regression for `MessageStatus.FAILED` across automatic, manual, and value-reinforcement paths |
| REM-002 | HIGH | Existing failed idempotency rows are skipped rather than retried | CODE: resolver skips every status except `queued` | Preserve duplicate safety while allowing retryable failed attempts to resume with the same provider key | Open | Idempotency test for failed → provider retry → sent/delivered and permanent-failure stop |
| REM-003 | HIGH | Global `LIMIT 20` runs before unsent-offset filtering | CODE: fully consumed appointments can occupy the entire batch | Prevent silent tenant/row starvation | Open | 21 consumed rows followed by one due row must process the due row |
| CAL-005 | MEDIUM | Cal.com→Google migration dropped legacy provider IDs but retained `sync_status='synced'` | RUNTIME: 4 historical synced rows have no event ID | Make calendar state truthful and support deletion/correction | Open | Backfill `legacy_unlinked`; reject future synced-without-provider-ID rows |
| OBS-001 | HIGH | Direct booking/reminder emails are not correlated to Resend webhook records | RUNTIME/CODE: provider acceptance IDs exist, but send-only key blocks read-back and no `Message` row can receive webhook status | Distinguish accepted, delivered, bounced, and failed | Open | Persist delivery attempts and replay signed delivered/bounced fixtures |
| MSG-001 | HIGH | Automated reminders have unknown recorded consent and no quiet-hours gate | RUNTIME/CODE: inspected contacts are `sms_consent_status='unknown'`; only opt-out is enforced | Retain demonstrable consent scope and enforce applicable send windows | Open — legal policy needed | Shared outbound gate test for unknown/withdrawn consent and local quiet hours |
| LOG-001 | MEDIUM | Customer phone/email values are bound into operational logs | CODE + RUNTIME | Minimize personal data in logs and retention scope | Open | Log-capture tests rejecting raw email/E.164 destinations |
| PRIV-001 | MEDIUM | Four external processors receive appointment/conversation data | DEDUCED: current public privacy notice/vendor disclosures were not re-verified | Accurately disclose purposes, processors, retention, rights, and deletion propagation | Open — legal/factual review needed | Release checklist plus reviewed privacy-register entry |
| MIN-001 | MEDIUM | Internet-reachable chatbot without technical age gate | DEDUCED | Decide intended audience and a defensible minors path | Open — product/legal decision needed | Age/audience test only if minors are excluded by design |
| AI-001 | MEDIUM | AI text agent can interact and book without a code-enforced identity disclosure | DEDUCED; production prompt disclosure was not inspected | Make bot identity clear where required and avoid relying on editable prompt luck | Open — re-verify current jurisdiction rules | First-turn disclosure contract test |

### Implemented in this pass

- No production message or calendar mutation was made. The audit used aggregate database reads, a Google event read, redacted logs, and provider-status records.
- One live post-connection chatbot booking was proved to exist on the connected owner's primary Google Calendar with matching timing and attendee metadata.
- The functional report and acceptance criteria are in `docs/appointment-booking-reminder-audit-2026-08-16.md`; redacted machine evidence is in the gitignored `.ezcoder/eyes/out/appointment-delivery-audit-2026-08-16.json`.

### Open — needs an engineering decision

1. Use one durable delivery-attempt/outbox model for calendar, email, SMS, and reminder touchpoints rather than adding more marker arrays.
2. Backfill four legacy calendar rows only after the required production appointment-table backup.
3. Define the transactional SMS consent/quiet-hours policy before wiring the shared send gate.

### Needs a lawyer

- Confirm the consent evidence and send-window policy for automated appointment reminders in the places customers are served.
- Confirm the required chatbot AI disclosure and public-surface minors position; rules and effective dates are jurisdiction-specific and must be re-verified before relying on this snapshot.
- Review actual privacy notice/vendor/retention facts; do not infer them from this engineering register.

### Re-verify before relying

- “Delivered” here means Telnyx's signed delivery status, not proof a person read the text. Resend evidence stops at provider acceptance because direct emails are not correlated and the key is send-only.
- Historical Cal.com events cannot be verified after their identifiers were dropped.
- The public chatbot UI, broad authentication surface, and product-wide accessibility were not audited in this focused pass.

## Addendum — Customer invoice-link DNS incident

Snapshot: 14 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

- **RUNTIME — Fixed for new and resent invoices:** production generated customer email targets with `https://app.maxteriorslighting.com` and SMS short links with `https://go.maxteriorslighting.com`; neither hostname had a traffic DNS record. Railway `FRONTEND_URL` now uses the reachable Vercel origin and `PUBLIC_BASE_URL` the reachable Railway origin.
- **RUNTIME — Verified:** the configuration deployment completed successfully at commit `83aebb43`; backend readiness and six deployment smoke tests passed, both frontend deployment smoke tests passed, the public invoice page served 200, and an unknown public invoice token returned the expected 404.
- **Payment control — Unchanged:** invoice amounts remain server-derived and card entry remains on hosted Stripe Checkout; no card data or new payment processor was introduced.
- **RUNTIME — Customer remediation completed:** three actionable invoices had customer links affected by the DNS move. Replacement emails for `INV-000007` and `INV-000008` were accepted by Resend; replacement texts for `INV-000004` and `INV-000008` were confirmed delivered by Telnyx. Every replacement targets the verified fallback frontend, and the texts use the verified Railway short-link origin. No opted-out contact was messaged, and SMS was not introduced as a new channel for any contact.
- **RUNTIME — Independent re-verification:** fail-fast reads reconfirmed both Railway origins, both exact email links against the public invoice API and rendered frontend route, and both corrected SMS rows as `delivered` with the right targets. All six backend and two frontend production smoke tests passed. The production Resend key is intentionally send-only, so provider delivery events cannot be read back; evidence for email stops at provider acceptance and exact-link validity, not inbox delivery.
- **RUNTIME — Live payment verified:** the public pay action for an outstanding production invoice created a hosted Stripe Checkout Session with `livemode=true`, `status=open`, and `payment_status=unpaid`. Stripe's amount matched the server-computed invoice balance, the hosted checkout loaded, and success/cancel URLs return to the reachable invoice page. No PaymentIntent or charge was created by the verification.
- **RUNTIME — Payment webhook verified:** Stripe reports enabled live webhook endpoints at the reachable Railway billing route with `checkout.session.completed` enabled, and a harmless event signed with the deployed webhook secret returned 200. The invoice return route also reconciled the open session as unpaid without mutating payment state.
- **RUNTIME — Operator-requested resend:** Marc Sheffman's `INV-000007` and Greg Bartelt's `INV-000008` were resent through their established channels after the live-payment proof. Resend accepted both emails; Telnyx confirmed Greg's SMS as `delivered`, targeting the reachable invoice origin. The SMS contact was not opted out, and no new messaging channel was introduced.
- **Residual infrastructure issue:** previously delivered branded links remain dead because the authoritative Cloudflare nameservers changed to a different zone; the stored edit token is scoped to the old zone, which Cloudflare reports as `moved`. New and replacement links work, but current-zone DNS access is still required before the branded origins can be restored.

## Addendum — Chatbot appointment booking and reminder delivery

Snapshot: 16 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Commit reviewed: deployed backend `e229d64584be7cfae81613d1f19ef630a9e1eb81`.

Scope: production chatbot appointment finalization, Google Calendar creation, booking notifications, automatic/manual appointment reminders, Telnyx/Resend delivery reconciliation, and the minimum messaging/privacy controls attached to those paths. This is a focused workflow audit, not a product-wide certification.

### Assumed exposure profile

- **Reach — Confirmed:** deployed public chatbot/SMS surfaces plus authenticated operator UI.
- **Jurisdictions — Assumed:** reachable worldwide; US and EU/UK duties may apply unless access is technically limited.
- **Personal data — Confirmed:** customer name, phone, email, conversation, appointment time/location, and calendar attendee data.
- **Third parties — Confirmed:** OpenAI, Google Calendar, Telnyx, and Resend process workflow data.
- **Messaging — Confirmed:** transactional calendar invitation, email, and automated SMS reminders; production reminders are configured SMS-only.
- **AI — Confirmed:** the appointment is booked through an AI text-agent tool.
- **Minors — Assumed possible, no technical age gate:** the home-services product is not directed to children, but its public surface is reachable without age verification.
- **Entity — Assumed commercial operator:** exact legal entity and contracting disclosures were not re-reviewed.

### Focused coverage ledger

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| 1 | Committed secrets and ignore gaps | pass | CODE: `.env*`, credential files, dumps, logs, probe output, and backups are ignored; only example env files are tracked. A dedicated secret-scanner binary was unavailable in this checkout, so this is not a fresh history scan. |
| 2 | Row-level security / equivalent | n-a | CODE: browsers do not access the database directly; FastAPI/SQLAlchemy is the only data path. |
| 3 | Admin/service key in browser | pass | CODE: Google, Telnyx, Resend, database, and encryption credentials remain backend-only. |
| 4 | Object authorization at server/data layer | pass | CODE: booking operates on the already workspace-scoped contact/agent; calendar ownership resolves through the assigned login-linked staff record. Existing calendar scope controls are recorded under CAL-001/CAL-004. |
| 4a | Access-granting defaults | pass | CODE: a missing login-linked staff/calendar produces `not_connected`; it does not grant another user's calendar. |
| 4b | Multi-tenant isolation | pass | CODE: booking staff resolution is constrained by the agent workspace; reminder queries load each appointment's own workspace/contact. No cross-tenant production data was returned by the aggregate audit. |
| 5 | Mass assignment | pass | CODE: tool arguments are explicitly validated/mapped; provider event IDs and sync state are server-written. |
| 6 | String-built queries | pass | CODE: SQLAlchemy expressions are used; the fixed `_mark_offset_sent` column comes from a server-owned channel map. |
| 7 | Unauthenticated internal endpoint | n-a | Booking finalization is an internal agent tool; the scoped audit added no new route. Existing public chat/webhook boundary controls were not re-audited. |
| 8 | Public writable/listable storage | n-a | No file or bucket storage in this workflow. |
| 9 | Expensive/abusable provider call | pass | CODE: duplicate booking has a database uniqueness guard and manual reminders retain the existing route limiter. Public chatbot rate limits were not re-audited. |
| 10 | Password hashing | n-a | No password path in scope. |
| 11 | Session cookie/token storage | pass | CODE: Google OAuth refresh/access tokens use encrypted backend storage; no browser provider token. |
| 12 | JWT verification | n-a | No JWT path changed or reviewed. |
| 13 | Credentialed wildcard CORS | n-a | No CORS change; product-wide policy not re-reviewed. |
| 14 | Payment data | n-a | Appointment booking/reminders do not collect card data. |
| 14b | Cleartext high-value identifiers | pass | CODE: Google tokens and customer contact fields use existing encrypted storage; provider IDs are not credentials. |
| 15 | Personal data in logs | fail | CODE/RUNTIME: reminder/booking/email logs bind full phone, from-number, and recipient email fields. See LOG-001. |
| 16 | Transport security | pass | RUNTIME: production API and Google/Telnyx/Resend calls use HTTPS. |
| 17 | SSRF | n-a | No user-supplied server fetch URL; provider endpoints are fixed. |
| 18 | Backup/restore | pass | Existing encrypted backup workflow applies. Any proposed appointment backfill must use the production backup/migration release procedure. |
| U1 | Privacy notice, deletion, vendor list | fail | DEDUCED: Google/Telnyx/Resend/OpenAI process appointment data; this pass did not verify that the current privacy notice names purposes, processors, retention, and deletion propagation. See PRIV-001. |
| U2 | Third-party scripts consent | n-a | No browser tracking script reviewed or added. |
| U3 | Account security baseline | n-a | Broad authentication/session security is outside this focused workflow audit. |
| U4 | Public-page accessibility | n-a | The audit exercised backend/provider behavior and did not alter or manually audit the public chatbot UI. Accessibility conclusions must not be inferred from this pass. |
| U5 | Email/SMS duties | fail | RUNTIME/CODE: automatic SMS sends consumed reminders with failed/missing delivery; all inspected contacts recorded consent as `unknown`; the worker checks opt-out but not consent or quiet hours. See REM-001, REM-002, OBS-001, and MSG-001. |
| U6 | Contact-form privacy | n-a | The booking data-entry disclosure shown before the conversation was outside runtime scope; no new form was added. |
| U7 | Error handling / logging | fail | CODE/RUNTIME: calendar side effects are non-durable background tasks; reminder provider failures are swallowed and marked sent; no reminder failures reached the dead-letter table. See BOOK-001 and REM-001. |
| U8 | Personal-liability/entity review | n-a | Exact operating entity was not established. |
| A1 | Image alternatives | n-a | No image UI reviewed or changed. |
| A2 | Form labels | n-a | No form UI reviewed or changed. |
| A3 | Keyboard operability | n-a | No UI interaction audit was performed. |
| A4 | Colour contrast | n-a | No literal UI colors were reviewed. |
| A5 | Focus visibility | n-a | No UI interaction audit was performed. |
| A6 | Media controls/captions | n-a | No audio/video surface was in the tested text-booking flow. |
| A7 | Page language | n-a | No document shell was reviewed or changed. |
| C1-US | Consumer contract duties | n-a | This scoped booking flow does not take payment or form the service contract by itself. |
| C1-EU/UK | Consumer pre-contract/withdrawal duties | n-a | Same scope reason; existing proposal/payment duties remain tracked elsewhere. |
| P1-US | Platform/user-content duties | n-a | Customers do not publish hosted content to other users through this workflow. |
| P1-EU/UK | Platform/user-content duties | n-a | Same scope reason. |
| M1 | Minors | fail | DEDUCED: the public chatbot has no technical age gate. The service is not child-directed, but terms alone would not prevent use. See MIN-001. |
| AI1 | Bot identity and AI disclosure | fail | DEDUCED: no source-enforced first-turn AI disclosure was found in the scoped text-agent path; a database prompt may contain one, but the behavior is not guarded. See AI-001. |

### Findings

| ID | Severity | Trigger | Evidence (RUNTIME / CODE / DEDUCED) | Obligation | Status | Guard |
|---|---|---|---|---|---|---|
| BOOK-001 | HIGH | Local booking commits before Google/email/SMS work starts in an in-memory task | CODE + RUNTIME: the one live post-connection event exists, but no durable outbox, restart replay, shutdown drain, or pending/failed sync worker exists | Make promised calendar/notification side effects durable and observable | Open | Add transaction-outbox tests including process death and transient Google failure |
| REM-001 | HIGH | Failed automatic/manual SMS can be recorded and reported as sent | RUNTIME: only 7 of 11 automatic markers correlate to delivered reminder copy; 3 correlate to failed messages and 1 to no message. CODE: callers do not inspect returned `Message.status` | Do not represent a failed provider request as delivery; retry/dead-letter it | Open | Regression for `MessageStatus.FAILED` across automatic, manual, and value-reinforcement paths |
| REM-002 | HIGH | Existing failed idempotency rows are skipped rather than retried | CODE: resolver skips every status except `queued` | Preserve duplicate safety while allowing retryable failed attempts to resume with the same provider key | Open | Idempotency test for failed → provider retry → sent/delivered and permanent-failure stop |
| REM-003 | HIGH | Global `LIMIT 20` runs before unsent-offset filtering | CODE: fully consumed appointments can occupy the entire batch | Prevent silent tenant/row starvation | Open | 21 consumed rows followed by one due row must process the due row |
| CAL-005 | MEDIUM | Cal.com→Google migration dropped legacy provider IDs but retained `sync_status='synced'` | RUNTIME: 4 historical synced rows have no event ID | Make calendar state truthful and support deletion/correction | Open | Backfill `legacy_unlinked`; reject future synced-without-provider-ID rows |
| OBS-001 | HIGH | Direct booking/reminder emails are not correlated to Resend webhook records | RUNTIME/CODE: provider acceptance IDs exist, but send-only key blocks read-back and no `Message` row can receive webhook status | Distinguish accepted, delivered, bounced, and failed | Open | Persist delivery attempts and replay signed delivered/bounced fixtures |
| MSG-001 | HIGH | Automated reminders have unknown recorded consent and no quiet-hours gate | RUNTIME/CODE: inspected contacts are `sms_consent_status='unknown'`; only opt-out is enforced | Retain demonstrable consent scope and enforce applicable send windows | Open — legal policy needed | Shared outbound gate test for unknown/withdrawn consent and local quiet hours |
| LOG-001 | MEDIUM | Customer phone/email values are bound into operational logs | CODE + RUNTIME | Minimize personal data in logs and retention scope | Open | Log-capture tests rejecting raw email/E.164 destinations |
| PRIV-001 | MEDIUM | Four external processors receive appointment/conversation data | DEDUCED: current public privacy notice/vendor disclosures were not re-verified | Accurately disclose purposes, processors, retention, rights, and deletion propagation | Open — legal/factual review needed | Release checklist plus reviewed privacy-register entry |
| MIN-001 | MEDIUM | Internet-reachable chatbot without technical age gate | DEDUCED | Decide intended audience and a defensible minors path | Open — product/legal decision needed | Age/audience test only if minors are excluded by design |
| AI-001 | MEDIUM | AI text agent can interact and book without a code-enforced identity disclosure | DEDUCED; production prompt disclosure was not inspected | Make bot identity clear where required and avoid relying on editable prompt luck | Open — re-verify current jurisdiction rules | First-turn disclosure contract test |

### Implemented in this pass

- No production message or calendar mutation was made. The audit used aggregate database reads, a Google event read, redacted logs, and provider-status records.
- One live post-connection chatbot booking was proved to exist on the connected owner's primary Google Calendar with matching timing and attendee metadata.
- The functional report and acceptance criteria are in `docs/appointment-booking-reminder-audit-2026-08-16.md`; redacted machine evidence is in the gitignored `.ezcoder/eyes/out/appointment-delivery-audit-2026-08-16.json`.

### Open — needs an engineering decision

1. Use one durable delivery-attempt/outbox model for calendar, email, SMS, and reminder touchpoints rather than adding more marker arrays.
2. Backfill four legacy calendar rows only after the required production appointment-table backup.
3. Define the transactional SMS consent/quiet-hours policy before wiring the shared send gate.

### Needs a lawyer

- Confirm the consent evidence and send-window policy for automated appointment reminders in the places customers are served.
- Confirm the required chatbot AI disclosure and public-surface minors position; rules and effective dates are jurisdiction-specific and must be re-verified before relying on this snapshot.
- Review actual privacy notice/vendor/retention facts; do not infer them from this engineering register.

### Re-verify before relying

- “Delivered” here means Telnyx's signed delivery status, not proof a person read the text. Resend evidence stops at provider acceptance because direct emails are not correlated and the key is send-only.
- Historical Cal.com events cannot be verified after their identifiers were dropped.
- The public chatbot UI, broad authentication surface, and product-wide accessibility were not audited in this focused pass.

## Focused addendum — contact AI memory (2026-08-17)

Scope: durable contact memory derived from CRM/SMS/voice interactions plus its operator-facing
review and correction surface. This is engineering guidance, **NOT LEGAL ADVICE**; the wider
register above remains open.

| ID | Severity | Trigger | Evidence (RUNTIME / CODE / DEDUCED) | Obligation | Status | Guard |
|---|---|---|---|---|---|---|
| MEM-001 | HIGH | AI-generated CRM memory can retain personal data and stale claims | CODE + RUNTIME: encrypted summary/fact columns, composite workspace scope, provenance/expiry/supersession, contact cascade deletion, and source-change invalidation trigger; local trigger exercise returned `invalidated` | Minimize access, make staleness explicit, and prevent generated text from outranking current CRM records | Implemented in this pass | Model/service/update tests, migration up→down→up, Alembic drift check, and encryption-key rotation coverage |
| MEM-002 | MEDIUM | OpenAI processes SMS/voice text to refresh memory | CODE: existing workspace/OpenAI credential path is reused; no new processor was added | Keep privacy notice, processor terms, retention, and deletion propagation accurate | Open — factual/legal review needed | Re-verify vendor and retention disclosures before launch/reliance |
| MEM-003 | HIGH | Realtime voice prompts combine CRM, SMS, human-authored messages, and generated voice summaries | CODE: workspace predicates on contact/campaign/offer/memory reads; live-tool-first authority; free text marked as data; stale summaries excluded; caller context capped at 21,000 characters and optional enrichment capped at 1 second | Prevent cross-tenant disclosure, prompt-injection precedence, stale financial/calendar claims, and unnecessary call-start exposure | Implemented in this pass | Returning caller, cross-channel, reschedule, accepted quote, stale memory, missing contact, tenant-scope, prompt-cap, timeout, and three-provider tool-bridge tests |
| MEM-004 | HIGH | The CRM assistant can retrieve consolidated contact PII and historical communications | CODE + TEST: `get_contact_context` resolves a workspace-scoped `ContactContextSnapshot`, rejects foreign-workspace IDs without disclosure, labels notes/timeline as non-authoritative, requires source timestamps, and logs argument names/code locations without values | Prevent cross-tenant disclosure, stale-state claims, ambiguous-person selection, and PII leakage into telemetry | Implemented in this pass | Ambiguous identity, conflicting state, 50-item cross-channel page, pagination, cross-workspace denial, approval-gate, prompt, schema, and telemetry regression tests |
| MEM-005 | HIGH | Operators can view and correct AI-inferred contact memory | CODE + TEST: a private/no-store, `crm:read` endpoint returns a bounded projection without identity, address, raw timeline, notes, record IDs, or financial amounts; `crm:write` mutations can only supersede generated facts and exclude contact-sourced authoritative facts | Minimize operator-visible PII, explain provenance/freshness/conflicts, and prevent a memory correction from silently changing CRM records | Implemented in this pass | Role/workspace authorization tests, projection minimization tests, generated-fact guard tests, typed API tests, and keyboard/label/focus component tests |
| MEM-006 | HIGH | SMS, voice, and CRM context/tool telemetry can copy message bodies, tool arguments/results, or directly identifying record IDs into logs | CODE + TEST: shared observability emits only HMAC-pseudonymous source/invocation refs, freshness/age, token counts, fixed route reason codes, allowlisted tool name/status, and correction category/action; touched SMS/voice raw body/argument/result logs were removed | Minimize telemetry, retain enough provenance to investigate stale/unsupported AI claims, and keep production bodies/PII out of eval artifacts | Implemented in this pass | Privacy payload/source-regression tests, strict body-free observation schema, 48-scenario local golden gate, and shadow-mode default |

### Implemented in this pass

- Sensitive summary and fact values use `EncryptedString`; deduplication compares decrypted values only inside the scoped service, and both new encrypted columns are declared in the key-rotation script.
- Prompt renderers mark summaries/facts as untrusted data, JSON-escape values, omit expired/superseded facts, and explicitly make `ContactContextSnapshot`/current-turn CRM tool results authoritative.
- Voice prompt assembly preserves current campaign/offer framing while separately labelling live CRM, recent SMS/human interactions, durable memory, and legacy voice summaries with provenance/freshness.
- Known-caller realtime sessions force the read-only, caller-bound `lookup_caller_record` tool; OpenAI, Grok, and ElevenLabs/Grok bridge tests pin this behavior.
- Memory logs contain only workspace/contact/conversation/message identifiers plus exception type; adjacent SMS-path raw phone/email/message previews touched in this pass were removed.
- The CRM assistant resolves contact identity before loading the consolidated snapshot, cites `observed_at`/`provenance.updated_at`, keeps mutating tools on their existing confirmation path, and excludes raw tool values/results/exception text from telemetry.
- The operator panel separates read-only CRM facts from generated memory, displays provenance/freshness and authoritative conflicts, and returns keyboard focus after correction/removal dialogs.
- AI context/tool/correction events HMAC-pseudonymize identifiers and record metadata/counts only; the local eval schema rejects message-body fields and keeps factual, unsupported-claim, stale-state, tool/action, and handoff metrics separate.

### Residual decisions

- Confirm the product retention period for contact memory and backups. Live rows cascade-delete with the contact, but backup retention is an operational/legal policy outside this code change.
- Re-verify that public privacy disclosures accurately describe AI processing of SMS/voice CRM data and the current OpenAI processor arrangement.
- The voice-context controls are CODE + automated-test evidence, not a live provider call. Runtime dashboard-added prompts/tools and provider-side retention were not inspected in this focused pass.
- SMS model routing remains in metadata-only `shadow` mode until the documented golden and reviewed-production gates pass; enabling `active` changes model cost and requires an operational rollout decision.
