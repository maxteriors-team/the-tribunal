# User assignment for sales and dispatch records

## Outcome

Add tenant-safe ownership to quotes and opportunities, and connect accepted quotes to the existing job-dispatch roster so an operator can choose the exact field team members when creating the job. Keep sales ownership and field crew assignment distinct: a quote owner is an active workspace user; a job assignee is an active `Technician` roster entry linked to a workspace user or external worker.

## Scope and behavior

- A quote has one optional `assigned_user_id` sales owner and an `assignee` display summary.
- New quotes inherit the linked opportunity owner when one exists; otherwise they default to the creating user. Operators can reassign or clear ownership after any quote lifecycle state through a dedicated endpoint.
- Opportunities expose their existing `assigned_user_id` as a usable owner field in create/edit UI. Managers can choose any active workspace member; sales-rep object scoping continues to force self-ownership.
- Quote-to-job conversion accepts `technician_ids` and creates the job with those roster assignments. Existing new-job and job-detail assignment flows remain the canonical way to change a job crew afterward.
- Only active members of the same workspace may become quote/opportunity owners. Only active technicians in the same workspace may receive new job assignments. Existing historical assignments remain readable after a member is removed or a roster entry is retired.
- Invoices remain billing records rather than separately assignable operational records; their related job and source quote provide ownership/dispatch context without creating conflicting assignee semantics.

## Backend changes

- Add `quotes.assigned_user_id` with an indexed `ON DELETE SET NULL` foreign key to `users.id` in `backend/app/models/quote.py` and a reversible Alembic migration under `backend/alembic/versions/`. Backfill from a same-workspace opportunity owner first, then a same-workspace `created_by_id`; leave invalid/unknown rows unassigned.
- Add a small workspace-membership assertion in `backend/app/services/workspaces/membership.py` and use it for every client-selected quote/opportunity owner to prevent cross-tenant user IDs.
- Extend `backend/app/schemas/quote.py` with owner fields, an assignee summary, a dedicated nullable assignment request, assignment filtering, and `technician_ids` on `QuoteConvertRequest`.
- Update `backend/app/services/quotes/quote_service.py` to default/inherit owners on every quote creation path, load assignee relationships without N+1 queries, filter by owner, update owner independently of locked quote content, and pass selected technician IDs into `JobService.create()` during conversion.
- Add the assignment route and list filter in `backend/app/api/v1/quotes.py` while preserving existing billing-write authorization.
- Update `backend/app/schemas/opportunity.py`, `backend/app/services/opportunities/opportunity_service.py`, and `backend/app/api/v1/opportunities.py` so managers can select a validated owner on create/update, sales reps remain forced to themselves, responses include an assignee summary, and the existing `owner_id` query parameter uses the correct integer user-ID type.
- Tighten `backend/app/services/jobs/job_service.py::_assert_technicians` so new assignments require an active roster entry in the current workspace; retired technicians remain visible on already-assigned jobs.

## Frontend changes

- Add a shared active-team-member query/picker using `frontend/src/lib/api/settings.ts`, `frontend/src/lib/query-keys.ts`, and a small component under `frontend/src/components/workspaces/`; show name, email, role, unassigned state, loading, and failure states.
- Extend `frontend/src/types/quote.ts`, `frontend/src/types/opportunity.ts`, `frontend/src/lib/api/quotes.ts`, and `frontend/src/lib/api/opportunities.ts` with integer owner IDs, assignee summaries, assignment mutation/filter support, and conversion technician IDs.
- Add an owner column and assignment action/dialog to `frontend/src/components/quotes/quotes-list.tsx`; invalidate quote queries after assignment and keep reassignment available for approved/declined/expired quotes.
- Add the owner picker to `frontend/src/components/opportunities/opportunity-create-sheet.tsx` and `frontend/src/components/opportunities/opportunity-detail-sheet.tsx`, and show the owner on `frontend/src/components/opportunities/opportunity-card.tsx`. Hide or lock reassignment when the caller only has own-pipeline capability.
- Extend `frontend/src/components/quotes/convert-quote-dialog.tsx` to load the existing workspace roster and render `frontend/src/components/jobs/technician-select.tsx`, then submit selected technician IDs with the schedule window. Preserve the existing empty selection as a valid unscheduled/unassigned dispatch-queue job.

## Risks and safeguards

- **Tenant isolation:** validate membership/roster ownership server-side; never trust picker options or a raw user/technician ID.
- **Role semantics:** do not turn quote owners into job technicians automatically; dispatch explicitly selects roster members during conversion.
- **Departed users:** return an assignee summary from the record relationship so historical ownership remains legible even when that user is no longer in the active picker.
- **Query volume:** eager-load owner relationships for list/detail responses to avoid one user query per record.
- **Migration safety:** use nullable fields, conditional same-workspace backfill joins, indexed foreign keys, and a clean downgrade.
- **API drift:** regenerate and commit `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` in the same change.

## Verification

- Backend service/API tests prove default/inherited quote ownership, explicit assignment and clearing, cross-workspace rejection, sales self-scoping, manager opportunity assignment, inactive/cross-workspace technician rejection, and quote conversion with selected job technicians.
- Frontend tests prove quote owner display/reassignment, opportunity owner create/edit behavior, role-restricted controls, and conversion payloads containing selected technicians.
- Run targeted backend pytest and frontend Vitest suites, then `make ci.codegen`, `make ci.backend`, `make ci.frontend`, and `make ci.migrations` because this changes models, a migration, public schemas, and generated clients.
- After implementation, exercise representative quote assignment, opportunity assignment, and quote conversion endpoints with `.ezcoder/eyes/http.sh` when the local authenticated backend is available; inspect status and response ownership/technician shapes.

## Steps

1. Add the nullable quote owner model field and reversible same-workspace backfill migration.
2. Implement reusable workspace-member validation and quote assignment schemas, service logic, filtering, response loading, and API endpoint.
3. Expose and validate opportunity ownership while preserving sales-rep self-scoping and correcting the owner filter type.
4. Accept selected active roster technicians during quote conversion and harden job assignment validation.
5. Regenerate backend OpenAPI and frontend generated API types.
6. Add shared team-member picker/query support and update handwritten quote/opportunity API types.
7. Add quote owner display and reassignment UI across all quote states.
8. Add opportunity owner create/edit/display UI with capability-aware restrictions.
9. Add technician selection to quote conversion using the existing dispatch roster component.
10. Add backend and frontend regression tests for tenant isolation, role behavior, assignment lifecycle, and conversion payloads.
11. Run targeted tests, codegen checks, migration checks, full backend/frontend CI, and representative local API probes.