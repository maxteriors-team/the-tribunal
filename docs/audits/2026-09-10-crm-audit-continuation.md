# Whole-CRM audit continuation: evidence and open coverage

**Status: PARTIAL. The original whole-CRM audit is not complete; task `bb7d2748` must remain open.**

This continues [the original 2026-09-09 audit](2026-09-09-crm-ux-reporting-audit.md), using its **87-route denominator**, with a separate [explicit route-by-route matrix](2026-09-10-crm-route-coverage.md). The initial phase exercised Practice Arena, invoices, reports, contacts and Today only. Nothing here retroactively calls another journey verified.

## 1. Baseline, safety and interruption

- Reviewed the current dirty checkout based on `a1d04eacd62badc13df3f2e2c2ed47db2ae7aef0`, not a release or production deployment. Existing application changes and untracked tests were protected. This report describes that unfinished local version.
- No application fixes, migrations, commits, deploys, production mutations, real messages, paid calls, model calls, payments, or phone-number purchases were performed.
- Browser: Chromium `148.0.7778.96`, local Next dev server on `127.0.0.1:3100`, 1440×1000 desktop and 390×844 narrow viewport. API requests were fulfilled locally using synthetic fixtures; unknown writes were blocked. Provider sockets were closed; only local Next development sockets were permitted. The backend URL was loopback port 9, not production. Sentry/telemetry were disabled for the audit server.
- Backend test runner denied real socket connections, including local databases, and used the existing tests' controlled fakes. The numeric probe separately allowed only the verified loopback Postgres host/port, did not start the application lifespan/workers, rejected commits, and rolled back all synthetic rows.
- The numeric probe used reserved example phone numbers, `example.invalid` emails and synthetic workspaces. It never queried customer rows by broad workspace scope. A final independent query found **0 surviving synthetic workspaces**. No secrets or customer PII are reproduced here.
- The run crossed midnight UTC: the successful financial seed records `2026-09-11` UTC; the report is dated for the September 10 local audit session. Browser schema fixtures use a fixed September 10 date; those screenshots are not the numeric ledger fixture.
- **Interrupted before completion:** a concurrent process changed another test file and removed this checkout's browser dependencies. The existing protected-file hash manifest matched before saving the reports; new concurrent work was left untouched. The final expected manifest differences are the original audit's new continuation link and restoration of the generated route-import file (the manifest was taken after dev-server startup). The broader role/browser pass stopped, the audit dev server was stopped, and its generated `next-env.d.ts` route imports were restored to their pre-run content. No dependency reinstall, reset, checkout, or interference with the other process was attempted.
- The user did not choose either continuation card. The conservative outcome was to save evidence/tasks and stop further runtime work, not silently assert completion.

### External-operation gate, still closed

| Operation | Required before continuation | Performed here |
|---|---|---|
| Voice, SMS, email, review/referral sends | Local fake or capture transport; explicit allowlisted synthetic/test destinations; spend authorization if any provider can bill | No real sends/calls |
| Assistant/practice/discovery AI | Controlled model/tool fake, or approved sandbox plus explicit spend ceiling | No paid model calls |
| Stripe checkout/deposit/subscription/portal | Test-mode keys and test customer/account; no live objects; spend authorization before any billable action | No provider checkout/payments |
| Calendar/provider search/number purchase | Fake adapter or isolated test account; no live calendar/customer mutation; purchase/spend approval where relevant | No live provider operations |

A locally rendered success page is never proof of a payment. A mocked send response is never proof of delivery.

## 2. Evidence ledger: what actually ran

Artifacts are preserved locally under `.ezcoder/eyes/out/crm-audit-20260910/`. They are ignored audit artifacts, not committed release assets. The tables below preserve the important evidence if those local artifacts are later cleaned up.

