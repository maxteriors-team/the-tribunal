# SaaS Subscription and Buyer Handoff Audit

- **Snapshot:** 2026-08-19
- **Reviewed by:** EZ Coder compliance-guard
- **Source snapshot:** `release/crm-operations-20260819` at `b32376066eb64feac05add9c9359db86fea868f6`, 7 commits ahead and 10 behind `origin/main`, plus a pre-existing dirty working tree that changed during review
- **Production observed:** backend `a805fa50ca2c391c65d8bee21b7a5cbccf2b2892`
- **Status:** **NOT READY for public self-service or a clean buyer handoff**
- **Legal note:** **NOT LEGAL ADVICE.** This is an engineering and business-risk register, not a certification that the product is lawful, secure, accessible, or compliant.

## Executive decision

The Tribunal is a substantial, working vertical CRM, but the current product is still an **owner-operated internal system**, not a transfer-ready subscription business.

The safest commercialization path is:

> **Invite-only, US B2B, one paid plan, customer-owned provider billing, and no built-in collection of the subscriber's customer payments until Stripe Connect or another approved marketplace-payments structure is live.**

Do **not** open public self-service yet. A newly registered owner can reach provider-backed features without a paid entitlement, the SaaS subscription lifecycle does not gate product access, and tenant invoice proceeds currently enter the platform's single Stripe account.

A buyer today would mainly be buying **code and operating risk**. After 3–5 paying design partners, measured gross margin, documented retention, a tested handoff, and the blockers below, the asset can credibly be sold as a subscription business.

## Recommended commercial shape

| Decision | Recommended default | Why |
|---|---|---|
| Initial customer | US home-service operators reactivating existing leads | Matches onboarding, campaign, appointment, and CRM strengths without selling every Jobber-replacement module at once. |
| Sales motion | Invite-only, sales-led onboarding | Prevents anonymous provider spend and lets one operator verify consent, sender registration, and integrations before activation. |
| Offer | One founding plan at **$497/workspace/month**, then validate with paid pilots | The repository's strategy already anchors around a roughly $500 DIY + AI tier; the current `$297` page is not tied to actual cost or entitlements. |
| Usage | Implement subscriber-owned Telnyx/OpenAI/Resend billing before pilot activation | Makes gross margin legible and removes open-ended AI/telephony liability. Workspace-scoped Resend and fully consistent Telnyx credentials are not implemented yet; never market these services as unlimited. |
| Customer payments | Disabled initially; add Stripe Connect before tenants collect through the CRM | The current global Stripe account is suitable for one merchant, not unrelated subscriber merchants. |

The initial sellable surface should be **contacts + shared inbox + compliant reactivation + appointments + simple pipeline/reporting**. Hide—not delete—the wider field-service, inventory, sales-wizard, scraping, and experimental modules until a paying customer needs them.

## What is already strong

| Area | Evidence | Readiness |
|---|---|---|
| Multi-tenancy | Workspace-scoped models, permission dependencies, cross-workspace tests, encrypted contact identifiers, and audit logging are present. | **AMBER/GREEN** — good foundation; not a penetration-test result. |
| Delivery controls | Central outbound compliance checks, SMS consent state, STOP suppression, quiet hours, email unsubscribe plumbing, webhook verification, and idempotency exist. | **AMBER** — SMS is materially stronger than voice-marketing enforcement. |
| Engineering controls | Lockfiles, backend/frontend CI, migration reversibility, CodeQL, secret scanning, smoke targets, health checks, and deployment SHA reporting exist. | **GREEN** for an early product. |
| Operational visibility | Sentry hooks, telemetry, request IDs, worker heartbeats, `/readyz`, and `/version` exist. | **AMBER** — alert ownership and incident response are not transfer-ready. |
| Product breadth | 79 frontend pages, roughly 583 API route decorators, 87 model files, 168 migrations, and 34 in-process worker specs. | **AMBER/RED** — capability is high, but buyer maintenance and release risk are also high. |

## Readiness scorecard

| Area | Result | Buyer interpretation |
|---|---|---|
| Subscription billing and entitlements | **RED** | Payment does not control access; lifecycle handling is incomplete. |
| Provider spend and unit economics | **RED** | Anonymous paid-workload abuse and margin cannot be bounded. |
| Tenant customer-payment flow | **RED** | Current architecture cannot be sold as a multi-merchant collection feature. |
| Legal/privacy/messaging package | **RED** | Core policies, contracts, disclosures, retention, and rights workflows are absent or unverified. |
| IP and account transferability | **RED** | Ownership names and vendor/account control are not aligned for diligence. |
| Functional quality | **AMBER/GREEN** | The current QA register has 18 remediated/fixed items, 1 in progress, 1 closed, and 7 medium/low items not started; live provider delivery remains unverified. |
| Security engineering | **AMBER** | Strong controls exist; PII logging, uploads, auth maturity, and spend abuse remain. |
| Operations and disaster recovery | **AMBER/RED** | Deployment tooling is good; source runbooks conflict and no restore drill is documented. |
| Scalability | **AMBER/RED** | One API process owns 34 poll loops; horizontal scaling duplicates work. |
| Sales evidence | **RED / NOT IN REPO** | No customer contracts, MRR cohorts, churn, gross margin, or support evidence was available to audit. |

## Ranked findings

Evidence labels mean: **RUNTIME** was executed and observed; **CODE** was read; **DEDUCED** follows from absence or combined product facts.

