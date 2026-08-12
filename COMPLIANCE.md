# Compliance Register

Snapshot: 12 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Commit reviewed: working tree on `669fd941` (uncommitted approved implementation).

Scope of this pass: landscape-lighting proposal deposit truth, accepted-quote conversion, crew assignment notifications, and authenticated installation-plan delivery. This is a focused feature review, not a certification or a full-product legal/security audit.

## Assumed exposure profile

- **Reach — Confirmed:** deployed CRM with authenticated staff UI plus public customer proposal/payment pages.
- **Jurisdictions — Assumed:** internet-reachable worldwide; United States plus EU/UK exposure may apply.
- **Personal data — Confirmed:** customer identity, address, property imagery, field notes, staff identity, and notification addresses.
- **Money — Confirmed:** consumer deposits use hosted Stripe Checkout; Tribunal retains provider identifiers and reconciled state, not card data.
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
| 7 | Unauthenticated internal endpoint | pass | RUNTIME: installation-plan request without authentication returned 401; no public token route exists. |
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
| U5 | Email duties | pass | CODE/RUNTIME: assignment copy is transactional, preference-aware, recipient-scoped, deduplicated, and contains no imagery/token. |
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
| LL-002 | BLOCKER | Consumer deposit state affects invoice credit | RUNTIME: paid 25% deposit credited exactly `$250.00`; exact conversion retry retained one job/invoice | Keep payment truth provider-derived and idempotent; never accept manual paid state | Fixed | Quote service integration tests plus runtime row-count/payment proof |
| LL-003 | HIGH | Transactional assignment email/push exposes private-work availability | RUNTIME: captured email had one installer recipient and availability copy; no image, token, provider payment ID, or procurement note | Scope recipients, honor preferences, deduplicate, and keep imagery behind authenticated access | Fixed | Notification unit tests, Redis dedupe, delivery counts, Mailpit artifact |
| LL-004 | HIGH | Failed delivery must remain retryable and truthful | RUNTIME: initial probe found a failed send retained its dedupe claim and a retry falsely said sent | Release dedupe claims after total failure; report delivery separately from committed job | Fixed | Post-fix exact retry remained `failed`; targeted tests and final backend CI |
| LL-005 | LAWYER | US consumers may pay a landscape-lighting deposit through the public proposal | CODE/DEDUCED: hosted checkout and server-derived totals are present, but the customer-facing cancellation, refund, tax, and contract terms were outside this review | Confirm the actual proposal terms match each US jurisdiction served | Open | Legal review of the deployed proposal and refund/cancellation policy |
| LL-006 | LAWYER | EU/UK consumers may pay a landscape-lighting deposit if the service is offered there | CODE/DEDUCED: no geographic block was established and jurisdiction-specific pre-contract/withdrawal wording was not reviewed | Confirm required pre-contract information, withdrawal handling, and any early-service waiver before offering there | Open if EU/UK consumers are served | Legal review plus a jurisdictional launch checklist |

## Implemented in this pass

- Stable quote/job/project links and database uniqueness prevent duplicate converted jobs.
- Public proposal schemas omit project IDs, plans, staff assignments, procurement, and job/payment handoff details.
- Installation imagery is authenticated and assignment-scoped with 404 non-disclosure.
- Payment truth remains Stripe-derived; scheduling an unpaid required deposit needs explicit acknowledgement but cannot mark it paid.
- Notifications target active direct/crew installers, honor existing master/preferences, use deterministic dedupe, report partial/failure separately, and omit imagery/tokens.
- Internal payment receipts identify the client using CRM name, email, phone, and quote number; payment credentials and provider identifiers remain excluded, and all customer-supplied values are HTML-escaped.
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


## Addendum — Teach AI and website-lead qualification

Snapshot: 12 August 2026 · NOT LEGAL ADVICE

- **Personal data — Confirmed:** approved lessons retain encrypted customer SMS, AI replies, ideal replies, and optional operator notes.
- **Tenant isolation — Fixed:** CRM-write authorization protects lesson creation; conversation, source message, agent, retrieval, and timeline agent metadata are workspace-scoped or server-derived.
- **Prompt injection — Fixed:** active examples are capped at 12/6,000 prompt characters, JSON-quoted, marked untrusted, and cannot override truthfulness, opt-out, qualification, booking, or tool rules.
- **Automated sales qualification — Fixed in code:** off by default, reuses captured form answers, asks one missing question at a time, requires evidence/score, preserves human handoff, and removes booking/availability tools until qualification persists.
- **Messaging — Unchanged:** Teach AI has no send path; existing consent and opt-out controls remain the only customer-message gates.
- **Key rotation — Fixed:** all four new `EncryptedString` columns are registered in `scripts/ops/reencrypt_with_old_key.py`, with a regression guard.
- **LAWYER before relying broadly:** define lesson retention and deletion propagation, disclose AI/personal-data reuse, and confirm lawful basis/data-subject rights where EU/UK leads are served.