| Evidence | Result | Claim allowed |
|---|---|---|
| `coverage.cjs`, `coverage-results.json`, 87 per-route JSON files | **87/87 initial-state desktop and mobile captures; 174 PNGs; 12 Tab observations per route** | Local initial rendering only; not completed workflows |
| Final initial-state browser run | 0 uncaught page errors; 86/87 document widths ≤390px; developer gallery `/dev/components` was 527px | The measured initial states only; no all-state responsive certification |
| Existing `frontend/e2e/contacts-import.spec.ts` | 3 passed | Import URL/back-forward/completion behavior against that test's mocked contacts API |
| Existing `frontend/e2e/role-matrix.spec.ts` | 8 passed, one per role | Protected route tier checks in the existing mocked-API test, not every role's every action |
| Existing `frontend/e2e/selected-controls.spec.ts` | 2 passed | Contact status and Practice Arena choice keyboard/focus/announced selection checks |
| `backend-unit.xml` | **1,067 passed, 4 skipped**, 539 deselected by the existing pytest marker selection | Selected service tests with network disabled; skipped/integration tests are not passes |
| `backend-api.xml` | **1,089 passed, 1 skipped** | Existing API tests with network disabled; not a live API/browser/database end-to-end run |
| `numeric_probe.py`, `numeric-results.json` | Rollback-only local DB reconciliation completed | Real service/SQL outputs for the explicit synthetic facts in section 4 |
| `roles.cjs`, `role-results.json` | 9 owner route observations recorded; stopped before the other roles and workspace-switch scenario | Partial additional role exploration only; **workspace switch/reload not completed** |

The initial browser harness incorrectly closed Next's own development WebSocket and captured unhydrated shells. Those results were rejected. The final 87-route run allowed only the local development socket and waited for workspace hydration; only that final manifest is counted. Numeric fixture setup also initially used incorrect field/enum assumptions. These were corrected against the actual model definitions, not by changing the application or weakening assertions. Failed attempts rolled back; only the final successful output is reported.

### Rendered review, not an accessibility certificate

Surface: data-dense CRM for operators and field staff, with customer-facing public entry pages. Primary jobs are finding the next action and preserving customer/workspace context. The existing dark/yellow product system was preserved; no redesign was requested.

Full-size screenshots inspected include messages desktop, campaign chooser mobile, calendar mobile, onboarding desktop, inventory mobile and reports desktop. Their visible initial states have consistent navigation and readable primary actions. Calendar and reports still require substantial vertical scrolling on narrow screens; that is an observation, not proof of a broken operation. The reports screenshot correctly warns that the synthetic returned window differs from the requested window; this is a working mismatch warning, **not** a real financial discrepancy.

The automated unnamed-button heuristic cannot resolve all associated HTML labels, so its switch/combobox results are not published as confirmed accessibility defects. Keyboard completion beyond the two named control tests, all overlay focus/return behavior, 320px reflow, 200%/400% zoom, contrast measurement, screen readers, forced colors, reduced-motion interactions, physical touch and Safari remain unverified. No WCAG/ADA conformance or broad quality score is claimed; the state-completeness and accessibility evidence gates remain open.

## 3. Explicit journey and role coverage

**CODE** means inspected source, not runtime proof. **R** means the route matrix's synthetic initial render. **T** names an executed test/probe. Unmentioned subflows are not implicitly verified.