| ID | Severity | Cause and evidence | What can actually happen | Fix and rough effort | If ignored |
|---|---|---|---|---|---|
| PAY-US-001 | **ILLEGAL** *(conditional)* | **CODE:** invoice and in-call Checkout sessions use the one global `settings.stripe_secret_key` without a connected-account or destination charge (`backend/app/services/invoices/invoice_service.py:862-881`, `backend/app/services/payments/call_payment_service.py:117-138`). | If independent subscribers collect their customers' money into the operator's account and the operator remits it, the product enters a payments/money-transmission question; if it is not remitted, funds are simply going to the wrong merchant. | Disable this feature for subscriber workspaces now. Use Stripe Connect or a merchant-of-record/payment-facilitator arrangement approved by Stripe and US payments counsel; expect a multi-week product and onboarding change. | Do not sell this feature. Operating an unauthorized funds-flow is not a normal backlog item. |
| PAY-EU-001 | **ILLEGAL** *(conditional)* | **DEDUCED:** the CODE-confirmed global funds-flow is reachable without a country restriction. | EU/UK merchant funds could create payment-services authorization, safeguarding, tax, and consumer-remedy exposure in addition to routing proceeds incorrectly. | Keep EU/UK merchant collection off. Get EU/UK payments counsel and implement an approved connected-account model before enabling it. | Worldwide availability does not make the US-only payment design portable. |
| BILL-001 | **BLOCKER** | **CODE:** `/billing/create-checkout-session` accepts a caller-controlled `price_id`; `STRIPE_PRICE_ID` is only a fallback (`backend/app/api/v1/billing.py:165-178`). `subscribed` is returned by billing status but is not referenced by product authorization anywhere else. | A user can register and use the CRM without paying; a crafted request can select another active Stripe Price from the platform account; `past_due`, failed payment, plan changes, refunds, pauses, and entitlements do not gate access. | Create a local subscription/entitlement record, allowlist server-owned plans, process the complete Stripe lifecycle, and enforce one server-side `require_entitlement()` dependency before paid/provider-backed actions. Roughly 1–2 focused engineering weeks plus Stripe test-clock coverage. | There is no enforceable subscription business, only an optional checkout page. |
| COST-001 | **BLOCKER** | **CODE:** public registration creates an owner workspace; onboarding buys a Telnyx number using the platform key (`workspace_setup.py:163-200`, `286-340`); owners can also call `/phone-numbers/purchase` (`phone_numbers.py:241-273`); OpenAI workspace resolution falls back to the global key (`openai_credentials.py:121-181`). There is no paid entitlement, usage quota, or spend ledger. | Anyone can create accounts and trigger phone-number, AI, SMS, voice, scraping, or geocoder costs on the seller's accounts. A card is not required before cost begins. | Immediately make registration invite-only or gate onboarding. Then require active payment, set per-workspace quotas/kill switches, and prefer buyer/customer-owned provider credentials. Roughly 2–5 days for containment; 2–4 weeks for complete metering. | One abusive account can create direct vendor charges and messaging liability. |
| AI-VENDOR-001 | **BLOCKER** | **CODE:** the UI offers a “ChatGPT subscription for OpenAI Realtime” (`frontend/src/components/settings/openai-chatgpt-card.tsx:224-281`); backend code impersonates the Codex client identity and sends `ChatGPT-Account-ID` headers (`openai_credentials.py:28-70`, `184-198`). **Official source:** OpenAI says ChatGPT and API billing are separate. | A core AI path relies on a consumer subscription/auth flow that is not documented as a supported third-party SaaS integration. It can break, be revoked, or create account/contract risk after sale. | Remove ChatGPT/Codex OAuth from the product. Use supported OpenAI Platform API projects/keys with workspace-owned billing, or a platform key with explicit metering. Roughly 2–5 days plus migration and customer communication. | The buyer inherits a brittle, unsupported dependency for the product's headline feature. |
| MSG-US-001 | **BLOCKER** | **CODE:** voice campaigns use an artificial voice, but contacts have SMS consent—not a source-enforced voice-consent/DNC record—and the compliance service's voice path checks quiet hours/global opt-out rather than proof of consent. The prompt tells the agent to sound human and gives no mandatory AI identity (`prompt_builder.py:114-126`). | A subscriber can place AI telemarketing calls without provable permission or National/State Do Not Call screening. Artificial/prerecorded voice rules create realistic complaint and private-action exposure. | Before any outbound AI call, enforce purpose-specific consent evidence, DNC scrubbing, caller identity, AI/artificial-voice disclosure, local-time rules, and an auditable suppression gate. Get telecom counsel to approve the script and campaign policy. | A customer complaint lands on both the subscriber and platform operator; logs currently may preserve the damaging evidence. |
| MSG-EU-001 | **BLOCKER** | **DEDUCED:** source inspection found no geographic restriction, jurisdictional consent policy, or EU/UK marketing-call gate. | EU ePrivacy and UK PECR rules can require prior consent and add caller-identification/opt-out duties beyond the US controls. | Keep EU/UK outbound marketing disabled until counsel defines country rules and code enforces them per recipient. | A generic “worldwide” launch silently expands the legal perimeter. |
| IP-001 | **BLOCKER** | **CODE:** the proprietary `LICENSE` grants rights from **Gahroot**, the repository is under `maxteriors-team`, CODEOWNERS names only `@Gahroot`, product branding says Maxteriors, and the requested sale entity is unconfirmed. | A buyer cannot prove clean title to the code, brand, customer data, domains, or vendor accounts. This commonly stops diligence even when the software works. | Assemble signed IP assignments from every contributor/contractor, identify the selling entity, align the license/copyright owner, and produce an asset schedule. Lawyer + owner task; usually days if records are clean, much longer if not. | The deal is priced as risky assets or fails title diligence. |
| PRICE-001 | **BLOCKER** | **CODE:** billing advertises `$297/month`, “unlimited lead uploads,” “no usage limitations,” and “Enterprise-grade encryption” (`frontend/src/app/billing/page.tsx:149-216`), while strategy docs propose several incompatible models and provider costs are only estimates. There is no actual usage ledger or COGS allocation. | Heavy AI/voice/scraping use can make gross margin negative; buyers cannot underwrite revenue quality. | Replace “unlimited” with explicit fair-use/quotas, choose one plan, record actual provider usage by workspace, and publish a contribution-margin report before adding tiers. Roughly 1–3 weeks after billing foundations. | Revenue can grow while cash margin gets worse. |
| BRAND-001 | **HIGH** | **CODE:** current uncommitted frontend work centralizes the app name as “The Tribunal,” but backend sender defaults and multiple customer-facing templates still hard-code “Maxteriors” (`backend/app/core/config.py:163`, `backend/app/services/email.py:63-1082`, `backend/app/services/email_layout.py:80`). | Subscriber customers can receive another contractor's brand, and the partial fix is not yet in a clean release. | Finish one platform-brand configuration, enforce workspace business branding in all customer-facing copy, and add a grep/test guard against seller-specific names. Roughly 2–5 days. | White-label trust breaks and the buyer inherits someone else's identity in customer messages. |
| PRIV-001 | **HIGH** | **DEDUCED:** no public privacy route or policy artifact exists; registration and lead-capture surfaces collect personal data. | Users and lead subjects are not told who collects data, why, which vendors receive it, how long it is kept, or how to exercise rights. | Publish a lawyer-reviewed privacy notice with the real entity, contacts, purposes, data classes, vendors, retention, rights, transfers, and jurisdiction scope. Template work is days; legal facts and review are owner/counsel tasks. | This is an easy-to-detect launch defect and blocks serious customer procurement. |
| PRIV-002 | **HIGH** | **CODE:** workspace “delete” only sets `is_active=False` (`workspaces.py:198-257`), and repository search found no workspace/account export or verified purge workflow. | Departing customers cannot port or erase their CRM data; deleted workspaces retain contacts, recordings/transcripts, messages, files, and integration data indefinitely. | Build tenant export, staged cancellation, hard-delete/purge with legal holds, backup propagation policy, and completion evidence. Roughly 2–4 weeks because cascades and vendors must be tested. | Churn becomes operationally dangerous and privacy requests require ad hoc database work. |
| PRIV-003 | **HIGH** | **DEDUCED:** no maintained subprocessor inventory or data-processing agreement is in the repository. Code integrates OpenAI, Telnyx, Resend, Stripe, Google, Meta, Cal.com, Sentry, Apify/scraping services, and a custom telemetry endpoint. | Subscriber procurement stalls; nobody can answer where lead, call, transcript, and payment metadata go or which contracts survive a sale. | Create a subprocessor register, execute processor agreements/data-processing addenda, document regions/retention, and make change notice part of customer terms. Owner + counsel, roughly 1–3 weeks depending on accounts. | A buyer accepts unknown vendor and international-transfer liabilities. |
| PRIV-004 | **HIGH** | **DEDUCED:** no approved retention schedule or automatic purge jobs cover contacts, messages, transcripts, recordings, attachments, audit logs, or backups. | Personal data accumulates forever, increasing breach impact and deletion cost. | Approve a record-class schedule, implement deletion jobs and holds, and test vendor/backup propagation. Roughly 1–3 engineering weeks after legal decisions. | Storage and incident liability compound every month. |
| PRIV-005 | **HIGH** | **CODE:** full user/agent speech is logged as `user_said`/`agent_said` (`voice_agent_base.py:148-155`, `225-231`); redaction keys do not include these names or `to_email` (`core/logging.py:14-102`). | CRM conversations, customer details, and recipient addresses can enter Railway/Sentry log retention and be visible to support operators or transferred in a sale. | Stop logging content, expand structural redaction, set retention, and add a test that representative PII never reaches a log sink. Roughly 1–3 days. | A routine support export can become a reportable data incident. |
| SEC-001 | **HIGH** | **CODE:** `EZPixelClient` initializes on every route and sends browser error telemetry to `https://prestyj-ez-pixel.ngrout70.workers.dev`; Sentry also initializes globally. No notice, processor record, buyer-owned account, or consent/legitimate-interest decision is source-enforced. | Errors and stacks may contain URLs or CRM/customer context and continue flowing to a hardcoded external endpoint after handoff. | Remove EZ Pixel for production or transfer it to a buyer-owned contracted service; minimize payloads, document Sentry, and gate non-essential telemetry as counsel directs. Roughly 1 day for removal, longer for governance. | The buyer receives a product that still phones home to an account it may not control. |
| AUTH-001 | **HIGH** | **CODE:** registration returns “Email already registered,” public accounts are not email-verified, and no MFA is offered for owners handling PII and telephony spend (`auth.py:113-139`). Rate limits, strong password hashing, secure cookies, CSRF protection, and password reset do exist. | Attackers can enumerate operator accounts; mistyped/fake emails create active workspaces; a single password compromise reaches customer data and provider-backed actions. | Make registration non-enumerating, verify email before activation/spend, and require MFA for owners/admins. Roughly 1–2 weeks. | Account takeover and spend abuse remain much easier than a buyer will accept. |
| SEC-002 | **HIGH** | **CODE:** contact attachments have a 10 MB limit, but trust the client MIME type/filename and perform no content-signature validation or malware scan (`contact_attachments.py:81-154`). | A tenant can store and distribute malicious or mislabeled files to staff. | Verify magic bytes, force safe download handling for risky types, scan uploads, quarantine failures, and test tenant authorization. Roughly 3–7 days. | The CRM becomes a malware delivery path inside subscriber teams. |
| OPS-001 | **HIGH** | **DEDUCED:** encrypted backup commands exist in source, but no automated offsite schedule, recovery-point/recovery-time objective, or completed restore-drill evidence is documented. | A database, key, or operator failure can cause unrecoverable customer loss; backup success can be assumed without proof. | Configure automated encrypted backups/PITR, escrow both encryption keys, perform a restore into an isolated environment, and record duration/evidence. Owner + operator, roughly 1–2 days once access is available. | A buyer cannot accept operational custody of production data. |
| OPS-002 | **MEDIUM** | **DEDUCED:** health, Sentry, telemetry, and heartbeats exist in source, but alert destinations, on-call owner, incident severity, and customer notification procedure are not documented. | Failures may be observable but nobody is accountable for reacting. | Assign alert owners, add an incident runbook, and run one tabletop. Roughly 1–2 days. | Monitoring becomes an expensive log archive rather than an operating control. |
| OPS-003 | **HIGH** | **CODE:** `docs/RUNBOOK-go-live.md` says direct-push `main`, assumes auto backend deploy, uses a plaintext `.dump`, and describes PostgreSQL 17; current deployment rules require PRs, manual backend upload from merged `main`, encrypted `.dump.enc`, and a PostgreSQL 18 prod client. The audited release branch is also 7 commits ahead and 10 behind `origin/main`. | A new operator can deploy the wrong tree, lose divergent work, fail to deploy, or create an unencrypted production-data dump. | Reconcile the branch without discarding dirty work, then replace the stale migration-specific runbook with one canonical buyer operations manual and test every command from a clean clone. Roughly 2–4 days after the branch is safe. | The handoff document and divergent branch actively increase outage, lost-work, and data-loss risk. |
| PRODUCT-001 | **MEDIUM** | **CODE:** the updated `docs/crm-functional-qa-audit-2026-08-18.md` records 18 remediated/fixed items, 1 in progress, 1 closed, and 7 medium/low findings not started. It reports that live Telnyx/OpenAI/Google/Cal.com/Resend delivery was unavailable. | The product is much closer to a pilot, but a buyer still inherits integration support ambiguity and unverified real-provider paths. | Finish QA-018 through QA-027's open items, then run a paid-pilot release against test/sandbox provider accounts and one consented end-to-end delivery path. Roughly 1–2 focused weeks plus provider setup. | Configuration failures and live-provider surprises become first-customer support incidents. |
| A11Y-001 | **HIGH** | **CODE:** several sales-wizard inputs remove the native outline (`frontend/src/components/sales-wizard/theme.css:244-363`) while `step-val` and related controls have no replacement focus rule; automated scans do not prove full keyboard visibility. | Keyboard users can lose track of focus in a core selling workflow. Accessibility demand letters often target source-visible defects like this. | Add a visible `:focus-visible` treatment and keyboard regression test to every affected control. Roughly 1 day. | The defect remains easy to demonstrate even if most axe checks pass. |
| A11Y-002 | **MEDIUM** | **CODE:** call recordings render with native audio controls while a transcript is conditional (`calls-list.tsx:517-545` and other audio surfaces). | A prerecorded call can be available without an equivalent transcript for a deaf user. | Guarantee a transcript or provide an adjacent accessible text alternative/status for every recording. Roughly 2–5 days plus transcription-failure handling. | Some call records remain unusable to disabled staff. |
| CLAIM-001 | **MEDIUM** | **CODE:** billing markets “Enterprise-grade encryption” while controls are mixed: selected fields and secrets are encrypted, but transcripts, notes, and logs are not uniformly protected. | Procurement may read the phrase as a broad, audited assurance the evidence cannot support. | Replace the claim with precise, verifiable controls and maintain a security overview. Roughly hours plus owner review. | The sales page creates avoidable misrepresentation risk. |
| SUPPORT-001 | **HIGH** | **DEDUCED:** no platform-admin/support console, audited support-access workflow, tenant usage view, subscription override, or customer export tool was found. | The operator must use Stripe/vendor dashboards or production SQL for routine support and offboarding. | Build the smallest audited operator console: tenant status, entitlement, usage, integration health, export/purge state, and no silent impersonation. Roughly 2–4 weeks. | Every support case becomes a privileged production operation. |
| SCALE-001 | **HIGH** | **RUNTIME:** production `/readyz` reported all 34 workers healthy; source inspection shows the deployed API process owns those poll loops. | More uvicorn workers or backend replicas duplicate schedulers and sends; one busy worker set competes with request handling. | Keep one replica during pilots, then extract workers or add leader election before horizontal scaling. Roughly 2–6 weeks depending on queue design. | Scaling the API can duplicate calls, messages, jobs, and provider cost. |
| LEG-001 | **HIGH** | **DEDUCED:** repository search found no public service-identity/contact page, while source and ownership artifacts use conflicting brand/entity names. | Customers cannot tell who contracts with them or where legal/privacy requests go. | Publish the real entity name, business address, support/legal/privacy contacts, and jurisdiction in the footer and contracts. Owner/counsel task, roughly 1 day after facts are known. | Contracts and notices may be unenforceable or misleading. |
| LEG-002 | **HIGH** | **DEDUCED:** no acceptable-use/messaging policy is bound to signup or campaign activation. | Subscribers can use scraping, AI voice, SMS, email, and payment tools in prohibited or unlawful ways while the operator has no contractual suspension standard. | Add an acceptable-use and messaging policy, require acceptance with version/timestamp, and enforce suspension/kill switches. Roughly 2–5 days plus counsel. | The operator owns the vendor complaints without a clear right to stop the customer. |
| MIN-001 | **HIGH** | **CODE:** public registration and lead forms have no technical age gate; intended B2B use is not source-enforced. | A minor can create an account or submit personal data, expanding contract-capacity and children's-data obligations. | Enforce 18+ business-purpose signup and state the audience clearly; avoid collecting children's data. Roughly 1 day plus terms review. | “Not intended for minors” in a future policy alone will not prevent collection. |
| CONTRACT-US-001 | **HIGH** | **CODE:** checkout has no bound Terms acceptance, renewal disclosure evidence, cancellation/refund policy, tax treatment, or contracting entity. | If individuals can subscribe, auto-renew and deceptive-practice claims become plausible; even B2B buyers lack a usable contract. | Restrict to verified businesses, present price/renewal/cancellation before payment, record acceptance/version, and have US SaaS terms/order form reviewed. Roughly 1–2 weeks with counsel. | Stripe can collect money while the operator cannot prove what the customer agreed to. |
| CONTRACT-EU-001 | **HIGH** | **DEDUCED:** worldwide reach has no EU/UK pre-contract information, withdrawal flow/waiver, VAT treatment, or unfair-terms review. | An EU/UK consumer or sole trader can reach checkout without required information or cancellation rights. | Geo-restrict launch to US B2B, or add jurisdiction-specific checkout, VAT, withdrawal, and privacy terms with counsel. | “B2B product” does not prevent a consumer from using an open checkout. |
| TAX-001 | **LAWYER** | **CODE:** Checkout does not collect enough tax/business-location evidence or enable a documented SaaS sales-tax/VAT process. | The seller may collect the wrong amount or fail registrations/returns as nexus grows. | Accountant/tax counsel must define US nexus and any VAT/OSS position; then configure Stripe Tax/address/tax-ID collection accordingly. | Tax liabilities do not disappear when billing itself works. |
| LIC-001 | **BACKLOG** | **CODE:** CI has no dependency-license or software-bill-of-materials (SBOM) gate. | A buyer must reconstruct third-party notices and distribution obligations during diligence. | Generate an SBOM and notices file; fail CI on unknown/prohibited licenses. Roughly 1–2 days. | Diligence takes longer and avoidable license questions reach lawyers. |
| DATA-001 | **HIGH** | **CODE:** lead discovery can use Google/Meta ad sources, website/people scraping, contact tracing, and inferred email patterns; raw Meta self-scraping is default-off but can be operator-enabled (`backend/app/services/ad_intelligence/compliance.py:33-65`, `backend/app/workers/prospect_enrichment_worker.py`). | “Public” business data can still violate source terms, privacy expectations, or country-specific direct-marketing rules; inferred addresses can target the wrong person and vendor accounts can be banned. | Allow only official/licensed providers in production, keep source/provenance and verification, honor suppression/access/deletion, prohibit auto-enrollment, and apply recipient-country outreach rules. Counsel/vendor review plus roughly 3–7 engineering days. | The buyer inherits data it may not be allowed to use and no reliable answer to “where did you get me?” |
| METRICS-001 | **HIGH** | **DEDUCED:** no evidence was supplied for paid customers, MRR, churn, cohorts, refunds, chargebacks, support load, or workspace-level gross margin. | The asset cannot be priced as a proven subscription business from code quality alone. | Build a buyer data room with bank/Stripe evidence, contracts, monthly cohorts, actual vendor COGS, support volume, incidents, and pipeline. Owner/accounting task. | Buyers discount the deal to replacement cost or an earn-out. |

