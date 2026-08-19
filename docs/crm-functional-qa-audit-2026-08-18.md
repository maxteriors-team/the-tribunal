# CRM Functional QA Audit

**Audit date:** 2026-08-18
**Environment:** Local Next.js/FastAPI stack, isolated QA workspace, fake contact data
**Status vocabulary:** Not Started / In Progress / Fixed / Retested / Closed

## Executive summary

**QA Score: 64/100. 2 critical issues, 8 high-priority issues, 12 medium issues, and 5 minor issues were identified; 26 remain open (25 Not Started and QA-018 In Progress), while QA-026 is Closed after retest. The biggest problems are concentrated in public embed lead capture, role permissions, campaign creation, fresh-workspace quote setup, accessibility, and mobile action clipping. Fix the 10 critical/high-priority items before adding additional CRM features.**

The internal CRM can register and onboard a workspace, create contacts, schedule appointments, save invoices, create automations, create opportunities, and generate a client quote link. The score is held below 100 because the anonymous embed is blocked twice, hidden modules remain reachable by lower roles, one campaign builder silently discards entered data, new workspaces have no priced quote lines, direct payment-success URLs make an unverified success claim, and multiple keyboard/mobile paths are not operable.

Live Telnyx, OpenAI API-key, Google Places, Cal.com, and Resend delivery were not available in this environment. Their missing-configuration and recovery states were exercised without spending money or contacting real people. Stripe was configured in test mode; no charge was completed. These provider-dependent delivery paths remain unverified against live vendor accounts.

## Coverage and evidence

- **140 rendered route checks:** 70 routes at desktop and 390px mobile viewports.
- **40 Settings checks:** 20 tabs at desktop and mobile, including controls, saves, switches, network failures, and axe scans.
- **350 role-route checks:** 50 authenticated routes for each of owner/admin/manager/dispatcher/sales_rep/member/lead_technician/technician, with targeted evidence captures for restricted modules.
- **Primary workflows:** registration, login, password reset, onboarding, contact creation/detail, appointment creation/cleanup, opportunity creation, automation creation, campaign drafting, invoice drafting, quote creation/client-link generation, public lead form, embed configuration, and missing-provider recovery.
- **Automated accessibility:** axe checks on the route set, Settings tabs, agent detail, and embed dialogs. This is not a WCAG conformance claim; screen-reader coverage was not completed.
- **Frontend CI:** passed lint/type/unit/build; **150 test files and 1,385 tests passed**.
- **Backend CI:** passed lint/type/tests; **4,581 tests passed**, 21 skipped, coverage 61.10%.
- **Contract/schema checks:** OpenAPI code generation and migration upgrade/check/downgrade/upgrade passed.
- **Browser E2E:** The stale selectors, shared-session parallelism, resize race, appointment test-data buildup, and Ad Library missing-provider route crash were fixed and retested. The harness-accepted foreground Chromium run completed with **21 passed and 1 skipped**.
- **Evidence root:** `.ezcoder/eyes/out/qa/`
- **Task backlog:** 19 ordered implementation tasks were added to the project task list.

### Post-fix verification

All commands below were run directly, without a pipeline or a construct that could hide the command's exit code.

| Check | Direct result |
|---|---|
| `make ci.frontend` | **PASSED / exit 0** as a direct foreground command: clean install, lint, typecheck, **150 test files / 1,385 tests**, and production build passed. The Ad Library recovery regression is included. Existing React Compiler, hook, `act`, unused-variable, and MSW warnings remain under QA-027. |
| `npm run e2e -- --project=chromium` | **PASSED / exit 0** as a direct foreground command with credentials preloaded outside the command: **21 passed / 1 skipped** across 22 tests using one worker. `ad-library.spec.ts` passed while the backend returned the provider-unavailable response. |

These are the only results classified as current harness-accepted post-fix proof. The E2E command used no redirection, pipeline, or embedded credential; the seeded credentials were loaded separately from the ignored QA credentials file. Transient local login-rate rows for `127.0.0.1` were cleared before the run because prior audit traffic had consumed the same account's 10-attempt window. The raw `429` copy remains covered by QA-020. The 64/100 product score is unchanged because QA-018 remains open for the Phone Numbers and Find Leads recovery surfaces.

