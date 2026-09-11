# CRM experience and reporting audit

**Audit date:** September 9, 2026, operator-local time. Some logs are September 10 UTC.

**Baseline:** current working tree on `main`, HEAD `b1755cb7`. Existing assistant, quote-tool, and navigation edits were included in the inventory and preserved. No application fixes, commits, deployments, production writes, real messages, calls, payment attempts, or paid AI requests were performed.

> **September 10 continuation, still incomplete:** [evidence, numerical reconciliation and scoped tasks](2026-09-10-crm-audit-continuation.md) · [explicit 87-route coverage matrix](2026-09-10-crm-route-coverage.md). New initial-state screenshots are not full journey verification. The original findings and prior working-tree updates below are preserved.

## Decision summary

**16 evidence-backed defects/usability gaps, plus explicitly unfinished capabilities and verification gaps.** Prioritize recovery, roleplay reliability, financial truth, and access to existing customer records before visual polish.

This is a repository-wide inventory with targeted functional and reporting verification, **not a claim that every CRM journey works**. All 87 page routes were inventoried; 399 literal API URL references were compared with the checked-in OpenAPI paths. Five surfaces were exercised in a local browser: Practice Arena, invoices, reports, contacts, and Today. Unexercised journeys are explicitly listed below and have a follow-up audit task.

### Evidence levels

- **Browser:** real application components with explicitly synthetic, contract-shaped API responses. External browser requests were blocked. Confirms UI behavior, not production backend availability.
- **Service:** actual Python services against local PostgreSQL with synthetic data and rollback; provider failures were injected at the external-client boundary.
- **Source:** traced active callers and implementations. Not presented as a live reproduction.
- **Unverified:** inventoried or inferred risk without a completed functional probe. Not counted as a confirmed defect.

**Priority:** P1 blocks a core task, hides existing records, or undermines financial/operational trust. P2 materially misleads or adds friction but has a workaround. No P0 production incident was established.

## Findings

### F01 · P1 · Failed pages tell users to retry but provide no retry

**Observed:** return HTTP 503 for the Practice Arena persona query. The rendered page says “We couldn't load agents. Please try again.” It contains **zero retry buttons and zero internal navigation links**. The whole app shell disappears.

**Cause:** 27 route error boundaries accept `unstable_retry`, but the installed Next.js error-boundary implementation supplies `reset`. `PageErrorState` receives an undefined retry callback. Global React Query handling throws 5xx errors into these boundaries.

**Evidence:** Browser `07-rehearsal-load-error-no-retry.png`; `frontend/src/app/agents/error.tsx:5-20`; `frontend/src/providers/providers.tsx:35-57`; installed `frontend/node_modules/next/dist/client/components/error-boundary.js` passes `reset: this.reset`. The same incorrect prop occurs in 27 `error.tsx` files, including contacts, jobs, messages, campaigns, invoices, reports, settings, billing, and Today.

**Acceptance:** every route boundary exposes a working retry using the installed framework contract; retry refetches/re-renders successfully after recovery. Preserve a safe way back to the app and avoid discarding recoverable form state. Test a real boundary, not only a manually supplied callback.

### F02 · P1 · AI roleplay times out before its synchronous workflow finishes

**Observed:** a controlled successful response taking 32 seconds becomes `timeout of 30000ms exceeded` at approximately 30.1 seconds. The page returns to “Run rehearsal” with no run ID, progress, or recovery.

**Cause:** the shared browser client has a 30-second deadline; `createRun` does not override it. The backend performs the entire AI conversation and scoring inline before returning. Six default turns involve sequential prospect/agent requests, then scoring. A timed-out browser is not a durable cancellation or status channel.

**Evidence:** Browser `03-rehearsal-client-timeout.png` and `browser-results.json`; `frontend/src/lib/api.ts:22`; `frontend/src/lib/api/roleplay.ts:47-51`; `backend/app/services/ai/roleplay/roleplay_service.py:218-304`.

**Limit:** injected latency proves the deadline mismatch; live provider latency and production incidence were not measured. Do not claim every real run necessarily times out.

**Acceptance:** creation returns a durable run identity promptly; execution has explicit running/completed/failed states and recoverable progress. Refresh/retry must not create duplicate paid runs. A run exceeding 30 seconds must remain recoverable and show its eventual result. Merely increasing a timeout does not solve lost identity or duplicate execution.

### F03 · P1 · Provider/scoring failures become real-looking grades

**Observed:** inject a provider failure into the real scorer. It returns an ordinary report with **overall score 0.0 and an empty summary**, rather than a failed/unscored result.