## Mandatory compliance coverage ledger

Every `fail` row maps to its own finding above. `pass` means the named source/runtime evidence was observed; it is not a certification.

### Security pre-deploy baseline

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| 1 | No committed secrets; ignore rules cover secret/generated files | pass | **CODE/prior RUNTIME:** root ignore rules cover env/backups/keys/artifacts; gitleaks is a required workflow and the 2026-08-19 release register records a clean full-history scan. This pass was not freshly rerun against the dirty tree. |
| 2 | Database row-level security for client-accessible tables | n-a | The browser has no direct database SDK; all data access goes through FastAPI. Server-side tenant scope is covered under item 4. |
| 3 | Auth brute-force, enumeration, reset, and MFA posture | fail | Rate limiting/password reset are present, but registration enumerates emails and creates active unverified owners; no MFA. `AUTH-001`. |
| 4 | Server-side authorization and tenant isolation | pass | Permission dependencies, workspace-scoped queries, encrypted lookup hashes, and cross-workspace tests are present. |
| 4b | Production fails closed; exact CORS/proxy trust | pass | Startup validates production URLs/secrets, CORS uses configured origins, and Railway proxy trust is constrained. |
| 5 | Webhook signature verification and replay/idempotency | pass | Stripe, Telnyx, and Resend verification/idempotency paths and tests exist. Billing subscription *business logic* still fails under `BILL-001`. |
| 6 | Upload size/type/name/malware controls | fail | Attachment size is capped, but MIME/signature scanning and malware quarantine are absent. `SEC-002`. |
| 7 | Private storage and unguessable access | pass | Contact attachments are workspace-authorized DB blobs with private caching; public static storage is documented for marketing assets only. |
| 8 | Payment data handled by hosted provider | pass | Stripe Checkout is used and no raw card data is stored. Multi-merchant funds-flow is separately failed under `PAY-US-001`/`PAY-EU-001`. |
| 9 | Rate limits and spend caps on expensive endpoints | fail | Public signup reaches platform Telnyx/OpenAI-backed actions without subscription, quota, or spend ledger. `COST-001`. |
| 10 | SSRF-safe outbound fetches | pass | URL validation/private-network defenses exist in scraping paths; prior security tests cover redirect revalidation. |
| 11 | Untrusted HTML sanitized | pass | React escaping and sanitizer/HTML-validation paths are present; no new unsanitized public sink was confirmed in this review. |
| 12 | Browser security headers/CSP | pass | CSP, frame, MIME, referrer, and permissions policies are configured; existing QA reported them. |
| 13 | Dependencies pinned and vulnerability-scanned | pass | Lockfiles are committed; recognized `make audit.security` exited 0 against the exported Python lock and frontend production dependencies. |
| 14 | Generic errors and safe structured logging | pass | API error envelopes and request IDs exist; content-level PII logging is a separate item 15 failure. |
| 15 | No PII/secrets in logs | fail | Full AI conversation turns and recipient identifiers use unredacted keys. `PRIV-005`. |
| 16 | Monitoring and alert ownership | fail | Monitoring exists, but alert/on-call/incident ownership is not documented. `OPS-002`. |
| 17 | Health checks, migration path, and rollback | pass | `/readyz`, `/version`, migration reversibility CI, smoke targets, and rollback commands exist, though the human runbook is stale under `OPS-003`. |
| 18 | Automated backup and verified restore | fail | Encrypted scripts exist, but no schedule/PITR objective or restore-drill evidence was found. `OPS-001`. |

