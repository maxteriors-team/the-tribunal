/**
 * Workspace role catalog for the dashboard UI.
 *
 * Mirrors the backend source of truth in `backend/app/core/roles.py`
 * (`AssignableRole`). `owner` is intentionally excluded — ownership is
 * established at workspace creation and transferred through dedicated flows, so
 * it is never offered in role pickers.
 *
 * Keep this list in sync with the backend `AssignableRole` literal; the
 * generated OpenAPI types (`InvitationCreate.role`, `UpdateMemberRoleRequest`)
 * are the contract these dropdowns must satisfy.
 */

export const ASSIGNABLE_ROLES = [
  "admin",
  "manager",
  "dispatcher",
  "sales_rep",
  "technician",
  "member",
] as const;

export type AssignableRole = (typeof ASSIGNABLE_ROLES)[number];

/** Human-readable label for any workspace role, including `owner`. */
export const ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  manager: "Manager",
  dispatcher: "Dispatcher",
  sales_rep: "Sales Rep",
  technician: "Technician",
  member: "Member",
};

/**
 * Short description shown beneath each role option in pickers. These summarize
 * the four access tiers enforced by `@/lib/permissions` (admin ⊃ manager ⊃ sales
 * ⊃ tech): admin alone sees reports and manages members/numbers; managers run
 * CRM, jobs, and billing; sales own their pipeline; tech/member read and message.
 */
export const ROLE_DESCRIPTIONS: Record<AssignableRole, string> = {
  admin: "Full access — team, billing, reports, and settings",
  manager: "Run CRM, jobs, and billing (no reports or member management)",
  dispatcher: "Run CRM, jobs, and billing (no reports or member management)",
  sales_rep: "Manage your own sales pipeline; text and call customers",
  technician: "View work, log time on jobs, and message customers",
  member: "View contacts and pipeline; text and call customers",
};

/** Display label for a role string, falling back to the raw value. */
export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}