| Requested journey | Source inspection / runtime evidence | Still not verified |
|---|---|---|
| Onboarding, registration/login/reset/invite | CODE: auth routes, auth/workspace providers, onboarding services; R entry/token/prerequisite screens; service/API test selections | Account lifecycle through local mail sink, expired/replayed tokens, completed onboarding/skip recovery, browser session expiry |
| Workspace switching and all roles | CODE: workspace provider, frontend permission map, backend role catalog and billing resolver; T eight protected-route tier tests; partial owner nine-route pass | Real API authorization matrix, switch during pending writes, Beta persistence after reload, stale-query isolation, every role's feature affordances |
| Contacts import/merge | CODE: CSV parser/import and duplicate handling; R list/detail; T three import navigation/completion tests and contact service tests | Real DB upload with partial errors, retry after interruption, full duplicate-resolution/merge workflow and dependent record migration. No working merge button was identified; this is a capability gap, not a reproduced broken control |
| Messages/calls | CODE: active clients/history/manual actions; R empty history; T conversations/messaging service tests and synthetic call metrics | Compose/send/retry/reconnect, inbox ordering under simultaneous events, recordings, answer/hang-up/device permission flows, delivery to capture destinations |
| Campaigns/automations | CODE: active channel builders/lifecycle/automation/approval paths; R entries/details; T campaign/automation service tests and numeric counters | Draft attachment failure/retry, schedule/pause/resume/cancel, automation trigger/action recovery, contact attribution, provider delivery |
| Assistant tools/approvals | CODE: tools, permission/approval paths and pending-action UI; R empty assistant and queue; T selected approval/API tests | Multi-tool conversation, editable action preview, approve/reject/expiry/idempotent execution through controlled tools, role- and tenant-specific tool boundaries end to end |
| Opportunity → estimate → proposal → deposit → job → invoice → renewal | CODE: active ledger, quote conversion/deposit/invoice/reporting flows; R all related entries/token/detail states; T selected service tests and numeric ledger/cost probe | One linked browser transaction across all stages; duplicate approval/payment events; alternate estimate variants; cancellation/refund; renewal idempotency and notification capture |
| Calendar/time/inventory | CODE: calendar ownership, scheduling, attendance and stock/costing paths; R empty calendar/time/inventory; T selected service tests, real local stock receipt/consumption/labor probe | Appointment CRUD/DST/conflict UI, clock-in/out and rounding, actual stock adjustment/return/reorder UI, concurrent consumption and keyboard completion |
| Lead discovery/segments | CODE: active discovery and segmentation paths; R entries; T discovery/segments service tests | Provider results, paginated selection/import, failed enrichment, duplicate handling, segment mutations and role restrictions in browser |
| Marketing/public forms | CODE: embed, offers, lead magnets and public submission boundaries; R all public/config/token/form entries | Actual valid/expired/invalid token submissions, consent and inline validation states, upload safety, lead creation/deduplication, confirmation and captured follow-up |
| Billing | CODE: selected/default-workspace mismatch; R synthetic billing; API tests | Two-workspace status/checkout/portal browser proof and test-mode Stripe lifecycle; no live actions authorized |
| Notifications/nudges | CODE: notification policy/recipient selection and nudges; R queue/settings entry; T policy/recipient tests | Delivery preferences through captured mail, read/unread/reconnect, quiet hours and notification detail navigation |
| Experiments | CODE: campaign/experiment paths; R list/create/detail | Experiment creation, enrollment, stop/rollout and counted outcome attribution with controlled facts |
| Referrals/reviews | CODE: partner/review flows and review configuration permission; R admin/public forms; T review logic tests | Intake-to-partner conversion, review solicitation/response/opt-out, duplicate webhook and capture-destination checks |
| Dashboard/campaign/team/financial reports | CODE + T local SQL/service reconciliation below; R empty visual states | Populated report rendering/drilldown/CSV against the same facts, cross-report filter and timezone boundaries, team assignments and snapshot history |

### All eight roles, without overclaiming

Canonical roles are in `backend/app/core/roles.py:37-147`; frontend capabilities and route tiers are in `frontend/src/lib/permissions.ts:25-190`.

| Role | Existing browser route-tier test | Additional nine-route pass | Real backend × all feature actions |
|---|---|---|---|
| owner | Passed | 9 recorded | Unverified |
| admin | Passed | Interrupted before evidence | Unverified |
| manager | Passed | Not completed | Unverified |
| dispatcher | Passed | Not completed | Unverified |
| sales_rep | Passed | Not completed | Unverified |
| member | Passed | Not completed | Unverified |
| lead_technician | Passed | Not completed | Unverified |
| technician | Passed | Not completed | Unverified |

The nine additional routes were dashboard, campaigns, lead magnets, segments, reviews, inventory, billing, find leads and settings. Their synthetic permission failures would still not replace real backend authorization tests.

## 4. Seeded numeric reconciliation

`numeric-results.json` SHA-256: `3d66fcbe7b963126f4a854431ec69d05ce4f95dd0c4d6ae28a3afb6e52b2716d`.

Facts were seeded in one uncommitted transaction: Alpha had 4 contacts; 3 answered voice rows with durations 60/120/180 seconds; 1 failed voicemail row with no-answer outcome; 3 ordinary outbound SMS rows (2 delivered, 1 failed); an SMS campaign with 4 recipients/3 sent/2 delivered/1 reply; and a voice-fallback campaign with 4 recipients/3 call attempts/0 SMS sent. All message rows belonged to one synthetic agent/contact conversation. No actual calls, SMS or automated textbacks ran.

Financial facts: approved USD1,000 quote with USD200 deposit already recorded; partial USD1,000 invoice with USD200 paid and due on the seed day; one linked job; 2 hours × USD50 labor; USD50 expense; receive 10 stock units at USD10, consume 3 on the job. Beta had a USD900,000 approved quote to detect accidental tenant aggregation. A final phase added an Alpha EUR100 approved quote without conversion.