**Cause:** reply helpers catch provider exceptions and substitute dialogue; scoring catches failures and falls back to zero-valued dimensions. The orchestrator then marks the run completed and emits the completion event. “The service failed” becomes indistinguishable from “the rep performed badly.”

**Evidence:** Service `reporting-probe.log`; `backend/app/services/ai/roleplay/report_scorer.py:126-188`; `agent_responder.py:106-122`; `prospect_simulator.py:79-91`; `roleplay_service.py:276-301,338-355`.

**Acceptance:** failed generation/scoring produces an explicit failed or unscored state, an actionable reason, and retry eligibility. Do not record numerical performance grades or successful-completion notifications/automation events for infrastructure failures. Preserve legitimate zero scores as a distinct valid outcome.

### F04 · P1 · Refreshing or leaving Practice Arena strands the rehearsal

**Observed:** start human practice, receive the prospect message, then reload. The transcript disappears. The browser makes **zero GET requests for run history or run detail**.

**Cause:** the only current run is held in component state. The API exposes `listRuns` and `getRun`, but the frontend does not call them. There is no history, resume link, or URL-bound run identity.

**Evidence:** Browser `01-human-rehearsal-started.png`, `02-rehearsal-lost-after-reload.png`; `frontend/src/components/agents/practice-arena.tsx:29-30,63-79`; `frontend/src/lib/api/roleplay.ts:38-45`.

**Acceptance:** save the selected run in the URL or equivalent durable navigation state; restore it after reload and workspace navigation; provide history and resume/view-report actions. Unfinished transcripts and completed reports remain accessible without another paid run.

### F05 · P1 · Import-contact links send users to Today and close the import

**Observed:** open `/contacts?import=true`. The browser ends at `/today` with **zero import dialogs**.

**Cause:** the effect removing the `import` query parameter navigates to `/`, not `/contacts`. The actual current root redirects to `/today` (the older project note saying `/contacts` is stale).

**Evidence:** Browser `10-import-deeplink.png`, `contacts-results.json`; `frontend/src/components/contacts/contacts-page.tsx:69-83`; `frontend/src/app/page.tsx:3-4`.

**Acceptance:** remove only the import parameter while remaining on Contacts; keep the dialog open until explicit completion/cancel, and preserve other relevant query parameters. Test a direct link and an in-app link.

### F06 · P1 · Older invoices and quotes silently disappear after 100 records

**Observed:** the invoice API fixture reports 101 total records and returns the first 100. The real UI shows 100 rows, **zero pagination controls**, and never requests page two.

**Cause:** invoice and quote lists request `{ page_size: 100 }`, render only `items`, and omit server-side pagination/search. The API already supports paging.

**Evidence:** Browser `04-invoices-first-100-only.png`, `browser-results.json`; `frontend/src/components/invoices/invoices-list.tsx:72-80,204-269`; `frontend/src/components/quotes/quotes-list.tsx:105-109`; `backend/app/api/v1/invoices.py:43-62`.

**Impact:** an operator cannot find, resend, reconcile, or act on an older document through these lists; report totals can legitimately include documents the UI cannot expose.

**Acceptance:** use the existing shared pagination pattern and real server totals; support finding a document beyond row 100. Test 0, 1, 100, 101, and multiple pages with stable ordering and preserved filters. Quote behavior is source-confirmed; invoice behavior is browser-confirmed.

### F07 · P1 · Contact conversations are looked up only among the newest 100

**Cause:** the contact conversation pane fetches the first 100 conversations for the entire workspace, then performs a client-side `find` for the selected contact. If that contact's conversation is older, `contactConversation` is null despite existing timeline data. AI assignment/toggle and mark-read paths depend on that value; handlers report “No conversation found for this contact.”

**Evidence:** Source `frontend/src/components/conversation/conversation-feed.tsx:59-76,224-275`; this component is mounted in the contact dialog and both contact-detail routes. `backend/app/api/v1/conversations.py:42-70` currently has no exact contact-ID filter on the list endpoint.

**Acceptance:** resolve the conversation by exact workspace-scoped contact identity, rather than increasing a list cap. Test a selected contact whose conversation lies beyond the first 100, including unread state and AI controls. Keep imported-conversation restrictions intact.

### F08 · P1 · Voided invoice revenue remains in job profitability

**Observed:** two jobs link to one $1,000 invoice. After setting the invoice to `void`, Job P&L still reports **$1,000 revenue and $1,000 profit**, while AR correctly reports **$0 outstanding**.

**Cause:** job P&L sums invoice totals without filtering invoice status. AR explicitly excludes draft and void invoices; the screens use different validity rules.

**Evidence:** Service `reporting-probe.log`; `backend/app/services/reporting/reporting_service.py:67-88,163-205`.