## Issue register

### QA-001 - Anonymous embed routes redirect to CRM login

- **Location:** `/embed/[publicId]`, `/embed/[publicId]/chat`, `/both`, `/fullpage`; `frontend/src/providers/auth-provider.tsx`
- **Affected element:** Every public voice/chat embed entry point
- **Expected:** An anonymous visitor sees the enabled agent widget.
- **Actual:** `GET /api/v1/auth/me` returns 401, refresh fails, and every valid or invalid embed route redirects to `/login`. `isPublicPathname()` omits `/embed/`.
- **Issue type:** Broken public workflow / authentication
- **Severity:** **Critical**
- **Recommended developer fix:** Add `/embed/*` to the public-route contract, prevent auth refresh redirects on embed pages, and add anonymous browser tests for all four modes and invalid IDs.
- **Evidence:** `.ezcoder/eyes/out/qa/agent-embed-audit.json`; `.ezcoder/eyes/out/qa/evidence/agent-embed/desktop-root.png`; reproduction: enable an agent embed, open its URL in a clean browser context, observe `/login`.
- **Status:** **Not Started**

### QA-002 - Embed config rejects the browser's same-origin request

- **Location:** `GET /api/v1/p/embed/{publicId}/config`; `backend/app/api/v1/public_embed.py`
- **Affected element:** Widget configuration bootstrap
- **Expected:** An enabled widget can fetch config while allowed-domain policy still rejects unauthorized customer origins.
- **Actual:** A normal same-origin browser GET does not send `Origin`; the endpoint returns `403 Origin not allowed`. Supplying `Origin: http://localhost:3000` manually returns 200, proving the browser request and API policy are incompatible. Parent-domain validation also cannot rely on the iframe's fetch Origin because that origin belongs to the hosted iframe, not its parent page.
- **Issue type:** Broken public workflow / security design
- **Severity:** **Critical**
- **Recommended developer fix:** Replace direct Origin dependence with a secure parent-page handshake or signed embed token/domain claim, support hosted same-origin config fetches, and retain explicit unauthorized-domain rejection tests.
- **Evidence:** `.ezcoder/eyes/out/qa/embed-probes/no-origin.txt`; `.ezcoder/eyes/out/http-20260818-220545.body` (`{"code":"forbidden","message":"Origin not allowed"}`); `.ezcoder/eyes/out/qa/agent-embed-audit.json`.
- **Status:** **Not Started**

### QA-003 - Capability rules are not enforced consistently across routes, actions, and reads

- **Location:** App shell and hidden modules including `/agents`, `/automations`, `/billing`, `/settings`, `/reports`, `/catalog`, and `/campaigns`; frontend permission/nav code plus matching backend routers
- **Affected element:** Direct URLs, module data, Create/Manage actions, and lower-role navigation
- **Expected:** Hidden modules are blocked by a route guard; actions and API reads/writes match `frontend/src/lib/permissions.ts`.
- **Actual:** Dispatcher can open AI Agents and Billing; member can open Automations and Team Settings; sales_rep can open AI Agents and sees create actions. Some APIs return protected data, some return 403, and static billing controls still render. The behavior differs by page instead of by capability.
- **Issue type:** Permission / authorization
- **Severity:** **High**
- **Recommended developer fix:** Introduce one capability-to-route/action map, guard direct routes before queries run, apply capabilities to every create/manage control, enforce the same dependency on backend read and write endpoints, and add the complete eight-role matrix to CI.
- **Evidence:** `.ezcoder/eyes/out/qa/permission-evidence.json`; `.ezcoder/eyes/out/qa/evidence/permissions/dispatcher-agents.png`; `member-automations.png`; `sales_rep-agents.png`.
- **Status:** **Not Started**

### QA-004 - General campaign builder silently discards entered data