### Universal legal/privacy baseline

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| U1 | Service identity and contact information | fail | Entity/brand/contact facts are absent or conflicting. `LEG-001`. |
| U2 | Privacy notice at collection surfaces | fail | No privacy route/policy was found. `PRIV-001`. |
| U3 | Access, correction, export, and deletion workflow | fail | Soft deactivation exists; complete export/purge does not. `PRIV-002`. |
| U4 | Security/privacy claims match evidence | fail | “Enterprise-grade encryption” is broader than the demonstrable controls. `CLAIM-001`. |
| U5 | Minors policy and technical gate | fail | Public signup/forms have no age gate. `MIN-001`. |
| U6 | Processor/subprocessor contracts | fail | Vendor inventory/contracts/regions/retention are not documented. `PRIV-003`. |
| U7 | Retention and deletion propagation | fail | No approved schedule or automated purge was found. `PRIV-004`. |
| U8 | Acceptable-use rules | fail | No bound acceptable-use/messaging contract exists. `LEG-002`. |

### Accessibility baseline

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| A1 | Image alternatives | pass | Prior QA ran axe over 23 desktop and 23 mobile CRM routes plus targeted surfaces with no scoped WCAG 2.2 A/AA violation; JSX linting is enabled. Coverage is not all 79 pages. |
| A2 | Form labels | pass | Prior route axe matrix and source spot checks found labelled controls on covered routes. |
| A3 | Keyboard operability | pass | Native/Radix controls and route keyboard checks cover representative paths; this is not a full manual assistive-technology audit. |
| A4 | Colour contrast | pass | Prior runtime axe checks compute rendered contrast and reported no serious/critical violation on covered routes. |
| A5 | Focus visibility | fail | Sales-wizard controls remove native outlines without complete replacement styles. `A11Y-001`. |
| A6 | Media controls and text alternatives | fail | Audio can render when transcript content is absent. `A11Y-002`. |
| A7 | Page language | pass | Root layout and live register HTML declare `lang="en"`. |

