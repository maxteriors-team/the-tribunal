# Compliance Register

Snapshot: 13 August 2026 · Reviewed by: EZ Coder compliance-guard · NOT LEGAL ADVICE

Commit reviewed: working tree on current `HEAD` (uncommitted approved implementation).

Scope: AI lead capture → consent-gated SMS → evidence-backed qualification → CRM phone/video booking → terminal acquisition cleanup, plus the existing focused AI/post-install review. This is engineering guidance and a focused feature review, not a certification or full-product audit.

## Assumed exposure profile

- **Reach — Confirmed:** deployed CRM with authenticated staff UI and public website lead forms.
- **Jurisdictions — Assumed:** worldwide reach; US plus EU/UK exposure may apply.
- **Personal data — Confirmed:** SMS bodies, phone numbers, form answers, AI replies, and operator notes.
- **AI decisions — Confirmed:** ordinary sales prequalification; no employment, lending, housing, health, or legal eligibility decision.
- **Messaging — Confirmed:** public form SMS consent is optional and unchecked; all acquisition SMS requires explicit `opted_in` state and passes through the global STOP/opt-out gate.
- **Minors — Assumed possible, not age-gated:** public home-services form is not child-directed but has no technical age gate.
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
| U1 | Privacy notice / deletion / vendor list | fail | CODE/DEDUCED: public form links notices, but AI qualification evidence/score retention and processor wording were not reviewed. |
| U2 | Third-party scripts consent | fail | CODE: form fires a Meta Pixel `Lead` event after submission whenever the host page loaded `fbq`; host-site prior-consent gating is outside this snippet. |
| U3 | Account security baseline | pass | Focused authorization and isolation tests passed; product-wide auth was not re-audited. |
| U4 | Public-page accessibility | pass | CODE: native labelled controls, optional checkbox, status region, visible privacy/terms links, keyboard-operable submit. |
| U5 | SMS duties | pass | CODE/tests: every funnel SMS uses unified delivery, explicit `opted_in`, stable idempotency, bounded waits, STOP/global opt-out, and no-automation suppression; blocked sends do not advance CRM status. |
| U6 | Contact form privacy | pass | CODE: optional unchecked box submits structured `sms_consent` only from its actual checked state; disclosure includes frequency, rates, STOP/HELP, privacy and terms. |
| U7 | Error/log handling | pass | CODE/tests: qualification logs carry IDs/counts/scores, not customer evidence/body text. |
| U8 | Personal-liability/entity review | n-a | Exact contracting entity was outside this pass. |
| A1 | Image alternatives | n-a | No image added to the public form or narrow operator extensions. |
| A2 | Form labels | pass | CODE: every public input is nested in a label; the optional SMS checkbox has adjacent disclosure. |
| A3 | Keyboard operability | pass | CODE: native form controls, links, buttons, dialog and operator links. |
| A4 | Colour contrast | pass | CODE: literal public-form foreground/background pairs are dark text on white/light surfaces; status red/green retain text labels, not colour-only meaning. |
| A5 | Focus visibility | pass | Native browser controls on the public snippet and existing design-system focus treatment in CRM. |
| A6 | Media controls/captions | n-a | No media. |
| A7 | Page language | fail | DEDUCED: standalone snippet cannot set the WordPress document's `lang`; host page must retain `lang="en"`. |
| D1-US | Automated qualification notice/fairness | pass | CODE: ordinary sales qualification is evidence-backed, human-correctable and handoff-capable; no regulated eligibility domain. |
| D1-EU/UK | AI transparency and privacy | fail | DEDUCED: AI scores public leads; deployed disclosure, lawful basis, retention, rights, and processor wording were not reviewed. |
| M1 | Minors | fail | CODE: public form has no age gate; product is not child-directed, but under-18 submission remains technically possible. |

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
| MSG-001 | BLOCKER | Acquisition funnel sends automated SMS | CODE/tests: every SMS sets `require_consent=true`, public form submits explicit checked state, blocked sends do not set `contacted`, STOP/global opt-out and `no-automation` stay enforced | Never text an opted-out or unconsented contact | Fixed | Delivery, worker, form, and provisioning tests |
| MSG-002 | HIGH | First outreach and delayed nurture could duplicate or continue after booking | CODE/tests: source is forced to `collect`, source-scoped `lead_created` stays new-contact-only, acquisition `funnel_id` runs are cancelled and resume/pre-send guarded | One owner for first SMS; stop acquisition nurture at booking | Fixed | Worker resume/event and script-graph tests |
| MSG-003 | HIGH | AI could claim a booking/Meet URL that Google never created | CODE/tests: booking requires explicit phone/video choice; CRM appointment stays authoritative; Meet URL is persisted only from provider response; failed video copy promises follow-up | Never fabricate a conference link or call a pending action booked | Fixed | AI tool/finalizer/copy tests |
| FORM-001 | HIGH | Optional checkbox previously recorded consent only in free-form notes | CODE: `sms_consent` now equals the checkbox's actual checked state and remains optional/unchecked | Store structured affirmative consent; never infer it from form submission | Fixed | Source fixture and lead-form tests |
| TRACK-001 | HIGH | Meta Pixel may receive a post-submit Lead event | CODE: snippet calls `fbq` if the host loaded it; consent-manager behavior is outside this repository | Gate advertising scripts/events behind prior consent where required and honor opt-out signals | Open operational | Host WordPress consent-manager runtime test |
| A11Y-001 | MEDIUM | WordPress host controls page language | DEDUCED: snippet cannot set document `lang` | Keep host page language declared | Open operational | Host-page accessibility check |
| MINOR-001 | MEDIUM | Public form has no technical age gate | CODE | Confirm business policy for under-18 inquiries; add an age gate if minors are not accepted | Open operational | Product/legal decision |