**Acceptance:** define and enforce eligible revenue statuses; voided documents contribute no revenue. Preserve the separate expected rule that a shared invoice contributes its revenue only once. Cover draft, sent, partial, paid, overdue, void, currency, and linked/unlinked cases without weakening existing tests.

### F09 · P2 · “Billable jobs” actually counts distinct invoices

**Observed:** **two jobs linked to one invoice report one billable job**. Revenue is correctly counted once, but the job count is wrong.

**Cause:** `billable_job_count = len(invoice_ids)` uses unique invoices as the denominator rather than billable jobs.

**Evidence:** Service `reporting-probe.log`; `backend/app/services/reporting/reporting_service.py:193-199`; `backend/app/schemas/reporting.py:73-74` calls this “Jobs with a linked invoice.”

**Acceptance:** report two billable jobs and one invoice's revenue for this fixture. If a distinct-invoice count is useful, label it separately rather than changing the meaning of “jobs.”

### F10 · P1 · “New clients” excludes older leads converted today

**Observed:** create a contact dated 75 days ago, mark it converted now, and call the real contact statistics service. **New clients in the past 30 days remains zero.**

**Cause:** the metric filters currently converted contacts by `Contact.created_at`, not their conversion date. The YTD metric has the same cohort basis. Its displayed label reads like new business won during the period, not recently created records that happen to be converted now. This particularly misrepresents lead reactivation, a core product workflow.

**Evidence:** Service `reporting-probe.log`; `backend/app/services/contacts/query_service.py:205-251`; `frontend/src/components/contacts/contacts-stats-cards.tsx:118-135`.

**Acceptance:** use a defined conversion event/date for a period-based new-client metric, including a policy for reconversion. Until that exists, accurately label the creation-cohort calculation rather than presenting it as period conversions. Reconcile it with a contact drilldown and workspace-local period boundaries.

### F11 · P2 · Contact status counts contradict the list and change their meaning

**Observed:** fixture has 100 new contacts plus one qualified contact. On page one the buttons show **All 101, New 25, Qualified 0**. Click Qualified: it returns the existing qualified contact and the buttons become **All 1, Qualified 1**.

**Cause:** All uses the filtered server total, while status counts use only currently loaded rows. The controls look like segment counts but mix populations and change after selecting a segment.

**Evidence:** Browser `08-contact-counts-all.png`, `09-contact-counts-filtered.png`; `frontend/src/components/contacts/contacts-page.tsx:185-199`; `contacts-filter-bar.tsx:26-49`.

**Acceptance:** compute counts over the same documented search/filter scope, independent of the current page; choosing a status must not redefine the “All” population. Reconcile every count with its drilldown.

### F12 · P2 · Growth from a zero baseline is fabricated as +100%

**Observed:** the real helper returns **+100% for both 0 → 1 and 0 → 10,000**.

**Cause:** `_pct_change` explicitly replaces an undefined percentage with 100. The visible cards do not disclose this convention.

**Evidence:** Service `reporting-probe.log`; `backend/app/services/contacts/query_service.py:29-41`.

**Acceptance:** show “New”, “No previous baseline”, or an explicitly defined non-percentage state for a zero denominator. Keep genuine positive, negative, and zero changes mathematically correct.

### F13 · P1 · Quote “Re-send email” can claim success without delivering

**Cause:** the menu's “Re-send email” action invokes the same `sendMutation` as “Mark as sent.” That calls the backend's status-transition path, which deliberately ignores the result of `_email_quote`. The frontend always toasts “Quote … sent.” A separate explicit delivery path already exists and handles failure honestly.

**Related surprise:** “Mark as sent” also attempts a courtesy email. A label that sounds like bookkeeping has an external-send side effect.

**Evidence:** Source `frontend/src/components/quotes/quotes-list.tsx:120-145,616-626`; `backend/app/services/quotes/quote_service.py:1345-1360,1845-1846`.

**Acceptance:** route all actions promising email delivery through the checked delivery path. A status-only action must not unexpectedly email a customer, or must explicitly disclose that effect. Inject missing destination, provider rejection, and success; only confirmed delivery acceptance gets the corresponding success message. No live emails were sent during this audit.

### F14 · P1 · Date-only due dates render one day early in US time zones

**Observed:** synthetic invoice `due_date = "2026-09-30"` renders **Sep 29, 2026** in America/New_York.

**Cause:** `formatDate` constructs `new Date(dateString)`. A date-only string is interpreted at UTC midnight, then formatted in the browser's local time zone. The helper is used for invoice due dates and quote validity dates, including public documents.