### Product-model obligations

| # | Checklist item | fail / pass / n-a | Evidence |
|---|---|---|---|
| C1-US | Consumer auto-renew/pre-contract duties | fail | Open checkout has no bound terms/renewal/cancellation evidence. `CONTRACT-US-001`. |
| C1-EU/UK | Consumer information/withdrawal/VAT duties | fail | No geo restriction or jurisdiction-specific checkout exists. `CONTRACT-EU-001`, `TAX-001`. |
| P1-US | Public user-content platform duties | n-a | CRM notes/files/messages are private business records; no public social/feed publishing feature was identified. |
| P1-EU/UK | DSA/Online Safety user-content duties | n-a | Same product-scope reason; reassess if public profiles, feeds, marketplaces, or shared media are added. |
| AI-US | Artificial-voice consent and disclosure | fail | No source-enforced voice consent/DNC/AI disclosure gate. `MSG-US-001`. |
| AI-EU/UK | Synthetic-media and direct-marketing disclosure | fail | No jurisdiction gate or required identity/disclosure. `MSG-EU-001`. |
| V-US | Value movement / merchant funds | fail | Global Stripe account receives tenant customer payments. `PAY-US-001`. |
| V-EU/UK | Payment-services / merchant funds | fail | Same flow is globally reachable. `PAY-EU-001`. |