- **Location:** `/campaigns/new`; `frontend/src/components/campaigns/campaign-form.tsx`
- **Affected element:** Campaign type, name, description, subject, message, audience, schedule, and Save as Draft
- **Expected:** Saving creates a draft or transfers all entered values into the selected campaign wizard.
- **Actual:** Multi-Channel Save as Draft returns to `/campaigns` with no campaign and no feedback. Email Save as Draft routes to `/campaigns/email/new`, but the entered campaign name and subject are blank. The same component contains uncontrolled placeholder audience/schedule fields.
- **Issue type:** Broken workflow / redundant UI / data loss
- **Severity:** **High**
- **Recommended developer fix:** Remove the fake general form, route type cards directly to real wizards, or implement typed draft-state transfer. Disable Multi-Channel until it has a persisted model and builder.
- **Evidence:** `.ezcoder/eyes/out/qa/core-workflows.json` (`multiChannelPathAfterSave=/campaigns`, `emailNameTransferred=false`, `emailSubjectTransferred=false`); `.ezcoder/eyes/out/qa/evidence/core-workflows/campaign-01-multichannel-save-noop.png`; `campaign-email-fields-discarded.png`.
- **Status:** **Not Started**

### QA-005 - Fresh workspace quote builder has no sellable package lines

- **Location:** `/sales-wizard`, Line Items step; onboarding/default workspace seeding
- **Affected element:** Landscape Lighting Design Packages and fixture quantities
- **Expected:** A newly onboarded workspace can select Good/Better/Best package fixtures, calculate a total, preview, and send.
- **Actual:** The Line Items screen describes package fixture counts but renders no package or fixture quantity controls. Only a free-form add-on can be entered. The QA flow could save a link only by adding an arbitrary $500 custom charge.
- **Issue type:** Empty/incomplete core workflow
- **Severity:** **High**
- **Recommended developer fix:** Seed a usable price book and package configuration during onboarding, or block the builder with a direct Price Book setup action until required SKUs exist.
- **Evidence:** `.ezcoder/eyes/out/qa/financial-workflows.json` (`noConfiguredLineItems=true`); `.ezcoder/eyes/out/qa/evidence/financial-workflows/quote-02-line-items.png`; generated client link returned 201 after custom charge.
- **Status:** **Not Started**

### QA-006 - Pipeline Add Opportunity cannot link a customer

- **Location:** `/opportunities`; `frontend/src/components/opportunities/opportunity-create-sheet.tsx`
- **Affected element:** Add Opportunity form
- **Expected:** A CRM deal can select or create its contact/customer from the primary pipeline action.
- **Actual:** The form has name, amount, stage, description, due date, and assignee, but no contact picker. The created opportunity returned `contact_id=null`, disabling customer-context call/schedule/quote behavior unless the user starts elsewhere.
- **Issue type:** Incomplete core workflow / data relationship
- **Severity:** **High**
- **Recommended developer fix:** Add a searchable contact/customer picker, show the relationship on cards/details, and allow edit/relink with workspace scoping.
- **Evidence:** `.ezcoder/eyes/out/qa/core-workflows.json` (`hasContactPicker=false`, `createdContactId=null`); `.ezcoder/eyes/out/qa/evidence/core-workflows/opportunity-01-form-no-contact.png`.
- **Status:** **Not Started**

### QA-007 - ChatGPT/OpenAI integration button is stuck disabled after hydration

- **Location:** `/settings?tab=integrations`
- **Affected element:** ChatGPT subscription for OpenAI Realtime Connect button
- **Expected:** Client configuration readiness controls one stable enabled/disabled state.
- **Actual:** React reports a hydration mismatch: the server emits `disabled=""` while the client emits `disabled={false}` and warns that it will not patch the attribute. The rendered Connect button remains disabled even while the copy tells the owner to click it.
- **Issue type:** Non-functional integration / hydration
- **Severity:** **High**
- **Recommended developer fix:** Derive readiness from deterministic server data or gate the complete integration card until mounted; add a hydration assertion and click test.
- **Evidence:** `.ezcoder/eyes/out/qa/settings-audit.json` integrations console error and `disabled=true`; `.ezcoder/eyes/out/qa/evidence/settings/desktop-integrations.png`.
- **Status:** **Not Started**

### QA-008 - Direct payment-complete URL makes an unverified success claim

