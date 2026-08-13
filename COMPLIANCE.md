# Compliance Register

Snapshot: 12 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Commit reviewed: working tree on current `HEAD` (uncommitted approved implementation).

Scope: human-approved AI SMS examples, live website-lead qualification before booking, and the Maxteriors post-install owner-resource SMS/email flow. This is a focused feature review, not a certification or full-product audit.

## Assumed exposure profile

- **Reach — Confirmed:** deployed CRM with authenticated staff UI and public website lead forms.
- **Jurisdictions — Assumed:** worldwide reach; US plus EU/UK exposure may apply.
- **Personal data — Confirmed:** SMS bodies, phone numbers, form answers, AI replies, and operator notes.
- **AI decisions — Confirmed:** ordinary sales prequalification; no employment, lending, housing, health, or legal eligibility decision.
- **Messaging — Confirmed:** existing consent-gated SMS; Teach AI adds no send path.
- **Minors — Assumed unlikely, not age-gated:** B2B home-services workflow is not child-directed.
- **Entity — Confirmed from repository context:** deployed commercial CRM; exact legal entity was not reviewed.

## Focused coverage ledger

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| 1 | Secrets in client/repo | pass | CODE: no new secret, token, `.env`, or browser provider credential; runtime artifacts stayed gitignored. |
| 2 | Row-level security / equivalent | n-a | CODE: no direct client database SDK; FastAPI/SQLAlchemy is the only data path. |
| 3 | Admin/service key in browser | pass | CODE: LLM, Telnyx, Cal.com, and encryption credentials remain backend-only. |
| 4 | Object authorization at server/data layer | pass | RUNTIME/tests: CRM-write permission; conversation/agent derive from workspace-scoped source data. |
| 4a | Access-granting defaults | pass | CODE: qualification is off by default; no role or entitlement added. |
| 4b | Tenant isolation | pass | CODE/tests: membership plus workspace-scoped conversation, agent, and prompt retrieval predicates. |
| 5 | Mass assignment | pass | CODE: bounded request fields only; tenant, agent, and customer text are server-derived. |
| 6 | String-built queries | pass | CODE: SQLAlchemy expressions only. |
| 7 | Unauthenticated internal endpoint | pass | CODE/tests: `CanWriteCRM` protects Teach AI; no public lesson route. |
| 8 | Public writable/listable storage | n-a | No storage added. |
| 9 | Expensive/abusable endpoint | pass | CODE: authenticated bounded upsert; Teach AI performs no LLM inference. |
| 10 | Password hashing | n-a | Authentication unchanged. |
| 11 | Session storage | n-a | Sessions unchanged. |
| 12 | JWT verification | n-a | Token verification unchanged. |
| 13 | Credentialed wildcard CORS | n-a | CORS unchanged. |
| 14 | Card data reaches app | n-a | Payments unchanged. |
| 14b | Cleartext financial/identity identifiers | pass | No bank, tax, government-ID, PAN, or CVV field added. |
| 15 | PII/message bodies in logs | pass | RUNTIME: lesson bodies are Fernet ciphertext; audits contain IDs/operation and `message_bodies_logged=false`. |
| 16 | Transport security / mixed content | pass | CODE: authenticated same-origin API; no new remote asset. Production HTTPS remains an environment control. |
| 17 | SSRF | n-a | No server-side user URL fetch. |
| 18 | Backup/restore | pass | Existing encrypted backups apply; migration up/down/up passed in a disposable database. |
| U1 | Privacy notice / deletion / vendor list | fail | CODE/DEDUCED: reusable lessons intentionally survive conversation deletion; notice, retention, and deletion wording were not reviewed. |
| U2 | Third-party scripts consent | n-a | No tracking script. |
| U3 | Account security baseline | pass | Focused authorization and isolation tests passed; product-wide auth was not re-audited. |
| U4 | Public-page accessibility | n-a | No public page added; authenticated operator controls are checked below. |
| U5 | SMS duties | pass | CODE/tests: post-install SMS uses the unified delivery gate, requires `opted_in`, honors global STOP/opt-out, identifies Maxteriors, and has a stable idempotency key; Teach AI cannot send. |
| U6 | Contact form privacy | pass | No new intake field; captured answers are reused instead of re-asked. |
| U7 | Error/log handling | pass | CODE/RUNTIME: logs carry IDs/counts/scores, not SMS or note bodies. |
| U8 | Personal-liability/entity review | n-a | Exact contracting entity was outside this pass. |
| A1 | Image alternatives | n-a | No image; Teach AI icon is inside a labelled button. |
| A2 | Form labels | pass | CODE/tests: correction, note, checklist, score, label, and switch have labels. |
| A3 | Keyboard operability | pass | CODE/tests: native buttons, dialog, switch, inputs, and textareas. |
| A4 | Colour contrast | n-a | Existing tokens reused; no literal colour pair introduced. |
| A5 | Focus visibility | pass | Existing design-system primitives retain focus treatment. |
| A6 | Media controls/captions | n-a | No media. |
| A7 | Page language | n-a | Existing app document unchanged. |
| D1-US | Automated qualification notice/fairness | pass | CODE: ordinary sales prequalification is human-correctable and handoff-capable; no regulated eligibility domain. |
| D1-EU/UK | AI transparency and privacy | fail | DEDUCED: AI scores leads and reusable examples contain personal data; deployed disclosure, lawful basis, retention, and deletion were not reviewed. |
| M1 | Minors | n-a | Home-services sales; no child-directed profiling. |