## Product and operational observations

### Subscription implementation is a stub, not a control plane

Recognized `make ci.backend` passes 4,659 tests, but the only billing-named test file is `backend/tests/api/test_billing_webhook_route.py`; it covers invoice/in-call webhook behavior, not SaaS checkout, price allowlisting, subscription state, dunning, cancellation timing, or product entitlements. Stripe's current subscription guidance expects access decisions to follow subscription and invoice events; `checkout.session.completed` plus `customer.subscription.deleted` is not enough.

A minimum subscription control plane needs:

1. A server-owned plan catalog and local subscription state keyed to workspace.
2. Stripe webhook event storage with idempotent processing and reconciliation.
3. Entitlements enforced at API dependencies—not only hidden in the frontend.
4. Quotas, provider-cost ledger, grace period, suspension, and manual override audit.
5. Tests for active, trialing, past-due, unpaid, paused, canceled, refund, duplicate, and out-of-order events.

### Product scope is too broad for a first buyer

The codebase is roughly 418,000 tracked source lines across a field-service CRM, AI voice/SMS, lead generation/scraping, proposals, payments, inventory, automations, campaigns, onboarding, and public surfaces. That breadth can be valuable after product-market fit, but it creates a large support matrix before the first repeatable subscription offer exists.

The existing strategy documents also conflict with the live product: appointment packages, performance fees, `$500`, `$1,000`, `$2,000`, `$2,500`, and the current `$297` plan all appear. Pick one offer and archive the rest as experiments.