- **Location:** `/payment-complete`; `frontend/src/app/payment-complete/page.tsx`
- **Affected element:** Payment received confirmation card
- **Expected:** Success is shown only after the backend verifies the Stripe Checkout session/payment.
- **Actual:** Opening `/payment-complete` directly with no session identifier says “Payment received” and “Your payment has been processed.”
- **Issue type:** Payment trust / false success state
- **Severity:** **High**
- **Recommended developer fix:** Require a Checkout session ID, verify it server-side, bind it to the invoice/workspace, and render pending/error/retry for missing, invalid, expired, or replayed sessions.
- **Evidence:** `.ezcoder/eyes/out/qa/evidence/route-scan/desktop/payment-complete.png`; reproduction: open `http://localhost:3000/payment-complete` directly.
- **Status:** **Not Started**

### QA-009 - Systemic WCAG failures block unnamed controls and form fields

- **Location:** Contacts, Quotes, Reports, Calendar, Settings, campaign/offer/agent steppers, embed dialog, and public carousel
- **Affected element:** Icon buttons, switches, tabs, quantity controls, progress bars, scroll regions, proposal/pricing fields, and report text
- **Expected:** Every control has an accessible name, every form control is labeled, progress has a name, scroll regions are keyboard-focusable, and text meets contrast requirements.
- **Actual:** The base route audit recorded 44 serious/critical/moderate rule instances across `button-name`, `aria-valid-attr-value`, `aria-progressbar-name`, `color-contrast`, and `scrollable-region-focusable`. Settings and embed scans add dozens of unlabeled controls, including 20 mobile Settings tabs and 23 critical embed-label failures.
- **Issue type:** Accessibility / keyboard and assistive technology
- **Severity:** **High**
- **Recommended developer fix:** Add explicit names/label associations, correct invalid ARIA values, name progress indicators, make intentional scroll containers focusable, repair report contrast, and add axe plus manual keyboard/screen-reader checks to CI.
- **Evidence:** `.ezcoder/eyes/out/qa/route-scan.json`; `.ezcoder/eyes/out/qa/settings-audit.json`; `.ezcoder/eyes/out/qa/agent-embed-audit.json`.
- **Status:** **Not Started**

### QA-010 - Mobile layout clips primary CRM actions

- **Location:** `/dashboard`, `/opportunities`, `/agents`, `/knowledge`, and related 390px layouts
- **Affected element:** View Contacts, Add Opportunity, Create Agent, Practice Arena, and agent selector
- **Expected:** Primary actions remain fully visible and tappable without hidden horizontal overflow.
- **Actual:** Objective bounding-box checks found controls outside the 390px viewport, including Dashboard View Contacts (right edge 424), Opportunities Add Opportunity (405), Agents Create Agent (447), and Knowledge selector (441). The page root reports no horizontal scroll, so some clipped content cannot be reached.
- **Issue type:** Responsive usability / visually defective
- **Severity:** **High**
- **Recommended developer fix:** Wrap header actions, allow text columns to shrink, stack actions below headings, and remove root overflow clipping. Add 320/390/768px screenshot and tap tests.
- **Evidence:** `.ezcoder/eyes/out/qa/route-scan.json` layout/clipped records; `.ezcoder/eyes/out/qa/evidence/contact-sheets/mobile-owner-1.png`; `mobile-owner-2.png`.
- **Status:** **Not Started**

### QA-011 - Mobile steppers and tab bars have undiscoverable clipped stages

- **Location:** `/reviews`, `/suggestions`, `/service-plans`, `/campaigns/pre-booking/new`, `/offers/new`, and quote/campaign steppers
- **Affected element:** Requests tab, Campaign Intelligence tab, Maintenance tab, calendar/offer steps, and later wizard stages
- **Expected:** All stages are visible, wrap intentionally, or sit in an obvious keyboard/touch scroll container.
- **Actual:** Later tabs/stages extend 20 to 400 pixels beyond the viewport with no visible overflow cue. Users cannot tell more stages exist.
- **Issue type:** Responsive navigation / confusing workflow
- **Severity:** **Medium**
- **Recommended developer fix:** Use labeled horizontal scrollers with edge fades and focus management, or compact/wrap the stepper while keeping the current stage and next action visible.
- **Evidence:** `.ezcoder/eyes/out/qa/route-scan.json`; `.ezcoder/eyes/out/qa/evidence/contact-sheets/mobile-owner-4.png`.
- **Status:** **Not Started**