**Evidence:** Browser invoice rows in `browser-results.json` and `04-invoices-first-100-only.png`; `frontend/src/lib/utils/date.ts:43-55`; `frontend/src/components/invoices/invoices-list.tsx:242-245`; `quotes/quotes-list.tsx:346-349`; `invoices/public-invoice-view.tsx:172`; `quotes/public-quote-view.tsx:382`.

**Acceptance:** distinguish calendar dates from instants. A September 30 due date remains September 30 in negative and positive UTC offsets, while actual timestamps still convert correctly. Test public and operator document views.

### F15 · P2 · Reports cannot reconcile displayed breakdowns and periods

**Observed:** COGS fixture contains six $100 rows and a $600 total. The report shows only five rows ($500), with no remaining-row count, subtotal explanation, or expansion control.

**Cause:** the component silently uses `breakdown.slice(0, 5)`. Additionally, Job P&L is requested without date parameters (all time), while COGS receives a default month-to-date window. The UI gives no shared period picker or clear per-card period for comparison. AR is an as-of balance, a third time basis. The cards are not interchangeable revenue/margin reports.

**Evidence:** Browser `05-reports-desktop.png`, `browser-results.json`; `frontend/src/components/reports/reports-overview.tsx:52-83,145-179,248-293`; `backend/app/services/reporting/reporting_service.py:132-135,247-268`.

**Acceptance:** show each card's basis and dates; add a compatible period control where appropriate; expose all COGS rows or clearly label top-N plus remainder. Provide actionable invoice/job/item drilldowns that reconcile to displayed totals. Do not force an as-of balance into a period-flow definition.

### F16 · P2 · Selected filter/practice states are visual-only

**Observed:** contact status controls have no `aria-pressed` before or after selection. They are ordinary buttons, not a selection widget with programmatic selection state. Practice Arena's AI/human chooser similarly changes only button styling.

**Evidence:** Browser contact results record `qualifiedAriaPressed: null` both times; source `frontend/src/components/contacts/contacts-filter-bar.tsx:35-49`; `frontend/src/components/agents/practice-arena.tsx:181-207`.

**Acceptance:** expose the active choice with appropriate native radio/tab semantics or correctly managed `aria-pressed`; preserve keyboard operation, focus, and visible selection. Test keyboard and assistive-technology announcement through the complete filter and practice-choice flows. This is not a full WCAG/ADA assessment or certification.

## Reporting discrepancy ledger

| Metric or display | Controlled input | Expected meaning | Actual | Finding |
|---|---|---|---|---|
| Job P&L revenue after void | One $1,000 void invoice linked to two jobs | $0 eligible revenue | $1,000 revenue and profit | F08 |
| Billable job count | Two jobs share one invoice | 2 jobs; invoice counted once financially | 1 billable job | F09 |
| New clients, 30 days | Lead created 75 days ago; converted now | 1 period conversion | 0 | F10 |
| Contact status facets | 101 total; qualified contact off page one | Qualified 1 regardless of page | Qualified 0, then 1 after click | F11 |
| Percentage growth | 0 → 1 and 0 → 10,000 | No defined percentage baseline | Both +100% | F12 |
| Invoice due date | September 30, New York browser | September 30 | September 29 | F14 |
| COGS breakdown | Six rows × $100 | $600 visibly reconcilable | $600 headline, $500 visible rows | F15 |
| AI score on provider failure | Scorer request raises | Failed/unscored | 0.0 with blank summary | F03 |

**Verified positives:** shared-invoice revenue is deduplicated correctly; AR excludes the void invoice in the controlled case. Existing reporting unit tests passed, and 49 reporting integration tests passed. The booked-revenue helper centralizes accepted-deal revenue across consumers and documents legacy-contact linkage; this audit did not prove every dashboard/campaign attribution total against production records.

## Explicitly unfinished or limited capabilities

These are not additional runtime bugs unless the product promises otherwise.

1. **Multi-channel campaign authoring is explicitly disabled.** `frontend/src/components/campaigns/campaign-form.tsx:68-76` marks it “Coming soon,” disabled. Do not count it as a completed campaign capability.
2. **Practice Arena is text-based.** Its interactive path is a textarea/transcript, not live microphone/audio rehearsal. No live voice-practice journey was verified or implemented; channel expectations should be explicit.
3. **Dormant campaign-contact API helpers reference absent backend operations.** `frontend/src/lib/api/campaigns.ts:168-212` includes remove, bulk-remove, get/update personalization, retry-failed, and skip URLs absent from the current campaign router/OpenAPI. Reference search found no current UI callers. This is unfinished/dead client surface, **not evidence of six currently broken visible buttons**. The list helper also assumes a paginated object while the backend contact-list route returns an array (`backend/app/api/v1/campaigns.py:413-437`). Implement an end-to-end contract before exposing these helpers, or remove the unused promises.
4. **Existing assistant changes are still uncommitted work.** They passed the frontend checks below but were not validated as a complete operational assistant workflow. No finding assumes those edits are deployed.

