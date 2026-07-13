/**
 * Capability-based access control for the dashboard UI.
 *
 * Mirror of the backend source of truth in `backend/app/core/permissions.py`.
 * The backend enforces every rule; this copy only decides what to *show* (nav
 * items, action buttons, route guards). Keep the two in lockstep — if you change
 * the matrix here, change it there (and vice versa), and update both unit tests.
 *
 * Five tiers, admin broadest → field narrowest:
 *   admin   ← owner, admin
 *   manager ← manager, dispatcher
 *   sales   ← sales_rep
 *   tech    ← member
 *   field   ← technician  (and any unknown/legacy role, fail-closed)
 *
 * Field technicians are operational-only: the jobs schedule and nothing else
 * (no contacts, pipeline, campaigns, billing/pricing, or other CRM surface).
 */

export type Capability =
  | "crm:read"
  | "crm:write"
  | "pipeline:write"
  | "pipeline:write_own"
  | "jobs:read"
  | "jobs:write"
  | "comms:send"
  | "comms:manage"
  | "billing:read"
  | "billing:write"
  | "reports:view"
  | "members:manage"
  | "workspace:manage";

export type Tier = "admin" | "manager" | "sales" | "tech" | "field";

const ROLE_TIERS: Record<string, Tier> = {
  owner: "admin",
  admin: "admin",
  manager: "manager",
  dispatcher: "manager",
  sales_rep: "sales",
  technician: "field",
  member: "tech",
};

const ALL_CAPABILITIES: Capability[] = [
  "crm:read",
  "crm:write",
  "pipeline:write",
  "pipeline:write_own",
  "jobs:read",
  "jobs:write",
  "comms:send",
  "comms:manage",
  "billing:read",
  "billing:write",
  "reports:view",
  "members:manage",
  "workspace:manage",
];

export const TIER_CAPABILITIES: Record<Tier, Capability[]> = {
  admin: [...ALL_CAPABILITIES],
  manager: [
    "crm:read",
    "crm:write",
    "pipeline:write",
    "pipeline:write_own",
    "jobs:read",
    "jobs:write",
    "comms:send",
    "billing:read",
    "billing:write",
  ],
  sales: ["crm:read", "pipeline:write_own", "jobs:read", "comms:send"],
  tech: ["crm:read", "jobs:read", "comms:send"],
  // Field technicians: operational-only — the jobs schedule and nothing else.
  field: ["jobs:read"],
};

/** Resolve a role string to its access tier (unknown/legacy → `field`, fail-closed). */
export function roleTier(role: string | null | undefined): Tier {
  if (!role) return "field";
  return ROLE_TIERS[role] ?? "field";
}

/** Return true when `role` is granted `capability`. */
export function can(role: string | null | undefined, capability: Capability): boolean {
  return TIER_CAPABILITIES[roleTier(role)].includes(capability);
}