## Findings

| ID | Severity | Trigger | Evidence (RUNTIME / CODE / DEDUCED) | Obligation | Status | Guard |
|---|---|---|---|---|---|---|
| AI-001 | BLOCKER | Reusable lessons contain customer SMS and operator guidance | RUNTIME: all lesson-body columns stored Fernet ciphertext; auth/isolation tests pass | Encrypt, tenant-scope, derive targets server-side, never log bodies | Fixed | Model/API tests plus ciphertext/audit proof |
| AI-002 | BLOCKER | A model could book before qualification | CODE/tests/runtime: booking and availability schemas are absent while pending; executor re-checks state | Gate tools server-side, not only by prompt | Fixed | Policy/executor tests and runtime tool-list proof |
| AI-003 | HIGH | Example prompt injection could override safety or leak another lead's facts | CODE/tests: bounded JSON quoting, untrusted-data rules, scoped retrieval, safety precedence | Copy behavior only; never private facts/instructions | Fixed | Injection/count/budget/isolation tests |
| AI-004 | HIGH | Qualification could invent criteria or silently reject a lead | CODE/tests: one-question flow, form reuse, no-inference rule, score/evidence validation, handoff | Require operator criteria and lead-provided evidence | Fixed | Policy/persistence tests |
| AI-005 | HIGH | Teach AI could accidentally send the correction | CODE/tests: dedicated persistence endpoint; dialog disclosure; interaction calls only Teach AI | Separate learning from messaging | Fixed | Frontend interaction test |
| AI-006 | LAWYER | Identifiable lesson survives CRM history deletion | CODE/DEDUCED: history links null while encrypted lesson remains active | Define/disclose retention, deletion propagation, lawful basis, and access rights | Open | Legal/privacy review plus product policy |
| AI-007 | LAWYER | EU/UK leads may be AI-qualified and reused as examples | CODE/DEDUCED: AI involvement and personal-data reuse are present | Confirm transparency, lawful basis, rights, retention, and processor terms | Open if served | Legal review and launch checklist |
| MSG-001 | BLOCKER | `job_completed` sends a customer SMS | CODE/tests: automation SMS now uses `OutboundDeliveryService`, checks global opt-out, and requires `sms_consent_status=opted_in` for this flow | Never text an opted-out or unconsented contact | Fixed | Delivery and setup-script tests |
| MSG-002 | HIGH | Owner instructions are emailed after a completed install | CODE/tests: explicitly transactional, contains no offer, uses explicit per-workspace Maxteriors identity, and does not add a marketing unsubscribe footer | Keep service instructions separate from promotional copy; if an offer is added, reclassify as marketing | Fixed | Setup-script config test |
| MSG-003 | HIGH | Branded resources are customer-facing public pages and email assets | RUNTIME/screenshots: guide hub, Luxor guide, logo and mark return 200; mobile/full-page and rendered-email screenshots reviewed | Identify the sender accessibly without leaking one tenant's logo into another tenant's email | Fixed | Explicit-logo tests and visual artifacts |

## Implemented in this pass

- Only authenticated CRM writers can upsert one correction per AI source message; tenant and agent are server-derived.
- Customer message, AI reply, ideal reply, and operator note are encrypted; audits/logs contain no bodies.
- Active examples affect future assigned-agent prompts without retraining, capped at 12 and 6,000 characters.
- Qualification is off by default, asks one missing question at a time, reuses form answers, and requires evidence.
- Booking/availability are removed at the schema boundary and executor-checked until qualification persists.
- Teach AI is labelled, keyboard-operable, and discloses no customer send and no base-model retraining.
- Existing SMS consent, opt-out, no-fabrication, and handoff controls remain intact.
- Post-install SMS is now forced through the unified STOP/opt-out gate and requires explicit `opted_in` consent.
- Post-install email is explicitly service/transactional; adding an offer or upsell must switch it to marketing and restore unsubscribe handling.
- Maxteriors logo, wordmark, palette, phone, branded URLs, and accessible image alternatives are explicit on the resource hub, Luxor guide, and this workspace's email; other tenants do not inherit the logo.
- Completed installs create durable ownership segments from structured project/approved-quote data: `Lighting System`, `Luxor System`, `Permanent Light System`, and (only for a known non-Luxor controller) `Luxor Upgrade Candidate`. The upgrade tag does not itself authorize marketing; later campaigns still use the existing consent/opt-out gates.

## Open — needs a decision from you

None for this approved implementation.

## Needs a lawyer

- Before launch, define lesson retention, customer/operator deletion propagation, and privacy-notice wording for reusable AI guidance.
- If EU/UK leads can use the form, confirm AI transparency, lawful basis, rights, retention, and LLM/SMS processor terms.

## Re-verify before relying (date-sensitive)

- US/EU/UK AI transparency, privacy, automated-decision, SMS, and accessibility requirements in each served jurisdiction.
- OpenAI/Telnyx data-processing, retention, and model-training terms for the production account/API mode.
- Verified: source, tests, disposable Postgres migration cycle, running Teach AI endpoint, ciphertext, and tool gates. Not verified: a real Telnyx send or Cal.com/Zoom invite; production credentials and spend were deliberately not used.
