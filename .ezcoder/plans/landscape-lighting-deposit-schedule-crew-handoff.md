# Landscape Lighting Deposit, Scheduling, and Crew Handoff

## Objective

Turn the accepted landscape-lighting proposal into one clear, truthful closeout path that lets an operator:

1. confirm or collect the required Stripe-backed deposit,
2. create and schedule the authoritative field-service job,
3. assign the installation crew/technicians, and
4. automatically expose the approved installation diagram inside that assigned job.

The customer-facing proposal remains the payment surface. Quotes remain the source of approval and deposit truth. Field-service jobs remain the source of schedule and assignment truth. The landscape project remains the editable design source.

## Current authoritative paths

- `backend/app/services/payments/quote_deposit_service.py` and `frontend/src/components/proposal/deposit-panel.tsx` already own hosted Stripe checkout and paid reconciliation. Do not add manual “paid” toggles or a second payment record.
- `backend/app/services/quotes/quote_service.py::approve_public()` already persists the customer-selected package before approval and deposit calculation.
- `backend/app/services/quotes/quote_service.py::convert_quote()` already creates the invoice/job, applies a paid deposit as an invoice payment, validates schedule windows and technician ownership, and commits quote/job/invoice links together.
- `backend/app/services/jobs/job_service.py` and `frontend/src/components/jobs/jobs-calendar.tsx` already own field-service jobs, scheduling, technician assignment, crew routing, status transitions, and field-user calendar visibility.
- `backend/app/services/notifications.py` already owns role-aware email/push notifications with preference handling and dedupe. Use it for assignment delivery status; do not create a parallel notification table.
- `backend/app/models/lighting_project.py` and its v2 document remain the editable plan source. Do not put customer design bytes in public `/static` or in the public proposal response.

## Recommended design

### 1. Persist stable cross-domain links, not copied business records

Add nullable, workspace-scoped foreign keys:

- `Quote.lighting_project_id -> lighting_projects.id`
- `Job.lighting_project_id -> lighting_projects.id`
- `Job.source_quote_id -> quotes.id` with a unique constraint, so retrying conversion cannot create a second job for the same quote.

Add `LightingProject.installation_shot_id` as the operator-selected installation sheet. It must reference a shot ID that exists in the validated v2 document.

Why this shape:

- the accepted quote is permanently tied to the design that produced it;
- conversion copies that stable project link onto the job;
- installers access the design through the job they are authorized to see;
- no mutable payment/schedule/assignment state is duplicated in landscape JSON;
- quote conversion becomes idempotent at the database boundary.

Migration file: `backend/alembic/versions/20260811_link_lighting_projects_to_quotes_jobs.py`, descending from the current `20260811_lighting_projects` Alembic head. The downgrade removes indexes/constraints/columns only; it never deletes customer projects, quotes, or jobs.

### 2. Lock the selected installation sheet before proposal delivery

Treat `LightingProject.installation_shot_id` as the explicit “selected diagram.” Add a selector to the studio’s Proposal workflow using the existing sheets and labels.

Before a landscape quote can be created/delivered:

- require a contact-linked, server-backed lighting project;
- require a valid selected installation sheet;
- flush pending autosave and block on unresolved conflict/sync error;
- save the selected sheet as project metadata;
- send `lighting_project_id` with the wizard payload.

The backend must validate project ownership and linkage (`workspace`, `contact`, and, when present, service location/opportunity). It writes `Quote.lighting_project_id`; it never trusts a client-supplied diagram URL or total.

Proposal/deposit behavior:

- Include the existing workspace deposit default in the landscape wizard payload so the quote gets `deposit_percentage` or `deposit_amount_fixed` and the public proposal naturally shows **Pay deposit** after approval.
- If the workspace deposit rule is disabled, show **No deposit required** instead of inventing an amount.
- Expose `deposit_required`, derived `deposit_amount`, and `deposit_paid` on authenticated quote detail/list responses so staff UIs display actual backend state.
- Do not expose `lighting_project_id`, installation-plan data, BOM/procurement, pre-con notes, costs, technician information, or job data through the unauthenticated public proposal schema.

### 3. Extend the existing conversion into a single operational handoff

Evolve `QuoteConvertRequest` rather than creating a separate landscape closeout endpoint:

- retain `create_invoice` / `create_job`;
- retain `scheduled_start`, `scheduled_end`, and `technician_ids`;
- add nullable `crew_id`;
- make conversion return an existing conversion result on exact retries;
- reject contradictory retries (different schedule, crew, technicians, or create flags) with `409` instead of creating or silently changing records.

For linked landscape quotes, job creation must:

