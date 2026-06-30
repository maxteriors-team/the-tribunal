/**
 * Capability-based access control for the dashboard UI.
 *
 * Mirror of the backend source of truth in `backend/app/core/permissions.py`.
 * The backend enforces every rule; this copy only decides what to *show* (nav
 * items, action buttons, route guards). Keep the two in lockstep — if you change
 * the matrix here, change it there (and vice versa), and update both unit tests.
 *
 * Four tiers, admin broadest → tech narrowest:
 *   admin   ← owner, admin
 *   manager ← manager, dispatcher
 *   sales   ← sales_rep
 *   tech    ← technician, member  (and any unknown/legacy role, fail-closed)
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

export type Tier = "admin" | "manager" | "sales" | "tech";

const ROLE_TIERS: Record<string, Tier> = {
  owner: "admin",
  admin: "admin",
  manager: "manager",
  dispatcher: "manager",
  sales_rep: "sales",
  technician: "tech",
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
};

/** Resolve a role string to its access tier (unknown/legacy → `tech`, fail-closed). */
export function roleTier(role: string | null | undefined): Tier {
  if (!role) return "tech";
  return ROLE_TIERS[role] ?? "tech";
}

/** Return true when `role` is granted `capability`. */
export function can(role: string | null | undefined, capability: Capability): boolean {
  return TIER_CAPABILITIES[roleTier(role)].includes(capability);
}