### QA-012 - Mobile Settings navigation becomes 20 unlabeled icons

- **Location:** `/settings` at 390px
- **Affected element:** All Settings tabs
- **Expected:** Each tab exposes a visible or assistive label and a clear selected state.
- **Actual:** Text labels are hidden, leaving two rows of icons. Playwright could not resolve any of the 20 tabs by accessible name, and axe reports unnamed button/tab failures.
- **Issue type:** Accessibility / confusing navigation
- **Severity:** **Medium**
- **Recommended developer fix:** Keep short visible labels, use a labeled select/accordion on mobile, or provide `aria-label` and tooltips while retaining a strong selected state.
- **Evidence:** `.ezcoder/eyes/out/qa/settings-audit.json` (`tabAccessibleByName=false` for all mobile tabs); `.ezcoder/eyes/out/qa/evidence/settings/mobile-profile.png`.
- **Status:** **Not Started**

### QA-013 - Mobile Pricing hides service identities

- **Location:** `/settings?tab=pricing` at 390px
- **Affected element:** Financing Presentation service-name fields and delete controls
- **Expected:** Owners can distinguish full service names before editing/deleting thresholds.
- **Actual:** Inputs show truncated values such as `bistro`, `christr`, `landsc`, and `perma`; delete icon buttons are unnamed. Axe records 10 unlabeled pricing controls.
- **Issue type:** Responsive form / accessibility
- **Severity:** **Medium**
- **Recommended developer fix:** Stack service name and threshold fields, allocate full-width names, name delete actions with the service, and associate labels with every input.
- **Evidence:** `.ezcoder/eyes/out/qa/evidence/settings/mobile-pricing.png`; `.ezcoder/eyes/out/qa/settings-audit.json`.
- **Status:** **Not Started**

### QA-014 - Compact Mode toggles visually but never persists or changes density

- **Location:** `/settings?tab=profile`
- **Affected element:** Compact Mode switch
- **Expected:** Toggling applies and persists a compact UI preference, or the control is absent.
- **Actual:** `aria-checked` changes from false to true, but reload resets it to false; no compact body/theme class is applied. The source renders an uncontrolled bare switch.
- **Issue type:** Non-functional preference
- **Severity:** **Medium**
- **Recommended developer fix:** Persist a real density preference and apply semantic spacing tokens, or remove the setting until implemented.
- **Evidence:** `.ezcoder/eyes/out/qa/compact-mode-audit.json`; `.ezcoder/eyes/out/qa/evidence/settings/compact-mode-after-click.png`.
- **Status:** **Not Started**

### QA-015 - Onboarding shows a duplicate inert CSV upload card

- **Location:** `/onboarding`, Import Leads; `frontend/src/app/onboarding/_steps/leads-step.tsx`
- **Affected element:** Upper Upload CSV card and lower real dropzone
- **Expected:** One clear, operable upload target.
- **Actual:** A large upper card looks clickable but has no click/drop handler; the real dropzone appears immediately beneath it. This creates a false action and redundant vertical space.
- **Issue type:** Confusing/redundant UI
- **Severity:** **Medium**
- **Recommended developer fix:** Remove the decorative card and promote the real keyboard-accessible dropzone as the only upload surface.
- **Evidence:** `.ezcoder/eyes/out/qa/evidence/bootstrap/05-onboarding-import-empty.png`; reproduction: click the upper card and observe no file chooser.
- **Status:** **Not Started**

### QA-016 - Manager Dashboard makes a forbidden revenue-pace request

- **Location:** `/dashboard` as manager
- **Affected element:** Month Pace / revenue target widget
- **Expected:** A manager with `reports:view` sees permitted pace data, or the widget is intentionally hidden without a failed request.
- **Actual:** `GET /revenue-targets/pace` returns 403 while the rest of Dashboard loads.
- **Issue type:** Permission mismatch / incomplete dashboard
- **Severity:** **Medium**
- **Recommended developer fix:** Align the endpoint with `reports:view` or gate the widget using the stricter capability before querying.
- **Evidence:** `.ezcoder/eyes/out/qa/permission-evidence.json`; `.ezcoder/eyes/out/qa/evidence/permissions/manager-dashboard.png`.
- **Status:** **Not Started**