- copy `Quote.lighting_project_id` to `Job.lighting_project_id`;
- set `Job.source_quote_id`;
- preserve the customer-selected package and final quote line items already frozen by public approval;
- set `crew_id` and technician assignments through existing workspace ownership validation;
- leave deposit truth untouched;
- create the invoice only through the existing conversion path, where a paid Stripe deposit is already credited exactly once.

Validation and transaction rules:

- an accepted quote may be scheduled whether the deposit is **paid**, **unpaid**, or **not required**, but the dialog must make the outstanding amount unmistakable and ask for explicit confirmation before scheduling with an unpaid required deposit;
- schedule requires both start/end and `end > start`;
- crew and technicians must belong to the workspace;
- a linked project and installation sheet must still exist at conversion;
- the quote lock, unique `source_quote_id`, and transaction prevent duplicate jobs/invoices from double clicks/retries;
- transaction-bound job creation/status automation stays unchanged; external email/push delivery runs only after commit and cannot roll back a successfully scheduled job.

### 4. Provide the crew copy through an assignment-scoped job endpoint

Add a narrow endpoint under the existing jobs router:

`GET /api/v1/workspaces/{workspace_id}/jobs/{job_id}/installation-plan`

It returns an installation-plan DTO, not the whole editable landscape document:

- project/job IDs, project name, selected sheet ID/label/title/number, project version and update timestamp;
- selected sheet photo and installation drawing data needed by the existing canvas renderer: fixtures, wire runs, plan images, annotations, measurements, highlights, arrows, dusk/settings;
- the fixture schedule and pre-con field brief needed for installation;
- no proposal pricing, deposit/payment data, customer-only proposal content, internal procurement costs, other sheets, or editable project mutation controls.

Authorization must be stricter than today’s general `CanReadJobs` detail endpoint:

- owner/admin/manager/dispatcher can read any workspace job plan;
- field technicians and crew leaders can read only a job directly assigned to their technician row or routed to one of their crews;
- sales/marketing/finance roles do not gain plan access merely because they have general workspace access;
- no public token route and no `/static` object;
- unauthorized cross-workspace and unassigned access returns 404 to avoid leaking job/project existence.

Render the response in a read-only `InstallationPlanPanel` inside `frontend/src/components/jobs/job-detail-dialog.tsx`, reusing `LightCanvas`/existing rendering primitives. Include **View installation plan**, **Print**, and **Download PNG** actions; the “copy” is automatically available from the assigned worker’s `/jobs` calendar without emailing durable customer imagery or creating a second mutable attachment.

### 5. Notify only the assigned installation team

After a successful conversion/schedule commit, resolve recipients from:

- directly assigned `Technician.user_id` values; and
- active crew members’ linked technician `user_id` values for `Job.crew_id`.

Deduplicate users, honor existing channel preferences, and call `notify_workspace_event()` with a `jobs` channel deep link to the job. Use a dedupe key scoped to the job plus current assignment/schedule version so an exact retry cannot spam the crew. Notification copy states that the installation plan is available in Tribunal; it does not attach customer photos or put an authorization token in email.

The conversion response must report `crew_notification` as `sent`, `partial`, `not_applicable`, or `failed` plus recipient counts. A notification failure is visible and retryable but does not make a committed job/payment operation look failed. Re-running the post-commit notifier with the same dedupe key is safe.

### 6. Replace the generic conversion dialog with a guided closeout state

Enhance `frontend/src/components/quotes/convert-quote-dialog.tsx` and reuse it from both Quotes and the Landscape Proposal workflow.

The dialog shows a three-step summary in one compact surface:

1. **Deposit** — Not required / Due ($amount with **Open customer payment page**) / Paid (timestamp when available). No staff-side “charge” or “mark paid” button.
2. **Schedule** — required start/end pickers for a job; preserve invoice-only conversion for non-job quotes.
3. **Installation team** — crew selector plus technicians, with the selected diagram’s label and a clear “shared automatically after scheduling” state.

On success, show authoritative links to **Open job** and **Open invoice**, plus crew-delivery result. The landscape studio should surface the same next-step card after a quote is approved: deposit state first, then **Schedule installation**. Do not auto-schedule merely because a proposal was approved or a deposit webhook arrived; material readiness and customer availability still require a human decision, matching `acceptance_handoff.py`.

## Files and symbols

### Backend models, schemas, migration