## Implemented in this pass

- Qualification requires configured questions, score threshold, evidence, and auto-approved booking; one deduped opportunity opens only after qualification.
- Phone/video choice is required. Phone copy names the lead's phone; video copy shows Google Meet only from Google's returned URL and exposes sync failure.
- First outreach is owned by the source-scoped `lead_created` automation; the source action is `collect`, returning contacts do not restart it, and every SMS requires explicit consent.
- Successful booking marks the contact/opportunity scheduled, emits a canonical event, cancels only that funnel's active runs, and guards parked/pre-send execution.
- The public WordPress checkbox is optional and unchecked; its actual checked state is sent as structured `sms_consent` beside frequency, rates, STOP/HELP, privacy, and terms disclosure.
- Existing quiet hours, rate limits, origin allowlists, honeypot, global opt-out, and `no-automation` controls were not weakened.
- Existing encrypted reusable AI lessons and post-install messaging controls remain as documented in their stable findings above.

## Open — needs a decision from you

- Confirm the host WordPress consent manager prevents Meta Pixel loading/firing before advertising consent where required.
- Decide whether under-18 homeowners may submit inquiries; add an age gate if not.

## Needs a lawyer

- Review the public SMS disclosure, privacy policy, terms, AI qualification disclosure, consent records, retention/deletion, and served jurisdictions before relying on this register.
- If EU/UK leads can submit, confirm AI transparency, lawful basis, rights, retention, and LLM/SMS processor terms.

## Re-verify before relying (date-sensitive)

- US/EU/UK AI transparency, privacy, automated-decision, SMS/telemarketing, minors, advertising tracking, and accessibility requirements in each served jurisdiction.
- OpenAI/Telnyx/Google/Meta data-processing, retention, consent-mode, and model-training terms for production accounts.
- Verified in this pass: 111 focused funnel tests, full backend CI (4,355 passed), full frontend lint/type/unit/build CI (140 test files), stable codegen, reversible migration CI, readiness endpoint, and live public lead submissions with consent on/off. External Telnyx, Google OAuth, production WordPress consent-manager, and production sends remain operational prerequisites.