| Metric | Seeded expectation / definition | Actual service output | Assessment |
|---|---|---|---|
| Contacts | 4 Alpha contacts | 4 | Reconciles |
| Core calls today | 3 voice, or 4 when voicemail belongs in “calls” | 3 | Explicit denominator mismatch with team scorecard; C04 |
| Team inbound calls / answered | 4 / 3 | 4 / 3 | Reconciles with voice + voicemail definition |
| Team answer rate | 3 ÷ 4 × 100 | 75% | Reconciles |
| Agent calls handled | 3 voice + 1 voicemail | 4 | Reconciles with team, not core channel scope |
| Average handle time | (60+120+180) ÷ 3 | 120 seconds | Reconciles |
| Core outbound SMS count | 3 rows, including failed | 3 | Counts attempts/rows, not successful delivery |
| SMS campaign sent progress | 3 ÷ 4 × 100 | 75% | Arithmetic correct for sent, not delivered; C03 |
| SMS delivery rate / reply rate | 2 ÷ 3 / 1 ÷ 3 | 0.6666667 / 0.3333333 | Reconciles |
| Voice campaign progress | 3 call attempts exist; no SMS sent | 0/4, 0% | All-channel card ignores voice activity; C03 |
| Missed-call textbacks | No automated textback executed; three ordinary SMS rows nearby | 1 | Temporal proxy, not confirmed automation attribution; C05 |
| USD booked revenue | USD1,000; exclude Beta USD900,000 | USD1,000, won_count 1 | Reconciles; tenant sentinel excluded |
| Deposit on quote | USD200 | Stored USD200 in fixture | Fixture fact, not payment-processor reconciliation |
| Current AR | USD1,000 − USD200 | USD800, current bucket | Reconciles; not a historical cash snapshot |
| Job invoice revenue | USD1,000 | USD1,000 | Reconciles in this current local version |
| Job labor/materials/expense | USD100 / USD30 / USD50 | USD100 / USD30 / USD50 | Reconciles |
| Job cost/profit/margin | USD180 / USD820 / 82% | USD180 / USD820 / 0.82 | Reconciles; unit-cost receipt/consumption path exercised |
| Mixed-currency booked revenue | USD1,000 and EUR100 must not become one USD total | won_value 1100, currency USD, won_count 2 | Reproduced discrepancy; C02 |
| Rows after rollback | No synthetic workspace persists | 0 synthetic workspaces | Rollback verified |

Agent success rate was 100% because its outcome classification denominator is not the team's 75% answered-call denominator. That difference alone is **not** filed as bad arithmetic. Revenue ROI was null with zero attributed AI cost, appropriately not fabricated as an infinite return.

This reconciles direct service/SQL results, not dashboard screenshot values. Cash settlement, tax, refunds, multi-currency conversion rates, historical AR and shared-invoice multi-job variants were not added to this probe. Earlier audit findings are not automatically closed; only the specific current USD fixture above is newly proven.

## 5. Findings and scoped remediation tasks

### Spec axis: functionality and honest product capability

**C01 · High · CODE · Billing follows the default workspace, not the selected workspace.**

- `frontend/src/app/billing/page.tsx:27-55` uses the selected workspace only to enable an unscoped subscription query and sends unscoped checkout/portal requests. `frontend/src/lib/api/billing.ts:3-22` contains no workspace argument.
- `backend/app/api/v1/billing.py:57-90,93-148` selects the current user's default/first workspace, then checks billing permissions on that result.
- Reproduce safely with an owner in Alpha/Beta: select Beta in the UI while Alpha remains the user's default; compare status and fake checkout account. This is source-confirmed; the interrupted browser switch scenario did not complete. The same page also turns a status-fetch error into the unsubscribed branch because it has no query error gate.
- Remediation **`33126458`**: pass/authorize the selected workspace through status, checkout and portal; workspace-key caches; retryable fetch errors instead of a trial offer. No real Stripe calls needed to prove routing.

**C07 · Medium · CODE · Some read-only route and mutation affordances do not match backend capabilities.**

