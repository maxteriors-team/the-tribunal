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
