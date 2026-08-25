# Direct implementation: per-user nudges, Clear All, and sales-rep quoting

Execution mode: implement immediately after this required review handoff; there is no human approval checkpoint and no schema migration.

## Outcome

- Members see, count, mutate, and clear only nudges assigned to them.
- Unassigned operational nudges are visible/delivered only to `crm:write` roles, not every workspace member.
- New contact nudges target the owner of the contact's latest open opportunity, falling back to the workspace owner; opportunity and quote nudges prefer their explicit assignee/creator.
- “Clear All” dismisses only active nudges visible to the caller (`pending`, `sent`, `snoozed`) in one atomic workspace-scoped update. It does not delete rows or alter another user's targeted nudges.
- Sales reps can create, view, edit, and send their own quotes/estimates without gaining invoice, payment, catalog, offline-deposit, job-conversion, or paid AI-render authority.

## Nudge implementation

- Add one reusable visibility predicate in `backend/app/api/v1/nudges.py`; apply it to list, stats, act, dismiss, snooze, and a new `PUT /clear-all` route. The predicate always includes `workspace_id` and `assigned_to_user_id == current_user.id`; only roles with `crm:write` also include `assigned_to_user_id IS NULL`.
- Add `NudgeClearAllResponse` in `backend/app/schemas/nudge.py`. Define `/clear-all` before UUID routes and use one parameterized SQL `UPDATE ... WHERE` over active statuses, returning the affected count.
- Extend `NudgeContext` in `backend/app/services/nudges/strategies/base.py` with a workspace-owner fallback, latest-open-opportunity contact ownership map, and an assignee resolver. Prefetch those values once in `nudge_generator.py`.
- Set `assigned_to_user_id` at every strategy `HumanNudge` construction: contact strategies use the context resolver, deal strategies prefer `Opportunity.assigned_user_id`, and workspace strategies use the owner fallback.
- Target quote-view and unsold-quote nudges in `quote_service.py` to `quote.assigned_user_id` first, then `quote.created_by_id`.
- Restrict legacy/unassigned delivery in `nudge_delivery.py` to active memberships whose role has `crm:write`; explicitly assigned nudges continue to resolve to one active user.
- Add backend tests proving user A cannot list/count/mutate/clear user B's nudges, sales cannot consume global nudges, managers can handle globals, Clear All is scoped/atomic, generated nudges resolve owners, and delivery has one intended recipient.

## Sales-rep quote capability fix

Root cause confirmed: `sales_rep` lacks `billing:read/write`, while every authenticated quote route and all quote navigation currently require those broad billing capabilities.

- Add dedicated `quotes:read` and `quotes:write` capabilities in `backend/app/core/permissions.py` and `frontend/src/lib/permissions.ts`. Grant them to owner/admin/manager/dispatcher/sales-rep tiers; do not grant billing capabilities to sales reps.
- Add `CanReadQuotes`/`CanWriteQuotes` dependencies in `backend/app/api/deps.py` and switch ordinary quote/estimate list, detail, create, edit, revision, line-item/service, approve/decline, send, wizard preview/save, and estimate-to-quote routes to them.
- Keep `billing:write` on invoice/job conversion, offline deposit recording, quote reassignment, paid AI image rendering, and billing/catalog/pricing controls. These operations move money, change another user's ownership, create operational work, or incur workspace spend.
- Add `quote_owner_scope(role, user_id)` beside `pipeline_owner_scope`. Sales reps receive their user ID; privileged quote roles receive `None`.
- Enforce ownership at the database boundary: list queries force the sales owner scope; sales-created plain/wizard/estimate quotes set `assigned_user_id=current_user.id`; every authenticated `{quote_id}` route runs a workspace-and-owner-scoped quote dependency before service mutation. Legacy sales-created rows remain reachable through `created_by_id` when `assigned_user_id` is null. Unauthorized or cross-workspace quote IDs return 404.
- Keep saved-comparison delivery billing-gated unless its token is also creator-scoped; do not create a token-based ownership bypass merely to widen navigation.
- Change quote/landscape/estimator navigation requirements in `frontend/src/components/layout/app-nav.ts` from `billing:read` to `quotes:read`; keep billing/invoice navigation unchanged.
- Add capability-matrix, RBAC-route, and integration tests proving two sales reps cannot read or mutate each other's quotes, each can author/send their own, managers retain workspace-wide quote access, and sensitive billing/spend routes remain forbidden to sales.

## Frontend Clear All

- Add `nudgesApi.clearAll()` in `frontend/src/lib/api/nudges.ts` and the count response in `frontend/src/types/nudge.ts`.
- Add a “Clear All” control to `frontend/src/components/nudges/nudges-page.tsx`, visible only when active visible nudges exist. Confirm before mutation, disable duplicate submissions, toast the dismissed count, and invalidate all workspace nudge list/stats query keys.
- Add focused component/API tests for confirmation, one request, pending state, and cache refresh.

## Generated contracts and verification

- Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, preserving unrelated working-tree changes already present in both files.
- Run focused Ruff, MyPy, backend unit/integration tests, frontend lint/type/tests, capability/RBAC tests, and `make ci.codegen`.
- Start/use the local backend and exercise authenticated nudge list, cross-user mutation, and clear-all behavior with `.ezcoder/eyes/http.sh`; inspect the redacted response and logs. If no local auth fixture/server exists, record that exact runtime gap after exhausting the existing harness.

## Steps

1. Implement the scoped nudge predicate, user-targeted generation/delivery, atomic Clear All endpoint, and isolation tests.
2. Add dedicated quote capabilities, sales ownership scoping at route/query boundaries, protected sensitive operations, and RBAC/ownership tests.
3. Add the frontend Clear All flow and switch quote navigation to the dedicated read capability with focused tests.
4. Regenerate API contracts without overwriting unrelated work, run all focused backend/frontend/codegen checks, execute the available runtime probe, and fix every failure before reporting only external gaps.