- `frontend/src/lib/permissions.ts:164-173` permits contacts readers onto lead magnets, while `backend/app/api/v1/lead_magnets.py:53,133-145` uses the outreach-write mutation permission on list access. Review configuration reads require workspace management (`backend/app/api/v1/reviews.py:78-88`) even when the review-list surface is available.
- Segment/automation create/edit/delete controls also need the all-role browser pass rather than assuming route admission grants write access. The backend authorization gates are compensating controls; no privilege escalation is claimed.
- Remediation **`b776d40b`**: reproduce each role, separate readable content from management config, and hide/disable unavailable mutations without weakening API authorization.

**C08 · Low · Resolved locally (2026-09-11) · Dormant generic campaign-contact contracts.**

- **Original finding (CODE):** `frontend/src/lib/api/campaigns.ts` promised a paginated contact list, a `status` query and an add response containing `skipped`. The backend returns an array, accepts `status_filter`/`limit`, and returns only `added`. Rechecked current OpenAPI: only GET/POST on the generic campaign-contact collection exist; get/remove/bulk-remove/personalization/retry/skip routes remain absent.
- **Caller recheck (CODE):** language-server navigation found only declarations for `campaignContactsApi` and each of its eight methods. Its three request/response interfaces and the shared `CampaignContact`/`CampaignContactStatus` types had only internal references. Source/import searches confirmed no active callers; the separate `campaignsApi` and channel-specific SMS/voice/email clients remain in use and unchanged.
- **Remediation `31d30cd1`:** removed all eight unused helpers, their three local interfaces, the two now-unused shared types and unused imports. No campaign-contact methods were deliberately retained, so there are no retained contracts to align or exercise. Backend routes, OpenAPI and generated API types were not changed by this remediation.
- **Verification (RUNTIME):** added `frontend/src/lib/api/campaigns.test.ts`, which imports the real module and rejects the dormant export. It failed before removal and passed afterward (1 test). A focused TypeScript check passed. Checks used lockfile-pinned dependencies in an isolated temporary directory and ignored configs under `.ezcoder/eyes/out/c08/`; the full frontend suite was not run.
- **Scope:** this removes unused contracts, not broken visible buttons. Combined multi-channel authoring remains explicitly unavailable; the chooser and supported channel builders were unchanged. No app/provider actions, production access, commits or deploys were performed. The broader audit remains partial.

**Disabled capability, not a defect claim:** combined multi-channel authoring remains explicitly unavailable in `frontend/src/app/campaigns/new/page.tsx`; voice with SMS fallback is a supported distinct campaign type, not proof that a combined authoring workflow exists. No enablement task was added. Contact import duplicate skipping likewise is not a contact merge workflow; merge completion remains an explicit coverage/capability gap.

### Standards axis: numerical correctness and recovery

**C02 · High · RUNTIME + CODE · The booked ledger silently sums incompatible currencies.**

- Reproduction: section 4, final EUR phase. USD1,000 + EUR100 returned `won_value: 1100`, `currency: "USD"`.
- `backend/app/services/reporting/booked_revenue.py:73-139,197-237` builds/sums opportunities and quotes without carrying currency through the ledger. The dashboard presents the shared result with a single currency; ordinary financial reports have separate mixed-currency guards.
- Remediation **`0035355e`**: group by explicit currency or reject incompatible aggregation consistently. Preserve canonical quote/opportunity deduplication. Never silently relabel or invent an FX conversion.

**C03 · Medium · RUNTIME + CODE · Campaign progress uses SMS sends for every channel and calls it delivery.**

- `backend/app/services/dashboard/dashboard_service.py:348-377` computes `messages_sent / total_contacts` regardless of channel. `frontend/src/components/dashboard/performance-metrics.tsx:182-188` exposes that as “delivery progress.”
- The voice fixture has three call attempts but displays 0/4, 0%; the SMS fixture has two deliveries but exposes three sends/75% as delivery progress. This is not an unreachable-client finding: the dashboard consumes this result.
- Remediation **`f6ebd4a3`**: define attempted/contacted versus delivered metrics per supported channel and label the progress bar truthfully, including its accessible name.

**C04 · Medium · RUNTIME + CODE · Core calls and team calls have different unlabelled channel denominators.**