### QA-017 - Calendar renders duplicate React keys

- **Location:** `/calendar` month grid
- **Affected element:** Day event markers/cards
- **Expected:** Every appointment/job placeholder has a stable unique key.
- **Actual:** Console repeatedly reports “Encountered two children with the same key, `none`,” and Next dev shows an issue badge.
- **Issue type:** Rendering integrity / console defect
- **Severity:** **Medium**
- **Recommended developer fix:** Prefix stable IDs by event type and never use a shared `none` fallback; add mixed appointment/job placeholder coverage.
- **Evidence:** `.ezcoder/eyes/out/qa/route-scan.json`; `.ezcoder/eyes/out/qa/frontend-unit-tests.log`; calendar screenshots show the Next issue badge.
- **Status:** **Not Started**

### QA-018 - Missing integrations collapse into generic page-load errors

- **Location:** `/phone-numbers`, `/find-leads`, `/find-leads-ai`, `/find-leads/ad-library`
- **Affected element:** Search and Sync actions
- **Expected:** Missing owner configuration explains which provider is unavailable and links to the exact setup action; transient outages offer retry without discarding the form or module.
- **Actual:** Phone Numbers and Find Leads still replace their modules with generic load errors when providers are unavailable. The Ad Library subcase is fixed and retested: its provider-unavailable 503 now renders a durable setup banner with an Integrations link while preserving the search form, advertiser results, and saved monitors.
- **Issue type:** Error recovery / configuration UX
- **Severity:** **Medium**
- **Recommended developer fix:** Ad Library now keeps handled mutation errors out of the route boundary. Apply the same durable provider-setup state to Phone Numbers and both Find Leads routes; preserve typed input, show Retry only for transient failures, and hide setup controls from roles without configuration rights.
- **Evidence:** Current harness proof: direct foreground `npm run e2e -- --project=chromium` exited 0 with the Ad Library spec passed and **21 passed / 1 skipped** overall. Broader open-surface evidence remains in `.ezcoder/eyes/out/qa/integration-error-audit.json`, `phone-search.png`, and `places-lead-search.png`; regression source: `frontend/src/app/find-leads/ad-library/ad-library-client.test.tsx`.
- **Status:** **In Progress**

### QA-019 - Offer builder sends a request with `workspace=null`

- **Location:** `/offers/new`
- **Affected element:** Lead Magnet data loading during builder initialization
- **Expected:** Queries remain disabled until the workspace ID exists.
- **Actual:** Desktop and mobile loads issue `GET /api/v1/workspaces/null/lead-magnets`, returning 422 before the valid workspace request.
- **Issue type:** API sequencing / console noise
- **Severity:** **Medium**
- **Recommended developer fix:** Gate the query with `enabled: Boolean(workspaceId)` and exclude null IDs from query keys and URLs.
- **Evidence:** `.ezcoder/eyes/out/qa/route-scan.json` failed responses for `/offers/new`.
- **Status:** **Not Started**

### QA-020 - Invalid login exposes raw Axios error text

- **Location:** `/login`
- **Affected element:** Authentication error message
- **Expected:** A concise, non-enumerating message such as “Email or password is incorrect.”
- **Actual:** The form displays “Request failed with status code 401.”
- **Issue type:** Confusing error copy / implementation leakage
- **Severity:** **Medium**
- **Recommended developer fix:** Map expected auth status codes to product copy while logging request IDs/details privately.
- **Evidence:** `.ezcoder/eyes/out/qa/evidence/public-forms/login-invalid.png`; `.ezcoder/eyes/out/qa/public-form-audit.json`.
- **Status:** **Not Started**

### QA-021 - Hardcoded tenant brands leak into multi-workspace surfaces