### Operations remain a single-person system

The repo has excellent local/release mechanics, but handoff knowledge lives partly in `CLAUDE.md`, while the human go-live runbook contradicts it. CODEOWNERS has one owner, service accounts are not inventoried, and no buyer can prove they control alerting, backups, DNS, encryption keys, or every provider from source alone.

## 90-day conversion plan

### Phase 1 — Contain risk (days 1–7)

1. Make signup invite-only; block number purchase, AI/voice/SMS, scraping, and onboarding provisioning without an active entitlement.
2. Disable tenant customer-payment Checkout; remove the unverified consumer OpenAI OAuth path and hardcoded external EZ Pixel.
3. Stop PII content logging; rotate/verify production secrets and assign incident/alert owners.
4. Lock the product to US businesses, age 18+, and one home-service use case.
5. Choose the one `$497/month + direct provider usage` pilot offer and remove “unlimited” claims.

**Exit evidence:** an unpaid test tenant cannot trigger one provider request; a paid test tenant can; no tenant-customer funds enter the platform Stripe account.

### Phase 2 — Build a real paid control plane (days 8–30)

1. Implement allowlisted plans, workspace subscriptions, full webhook reconciliation, entitlements, dunning/grace, quotas, and kill switches.
2. Use supported workspace-owned OpenAI/Telnyx/Resend accounts and show their health/cost to the operator.
3. Publish reviewed B2B Terms, Privacy Notice, data-processing terms, acceptable-use/messaging policy, and subprocessor list.
4. Fix the highest-risk QA, accessibility, upload, and branding findings; add owner MFA/email verification.
5. Automate backups, complete one restore drill, and replace the stale operations runbook.

**Exit evidence:** Stripe test clocks cover lifecycle states; P1 critical-funnel findings are zero; backup restoration, cancellation/export, and provider kill-switch drills pass.

### Phase 3 — Prove the business (days 31–75)

1. Onboard 3–5 paid design partners manually and record accepted terms/consent configuration.
2. Measure monthly revenue, provider COGS, gross margin, activation time, support hours, message/call usage, appointments, and churn intent by workspace.
3. Run weekly quote/campaign/appointment/inbox acceptance tests and close product friction before adding modules.
4. Collect truthful case studies only from measured customer results; no fabricated urgency, scarcity, or guarantees.
5. Decide whether connected payments are demanded; build Stripe Connect only if pilots will pay for it.

**Exit evidence:** at least two billing cycles, known contribution margin, documented support load, and references/case studies with written permission.

### Phase 4 — Prepare transfer (days 76–90)

1. Move domains, GitHub, Railway, Vercel, Stripe, Telnyx, Resend, Google, Meta, Cal.com, Sentry, OpenAI, and scraping accounts into the selling entity or a transfer schedule.
2. Resolve IP assignments, brand/trademark/domain rights, customer contract assignment, data-transfer notices, and vendor change-of-control terms.
3. Give the buyer a clean-clone deployment, backup restore, key-rotation, incident, billing, offboarding, and rollback rehearsal.
4. Operate together for two release cycles; the buyer leads the second while the seller observes.
5. Sign acceptance only after production version, alerts, backups, billing, provider spend, and customer support are buyer-controlled.

**Exit evidence:** no personal seller account is required for a deploy, incident, refund, data request, or customer cancellation.

## Buyer handoff package

| Package | Required contents | Current evidence |
|---|---|---|
| Corporate/IP | Selling entity, cap table, contributor IP assignments, proprietary license alignment, domains/trademarks, third-party notices | **Missing/unconfirmed**; ownership names conflict. |
| Customer/revenue | Executed assignable contracts, MRR cohorts, churn, accounts receivable, refunds/chargebacks, pipeline, case-study permissions | **Not supplied in repo**. |
| Financial/unit economics | Stripe/bank reconciliation, actual provider COGS by workspace, taxes, gross margin, liabilities, prepaid commitments | **Missing**; only estimates exist. |
| Data/legal | Privacy/Terms/DPA/AUP, subprocessor register, retention schedule, rights log, incidents, telecom consent evidence, insurance | **Mostly missing/unconfirmed**. |
| Technical/operations | Architecture, inventory, clean build, CI history, migrations, SBOM, backup/restore evidence, SLOs, on-call, support, vendor ownership | **Partial**; strong code controls but stale runbook and no transfer drill. |