- `dashboard_service.py:166-174` restricts core calls to `voice`; `scorecard_service.py:465-511` includes voice and voicemail. The same fixture produced core calls 3 and team/agent calls 4.
- Remediation **`9c87a9a7`**: align the intended definition or label the difference. Do not force unrelated answer-rate and classified-outcome rates to match.

**C05 · Medium · RUNTIME + CODE · Missed-call textback counts are temporal coincidence, not confirmed execution.**

- `scorecard_service.py:615-644` selects outbound SMS solely by channel/direction/window; `_has_textback` at lines 181-193 checks a same-contact time window. It does not require an automation association or delivery status.
- The fixture executed no textback automation but returned `missed_calls_textback_sent: 1` because ordinary outbound SMS existed nearby. The stronger failed-only-message variant remains source-derived, not runtime-tested.
- Remediation **`9c87a9a7`** also covers this: instrument actual textback attribution/delivery or clearly label a follow-up proxy; add failed/queued/ordinary-message regression cases.

**C06 · Medium · CODE · Retrying a partially created campaign can duplicate drafts.**

- `frontend/src/app/campaigns/sms/new/page.tsx:94-136` creates the campaign, then attaches contacts in a second request; failure only toasts an error and a retry starts creation again. Similar sequencing is in voice/new, email/new and pre-booking/new pages.
- Reproduction to perform: fulfill create once, fail attachment, retry; assert a second create is not issued and the existing draft remains recoverable. This scenario was traced in source, **not completed in the interrupted browser run**.
- Remediation **`b2e57268`**: retain/reuse the draft or create an atomic/idempotent boundary. Do not delete a user's partly saved campaign or start sending to make the test pass.

### Candidate filtering

Rejected or withheld conclusions include: unused helpers are visible broken buttons; disabled multi-channel is a broken enabled wizard; the report fixture's deliberate date mismatch is a real backend reporting error; all heuristic unnamed controls fail accessible-name computation; empty fixtures prove populated workflows; green API tests prove all role/tenant boundaries; and a reviewer suggestion about generic approval labels without a confirmed current active path. These are not remediation findings.

## 6. Reproduction commands and source comparison

The existing OpenAPI-generated schema, local e2e patterns and real Playwright source were read before writing the audit harness. The local corpus reference was `vercel/next.js`, `packages/next/src/experimental/testmode/playwright/page-route.ts:21-65`: explicit route fulfillment, explicit unhandled-request handling, and request seams. This guided the harness; it does not prove product correctness. Playwright source was resolved for the installed 1.63.0 version rather than assuming new APIs.

Run only in an isolated local checkout with the matching dependencies and no other dev server/dependency installation modifying it:

```bash
# From repository root: loopback backend, telemetry disabled.
NEXT_PUBLIC_API_URL=http://127.0.0.1:9 \
NEXT_PUBLIC_SENTRY_DSN= SENTRY_DSN= SENTRY_AUTH_TOKEN= NEXT_TELEMETRY_DISABLED=1 \
npm --prefix frontend run dev -- --hostname 127.0.0.1 --port 3100

node .ezcoder/eyes/out/crm-audit-20260910/coverage.cjs

PLAYWRIGHT_BASE_URL=http://127.0.0.1:3100 E2E_ALLOW_PROVISIONING=0 \
E2E_USER_EMAIL= E2E_USER_EMAIL_TEMPLATE= E2E_USER_PASSWORD= \
npm --prefix frontend run e2e -- e2e/role-matrix.spec.ts \
e2e/contacts-import.spec.ts e2e/selected-controls.spec.ts --workers=1 \
--output=../.ezcoder/eyes/out/crm-audit-20260910/e2e

# Existing service/API tests; safe_tests.py rejects all real socket I/O.
cd backend
PYTHONPATH=. .venv/bin/python ../.ezcoder/eyes/out/crm-audit-20260910/safe_tests.py \
  tests/services/onboarding tests/services/workspaces tests/services/contacts \
  tests/services/test_contact_import.py tests/services/conversations tests/services/messaging \
  tests/services/campaigns tests/services/automations tests/services/approval \
  tests/services/opportunities tests/services/quotes tests/services/prebooking \
  tests/services/jobs tests/services/invoices tests/services/recurring_jobs \
  tests/services/calendar tests/services/inventory tests/services/lead_discovery \
  tests/services/segments tests/services/dashboard tests/services/reporting \
  tests/services/payments tests/services/test_notification_policy.py \
  tests/services/test_notification_recipients.py tests/services/test_review_service_logic.py \
  -q --tb=short --junitxml=../.ezcoder/eyes/out/crm-audit-20260910/backend-unit.xml
PYTHONPATH=. .venv/bin/python ../.ezcoder/eyes/out/crm-audit-20260910/safe_tests.py \
  tests/api -q --tb=short \
  --junitxml=../.ezcoder/eyes/out/crm-audit-20260910/backend-api.xml

# Separate DB-only probe: asserts loopback, blocks non-DB network, refuses commits.
PYTHONPATH=. .venv/bin/python ../.ezcoder/eyes/out/crm-audit-20260910/numeric_probe.py
```