## Verification results and limits

| Check | Result | Interpretation |
|---|---|---|
| Frontend test suite | **212 files, 1,814 tests passed** | Existing tests are green; reproduced workflow defects are uncovered cases. |
| Frontend typecheck | **Passed** | Run against the same working tree with local Next dev-generated types; no build/release claim. |
| Reporting default test selection | **102 passed, 51 deselected** | Default pytest excludes integration tests. |
| Reporting integration selection | **49 passed, 2 failed** | Not release-green; failures described below. |
| Roleplay existing tests | **13 passed** | Does not validate live provider latency or the browser deadline. |
| Browser roleplay/invoice/report harness | **Completed, no page errors** | Confirmed controlled timeout, lost resume, truncation, failed recovery, and report breakdown issues. |
| Browser contacts/import harness | **Completed, no page errors** | Confirmed inconsistent counts, missing selection state, import redirect. |
| Service discrepancy probe | **Intentionally red, exit 1** | Printed actual service discrepancies, then asserted the incorrect job count; defects remain unfixed. |
| Reports mobile viewport | **390px viewport, 390px document width** | No horizontal document overflow in the sampled state; not a full mobile-flow audit. |
| Static route/link inventory | **87 routes; no unmatched static internal link literals in the scan** | Dynamic/generated links and backend-generated destinations need separate verification. |
| API URL scan | **399 literal references inspected** | Not a full method/body/response-contract test. Dynamic suffixes and base-path factories excluded from unmatched-route conclusions. |

### Verification-gate rerun

Re-ran the current artifacts and project checks without shell output redirection:

| Current check | Result |
|---|---|
| `npm --prefix frontend run test -- --reporter=dot` | 212 files / 1,814 tests passed. |
| Backend `pytest tests/services/reporting tests/api/test_roleplay_api.py tests/services/ai/test_roleplay_engine.py -q --tb=short` | 115 passed; 51 integration cases deselected. |
| `node .ezcoder/eyes/out/crm-audit-20260909/browser.cjs` | Exit 0; current harness reproduced the documented defects, with no page errors. |
| Same browser harness with `--contacts` | Exit 0; reproduced incorrect counts and the import redirect. |
| `npm --prefix frontend run typecheck`, **after** stopping the server and restoring `frontend/next-env.d.ts` | Passed against the final file contents. |
| Backend `pytest -c pyproject.toml ../.ezcoder/eyes/out/crm-audit-20260909/reporting_probe.py -q --tb=short` | **Not green.** The standalone probe executes during collection and exits 2 on its preserved assertion: two billable jobs are reported as one. All synthetic rows rolled back. |

The reporting probe's failing assertion was not removed, skipped, or relaxed. It also reproduced void-invoice revenue, missed recent conversion, invented zero-baseline growth, and false provider-failure grade discrepancies. Fixing application behavior remains queued in the remediation tasks; successful audit-harness execution is not evidence that those product defects are fixed. The two previously failing reporting integration tests were not rerun during this gate pass and remain open.

### The two reporting integration failures are not two extra confirmed product bugs