- `backend/app/models/lighting_project.py` — add `installation_shot_id` and relationships.
- `backend/app/models/quote.py` — add `lighting_project_id` relationship.
- `backend/app/models/field_service.py` — add `source_quote_id`, `lighting_project_id`, indexes/relationship.
- `backend/app/models/__init__.py` — keep model registration/import ordering valid.
- `backend/app/schemas/lighting_project.py` — project response/update metadata and selected-shot validator.
- `backend/app/schemas/proposal_wizard.py` — optional staff-only `lighting_project_id` on the authenticated save payload only; leave client-safe allowlist unchanged.
- `backend/app/schemas/quote.py` — deposit truth fields, `crew_id`, idempotent conversion response, crew-delivery DTO.
- `backend/app/schemas/job.py` — installation-plan DTOs and linked IDs needed by authenticated job views.
- `backend/alembic/versions/20260811_link_lighting_projects_to_quotes_jobs.py` — reversible schema change.

### Backend services and routes

- `backend/app/services/lighting_projects.py` — validate/update selected installation shot and build a redacted read-only plan DTO.
- `backend/app/services/quotes/quote_service.py` — validate/persist lighting project link; harden `convert_quote()` idempotency; copy project/quote links; accept crew assignment; return notification status.
- `backend/app/services/jobs/job_service.py` — assignment-aware installation-plan lookup and recipient resolution.
- `backend/app/services/notifications.py` — add/route the assignment event through existing preference/dedupe behavior only if the current generic API cannot return per-recipient delivery counts cleanly.
- `backend/app/api/v1/lighting_projects.py` — selected-sheet update via existing project update semantics.
- `backend/app/api/v1/quotes.py` — pass the expanded conversion request and run best-effort notification after commit.
- `backend/app/api/v1/jobs.py` — assignment-scoped installation-plan route.

### Frontend API and workflow UI

- `frontend/src/lib/estimator/landscape-document.ts` and `frontend/src/lib/estimator/landscape-draft.ts` — preserve full v2 state when draft helpers update proposal/linkage metadata; do not introduce document v3 for relational linkage.
- `frontend/src/lib/estimator/landscape-proposal.ts` — include deposit configuration and `lighting_project_id` in the authenticated wizard payload.
- `frontend/src/components/landscape-lighting/use-lighting-project-autosave.ts` — expose an awaitable flush/save-now result so quote creation cannot race pending project changes.
- `frontend/src/components/landscape-lighting/lighting-project-editor.tsx` — pass project identity/current project state and save barrier into the designer.
- `frontend/src/components/estimator/light-designer.tsx` — installation-sheet selection, deposit-aware payload, approved-project next-step card, and shared conversion dialog entry point.
- `frontend/src/lib/api/quotes.ts`, `frontend/src/types/quote.ts` — typed deposit/conversion/notification fields.
- `frontend/src/lib/api/jobs.ts`, `frontend/src/hooks/useJobs.ts`, `frontend/src/lib/query-keys.ts`, `frontend/src/lib/query-options.ts` — installation-plan query and cache keys.
- `frontend/src/components/quotes/convert-quote-dialog.tsx` — guided deposit/schedule/team closeout and crew selection.
- `frontend/src/components/quotes/quotes-list.tsx` — pass full quote state and open job/invoice links after conversion.
- `frontend/src/components/jobs/job-detail-dialog.tsx` plus a focused `frontend/src/components/jobs/installation-plan-panel.tsx` — assigned-team copy, print, PNG export, and safe loading/error states.
- `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` — regenerate together after API/schema changes.

## Verification

### Backend proof

- Extend `backend/tests/test_lighting_projects.py` for selected-sheet validity, optimistic concurrency, and project/contact/workspace mismatches.
- Extend `backend/tests/services/quotes/test_wizard_flow.py` for workspace deposit defaults and linked-project persistence.
- Extend `backend/tests/services/quotes/test_quote_service.py` for paid/unpaid/no-deposit conversion, paid-deposit invoice credit exactly once, crew + technician assignment, copied links, exact retry, contradictory retry, and concurrent retry protection.
- Add focused job installation-plan API tests for manager access, direct technician access, crew access, unassigned technician denial, sales/finance denial, cross-workspace denial, redaction, and missing/stale selected sheet.
- Test notification recipient dedupe, preferences, exact-retry dedupe, partial/failure reporting, and “commit succeeds even if delivery fails.”
- Run `make ci.backend`, `make ci.migrations`, and `make ci.codegen` after committing generated contracts as required by this repo’s codegen check.

### Frontend proof

- Extend `frontend/src/components/quotes/convert-quote-dialog.test.tsx` for all deposit states, explicit unpaid confirmation, schedule validation, crew/technician selection, selected-plan summary, and delivery result.
- Extend `frontend/src/components/jobs/job-detail-dialog.test.tsx` for authorized plan loading, redacted read-only rendering, error/empty states, print, and PNG download.
- Extend `frontend/src/components/estimator/light-designer.test.tsx` and `frontend/src/components/landscape-lighting/use-lighting-project-autosave.test.tsx` for installation-sheet selection, save-before-quote, configured deposit payload, and approved-project next-step states.
- Extend `frontend/e2e/landscape-lighting-studio.spec.ts` with a route-intercepted flow: select install sheet → create/send quote → model approval/unpaid then paid deposit → schedule + assign → open assigned job → render the exact selected sheet.
- Run targeted Vitest first, then `make ci.frontend`.