Do not run the last command against production or substitute production credentials. No migration was applied to make this fixture work. The local schema still required a phone number, so reserved synthetic numbers were supplied; the application schema was not changed.

## 7. Remaining completion work, in order

1. Obtain a stable, isolated local checkout/dependency snapshot, preserve the current dirty work and copy the ignored evidence harnesses. Do not reinstall dependencies into a checkout another process is using.
2. Complete the multi-workspace and all-role feature/action matrix against a real local API with synthetic membership data. Finish auth/onboarding/email-sink recovery before treating these journeys as verified.
3. Seed linked, nonempty records and execute contacts import/duplicate resolution; messages/calls; campaign/automation failure recovery; assistant approvals; the complete quote/deposit/job/invoice/renewal chain; and calendar/time/inventory mutations with fake providers. Keep every missing branch explicit.
4. Exercise valid/invalid public forms/tokens, discovery-to-segment/contact conversion, notifications/experiments/referrals/reviews, and test-mode billing only after the destination/provider/spend gates are satisfied.
5. Render dashboard, campaign, team and financial views from the same section-4 facts; compare cards, filters, drilldowns and exports. Complete mobile scrolling/dialog/error states and keyboard actions rather than stopping at navigation.
6. Attach exact observations to the route/journey matrix and close `bb7d2748` only when this original scope is proven or the user explicitly narrows it. Do not replace the incomplete status with a broad “verified CRM” claim.

**Verdict: incomplete assessment with documented findings; whole-CRM audit remains unfinished.** Seven scoped remediation tasks were added, none implemented during the original audit. The subsequent local C08 cleanup is recorded above; it does not complete the remaining audit scope.

## 8. Current verification-gate follow-up

The requested recognized, bounded pytest command was run successfully:

```bash
cd backend && PYTHONPATH=. .venv/bin/pytest \
  ../.ezcoder/eyes/out/crm-audit-20260910/test_audit_verification.py \
  -q --tb=short \
  --junitxml=../.ezcoder/eyes/out/crm-audit-20260910/verification-gate.xml
```

**Result: 6 passed in 3.48 seconds, zero skipped.** The audit-only test file exercises the actual harnesses; it does not modify application behavior.

| Listed change | Current verification | Remaining limit |
|---|---|---|
| `coverage.cjs` | Node syntax check executed within pytest | Browser runtime not reverified; local Playwright is missing |
| `roles.cjs` | Node syntax check executed within pytest | Incomplete role/workspace browser run remains incomplete; Playwright is missing |
| `numeric_probe.py` | Compiled and executed against loopback Postgres; assertions checked contacts, call facts, AR 800, cost 180, profit 820, margin 0.82 and zero remaining synthetic workspaces | The mixed-currency defect reproduced; a passing audit reproduction does not mean the product behavior is correct |
| `safe_tests.py` | Compiled and executed with a controlled pytest entry point; all four connection paths rejected, sensitive provider env blanked, and pytest exit code 7 preserved | This checks runner safety/exit handling, not every test in the application |
| `frontend/next-env.d.ts` | `npm --prefix frontend run typecheck` attempted | **Unverified:** exit 127, `tsc: command not found` |

The project's bounded role/import/control e2e command was also attempted again with loopback URL and provisioning disabled. It exited 127 with `playwright: command not found`; no browser tests ran in that attempt. Dependencies were not installed into the shared checkout. The current frontend/type verification gap remains open, rather than relying on historical green results.

The verification wrapper writes the new numeric output to pytest's temporary directory, preserving the original audit JSON and its recorded hash. No original application assertion was relaxed, no paid provider was called, and no production or customer data was mutated.