**2026-09-10 follow-up:** repaired locally without changing existing assertions. The original identifiers below do not match the archived log or this checkout; the corrected reproduction, fixes, and passing suite are recorded in [Reporting integration fixture repair](#reporting-integration-fixture-repair--2026-09-10).

- `test_conversion_rate`: duplicate `(workspace_id, invoice number)` fixture violates the existing invoice uniqueness constraint. The local integration test setup needs distinct synthetic numbers.
- `test_revenue_target_query_matches_accepted_quotes`: expects two June deals but sees one; the fixture accepts a quote at June 1 00:00 UTC, which belongs to May in the workspace's US time zone. Align the fixture's intended time basis before judging the product calculation. Do not weaken the assertion just to obtain green.

Both failures are recorded in `reporting-integration-tests.log`. The synthetic workspace left committed by the second failing test was identified by exact ID, fixture name/slug, and creation timestamp, then cleaned up using that test's cleanup helper. No existing CRM workspace was removed. The standalone service probe rolled back its synthetic rows.

### Local evidence and reproduction commands

Artifacts are under `.ezcoder/eyes/out/crm-audit-20260909/` (gitignored; synthetic data only). The durable summaries above do not depend on retaining images.

```sh
# Start local UI against a deliberately unavailable local API.
# The browser harness intercepts API traffic; it blocks external requests.
NEXT_PUBLIC_API_URL=http://127.0.0.1:8999 NEXT_TELEMETRY_DISABLED=1 \
  npm --prefix frontend run dev -- --hostname 127.0.0.1 --port 3100

node .ezcoder/eyes/out/crm-audit-20260909/browser.cjs
node .ezcoder/eyes/out/crm-audit-20260909/browser.cjs --contacts

# Requires the existing LOCAL database/schema. The script rejects remote hosts.
(cd backend && PYTHONPATH=. .venv/bin/python \
  ../.ezcoder/eyes/out/crm-audit-20260909/reporting_probe.py)

npm --prefix frontend run test -- --reporter=dot
npm --prefix frontend run typecheck
(cd backend && .venv/bin/pytest tests/services/reporting -q --tb=short)
(cd backend && .venv/bin/pytest tests/services/reporting -m integration -q --tb=short)
(cd backend && .venv/bin/pytest tests/api/test_roleplay_api.py \
  tests/services/ai/test_roleplay_engine.py -q --tb=short)
```

The audit dev server was stopped. Its automatic `next-env.d.ts` path changes were restored; existing application edits were not overwritten. The integration suite is not wholly rollback-only, so reruns must retain the local-host guard and fixture cleanup discipline.

## Experience direction

**Surface:** data-dense operational application for home-service owners, office staff, salespeople, and field users. Inferred primary job: take a lead from first contact to an honestly reported, paid job without losing context or wondering whether an action happened.

Preserve existing components and visual language. Prioritize **find → act → understand status → recover → reconcile**. Reuse the existing page-state, pagination, capability, and query-key primitives instead of introducing a new UI system. Distinguish operational state changes from real customer sends; calendar dates from timestamps; data absence from system failure; AI performance from provider failure; balances from period-based metrics.

No global visual-quality score or accessibility conformance claim is awarded: the unverified workflows, role matrix, keyboard/assistive-technology cases, and production checks below prevent an honest whole-product score.

## Coverage and remaining end-to-end work

| Area | Evidence obtained | Still unverified |
|---|---|---|
| Navigation, home, global error behavior | Route/link inventory, rendered shell, Today redirect, shared error source | Every role's landing page, browser history across every route, persistent draft recovery |
| Contacts and import | Browser paging/filter counts/deep link; real service metrics; existing tests | CSV validation/import completion, duplicates/merge, bulk changes, role-specific editing |
| Contact timeline, messages, calls | Active conversation caller and API trace; shared error coverage | Real inbound/outbound messaging, attachments, unread reconciliation, call control/recordings |
| AI agents and Practice Arena | Browser setup/human start/refresh/timeout/failure; scorer failure; 13 tests | Paid generation quality, real voice, OAuth/credential variants, cross-tab concurrency |
| Assistant | Inventory includes current user edits; frontend tests/typecheck | Real tool execution, approval/recovery, post-action reconciliation and briefing behavior |
| Campaigns and automations | Campaign form/detail and client/router contract review; reporting helper review | Per-recipient execution, stop/retry, opt-out behavior, delivery status, multi-step automation recovery |
| Quotes, invoices, public document dates | Invoice browser paging/dates; quote delivery trace; P&L/AR service probes | Live deposits/payments/refunds, signature/approval, conversion, external delivery, public-token expiry |
| Reports, dashboard, scorecard/scoreboard | Reports browser desktop/mobile; financial/contact service probes; reporting tests; booked-revenue source | Production ledger reconciliation, complete attribution/window audit, team rankings and every drilldown |
| Jobs, calendar, time, inventory, catalog, service plans | Route and literal API contract inventory; job/inventory reporting tests | Scheduling conflicts, drag/keyboard alternatives, time reconciliation, stock posting and reversals, renewals |
| Opportunities and lighting estimators/projects | Route/API inventory; linked quote/revenue reporting paths | Complete estimate → proposal → approval/deposit → job → invoice journey and context preservation |
| Lead discovery, lists/segments, referral partners, reviews | Route/API inventory | Provider-backed search/enrichment, export/import, criteria reconciliation, referral/review lifecycle |
| Offers, lead magnets, embed, public lead capture | Route/API inventory | Anonymous submission, consent, duplicate handling, thank-you/delivery, follow-up routing |
| Login/register/reset/invite/onboarding/settings/billing | Route/API inventory; shared error and existing frontend tests | Complete unauthenticated/session-expiry/workspace-switch and role matrix; subscription changes |
| Experiments, suggestions, nudges, approvals | Route/API inventory | Execute/approve/reject/snooze recovery, stale decisions, completion and attribution reconciliation |
| Accessibility and responsive behavior | Report viewport, control-state findings, shared component/source review | Full keyboard, screen reader, zoom/reflow, focus, contrast, mobile/touch and reduced-motion matrix |

**Boundaries for the remaining audit task:** use disposable local data and provider sandboxes/fakes first. Real calls/messages, paid AI, payments, or production-changing actions require explicit test destinations/sandbox access and spend authorization. Do not interpret an unverified cell as a pass or as a confirmed broken feature.

## Complete route inventory

Every entry below was inventoried; only the surfaces marked above have runtime evidence.

| Group | Count | Routes |
|---|---:|---|
| agents | 4 | `/agents/[id]`, `/agents/create`, `/agents`, `/agents/practice` |
| assistant | 1 | `/assistant` |
| automations | 1 | `/automations` |
| billing | 1 | `/billing` |
| calendar | 1 | `/calendar` |
| calls | 1 | `/calls` |
| campaigns | 7 | `/campaigns/[id]`, `/campaigns/email/new`, `/campaigns/new`, `/campaigns`, `/campaigns/pre-booking/new`, `/campaigns/sms/new`, `/campaigns/voice/new` |
| catalog | 1 | `/catalog` |
| christmas-lights | 2 | `/christmas-lights`, `/christmas-lights/renew` |
| contacts | 3 | `/contacts/[id]/details`, `/contacts/[id]`, `/contacts` |
| dashboard | 1 | `/dashboard` |
| dev | 1 | `/dev/components` |
| embed | 4 | `/embed/[publicId]/both`, `/embed/[publicId]/chat`, `/embed/[publicId]/fullpage`, `/embed/[publicId]` |
| estimator | 1 | `/estimator` |
| experiments | 3 | `/experiments/[id]`, `/experiments/new`, `/experiments` |
| find-leads | 3 | `/find-leads/ad-library`, `/find-leads`, `/find-leads/people` |
| find-leads-ai | 1 | `/find-leads-ai` |
| password recovery | 2 | `/forgot-password`, `/reset-password` |
| inventory | 1 | `/inventory` |
| invite | 1 | `/invite/[token]` |
| invoices | 1 | `/invoices` |
| jobs | 1 | `/jobs` |
| knowledge | 1 | `/knowledge` |
| landscape-lighting | 2 | `/landscape-lighting/[projectId]`, `/landscape-lighting` |
| lead-magnets | 2 | `/lead-magnets/new`, `/lead-magnets` |
| authentication | 2 | `/login`, `/register` |
| messages | 1 | `/messages` |
| nudges | 1 | `/nudges` |
| offers | 3 | `/offers/[id]`, `/offers/new`, `/offers` |
| onboarding | 2 | `/onboarding`, `/sales-onboarding` |
| opportunities | 2 | `/opportunities/[id]`, `/opportunities` |
| public | 7 | `/p/compare/[token]`, `/p/invoices/[token]`, `/p/landing`, `/p/offers/[slug]`, `/p/quotes/[token]`, `/p/referral-partners/intake`, `/p/reviews/[token]` |
| root | 1 | `/` |
| payment return | 2 | `/payment-cancelled`, `/payment-complete` |
| pending-actions | 1 | `/pending-actions` |
| permanent-lighting | 2 | `/permanent-lighting/[projectId]`, `/permanent-lighting` |
| phone-numbers | 1 | `/phone-numbers` |
| quotes | 1 | `/quotes` |
| referral-partners | 2 | `/referral-partners/[partnerId]`, `/referral-partners` |
| reports | 2 | `/reports`, `/reports/sales` |
| reviews | 1 | `/reviews` |
| scoreboard | 1 | `/scoreboard` |
| scorecard | 1 | `/scorecard` |
| segments | 1 | `/segments` |
| service-plans | 1 | `/service-plans` |
| settings | 1 | `/settings` |
| suggestions | 1 | `/suggestions` |
| time | 1 | `/time` |
| today | 1 | `/today` |
| upsell | 1 | `/upsell` |

## Remediation task order

Tasks are queued for implementation, **not executed by this audit**:

1. Repair shared route recovery (F01).
2. Make roleplay execution truthful and durable (F02–F03), then add history/resume UI (F04).
3. Reconcile job financial metrics (F08–F09).
4. Reconcile contact conversion, segment, and trend metrics (F10–F12).
5. Repair exact conversation lookup and document pagination (F06–F07).
6. Correct calendar-date rendering (F14), import deep links (F05), and quote delivery semantics (F13).
7. Make reports reconcilable and selectable controls accessible (F15–F16).
8. Complete the remaining workflow audit and repair integration test fixtures without weakening checks.

### Queued task IDs

| Task | ID | Finding / scope |
|---|---|---|
| Restore failed-page recovery | `c6c79d3f` | F01 |
| Reliable, failure-aware AI roleplay | `0c4492ef` | F02–F03 |
| Roleplay history and resume | `41a19e9f` | F04; follows roleplay execution |
| Job financial accuracy | `f3a85a4b` | F08–F09 |
| Contact metrics and counts | `023a1153` | F10–F12 |
| Exact contact-conversation lookup | `3b792c8a` | F07 |
| Invoice/quote pagination | `c27a2d64` | F06 |
| Calendar-date correctness | `29f30ec6` | F14 |
| Import-link recovery | `5b8253b9` | F05 |
| Honest quote delivery | `5e0e4b83` | F13 |
| Reconcilable reports | `c9630482` | F15; coordinate with financial fixes |
| Accessible selected states | `6c6f4e83` | F16; coordinate with contact/roleplay UI |
| Reporting integration fixture repair | `3fa174c9` | Two failing integration tests |
| Complete remaining workflow audit | `bb7d2748` | Every unverified cell in the coverage matrix |

## Reporting integration fixture repair — 2026-09-10

Task `3fa174c9` is verified locally. No production database access, application calculation changes, migrations, commits, or deployments were needed.

### Corrected reproduction

The two node IDs quoted in the original audit were absent at checkout `a1d04eac`; selecting them returned pytest's `not found` error. The archived `reporting-integration-tests.log` actually contains these failures:

- `test_capacity_query.py::test_estimate_capacity_never_leaks_another_workspaces_appointments`: five appointments reused one contact's live slot, violating `uq_appointments_live_contact_slot`.
- `test_revenue_target_query.py::test_pace_counts_the_month_actuals_from_the_live_crm`: a June 1 midnight UTC contact falls in May under the implicit US timezone, so the June lead count was one rather than two.

A fresh local reproduction, protected by outer rollback transactions, returned **78 passed, 10 failed**: those two fixture failures plus eight success-only cleanup failures. The latter loaded an unrelated, locally unmigrated `phone_numbers.inbound_ring_operators` column through ORM workspace deletion. All 12,958 pre-existing workspace IDs were preserved. That unrelated work and its migration were left untouched.

### Repair and calculation proof

- Synthetic invoice numbers now use the full UUID rather than six hex characters. There is no `test_conversion_rate` in the current reporting-service test module; existing conversion coverage in the sales-performance tests remains enabled and passes.
- The five other-workspace appointments occupy distinct hourly slots, still in July and still for the same contact. Tenant-isolation assertions are unchanged.
- Revenue-target workspaces explicitly use UTC for their UTC-calendar fixtures. The existing approved estimate now has an explicit July acceptance date, preserving its June estimate count without accidentally contributing June booked revenue or depending on the wall clock.
- Added `test_revenue_target_query_matches_accepted_quotes`, parameterized over UTC and America/Chicago. It calls the real `get_booked_revenue_totals` helper and `RevenueTargetService.get_pace`: the same $1,000 quote accepted at June 1 00:00 UTC appears once in June under UTC and once in May under Chicago, with zero in the opposite month. These paths show correct production calculations; no timezone or revenue query was relaxed.
- Revenue-target sessions now join an outer transaction through savepoints. Service commits remain exercised, but `finally` rolls back every fixture row on success, setup failure, or assertion failure. Dedicated regression cases inject an assertion failure and a real uniqueness violation after a service commit, then verify the workspace and target are absent from a fresh session. The old success-only deletion helper is removed, and the tests enforce a loopback database host.

### Verification

**RUNTIME:** PostgreSQL 17.10 in the local `aicrm-postgres` container; `DATABASE_URL` explicitly pinned to `127.0.0.1:5432/aicrm`, `ENVIRONMENT=test`, background workers disabled. No production connection was used.

```text
cd backend
.venv/bin/pytest tests/services/reporting -m integration -q --tb=short
92 passed, 102 deselected in 5.99s
```

- Ruff lint and format checks passed for all three edited test files.
- An AST comparison against HEAD confirmed every pre-existing test and its assertion expressions remain unchanged.
- Exact pre/post row-ID sets matched for workspaces, contacts, invoices, quotes, revenue targets, opportunities, pipelines, appointments, and field-service jobs, including the injected-failure cases. No retained fixture rows were found in those nine tables; rollback does not rewind PostgreSQL sequences.
- A SHA-256 fingerprint confirmed all pre-existing uncommitted files remained byte-for-byte unchanged. The passing result applies to this local reporting suite, not a production-wide financial audit.