- **Location:** `/campaigns/email/new`, root app metadata/manifest, estimator defaults, and `/p/landing`
- **Affected element:** Wordmarks, placeholders, page title, manifest name, and public metadata
- **Expected:** Multi-tenant UI uses the current workspace/business brand or a neutral product brand.
- **Actual:** Email Campaign hardcodes “Maxteriors” and a Maxteriors sender placeholder; public landing metadata hardcodes PRESTYJ; app metadata/manifest hardcodes Maxteriors even in `CRM's Workspace`.
- **Issue type:** Multi-tenant branding / confusing content
- **Severity:** **Medium**
- **Recommended developer fix:** Centralize product versus workspace brand roles, load customer-facing business copy from workspace proposal settings, and remove tenant-specific fallbacks from shared surfaces.
- **Evidence:** `.ezcoder/eyes/out/qa/evidence/contact-sheets/desktop-owner-4.png`; `frontend/src/app/campaigns/email/new/page.tsx`; `frontend/src/app/layout.tsx`; `frontend/src/app/manifest.ts`; `frontend/src/app/p/landing/page.tsx`.
- **Status:** **Not Started**

### QA-022 - Field-role redirects happen after restricted API requests and fail inconsistently

- **Location:** Direct non-calendar URLs as lead_technician/technician
- **Affected element:** Route guard and initial data queries
- **Expected:** Restricted users redirect before protected module code mounts or queries run.
- **Actual:** Technician routes sometimes redirect to Calendar only after one or more 403 requests; lead_technician often remains on a generic error page with repeated 403s. The behavior varies by route.
- **Issue type:** Permission UX / request sequencing
- **Severity:** **Medium**
- **Recommended developer fix:** Apply synchronous server/layout route guards from the capability map before mounting page queries; preserve a single clear access-denied destination.
- **Evidence:** `.ezcoder/eyes/out/qa/permission-audit.json`; `.ezcoder/eyes/out/qa/permission-evidence.json`; `lead_technician-contacts.png`; technician route records.
- **Status:** **Not Started**

### QA-023 - Mixed-format onboarding area-code paste loses digits

- **Location:** `/onboarding`, Import Leads
- **Affected element:** Preferred Area Code
- **Expected:** Pasting `abc313x`, `(313)`, or `313-` normalizes to `313`, subject to three digits.
- **Actual:** Browser `maxLength=3` truncates the raw string before React removes non-digits, so `abc313x` becomes empty and `(313)` can become `31`.
- **Issue type:** Input polish
- **Severity:** **Low**
- **Recommended developer fix:** Sanitize the full pasted value before slicing to three digits; add paste-focused tests.
- **Evidence:** `.ezcoder/eyes/out/qa/bootstrap-report.json` (`areaCodeFilteredValue=""`).
- **Status:** **Not Started**

### QA-024 - Settings saves often provide no success confirmation

- **Location:** Multiple `/settings` tabs, including Profile, Notifications, Reviews, Pricing, Sales Targets, Pipeline, Neighbors, and Lead Sources
- **Affected element:** Save buttons
- **Expected:** Save produces a brief status announcement and visible confirmation.
- **Actual:** No toast or alert text was present after the save smoke tests, leaving the owner unsure whether persistence completed.
- **Issue type:** Feedback/polish
- **Severity:** **Low**
- **Recommended developer fix:** Standardize save mutations on one accessible success/error toast pattern and disable buttons while pending.
- **Evidence:** `.ezcoder/eyes/out/qa/settings-audit.json`, `saveActions[].feedback=""`.
- **Status:** **Not Started**

### QA-025 - Settings navigation is excessively dense on desktop

- **Location:** `/settings` desktop
- **Affected element:** Single rail containing 20 tabs
- **Expected:** Related settings are grouped and scannable without memorizing a long flat rail.
- **Actual:** Twenty equal-weight tabs wrap across multiple rows, making integrations, billing, team, automation rules, and personal settings visually indistinguishable.
- **Issue type:** Information architecture / polish
- **Severity:** **Low**
- **Recommended developer fix:** Group tabs into Personal, CRM, Automation, Integrations, and Workspace sections while preserving direct `?tab=` URLs.
- **Evidence:** `.ezcoder/eyes/out/qa/evidence/settings/desktop-integrations.png` and other desktop Settings captures.
- **Status:** **Not Started**

### QA-026 - Browser E2E suite has stale selectors and shared-session parallel flakes