### Account and secret transfer inventory

Do not send secrets in a document or chat. Transfer account ownership first, then rotate credentials in a planned window.

| System | Buyer must control | Rotation/transfer risk |
|---|---|---|
| GitHub / domains / DNS / support email | Organization owner, repo, branch rules, domains, recovery methods | Update CODEOWNERS, issue links, deploy integrations, and legal contacts together. |
| Railway / Postgres / Redis / Vercel | Billing owner, service owner, env vars, deploy hooks, logs, alerts | Backend deploy is manual; Vercel main deploy is automatic. Test from buyer identity. |
| Encryption and backups | `ENCRYPTION_KEY`, prior-key chain if used, backup key, restore artifacts | Losing keys makes encrypted rows/backups unrecoverable; rotate only with tested scripts and retained prior keys. |
| Stripe / Telnyx / Resend / OpenAI | Buyer-owned business accounts, webhook secrets, sender/phone registrations, billing methods | Do not transfer a personal ChatGPT session or keep merchants on the seller's payment account. |
| Google / Meta / Cal.com / Sentry / scrapers | OAuth apps, API projects, webhook URLs, processor terms, alert destinations | Revoking the seller too early can silently break lead capture, calendars, maps, and monitoring. |

## Verification performed

The first recognized frontend gate exposed four failing accessibility-label tests. `frontend/src/components/settings/upsell-ranks-settings-card.tsx` now gives each repeated field a unique accessible name (`Rank N name`, `Rank N target`, and `Rank N bonus`); its focused 8-test file passed, then the full frontend gate passed.

Each `make` verification below was rerun as its own top-level command against the current working tree; only exit-0 results are recorded.

| Check | Result | Evidence type |
|---|---|---|
| `make audit.security` | Exit 0; exported Python lock: `No known vulnerabilities found`; frontend production dependencies: `0 vulnerabilities` | **RUNTIME** |
| `make ci.backend` | Exit 0; lock/env, Ruff, format, mypy, import boundary, 4,659 tests passed, 21 skipped, 61.26% coverage | **RUNTIME** |
| `make ci.frontend` after label fix | Exit 0; dependency install/audit, env check, lint with 36 warnings and 0 errors, typecheck, 1,457 tests passed in 162 files, Next.js production build passed | **RUNTIME** |
| `make audit.handoff` | Exit 0; required sections, evidence labels, ledger mappings, Markdown tables, repository paths, register linkage, and whitespace validated | **RUNTIME** |
| Production backend `/version` | HTTP 200; SHA `a805fa50...`, an `origin/main` ancestor | **RUNTIME** |
| Production backend `/readyz` | HTTP 200; database, Redis, startup, and all 34 worker checks reported healthy | **RUNTIME** |
| Production frontend `/register` | HTTP 200; public registration page reachable, `lang="en"`, Maxteriors metadata present | **RUNTIME** |
| Existing functional audit document | Records 18 remediated/fixed, 1 in progress, 1 closed, 7 medium/low items not started, and prior route/axe results; those flows were not rerun here | **CODE** |

## Not verified

This audit did **not** use an authenticated production account, charge a card, buy/release a phone number, place a call, send SMS/email, inspect provider dashboards/contracts, inspect production customer rows, test restore from a real backup, run a fresh full-history secret scan, perform a penetration test, perform a complete manual screen-reader audit, or validate revenue/customer claims.

The working tree was already dirty and changed during this review; the branch was 7 commits ahead and 10 behind `origin/main`. This pass changed the audit/register, added a structural guard, and fixed unique labels in `UpsellRanksSettingsCard`; conclusions reflect files as last read, not a clean committed release. Production is on an older SHA than the audited working tree.

## Needs a lawyer or accountant

1. **Payments:** whether the intended tenant customer-payment flow requires Stripe Connect, payment-facilitator sponsorship, money-transmitter authorization, safeguarding, or another arrangement in each launch jurisdiction.
2. **Telemarketing:** AI/artificial-voice consent, National and state Do Not Call rules, call recording, scripts, lead-source evidence, quiet hours, and platform/customer allocation of responsibility.
3. **Contracts/data:** selling entity, B2B Terms/order form, privacy notice, data-processing terms, subprocessors, cross-border transfers, retention, assignment/change-of-control, and cyber insurance.
4. **Tax:** US SaaS sales-tax nexus and any VAT/OSS obligations, including what location/business evidence Checkout must collect.
5. **IP/transaction:** contributor assignments, brand/domain ownership, customer/vendor contract assignment, data-transfer notice, and deal structure.

## Date-sensitive official references

Verified 2026-08-19; re-check before implementation or signing:

- Stripe Connect overview: <https://docs.stripe.com/connect>
- Stripe subscription webhooks and access lifecycle: <https://docs.stripe.com/billing/subscriptions/webhooks>
- Stripe Checkout subscriptions: <https://docs.stripe.com/payments/checkout/build-subscriptions>
- OpenAI: ChatGPT and API billing are separate platforms: <https://help.openai.com/en/articles/9039756-managing-billing-settings-on-chatgpt-web-and-platform>
- OpenAI: a ChatGPT subscription cannot be transferred to API service: <https://help.openai.com/en/articles/8156019-i-want-to-move-my-chatgpt-subscription-to-the-api>
- FTC Telemarketing Sales Rule business guidance: <https://www.ftc.gov/business-guidance/resources/complying-telemarketing-sales-rule>
- FCC TCPA reference: <https://www.fcc.gov/sites/default/files/tcpa-rules.pdf>