### Runtime eyes

With local services running, use `.ezcoder/eyes/http.sh` to prove:

- linked landscape quote creation and authenticated quote deposit fields;
- rejected unassigned/cross-workspace installation-plan reads;
- accepted assigned-technician read with no payment/procurement leakage;
- conversion returns one job across a retry and truthful crew-notification status;
- `/readyz` remains non-500 after migration.

Use `.ezcoder/eyes/mail.sh clear`, trigger one scheduled-assignment notification, then confirm count/recipient/copy/deep link and no customer image/token in the captured email. Use `.ezcoder/eyes/logs.sh` to check conversion/notification logs for duplicate sends or tracebacks.

## Compliance and residual risk

Controls included:

- PCI-sensitive card entry remains entirely on Stripe Checkout; Tribunal stores only session/payment IDs and reconciled status.
- Payment state is provider-derived and cannot be manually fabricated in this workflow.
- Accepted package, quote totals, deposit computation, invoice credit, and schedule validation remain server-authoritative.
- Installation imagery is authenticated, workspace-scoped, assignment-scoped, private-cache only, and absent from public/static surfaces and notification payloads.
- Notifications honor preferences and report delivery separately from transaction success.
- Audit logs cover quote conversion, schedule/assignment, installation-plan access, and delivery attempts without logging diagram bytes or public/payment tokens.

Residual risks that remain after implementation:

- an authorized installer can still download/screenshot the plan; policy, offboarding, and device controls remain operational responsibilities;
- email/push confirms availability but cannot prove the installer opened the plan, so “delivered” must not be labeled “viewed”;
- scheduling before an unpaid deposit is intentionally possible after an explicit warning; business policy may later choose to forbid it, but this implementation will not silently enforce an unstated rule;
- existing customer photos remain stored inside the lighting-project JSON/database; this task narrows delivery exposure but does not migrate all project media to object storage.

## Steps

1. Add the reversible Alembic migration and ORM relationships linking lighting projects to quotes/jobs, including `installation_shot_id`, unique `Job.source_quote_id`, and supporting indexes.
2. Extend lighting-project, proposal-wizard, quote, and job schemas with validated selected-sheet linkage, authenticated deposit truth, crew conversion input, idempotent conversion/delivery output, and redacted installation-plan DTOs while keeping the public proposal allowlist unchanged.
3. Update `LightingProjectService` and landscape project routes to validate and persist the selected installation sheet under existing workspace/contact/concurrency rules.
4. Update landscape proposal construction and `QuoteService.save_from_wizard()` to apply the workspace deposit default and persist a server-validated `lighting_project_id` on the quote.
5. Harden `QuoteService.convert_quote()` to lock/reuse exact retries, reject contradictory retries, set crew/technician assignments, and copy source-quote/lighting-project links while preserving existing Stripe-deposit invoice credit behavior.
6. Add assignment-aware installation-plan lookup and the authenticated jobs endpoint, returning only the selected sheet, fixture schedule, pre-con brief, and safe renderer inputs.
7. Add post-commit crew recipient resolution and preference-aware deduplicated notifications, returning truthful sent/partial/not-applicable/failed status without rolling back successful conversion.
8. Extend frontend API wrappers, domain types, query keys/options, and autosave with an awaitable save barrier for linked project/quote/job data.
9. Add the studio installation-sheet selector, workspace-default deposit payload, and approved-proposal next-step card that opens the shared closeout dialog.
10. Upgrade the quote conversion dialog/list integration with deposit status, unpaid-deposit confirmation, required schedule validation, crew/technician selection, selected-plan summary, authoritative success links, and delivery status.
11. Add the read-only installation-plan panel to job details with assigned-worker access, print, PNG download, and page-state loading/error handling.
12. Add backend/frontend/e2e coverage for deposit truth, idempotent conversion, schedule/assignment, authorization/redaction, selected-sheet fidelity, and notification outcomes.
13. Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, then run targeted tests, `make ci.backend`, `make ci.frontend`, `make ci.migrations`, and `make ci.codegen` in the repository-required order.
14. Run local HTTP, mail, and log eyes to prove one end-to-end accepted-proposal → paid/unpaid deposit state → scheduled assigned job → authorized installation-plan handoff with no duplicate or unauthorized disclosure.