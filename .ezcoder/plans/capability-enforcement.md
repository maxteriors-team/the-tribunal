# Consistent Capability Enforcement

## Objective

Make the existing capability matrix authoritative from browser navigation through API execution, so hidden navigation cannot be bypassed by direct URLs or direct requests. Preserve tenant scoping and return `403` for authenticated workspace members who lack a required capability.

## Canonical policy

Use the role/capability sets in `frontend/src/lib/permissions.ts` and the route inventory in `frontend/src/components/layout/app-nav.ts` as the frontend source of truth. Mirror the same policy with `Capability` and `ROLE_CAPABILITIES` in `backend/app/core/permissions.py`.

| Surface                                                                            | Read / enter                       | Create or manage                                        |
| ---------------------------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------- |
| Agents, agent knowledge/prompts/profiles/suggestions/experiments                   | `crm:read`                         | `workspace:manage`                                      |
| Automations                                                                        | `crm:read`                         | `outreach:write`                                        |
| Campaigns, voice/drip campaigns, campaign reports, message tests/templates, offers | `crm:read`                         | `outreach:write`                                        |
| Billing                                                                            | `billing:read`                     | `billing:write`                                         |
| Catalog                                                                            | `billing:read`                     | `billing:write`                                         |
| Reports                                                                            | `reports:view`                     | Existing explicit administrative target-management gate |
| Personal settings                                                                  | Authenticated user                 | Self only                                               |
| Workspace/integration/API-key settings                                             | `workspace:manage`                 | `workspace:manage`                                      |
| Team settings                                                                      | `members:manage`                   | `members:manage`                                        |
| Pricing/proposal/attach/card settings                                              | `billing:read`                     | `billing:write`                                         |
| Outreach settings                                                                  | `crm:read`                         | `outreach:write`                                        |
| Pipeline settings                                                                  | `crm:read`                         | `pipeline:write`                                        |
| Tags/lead-source settings                                                          | `crm:read`                         | `crm:write`                                             |
| Locations settings                                                                 | Existing `locations:manage` policy | Existing `locations:manage` policy                      |

Field roles (`lead_technician`, `technician`) remain fail-closed to the existing operational URL allowlist even if a future capability is accidentally granted.

## Steps

1. Encode route requirements and write-screen overrides in `app-nav.ts`, then apply the shared direct-URL decision in `app-sidebar.tsx`.
2. Gate agent, automation, campaign/offer, billing, catalog, and Settings management affordances with `useCapabilities()`.
3. Add reusable backend read/write dependency chokepoints and active-workspace billing capability aliases.
4. Apply matching gates to agent-family, campaign-family, billing, settings/integration/API-key, automation, catalog, and reporting routers without changing tenant/object scoping.
5. Add exhaustive eight-role capability matrices plus frontend route/action and backend route/request regression tests.
6. Run targeted format, lint, type, test, codegen-drift, and runtime HTTP/log checks; fix every relevant failure.
7. Record the authorization control in `COMPLIANCE.md` and mark task `12bdcaf6` done only after the evidence passes.

## Implementation

### 1. Frontend route policy and direct-URL guard

- Add missing `requires` entries for Agents, AI Suggestions, Automations, Experiments, Campaigns, and Offers in `app-nav.ts`.
- Export pure longest-prefix route lookup/access helpers from `app-nav.ts`.
- Add explicit write-screen overrides for agent create/configure routes and campaign creation routes.
- Replace the field-only redirect in `app-sidebar.tsx` with the shared access helper, covering both field tiers and every capability-gated route.
- Redirect denied routes to the first safe home (`/calendar` for on-site roles, `/contacts` for CRM readers, `/settings` otherwise) and render no protected child content while redirecting.

### 2. Frontend action enforcement

- Use `useCapabilities()` at the top-level feature clients.
- Hide create/configure/activate/duplicate/delete controls for agents unless `workspace:manage`; retain read-only listing and separately permitted practice/test-call behavior.
- Hide campaign/offer/automation create and lifecycle controls unless `outreach:write`; retain details and analytics for `crm:read` users.
- Hide catalog mutations unless `billing:write`; keep catalog reads behind `billing:read`.
- Disable billing checkout/portal controls unless `billing:write`.
- Filter Settings tabs through a single exported tab-capability map; a forbidden `?tab=` deep link falls back to Profile and never mounts the unauthorized tab component.

### 3. Backend capability chokepoints

- Mark capability dependencies with inspectable metadata and add an active-workspace billing read/write dependency pair in `backend/app/api/deps.py`.
- Apply method-aware read/write gates at router level where one policy covers the whole feature, preventing future endpoints from defaulting to membership-only access.
- Agent family: gate `agents`, prompt versions, human profiles, knowledge documents, suggestions/experiments, and agent-scoped bookable staff reads/writes.
- Campaign family: retain the already-gated core campaign/pre-booking routes and cover voice campaigns, drip campaigns, campaign reports, message tests/templates, and offers.
- Billing: `status` requires active-workspace `billing:read`; checkout and portal require `billing:write`; Stripe webhook remains public and signature-verified.
- Settings: apply the table above to workspace settings; protect integration credential reads plus API-key management with `workspace:manage`; leave personal profile/notification and personal calendar flows self-scoped.
- Retain existing automation, catalog, reporting, revenue-target, workspace, tenant, and object-level checks; capability gates are additive, not a replacement for `workspace_id` filtering.

### 4. Matrix and regression tests

- Replace partial role examples with an explicit independent matrix for all eight roles: `owner`, `admin`, `manager`, `dispatcher`, `sales_rep`, `member`, `lead_technician`, `technician`.
- Assert every capability for every role in both frontend and backend tests, including dispatcher-manager equivalence and lead/technician operational differences.
- Add frontend route-policy tests for nav visibility, direct URL denial, write-only subroutes, and Settings tab filtering.
- Add backend route-policy tests that enumerate every protected route and inspect its required read/write capability, plus representative HTTP tests proving allowed roles proceed and denied roles receive non-disclosing `403` responses.
- Add action-rendering tests for the high-risk top-level controls where existing component harnesses make this proportional.

### 5. Generated contracts, compliance record, and proof

- Regenerate/check OpenAPI clients only if FastAPI dependency changes alter committed artifacts.
- Update the existing `COMPLIANCE.md` authorization finding as a dated CODE/TEST result; do not claim product-wide compliance.
- Run targeted backend Ruff/type/pytest checks and frontend Vitest/TypeScript/lint checks.
- Start the local backend if prerequisites are available and use `.ezcoder/eyes/http.sh` against representative agent, billing, settings, report, and campaign endpoints to confirm authenticated under-privilege returns `403` and unauthenticated access returns `401`; inspect logs for tracebacks.

## Safety constraints

- Do not modify or overwrite the unrelated dirty work already present, especially the current auth-provider and feature/UI changes.
- Do not weaken existing workspace/object scoping, field-assignment checks, public webhook signature checks, or personal-calendar ownership.
- Do not put authorization solely in React; backend gates are the security boundary.