- **Location:** `frontend/e2e/contact-flow.spec.ts`, `appointment-happy-path.spec.ts`, `landscape-lighting-studio.spec.ts`, and `frontend/playwright.config.ts`
- **Affected element:** CI browser test reliability
- **Expected:** The checked-in E2E suite uses current accessible labels, remains repeatable, and does not race one seeded user's refresh-token session.
- **Actual:** The original strict Contacts match, stale `14:00` option, parallel shared account, immediate resize measurement, and leaked appointment fixtures were reproduced. They are now corrected: exact/current accessible locators pass, seeded credentials force one worker, geometry polls until resized, and appointment/contact fixtures are deleted after each run. The harness-accepted foreground full Chromium run passes.
- **Issue type:** QA infrastructure
- **Severity:** **Low**
- **Recommended developer fix:** Implemented role/exact locators, the accessible `2:00 PM` label, shared-credential serialization, asynchronous geometry polling, and fixture cleanup. Keep parallelism only for isolated per-worker accounts.
- **Evidence:** Direct foreground `npm run e2e -- --project=chromium`: exit 0, **21 passed / 1 skipped**, 22 tests using one worker; `frontend/playwright.config.ts`.
- **Status:** **Closed**

### QA-027 - Passing CI still emits material warning debt

- **Location:** Frontend React Compiler/lint tests, backend AsyncMock tests, migration metadata
- **Affected element:** Build/test signal quality and future framework compatibility
- **Expected:** Passing CI is quiet enough that new regressions are visible.
- **Actual:** Frontend logs repeated skipped compilation, render-time ref access, setState-in-effect, act, and unmatched MSW warnings; backend logs unawaited AsyncMock warnings; migration check warns about an unresolvable FK cycle.
- **Issue type:** Engineering quality / performance risk
- **Severity:** **Low**
- **Recommended developer fix:** Burn down warnings by category, fail on newly introduced warning classes, await AsyncMocks, add missing MSW handlers, and document or break the FK cycle before toolchain upgrades make it fatal.
- **Evidence:** `.ezcoder/eyes/out/qa/ci-frontend.log`; `.ezcoder/eyes/out/qa/ci-backend.log`; `.ezcoder/eyes/out/qa/ci-migrations.log`.
- **Status:** **Not Started**

## Verified working behavior

- Account registration, required-field validation, login, forgot-password privacy response, invalid reset-token handling, and invited-role registration.
- Onboarding step validation, CSV upload, agent creation, and graceful missing-SMS-number warning.
- Contact creation and detail view using fake data.
- Appointment creation at `2:00 PM`, calendar visibility, and cleanup (`201` then `204`).
- Invoice draft creation with linked contact, line item, tax, due date, and totals (`201`).
- Inactive automation creation with a Wait step (`201`).
- Opportunity creation and pipeline visibility (`201`), subject to QA-006.
- Quote preview/save and real public client-link generation (`201`), subject to QA-005.
- Forgot-password request returns a generic success for unknown email; invalid reset token returns 400 with actionable copy.
- Public lead-call form validates phone input and shows an inline failure when Telnyx is unavailable.
- Backend, frontend, codegen, and reversible-migration CI all pass.

## Score rationale and release gate

**64/100** reflects a broad internal CRM that works for several owner workflows but fails its public embed lead-capture path, has inconsistent permission boundaries, and presents high-risk false or discarded states in campaigns and payments. The score cannot reach 100 until:

1. Both anonymous embed blockers are closed and retested on a real parent domain.
2. The eight high-priority issues are fixed with role, mobile, and accessibility regression coverage.
3. Live provider sends/calls/searches and Stripe return verification are tested in controlled vendor sandboxes.
4. The checked-in E2E suite passes repeatably, including durable provider-missing recovery instead of a route-level crash.
5. A manual WCAG 2.2 AA keyboard and screen-reader assessment closes the automated accessibility findings.

**Release recommendation:** Do not ship the public embed, generic campaign builder, or unverified payment-success page in their current state. Internal owner workflows may continue in controlled use, but role-restricted accounts should not be expanded until QA-003 and QA-022 are resolved.
